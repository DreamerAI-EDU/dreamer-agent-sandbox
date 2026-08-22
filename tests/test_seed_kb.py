"""Phase 7 B21 — seed_kb.py tests.

Covers spec §2.3 frontmatter validation, §2.4 config generation, §2.6
idempotency, exit codes (§2.7), and the acceptance-check failure paths
(spec §8 items 5/6) with the HTTP layer mocked (convention #12 monkeypatch,
no reliance on external env / container).
"""

from __future__ import annotations

import json
import textwrap

import pytest

import scripts.seed_kb as seed


# --- fixtures ----------------------------------------------------------------

@pytest.fixture
def kb_fs(tmp_path, monkeypatch):
    """Build a throwaway repo layout (kb/manifest.yaml + knowledge_bases/)."""
    kb_sot = tmp_path / "knowledge_bases"
    kb_sot.mkdir()
    runtime = tmp_path / "deeptutor" / "kb_runtime"
    runtime.mkdir(parents=True)

    manifest_path = tmp_path / "kb" / "manifest.yaml"
    manifest_path.parent.mkdir()

    good_md = textwrap.dedent("""\
        ---
        topic_id: ethical-ai-bias-01
        subject: AI Ethics
        topic: "Bias and Fairness"
        dreamer_phase: Dream
        modes_allowed:
          - contextual
          - direct
        grade_level: P4-P6
        kb_name: dreamer-ethical-ai
        ib_atl_skills:
          - thinking-critical
        ethical_ai_tags:
          - fairness
        ---
        # Body
        Students explore fairness in AI systems.
        """)

    (kb_sot / "dreamer-ethical-ai").mkdir()
    (kb_sot / "dreamer-ethical-ai" / "ethical-ai-bias-01.md").write_text(
        good_md, encoding="utf-8"
    )
    (kb_sot / "dreamer-maths-ai").mkdir()
    (kb_sot / "dreamer-maths-ai" / "maths-fractions-01.md").write_text(
        textwrap.dedent("""\
            ---
            topic_id: maths-fractions-01
            subject: maths
            topic: "Fractions"
            dreamer_phase: Discover
            modes_allowed:
              - direct
            grade_level: P4-P6
            kb_name: dreamer-maths-ai
            ---
            # Fractions
            Fraction basics.
            """)
        , encoding="utf-8")

    manifest = textwrap.dedent("""\
        version: 1
        last_updated: "2026-08-22"
        knowledge_bases:
          - name: dreamer-ethical-ai
            rag_provider: llamaindex
            docs_dir: dreamer-ethical-ai/
            expected_doc_count: 1
          - name: dreamer-maths-ai
            rag_provider: llamaindex
            docs_dir: dreamer-maths-ai/
            expected_doc_count: 1
        """)
    manifest_path.write_text(manifest, encoding="utf-8")

    monkeypatch.setattr(seed, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(seed, "MANIFEST_PATH", manifest_path)
    monkeypatch.setattr(seed, "KB_SOT_DIR", kb_sot)
    monkeypatch.setattr(seed, "KB_RUNTIME_DIR", runtime)
    monkeypatch.setattr(seed, "STATE_FILE", runtime / ".seed_state.json")
    return {
        "tmp_path": tmp_path,
        "kb_sot": kb_sot,
        "runtime": runtime,
        "good_md": good_md,
    }


# --- manifest validation -----------------------------------------------------

def test_manifest_load_ok(kb_fs):
    manifest = seed.load_manifest(seed.MANIFEST_PATH)
    assert manifest["version"] == 1
    assert [kb["name"] for kb in manifest["knowledge_bases"]] == [
        "dreamer-ethical-ai", "dreamer-maths-ai"
    ]


def test_manifest_missing_field(kb_fs):
    path = kb_fs["tmp_path"] / "kb" / "manifest.yaml"
    path.write_text(
        "version: 1\nknowledge_bases:\n  - name: x\n    rag_provider: llamaindex\n",
        encoding="utf-8",
    )
    with pytest.raises(seed.SeedError, match="docs_dir"):
        seed.load_manifest(path)


def test_manifest_duplicate_name(kb_fs):
    path = kb_fs["tmp_path"] / "kb" / "manifest.yaml"
    path.write_text(
        "version: 1\nknowledge_bases:\n"
        "  - {name: a, rag_provider: llamaindex, docs_dir: a/, expected_doc_count: 1}\n"
        "  - {name: a, rag_provider: llamaindex, docs_dir: b/, expected_doc_count: 1}\n",
        encoding="utf-8",
    )
    with pytest.raises(seed.SeedError, match="duplicate"):
        seed.load_manifest(path)


# --- frontmatter validation (spec §2.3) -------------------------------------

def _write(kb_fs, kb, fname, content):
    p = kb_fs["kb_sot"] / kb / fname
    p.parent.mkdir(exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return p


def _fm(**overrides):
    body = overrides.pop("__body", "# Body\nContent here.")
    base = {
        "topic_id": "t-01",
        "subject": "AI Ethics",
        "topic": "T",
        "dreamer_phase": "Dream",
        "modes_allowed": ["contextual"],
        "grade_level": "P4-P6",
        "kb_name": "dreamer-ethical-ai",
    }
    base.update(overrides)
    yaml_block = "\n".join(
        f"{k}: {json.dumps(v) if isinstance(v, list) else v}" for k, v in base.items()
    )
    return f"---\n{yaml_block}\n---\n{body}"


def test_frontmatter_ok(kb_fs):
    assert seed.validate_frontmatter(
        _write(kb_fs, "dreamer-ethical-ai", "ok.md", _fm()), "dreamer-ethical-ai"
    ) == []


def test_frontmatter_grade_level_m1_rejected(kb_fs):
    errs = seed.validate_frontmatter(
        _write(kb_fs, "dreamer-ethical-ai", "bad-grade.md", _fm(grade_level="M1-M3")),
        "dreamer-ethical-ai",
    )
    assert any("grade_level" in e for e in errs)


def test_frontmatter_span_exception_allowed(kb_fs):
    # Spec §10.3: internal KBs may use P1-S3 cross-span.
    assert seed.validate_frontmatter(
        _write(kb_fs, "dreamer-ethical-ai", "span.md", _fm(grade_level="P1-S3")),
        "dreamer-ethical-ai",
    ) == []


def test_frontmatter_span_exception_not_for_other_kb(kb_fs):
    errs = seed.validate_frontmatter(
        _write(kb_fs, "dreamer-maths-ai", "span.md", _fm(kb_name="dreamer-maths-ai", grade_level="P1-S3")),
        "dreamer-maths-ai",
    )
    assert any("grade_level" in e for e in errs)


def test_frontmatter_phantom_field_rejected(kb_fs):
    errs = seed.validate_frontmatter(
        _write(kb_fs, "dreamer-ethical-ai", "phantom.md",
               _fm(domain_agent_owner="compere-agent")),
        "dreamer-ethical-ai",
    )
    assert any("domain_agent_owner" in e for e in errs)


def test_frontmatter_atl_in_body_rejected(kb_fs):
    errs = seed.validate_frontmatter(
        _write(kb_fs, "dreamer-ethical-ai", "atl.md",
               _fm(__body="# Body\nStudents use ATL skills here.")),
        "dreamer-ethical-ai",
    )
    assert any("ATL" in e for e in errs)


def test_frontmatter_ib_atl_fieldname_allowed(kb_fs):
    # ib_atl_skills as a frontmatter field is metadata, not body text.
    errs = seed.validate_frontmatter(
        _write(kb_fs, "dreamer-ethical-ai", "atlfield.md",
               _fm(**{"ib_atl_skills": ["thinking-critical"]})),
        "dreamer-ethical-ai",
    )
    assert not any("ATL" in e for e in errs)


def test_frontmatter_aigc_marker_rejected(kb_fs):
    errs = seed.validate_frontmatter(
        _write(kb_fs, "dreamer-ethical-ai", "aigc.md",
               "---\nAIGC:\n    ContentProducer: x\n---\n# Body\n"),
        "dreamer-ethical-ai",
    )
    assert any("AIGC" in e for e in errs)


def test_frontmatter_missing_required(kb_fs):
    content = textwrap.dedent("""\
        ---
        subject: AI Ethics
        topic: T
        dreamer_phase: Dream
        modes_allowed:
          - contextual
        grade_level: P4-P6
        kb_name: dreamer-ethical-ai
        ---
        # Body
        """)
    errs = seed.validate_frontmatter(
        _write(kb_fs, "dreamer-ethical-ai", "missing.md", content),
        "dreamer-ethical-ai",
    )
    assert any("topic_id" in e for e in errs)


def test_frontmatter_bad_modes(kb_fs):
    errs = seed.validate_frontmatter(
        _write(kb_fs, "dreamer-ethical-ai", "modes.md", _fm(modes_allowed=["weird"])),
        "dreamer-ethical-ai",
    )
    assert any("modes_allowed" in e for e in errs)


# --- config generation (spec §2.4 + samples contract) ------------------------

def test_metadata_format(kb_fs):
    meta = seed.build_metadata("dreamer-ethical-ai")
    assert meta["name"] == "dreamer-ethical-ai"
    assert meta["rag_provider"] == "llamaindex"
    assert meta["needs_reindex"] is True
    # created_at uses space separator (samples contract), not T.
    assert "T" not in meta["created_at"]
    assert meta["created_at"].count(" ") == 1


def test_kb_config_preserves_runtime_state(kb_fs):
    manifest = seed.load_manifest(seed.MANIFEST_PATH)
    runtime_config = {
        "knowledge_bases": {
            "dreamer-ethical-ai": {
                "rag_provider": "llamaindex",
                "status": "ready",
                "index_versions": [{"version": "version-1", "ready": True}],
            }
        }
    }
    cfg, changed = seed.build_kb_config(manifest, runtime_config)
    assert changed is True
    entry = cfg["knowledge_bases"]["dreamer-ethical-ai"]
    assert entry["status"] == "ready"  # runtime state preserved
    assert entry["index_versions"][0]["version"] == "version-1"
    # New KB gets a registered stub.
    assert cfg["knowledge_bases"]["dreamer-maths-ai"]["status"] == "registered"


# --- mirror + idempotency (spec §2.6) ----------------------------------------

def test_mirror_md_files_and_idempotent(kb_fs):
    src = kb_fs["kb_sot"] / "dreamer-ethical-ai"
    dst = kb_fs["runtime"] / "dreamer-ethical-ai" / "raw"
    changed = seed.mirror_md_files(src, dst, "dreamer-ethical-ai")
    assert len(changed) == 1
    assert (dst / "ethical-ai-bias-01.md").exists()
    # Second run: nothing changed (same hash).
    changed2 = seed.mirror_md_files(src, dst, "dreamer-ethical-ai")
    assert changed2 == []


def test_mirror_removes_stale(kb_fs):
    src = kb_fs["kb_sot"] / "dreamer-ethical-ai"
    dst = kb_fs["runtime"] / "dreamer-ethical-ai" / "raw"
    dst.mkdir(parents=True)
    (dst / "stale.md").write_text("old", encoding="utf-8")
    seed.mirror_md_files(src, dst, "dreamer-ethical-ai")
    assert not (dst / "stale.md").exists()


# --- HTTP-failure paths (monkeypatch, convention #12) ------------------------

class FakeAPI:
    def __init__(self, **kwargs):
        self.kwargs = kwargs


def _fake_api_factory(health, kbs, reindex_exc=None, kb_status=None):
    class _Fake:
        def __init__(self, *args, **kwargs):
            self._reindex_exc = reindex_exc

        def health(self):
            return health

        def list_kbs(self):
            return kbs

        def kb_status(self, kb_name):
            if kb_status is not None:
                return kb_status(kb_name)
            return {"statistics": {"raw_documents": 1, "needs_reindex": False}}

        def reindex(self, kb_name):
            if self._reindex_exc:
                raise self._reindex_exc
            return {}

        def test_embeddings(self):
            return {}

    return _Fake


def test_check_kb_count_zero_fails(monkeypatch, kb_fs, capsys):
    monkeypatch.setattr(seed, "TutorAPI", _fake_api_factory(
        {"status": "ok", "knowledge_bases_count": 0}, []
    ))
    args = seed.argparse.Namespace(api_base="http://x", timeout=1.0, wait=1.0)
    assert seed.cmd_check(args) == seed.EXIT_VERIFY_FAIL
    out = capsys.readouterr().out
    assert "KB count = 0" in out


def test_check_embedding_failure_fails(monkeypatch, kb_fs, capsys):
    class _Bad:
        def __init__(self, *a, **k):
            pass

        def health(self):
            return {"status": "ok", "knowledge_bases_count": 2}

        def list_kbs(self):
            return [{"name": "dreamer-ethical-ai",
                     "statistics": {"raw_documents": 1}}]

        def test_embeddings(self):
            raise seed.SeedError("no embedding model")

    monkeypatch.setattr(seed, "TutorAPI", _Bad)
    args = seed.argparse.Namespace(api_base="http://x", timeout=1.0, wait=1.0)
    assert seed.cmd_check(args) == seed.EXIT_VERIFY_FAIL


def test_sync_reindex_failure_exits_verify_fail(monkeypatch, kb_fs, capsys):
    """Convention #12: failure is injected via monkeypatch, not filesystem
    side effects."""
    monkeypatch.setattr(seed, "restart_container", lambda: None)
    monkeypatch.setattr(seed, "wait_ready", lambda api, t: True)
    monkeypatch.setattr(seed, "TutorAPI", _fake_api_factory(
        {"status": "ok", "knowledge_bases_count": 2},
        [{"name": "dreamer-ethical-ai", "statistics": {"raw_documents": 1}},
         {"name": "dreamer-maths-ai", "statistics": {"raw_documents": 1}}],
        reindex_exc=seed.SeedError("reindex boom"),
    ))
    args = seed.argparse.Namespace(api_base="http://x", timeout=1.0, wait=1.0)
    assert seed.cmd_sync(args) == seed.EXIT_VERIFY_FAIL
    out = capsys.readouterr().out
    assert "reindex boom" in out


def test_sync_noop_when_nothing_changed(monkeypatch, kb_fs, capsys):
    """Spec §2.6: unchanged hashes => no reindex, no restart, exit 0."""
    calls = {"restart": 0, "reindex": []}

    def fake_restart():
        calls["restart"] += 1

    class _Fake:
        def __init__(self, *a, **k):
            pass

        def health(self):
            return {"status": "ok", "knowledge_bases_count": 2}

        def kb_status(self, kb_name):
            return {"statistics": {"raw_documents": 1, "needs_reindex": False}}

        def reindex(self, kb_name):
            calls["reindex"].append(kb_name)
            return {}

    monkeypatch.setattr(seed, "restart_container", fake_restart)
    monkeypatch.setattr(seed, "wait_ready", lambda api, t: True)
    monkeypatch.setattr(seed, "TutorAPI", _Fake)

    args = seed.argparse.Namespace(api_base="http://x", timeout=1.0, wait=1.0)
    # First sync populates state and config.
    assert seed.cmd_sync(args) == seed.EXIT_OK
    assert calls["restart"] == 1
    assert set(calls["reindex"]) == {"dreamer-ethical-ai", "dreamer-maths-ai"}

    # Second sync: same hashes + same config => no-op.
    calls["restart"] = 0
    calls["reindex"] = []
    assert seed.cmd_sync(args) == seed.EXIT_OK
    assert calls["restart"] == 0
    assert calls["reindex"] == []
