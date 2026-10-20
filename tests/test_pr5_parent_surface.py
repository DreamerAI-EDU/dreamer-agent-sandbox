"""PR-5 T-5 — parent / teacher surface separation (施工令 §四.2 / §B3 / §B4).

验收对照:

  T-5 遮罩: 家长端报告 payload（列表 + 单份详情，原始 JSON 文本）对禁词表
      `IB` / `ATL` / `Inquirer` / `Learner Profile` / `Proficient` / `Excellent`
      / `kid_label` / `citations` / `cost` 零命中；内部机器槽
      `teacher_edits` / `review` / `internal_label` / `last_label_internal`
      连键都不存在（不是“存在但为 null”——null 一样证明槽漏了）。
  T-5 crosswalk: 老师端 crosswalk（设计书 §6 九行 + 口径答案）任何一句都不得
      出现在任何 parent 路由的响应里。
  T-5 状态: pending / rejected / superseded 的报告对家长路由不可达（404），
      列表只为 approved 版本出现。
  T-5 角色: parent 打不开老师路由（403），teacher 打不开家长路由（403），
      别人的孩子读不到（403）。

口径备注（写给复验用，不是放宽条件）:
  `age_band` 是 PR-3/T-3 要求 round-trip 的**机器字段**（家长 console 从不渲染
  它，只渲染 parentReportCopy.bandLabel 的冻结友好名）。因此本档对 band 原始
  代码（`P1-P3` / `P4-P6` / `S1-S3`）的判定是：**只允许出现在 `age_band`
  字段的值里**，出现在任何其它字符串中即 RED（见
  ``test_t5_raw_band_code_survives_only_as_the_machine_field``）。

本档只读既有端点契约（PR-2 / PR-3 / PR-5 已落库），不改任何后端行为。
"""

from __future__ import annotations

import json
import os
import sys

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("PYTHONPATH", REPO_ROOT)
sys.path.insert(0, REPO_ROOT)

# Reuse the canonical world (1 teacher-owned class + confirmed roster + real
# agent activity) and the cookie helper — same datastore, no second fixture.
from tests.test_reports_api import (  # noqa: E402,F401
    P1,
    P2,
    SID_A,
    SID_D,
    T1,
    client,
    world,
    _cookie_header,
)

from auth import db as auth_db  # noqa: E402

CLASS_A = "class-0001"


@pytest.fixture
def pr5_world(world):
    """Reused world + the PR-2/PR-3 column set (week_no / skill_code / score).

    ``test_reports_api.world`` only applies the class-meta migration, so the
    teacher-score columns that ``build_dimension_scores`` reads have to be
    added on top. Same datastore, same users — no second fixture.
    """
    auth_db.apply_phase8_parent_reports_migration()
    return world

#: 施工令 §三 banned terms (payload layer). Band raw codes are handled
#: separately below — they legally survive inside the `age_band` machine field.
BANNED_TERMS = (
    "IB",
    "ATL",
    "Inquirer",
    "Learner Profile",
    "Proficient",
    "Excellent",
    "kid_label",
    "citations",
    "cost",
)

#: Internal slots that must be ABSENT as keys (a null value still leaks them).
BANNED_KEYS = (
    "kid_label",
    "citations",
    "cost",
    "cost_summary",
    "teacher_edits",
    "review",
    "internal_label",
    "last_label_internal",
)

RAW_BAND_CODES = ("P1-P3", "P4-P6", "S1-S3")


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _walk(node, path="$"):
    """Yield (json-path, value) for every leaf value."""
    if isinstance(node, dict):
        for key, value in node.items():
            yield from _walk(value, f"{path}.{key}")
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from _walk(value, f"{path}[{index}]")
    else:
        yield path, node


def _text_hits(payload, terms):
    """[(path, term, excerpt)] for every banned term found in a string value."""
    hits = []
    for path, value in _walk(payload):
        if not isinstance(value, str):
            continue
        for term in terms:
            if term in value:
                hits.append((path, term, value[:120]))
    return hits


def _key_hits(payload, keys):
    return [
        path for path, _ in _walk(payload) if path.rsplit(".", 1)[-1] in keys
    ]


def _dumps(payload) -> str:
    return json.dumps(payload, ensure_ascii=False)


async def _draft(client, student_id=SID_A, week_from=1, week_to=3):
    resp = await client.post(
        "/api/teacher/reports/generate",
        json={
            "student_id": student_id,
            "class_id": CLASS_A,
            "week_from": week_from,
            "week_to": week_to,
        },
        headers=_cookie_header(T1),
    )
    assert resp.status == 201, await resp.text()
    return await resp.json()


async def _approved_report(client, student_id=SID_A, week_from=1, week_to=3):
    """POST generate -> POST approve, returns the approved row."""
    row = await _draft(client, student_id, week_from, week_to)
    resp = await client.post(
        f"/api/teacher/reports/{row['report_id']}/approve",
        json={},
        headers=_cookie_header(T1),
    )
    assert resp.status == 200, await resp.text()
    body = await resp.json()
    assert body["status"] == "approved"
    return body


# ---------------------------------------------------------------------------
# T-5 — parent payload gate (list + detail)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_t5_parent_detail_payload_has_no_banned_term(pr5_world, client):
    report = await _approved_report(client)

    resp = await client.get(
        "/api/parent/reports",
        params={"student_id": SID_A, "report_id": report["report_id"]},
        headers=_cookie_header(P1),
    )
    assert resp.status == 200, await resp.text()
    body = await resp.json()

    hits = _text_hits(body, BANNED_TERMS)
    assert hits == [], f"banned term(s) reached the parent payload: {hits}"
    assert _key_hits(body, BANNED_KEYS) == [], (
        f"internal slot(s) still present in the parent payload: "
        f"{_key_hits(body, BANNED_KEYS)}"
    )


@pytest.mark.asyncio
async def test_t5_parent_list_payload_has_no_banned_term(pr5_world, client):
    await _approved_report(client)

    resp = await client.get(
        "/api/parent/reports",
        params={"student_id": SID_A},
        headers=_cookie_header(P1),
    )
    assert resp.status == 200, await resp.text()
    body = await resp.json()
    assert body["count"] == 1, body

    hits = _text_hits(body, BANNED_TERMS)
    assert hits == [], f"banned term(s) in the parent list payload: {hits}"
    assert _key_hits(body, BANNED_KEYS) == []


@pytest.mark.asyncio
async def test_t5_raw_band_code_survives_only_as_the_machine_field(pr5_world, client):
    """The stored band may round-trip as `age_band` (T-3), nowhere else.

    The parent console renders the frozen §三 friendly name instead (§B3); this
    assertion pins the payload boundary so a code can never leak through a
    narrative / topic / descriptor string.
    """
    report = await _approved_report(client)
    resp = await client.get(
        "/api/parent/reports",
        params={"student_id": SID_A, "report_id": report["report_id"]},
        headers=_cookie_header(P1),
    )
    body = await resp.json()

    offenders = []
    for path, value in _walk(body):
        if not isinstance(value, str):
            continue
        leaf = path.rsplit(".", 1)[-1]
        for code in RAW_BAND_CODES:
            if code in value and leaf != "age_band":
                offenders.append((path, code, value[:120]))
    assert offenders == [], f"raw band code escaped `age_band`: {offenders}"

    # ...and it DOES survive there: that is the T-3 contract, not a leak.
    assert body["report"]["age_band"] == "P4-P6"


@pytest.mark.asyncio
async def test_t5_full_student_id_never_on_parent_surface(pr5_world, client):
    report = await _approved_report(client)
    resp = await client.get(
        "/api/parent/reports",
        params={"student_id": SID_A, "report_id": report["report_id"]},
        headers=_cookie_header(P1),
    )
    blob = _dumps(await resp.json())
    assert SID_A not in blob, "full student id leaked to the parent surface"
    assert report["report_id"] in blob  # the report id itself is the handle


# ---------------------------------------------------------------------------
# T-5 — crosswalk (teacher-only) never reaches a parent route
# ---------------------------------------------------------------------------


def _crosswalk_strings():
    """Every §6 string, straight out of the checked-in machine copy."""
    path = os.path.join(REPO_ROOT, "config", "pr5_frozen_copy.json")
    with open(path, "r", encoding="utf-8") as fh:
        crosswalk = json.load(fh)["crosswalk"]
    strings = [crosswalk["purpose"], crosswalk["standardAnswer"]]
    strings.extend(crosswalk["columns"].values())
    for row in crosswalk["rows"]:
        strings.extend(row.values())
    return [s for s in strings if s]


@pytest.mark.asyncio
async def test_t5_crosswalk_text_absent_from_every_parent_response(pr5_world, client):
    report = await _approved_report(client)
    strings = _crosswalk_strings()
    assert len(strings) >= 9 + 5, len(strings)

    responses = []
    for params in (
        {"student_id": SID_A},
        {"student_id": SID_A, "report_id": report["report_id"]},
    ):
        resp = await client.get(
            "/api/parent/reports", params=params, headers=_cookie_header(P1)
        )
        assert resp.status == 200
        responses.append(_dumps(await resp.json()))

    for blob in responses:
        leaked = [s for s in strings if s in blob]
        assert leaked == [], f"teacher crosswalk text on the parent surface: {leaked}"


# ---------------------------------------------------------------------------
# T-5 — state gate (only approved is reachable)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_t5_pending_draft_is_invisible_to_the_parent(pr5_world, client):
    draft = await _draft(client)

    listing = await client.get(
        "/api/parent/reports",
        params={"student_id": SID_A},
        headers=_cookie_header(P1),
    )
    assert listing.status == 200
    assert (await listing.json())["count"] == 0

    detail = await client.get(
        "/api/parent/reports",
        params={"student_id": SID_A, "report_id": draft["report_id"]},
        headers=_cookie_header(P1),
    )
    assert detail.status == 404


@pytest.mark.asyncio
async def test_t5_rejected_draft_is_invisible_to_the_parent(pr5_world, client):
    draft = await _draft(client)
    resp = await client.post(
        f"/api/teacher/reports/{draft['report_id']}/reject",
        json={"note": "再補證據"},
        headers=_cookie_header(T1),
    )
    assert resp.status == 200
    assert (await resp.json())["status"] == "rejected"

    detail = await client.get(
        "/api/parent/reports",
        params={"student_id": SID_A, "report_id": draft["report_id"]},
        headers=_cookie_header(P1),
    )
    assert detail.status == 404


@pytest.mark.asyncio
async def test_t5_superseded_version_is_not_listed(pr5_world, client):
    first = await _approved_report(client, week_from=1, week_to=2)
    second = await _approved_report(client, week_from=1, week_to=2)
    assert first["report_id"] != second["report_id"]

    resp = await client.get(
        "/api/parent/reports",
        params={"student_id": SID_A},
        headers=_cookie_header(P1),
    )
    rows = (await resp.json())["reports"]
    assert [r["report_id"] for r in rows] == [second["report_id"]]

    old = await client.get(
        "/api/parent/reports",
        params={"student_id": SID_A, "report_id": first["report_id"]},
        headers=_cookie_header(P1),
    )
    assert old.status == 404


# ---------------------------------------------------------------------------
# T-5 — role / ownership gates around the two consoles
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_t5_parent_cannot_reach_teacher_report_routes(pr5_world, client):
    report = await _approved_report(client)
    parent = _cookie_header(P1)

    listing = await client.get("/api/teacher/reports", headers=parent)
    assert listing.status == 403

    detail = await client.get(
        f"/api/teacher/reports/{report['report_id']}", headers=parent
    )
    assert detail.status == 403

    edit = await client.put(
        f"/api/teacher/reports/{report['report_id']}",
        json={"edits": [{"field": "content", "to": "x"}]},
        headers=parent,
    )
    assert edit.status == 403


@pytest.mark.asyncio
async def test_t5_teacher_cannot_reach_parent_report_route(pr5_world, client):
    await _approved_report(client)
    resp = await client.get(
        "/api/parent/reports",
        params={"student_id": SID_A},
        headers=_cookie_header(T1),
    )
    assert resp.status == 403


@pytest.mark.asyncio
async def test_t5_other_parent_cannot_read_the_report(pr5_world, client):
    report = await _approved_report(client)
    for params in (
        {"student_id": SID_A},
        {"student_id": SID_A, "report_id": report["report_id"]},
    ):
        resp = await client.get(
            "/api/parent/reports", params=params, headers=_cookie_header(P2)
        )
        assert resp.status == 403, params

    # ...and P2's own reachable set does not contain the report either.
    own = await client.get(
        "/api/parent/reports",
        params={"student_id": SID_D, "report_id": report["report_id"]},
        headers=_cookie_header(P2),
    )
    assert own.status == 404


# ---------------------------------------------------------------------------
# A4 — review view keeps the internal slots on the TEACHER side only
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_t5_review_slots_exist_on_teacher_side_only(pr5_world, client):
    report = await _approved_report(client)
    teacher = await client.get(
        f"/api/teacher/reports/{report['report_id']}", headers=_cookie_header(T1)
    )
    assert teacher.status == 200
    teacher_body = await teacher.json()
    assert "review" in teacher_body
    assert "teacher_edits_count" in teacher_body
    assert "cost_summary" in teacher_body
    assert teacher_body["draft_url"] == f"/teacher/reports/{report['report_id']}"

    parent = await client.get(
        "/api/parent/reports",
        params={"student_id": SID_A, "report_id": report["report_id"]},
        headers=_cookie_header(P1),
    )
    parent_body = await parent.json()
    assert "teacher_edits" not in _dumps(parent_body)
    assert "review" not in _dumps(parent_body)
    # the draft route is teacher-only; the parent projection has no such handle
    assert "/teacher/" not in _dumps(parent_body)




# ===========================================================================
# §三 / §6 frozen-copy anchor — the second and third assertion groups.
#
# The literals below are transcribed from the two SIGNED originals and are the
# independent reference for this test (they are deliberately NOT read out of
# config/pr5_frozen_copy.json — a self-referential check would pass even if the
# extractor mangled the wording):
#
#   施工令 PR-5 (2026-10-20) §三         sha256 C7BBF6EE…F736D5
#   设计书 v1.1 第 6 章                  sha256 753A691F…737429
#
# scripts/extract_pr5_frozen_copy.py pins the same two digests, so the chain is
#   signed original -> extractor (hash-gated) -> JSON -> front-end constant
# and every hop is covered by an assertion here.
# ===========================================================================

FRONTEND_LIB = os.path.join(REPO_ROOT, "frontend", "src", "lib")
FROZEN_COPY_JSON = os.path.join(REPO_ROOT, "config", "pr5_frozen_copy.json")

#: 施工令 §三 band 家长友好名 — 3 bands x 3 languages, character for character.
FROZEN_BAND_GRID = {
    "P1-P3": {
        "en": "Lower Primary (P1–P3)",
        "zh-hk": "小學低年級組（P1–P3）",
        "zh-cn": "小学低年级组（P1–P3）",
    },
    "P4-P6": {
        "en": "Upper Primary (P4–P6)",
        "zh-hk": "小學高年級組（P4–P6）",
        "zh-cn": "小学高年级组（P4–P6）",
    },
    "S1-S3": {
        "en": "Secondary (S1–S3)",
        "zh-hk": "中學組（S1–S3）",
        "zh-cn": "中学组（S1–S3）",
    },
}

#: 施工令 §三 "等级名沿用冻结名" line (order: 3 / 2 / 1 / 0).
FROZEN_LEVEL_NAMES = {
    "en": ["Exemplary", "Achieved", "Developing", "Not Yet"],
    "zh-hk": ["出色", "達標", "進展中", "尚未開始"],
    "zh-cn": ["出色", "达标", "进展中", "尚未开始"],
}

#: 施工令 §三 banned-term list (render layer + payload layer).
FROZEN_BANNED_TERMS = (
    "IB",
    "ATL",
    "Inquirer",
    "Learner Profile",
    "Proficient",
    "Excellent",
    "kid_label",
    "citations",
    "cost",
    "P1-P3",
    "P4-P6",
    "S1-S3",
)

#: 设计书 v1.1 §6 — heading / purpose / columns / nine rows / standard answer.
FROZEN_CROSSWALK = {
    "sectionHeading": "## 第 6 章　老师 crosswalk 一页纸（内部专用，永不出家长版）",
    "purpose": "用途：老师口头向家长解释评分依据的统一口径；印一张过胶贴住工位即可。",
    "columns": {
        "parentSees": "家长版见到",
        "internal": "内部对应（IB ATL）",
        "oralBridge": "口头桥示例（广东话）",
    },
    "rows": [
        ("Dream（想象）", "Thinking Skills — Creative Thinking",
         "「即係國際課程講嘅創意思維——我哋睇佢作品有幾原創。」"),
        ("Discover（探究）", "Research ＋ Critical Thinking",
         "「即係資訊素養同事實查核——佢識唔識『先查證再信』。」"),
        ("Design（创造）", "Communication — Literacy ＋ 執行力",
         "「即係將諗法變成成品嘅能力，仲要識改到更好。」"),
        ("Deliver（分享）", "Communication — Exchanging Information",
         "「即係口頭表達同台上自信。」"),
        ("等级 3 Exemplary", "超出年级期望",
         "「佢做嘅嘢已經超越呢個年級嘅要求。」"),
        ("等级 2 Achieved", "达到年级期望",
         "「佢穩穩陣陣達到咗要求。」"),
        ("等级 1 Developing", "发展中，需要支架",
         "「佢喺路上，仲需要多啲扶一扶。」"),
        ("等级 0 Not Yet", "尚未展现（非批评）",
         "「唔係佢差，係呢項未開始評——下階段先係重頭。」"),
        ("Learner Profile 亮点", "IB Learner Profile",
         "「國際課程會叫呢啲做學習者特質，我哋報告用返自己嘅小朋友语言。」"),
    ],
    "standardAnswer": (
        "若家长直接问「系咪 IB 嗰套？」标准答案：「我哋把尺同國際課程嘅能力框架對齊，"
        "但用 Dreamer 自己嘅语言同作品证据嚟呈现，等家长唔使读教育学都睇得明。」"
    ),
}


def _read_text_utf8(path: str) -> str:
    with open(path, "r", encoding="utf-8") as fh:
        return fh.read()


def _frozen_copy() -> dict:
    return json.loads(_read_text_utf8(FROZEN_COPY_JSON))


def _ts_band_grid(source: str) -> dict:
    """Parse `BAND_LABELS` out of parentReportCopy.ts (keys + 3 cells each)."""
    import re

    block = source.split("export const BAND_LABELS", 1)[1].split("};", 1)[0]
    grid = {}
    for code, body in re.findall(
        r"'(P1-P3|P4-P6|S1-S3)':\s*\{(.*?)\}", block, re.S
    ):
        cells = dict(
            (lang.strip("'"), text)
            for lang, text in re.findall(
                r"(en|'zh-hk'|'zh-cn'):\s*'([^']*)'", body
            )
        )
        grid[code] = cells
    return grid


def _ts_level_names(source: str) -> dict:
    """Parse `LEVEL_LABELS` out of parentReportCopy.ts (lang -> [3,2,1,0])."""
    import re

    block = source.split("export const LEVEL_LABELS", 1)[1].split("};", 1)[0]
    names = {}
    for key, body in re.findall(r"(en|'zh-hk'|'zh-cn'):\s*\{(.*?)\}", block, re.S):
        ordered = dict(re.findall(r"(\d):\s*'([^']*)'", body))
        names[key.strip("'")] = [ordered[str(n)] for n in (3, 2, 1, 0)]
    return names


# ---------------------------------------------------------------------------
# 三语九格 band 文案 — 逐字锚点
# ---------------------------------------------------------------------------


def test_band_grid_machine_copy_matches_signed_brief():
    """config/pr5_frozen_copy.json == 施工令 §三, all nine cells."""
    grid = _frozen_copy()["bandLabels"]
    assert list(grid) == list(FROZEN_BAND_GRID), grid
    for code, cells in FROZEN_BAND_GRID.items():
        assert grid[code] == cells, f"band {code} drifted: {grid[code]!r}"
        for lang, text in cells.items():
            assert text.strip() != code, f"{code}/{lang} is the raw code"


def test_band_grid_frontend_constant_matches_signed_brief():
    """parentReportCopy.BAND_LABELS == 施工令 §三, all nine cells, same mapping."""
    source = _read_text_utf8(os.path.join(FRONTEND_LIB, "parentReportCopy.ts"))
    grid = _ts_band_grid(source)
    assert set(grid) == set(FROZEN_BAND_GRID), grid
    for code, cells in FROZEN_BAND_GRID.items():
        assert grid[code] == cells, f"front-end band {code} drifted: {grid[code]!r}"


def test_level_names_machine_copy_and_frontend_match_signed_brief():
    """§三 frozen level names (3/2/1/0) in both the JSON and the TS constant."""
    machine = _frozen_copy()["levelNames"]
    assert machine == FROZEN_LEVEL_NAMES, machine

    source = _read_text_utf8(os.path.join(FRONTEND_LIB, "parentReportCopy.ts"))
    assert _ts_level_names(source) == FROZEN_LEVEL_NAMES


def test_banned_terms_machine_copy_matches_signed_brief():
    """§三 banned-term list (12 terms, order included) is the frozen copy's list."""
    assert tuple(_frozen_copy()["forbiddenTerms"]) == FROZEN_BANNED_TERMS
    # the payload-layer subset used above must stay inside the frozen list
    assert set(BANNED_TERMS) <= set(FROZEN_BANNED_TERMS)


# ---------------------------------------------------------------------------
# crosswalk §6 九行 — 逐字锚点
# ---------------------------------------------------------------------------


def test_crosswalk_machine_copy_matches_signed_design_book():
    """config/pr5_frozen_copy.json == 设计书 §6: heading, purpose, columns, 9 rows."""
    crosswalk = _frozen_copy()["crosswalk"]
    assert crosswalk["sectionHeading"] == FROZEN_CROSSWALK["sectionHeading"]
    assert crosswalk["title"] == FROZEN_CROSSWALK["sectionHeading"][3:]
    assert crosswalk["purpose"] == FROZEN_CROSSWALK["purpose"]
    assert crosswalk["columns"] == FROZEN_CROSSWALK["columns"]
    assert crosswalk["standardAnswer"] == FROZEN_CROSSWALK["standardAnswer"]

    rows = [
        (row["parentSees"], row["internal"], row["oralBridge"])
        for row in crosswalk["rows"]
    ]
    assert len(rows) == 9, f"§6 must stay nine rows, got {len(rows)}"
    assert rows == FROZEN_CROSSWALK["rows"]


def test_crosswalk_frontend_constant_matches_signed_design_book():
    """teacherCrosswalk.ts carries every §6 cell verbatim (9 rows x 3 cells)."""
    source = _read_text_utf8(os.path.join(FRONTEND_LIB, "teacherCrosswalk.ts"))

    assert f'"{FROZEN_CROSSWALK["sectionHeading"]}"' in source
    assert f'"{FROZEN_CROSSWALK["purpose"]}"' in source
    assert f'"{FROZEN_CROSSWALK["standardAnswer"]}"' in source
    for key, text in FROZEN_CROSSWALK["columns"].items():
        assert f"{key}: \"{text}\"" in source, (key, text)

    # Rows are indented 4 spaces; the column-head object only 2 (the interface
    # annotation carries no string literal). 9 rows => 9 indented row markers.
    row_marker = '\n    parentSees: "'
    assert source.count(row_marker) == 9, (
        f"expected exactly nine crosswalk rows, got {source.count(row_marker)}"
    )
    for index, (parent_sees, internal, oral_bridge) in enumerate(
        FROZEN_CROSSWALK["rows"], start=1
    ):
        for cell in (parent_sees, internal, oral_bridge):
            assert f'"{cell}"' in source, f"row {index} cell not verbatim: {cell!r}"

    # verbatim means byte-identical, not "same meaning": no doubled spaces or
    # straight-quote substitutions smuggled into the Cantonese oral bridges.
    for _, _, oral_bridge in FROZEN_CROSSWALK["rows"]:
        assert "  " not in oral_bridge


def test_parent_pages_never_import_the_teacher_crosswalk():
    """§B4/A6: the crosswalk is teacher-only — no parent module may import it."""
    parent_dir = os.path.join(REPO_ROOT, "frontend", "src", "pages", "parent")
    offenders = []
    for name in sorted(os.listdir(parent_dir)):
        if not name.endswith((".tsx", ".ts")):
            continue
        text = _read_text_utf8(os.path.join(parent_dir, name))
        if "teacherCrosswalk" in text or "CROSSWALK_ROWS" in text:
            offenders.append(name)
    guard = _read_text_utf8(
        os.path.join(REPO_ROOT, "frontend", "src", "hooks", "useParentReportsGuard.ts")
    )
    assert "teacherCrosswalk" not in guard and "CROSSWALK_ROWS" not in guard
    assert offenders == [], f"parent module(s) importing the crosswalk: {offenders}"
