"""PR-6 S2 — approve-time PDF pipeline + B5 download endpoints.

验收对照（施工令 PR-6 §S2-1/3/4、§五-3/4）:

  * **approve 當下生成**：approve 之後 ``pdf_path`` / ``pdf_sha256`` 非空、
    檔案存在、``sha256(file) == pdf_sha256``。
  * **PDF 失敗＝approve 失敗**：renders raises → approve 回 500，狀態仍係
    ``pending_review``，兩欄留空（冇「approved 但冇 PDF」中間態）。
  * **B5 下載端點**：家長 ownership gate（非本人子女 403）、approved only
    （pending 404，唔洩狀態）；教師側同一個 gate，非本班 403、pending 409；
    approved 兩邊 bytes 一致，``Content-Type: application/pdf``、
    ``Content-Disposition: attachment``、檔名 ``dreamer-report-<前8位>.pdf``。
  * **supersede 鏈**：新 approval 生成新 PDF，舊檔案留檔唔刪（audit）。
"""

from __future__ import annotations

import hashlib
import os

import pytest

from auth.api import ReportPdfError

# Reuse the PR-3 harness (fresh DB, seeded roster) rather than re-inventing it.
from tests.test_report_state_machine import (  # noqa: F401
    P1,
    P2,
    SID_A,
    SID_D,
    T1,
    T2,
    _cookie_header,
    _report_rows,
    client,
    world,
)


def _pdf_dir(tmp_path, monkeypatch) -> str:
    target = str(tmp_path / "report_pdfs")
    monkeypatch.setenv("DREAMER_REPORT_PDF_DIR", target)
    return target


async def _draft(client, user_id: str = T1, student_id: str = SID_A, **extra) -> str:
    body = {"student_id": student_id, "class_id": "class-0001"}
    body.update(extra)
    resp = await client.post(
        "/api/teacher/reports/generate", json=body, headers=_cookie_header(user_id)
    )
    assert resp.status == 201, await resp.text()
    return (await resp.json())["report_id"]


async def _approve(client, report_id: str, user_id: str = T1):
    return await client.post(
        f"/api/teacher/reports/{report_id}/approve",
        json={},
        headers=_cookie_header(user_id),
    )


def _row(db_path: str, report_id: str):
    rows = _report_rows(db_path)
    return next(r for r in rows if r["report_id"] == report_id)


async def _parent_pdf(client, user_id: str, report_id: str, student_id: str = SID_A):
    return await client.get(
        f"/api/parent/reports/{report_id}/pdf",
        params={"student_id": student_id},
        headers=_cookie_header(user_id),
    )


async def _teacher_pdf(client, user_id: str, report_id: str):
    return await client.get(
        f"/api/teacher/reports/{report_id}/pdf", headers=_cookie_header(user_id)
    )


# ---------------------------------------------------------------------------
# approve 當下生成
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_approve_stores_pdf_path_and_sha(client, world, tmp_path, monkeypatch):
    pdf_dir = _pdf_dir(tmp_path, monkeypatch)
    report_id = await _draft(client)
    resp = await _approve(client, report_id)
    assert resp.status == 200, await resp.text()

    row = _row(world["db_path"], report_id)
    assert row["status"] == "approved"
    assert row["pdf_path"].endswith("%s.pdf" % report_id)
    assert len(row["pdf_sha256"]) == 64

    absolute = os.path.join(pdf_dir, "%s.pdf" % report_id)
    assert os.path.isfile(absolute)
    with open(absolute, "rb") as handle:
        data = handle.read()
    assert data.startswith(b"%PDF")
    assert hashlib.sha256(data).hexdigest() == row["pdf_sha256"]


@pytest.mark.asyncio
async def test_approve_fails_closed_when_render_fails(client, world, tmp_path, monkeypatch):
    _pdf_dir(tmp_path, monkeypatch)
    report_id = await _draft(client)

    def _boom(*_args, **_kwargs):
        raise ReportPdfError("render exploded")

    import auth.api as api_mod

    original = api_mod._write_report_pdf
    monkeypatch.setattr(api_mod, "_write_report_pdf", _boom)
    resp = await _approve(client, report_id)
    assert resp.status == 500, await resp.text()

    row = _row(world["db_path"], report_id)
    assert row["status"] == "pending_review"   # 冇「approved 但冇 PDF」
    assert row["approved_at"] == ""
    assert row["pdf_path"] == ""
    assert row["pdf_sha256"] == ""

    # 重試（renderer 復原後）仍然可以正常 approve
    monkeypatch.setattr(api_mod, "_write_report_pdf", original)
    retry = await _approve(client, report_id)
    assert retry.status == 200, await retry.text()
    assert _row(world["db_path"], report_id)["pdf_sha256"]


# ---------------------------------------------------------------------------
# B5 下載端點
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_parent_download_serves_the_approved_bytes(client, world, tmp_path, monkeypatch):
    _pdf_dir(tmp_path, monkeypatch)
    report_id = await _draft(client)
    await _approve(client, report_id)

    resp = await _parent_pdf(client, P1, report_id)
    assert resp.status == 200, await resp.text()
    assert resp.headers["Content-Type"] == "application/pdf"
    disposition = resp.headers["Content-Disposition"]
    assert disposition.startswith("attachment;")
    assert "dreamer-report-%s.pdf" % report_id[:8] in disposition

    body = await resp.read()
    assert body.startswith(b"%PDF")
    assert hashlib.sha256(body).hexdigest() == _row(world["db_path"], report_id)["pdf_sha256"]


@pytest.mark.asyncio
async def test_parent_download_is_approved_only(client, world, tmp_path, monkeypatch):
    _pdf_dir(tmp_path, monkeypatch)
    report_id = await _draft(client)          # 仍是 pending_review
    resp = await _parent_pdf(client, P1, report_id)
    assert resp.status == 404                  # 唔洩狀態，同不存在一樣


@pytest.mark.asyncio
async def test_parent_download_blocks_other_families(client, world, tmp_path, monkeypatch):
    _pdf_dir(tmp_path, monkeypatch)
    report_id = await _draft(client)
    await _approve(client, report_id)

    # P2 的子女係 SID_D；用 SID_A 嘅 id 直接查 → ownership gate
    resp = await _parent_pdf(client, P2, report_id, student_id=SID_A)
    assert resp.status == 403


@pytest.mark.asyncio
async def test_teacher_download_matches_parent_bytes(client, world, tmp_path, monkeypatch):
    _pdf_dir(tmp_path, monkeypatch)
    report_id = await _draft(client)
    await _approve(client, report_id)

    teacher = await _teacher_pdf(client, T1, report_id)
    assert teacher.status == 200, await teacher.text()
    parent = await _parent_pdf(client, P1, report_id)
    assert teacher.headers["Content-Type"] == "application/pdf"
    assert await teacher.read() == await parent.read()


@pytest.mark.asyncio
async def test_teacher_download_pending_is_state_error(client, world, tmp_path, monkeypatch):
    _pdf_dir(tmp_path, monkeypatch)
    report_id = await _draft(client)
    resp = await _teacher_pdf(client, T1, report_id)
    assert resp.status == 409


@pytest.mark.asyncio
async def test_teacher_download_blocks_other_teachers(client, world, tmp_path, monkeypatch):
    _pdf_dir(tmp_path, monkeypatch)
    report_id = await _draft(client)          # class-0001 → T1
    await _approve(client, report_id)
    resp = await _teacher_pdf(client, T2, report_id)
    assert resp.status == 403


@pytest.mark.asyncio
async def test_regenerated_file_still_verifies_against_stored_hash(
    client, world, tmp_path, monkeypatch
):
    """檔案被清走（新容器／volume 重掛）時重render，hash 必須吻合才出街."""
    pdf_dir = _pdf_dir(tmp_path, monkeypatch)
    report_id = await _draft(client)
    await _approve(client, report_id)
    stored_hash = _row(world["db_path"], report_id)["pdf_sha256"]

    os.remove(os.path.join(pdf_dir, "%s.pdf" % report_id))
    resp = await _parent_pdf(client, P1, report_id)
    assert resp.status == 200, await resp.text()
    assert hashlib.sha256(await resp.read()).hexdigest() == stored_hash


# ---------------------------------------------------------------------------
# supersede 鏈 — 舊 PDF 留檔
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_supersede_keeps_the_old_pdf_on_disk(client, world, tmp_path, monkeypatch):
    pdf_dir = _pdf_dir(tmp_path, monkeypatch)
    v1 = await _draft(client)
    await _approve(client, v1)
    v1_pdf = os.path.join(pdf_dir, "%s.pdf" % v1)
    assert os.path.isfile(v1_pdf)

    v2 = await _draft(client)                  # 同一區間再生成 → v2
    assert v2 != v1
    await _approve(client, v2)

    v2_pdf = os.path.join(pdf_dir, "%s.pdf" % v2)
    assert os.path.isfile(v2_pdf)
    assert os.path.isfile(v1_pdf)              # audit：舊檔唔刪
    assert _row(world["db_path"], v1)["status"] == "superseded"
    assert _row(world["db_path"], v2)["status"] == "approved"
