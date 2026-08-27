"""
Phase 7 B22 — health_monitor --check-kb runtime KB fail-loud tests.

Covers the check_kb decision matrix (aligned with `seed_kb --check` runtime
semantics; source frontmatter validation is intentionally NOT here):
  - ok path (content KBs raw_documents>0, embeddings ok)            -> exit 0
  - KB count = 0                                                    -> exit 1
  - content KB raw_documents = 0                                    -> exit 1
  - structural KB (expected_doc_count 0) raw 0 is NOT a failure     -> exit 0
  - embedding profile failure                                       -> exit 1
  - DeepTutor unreachable                                           -> exit 3
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import health_monitor  # noqa: E402
import seed_kb  # noqa: E402


class FakeAPI:
    """Stub TutorAPI: health / list_kbs / test_embeddings with settable state."""

    def __init__(self) -> None:
        self.health_resp = {"status": "ok", "knowledge_bases_count": 2}
        self.kbs = [
            {"name": "dreamer-ethical-ai", "statistics": {"raw_documents": 6}},
            {"name": "dreamer-assessment", "statistics": {}},
        ]
        self.embedding_ok = True
        self.not_ready = False

    def health(self):
        if self.not_ready:
            raise seed_kb.SeedError("connection refused")
        return self.health_resp

    def list_kbs(self):
        return self.kbs

    def test_embeddings(self):
        if not self.embedding_ok:
            raise seed_kb.SeedError("ollama unreachable")


MANIFEST_TMPL = """\
version: 1
last_updated: "2026-08-27"
knowledge_bases:
  - name: dreamer-ethical-ai
    rag_provider: llamaindex
    docs_dir: dreamer-ethical-ai/
    expected_doc_count: 6
  - name: dreamer-assessment
    rag_provider: llamaindex
    docs_dir: dreamer-assessment/
    expected_doc_count: 0
"""


@pytest.fixture
def manifest(tmp_path):
    p = tmp_path / "manifest.yaml"
    p.write_text(MANIFEST_TMPL, encoding="utf-8")
    return p


@pytest.fixture
def fake_api(monkeypatch):
    api = FakeAPI()
    monkeypatch.setattr(
        seed_kb, "TutorAPI", lambda base, timeout: api
    )
    return api


def test_ok(fake_api, manifest):
    code, msg = health_monitor.check_kb("http://x", str(manifest))
    assert code == seed_kb.EXIT_OK
    assert "KB ok" in msg


def test_count_zero_fail_loud(fake_api, manifest):
    fake_api.health_resp = {"status": "ok", "knowledge_bases_count": 0}
    code, msg = health_monitor.check_kb("http://x", str(manifest))
    assert code == seed_kb.EXIT_VERIFY_FAIL
    assert "count = 0" in msg


def test_content_raw_zero_fail_loud(fake_api, manifest):
    fake_api.kbs[0]["statistics"]["raw_documents"] = 0
    code, msg = health_monitor.check_kb("http://x", str(manifest))
    assert code == seed_kb.EXIT_VERIFY_FAIL
    assert "raw_documents = 0" in msg


def test_structural_raw_zero_is_ok(fake_api, manifest):
    # dreamer-assessment (expected_doc_count=0) reports no statistics:
    # raw_documents=0 must NOT trigger fail-loud.
    code, msg = health_monitor.check_kb("http://x", str(manifest))
    assert code == seed_kb.EXIT_OK


def test_embedding_failure_fail_loud(fake_api, manifest):
    fake_api.embedding_ok = False
    code, msg = health_monitor.check_kb("http://x", str(manifest))
    assert code == seed_kb.EXIT_VERIFY_FAIL
    assert "embedding" in msg


def test_api_unreachable_not_ready(fake_api, manifest):
    fake_api.not_ready = True
    code, msg = health_monitor.check_kb("http://x", str(manifest))
    assert code == seed_kb.EXIT_NOT_READY
