#!/usr/bin/env python3
"""Phase 7 B21 — KB seed mechanism.

Three modes:
  --check            read-only validation (manifest + frontmatter + API status)
  --sync  (default)  full pipeline: sync -> config -> restart -> reindex -> verify
  --force-rebuild    wipe runtime config + full reindex (requires --confirm)

Contract references:
  - spec:   docs/phase7-B21-kb-seed-規格.md §2
  - config: docs/phase7-kb-config-samples.md

Design invariants (from spec + probe findings):
  - Host is the ONLY write path (container kb_sot is ro). We write runtime KBs
    under deeptutor/kb_runtime/ which is mounted rw at /app/data/knowledge_bases.
  - Reindex only scans KB/raw/ (recursive). Source md files must live there.
  - Config (kb_config.json / metadata.json) is generated from manifest (SoT),
    but runtime state fields (index_versions / last_indexed_*) owned by
    DeepTutor are preserved, never clobbered.
  - Idempotent: unchanged doc hashes skip reindex; unchanged config skips restart.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:  # pragma: no cover - environment setup issue
    yaml = None

REPO_ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = REPO_ROOT / "kb" / "manifest.yaml"
KB_SOT_DIR = REPO_ROOT / "knowledge_bases"
KB_RUNTIME_DIR = REPO_ROOT / "deeptutor" / "kb_runtime"
STATE_FILE = KB_RUNTIME_DIR / ".seed_state.json"
DOCKER_CONTAINER = "dreamer-deeptutor"
DEFAULT_API_BASE = "http://127.0.0.1:8001"

# --- Spec §2.3 validation rules ----------------------------------------------

REQUIRED_FRONTMATTER = {
    "topic_id", "subject", "topic", "modes_allowed",
    "grade_level", "kb_name", "dreamer_phase",
}
ALLOWED_GRADE_LEVELS = {"P1-P3", "P4-P6", "S1-S3"}
ALLOWED_MODES = {"contextual", "direct", "hybrid"}
# Spec §10.3: internal (agent-facing) KBs may use cross-span grade_level.
SPAN_EXCEPTION_KBS = {"dreamer-assessment", "dreamer-ethical-ai"}
SPAN_GRADE_LEVELS = {"P1-S3"}
FORBIDDEN_FIELDS = {"domain_agent_owner"}
RUBRIC_LEGACY_WORDS = (
    "Emerging", "Proficient", "Mastering",
    "Exceeds Expectations", "Meets Expectations",
)
IB_ATL_WORDS = ("IB", "ATL", "Approaches to Learning")
AIGC_MARKERS = ("ContentProducer", "内容由AI")

EXIT_OK = 0
EXIT_VERIFY_FAIL = 1
EXIT_MANIFEST_FAIL = 2
EXIT_NOT_READY = 3


class SeedError(Exception):
    """Raised for validation failures with a user-facing message."""


# --- Utilities ---------------------------------------------------------------

def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def load_manifest(manifest_path: Path) -> dict[str, Any]:
    if not manifest_path.exists():
        raise SeedError(f"manifest not found: {manifest_path}")
    if yaml is None:
        raise SeedError("PyYAML is required (pip install PyYAML>=6.0)")
    with open(manifest_path, encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    if not isinstance(data, dict) or data.get("version") != 1:
        raise SeedError("manifest must have version: 1")
    kbs = data.get("knowledge_bases")
    if not isinstance(kbs, list) or not kbs:
        raise SeedError("manifest must contain non-empty knowledge_bases list")
    names: set[str] = set()
    for entry in kbs:
        if not isinstance(entry, dict):
            raise SeedError("knowledge_bases entries must be mappings")
        name = entry.get("name")
        if not name or not isinstance(name, str):
            raise SeedError("each KB entry needs string name")
        if name in names:
            raise SeedError(f"duplicate KB name in manifest: {name}")
        names.add(name)
        for key in ("rag_provider", "docs_dir", "expected_doc_count"):
            if key not in entry:
                raise SeedError(f"KB {name}: missing manifest field '{key}'")
        if not isinstance(entry["expected_doc_count"], int) or entry["expected_doc_count"] < 0:
            raise SeedError(f"KB {name}: expected_doc_count must be non-negative int")
    return data


def split_frontmatter(text: str) -> tuple[dict[str, Any], str] | None:
    """Return (frontmatter dict, body text) or None if no frontmatter block."""
    if not text.startswith("---\n") and not text.startswith("---\r\n"):
        return None
    lines = text.splitlines()
    end = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end = i
            break
    if end is None:
        return None
    fm_text = "\n".join(lines[1:end])
    body = "\n".join(lines[end + 1:])
    try:
        fm = yaml.safe_load(fm_text)
    except yaml.YAMLError as exc:
        raise SeedError(f"frontmatter YAML parse error: {exc}") from exc
    if not isinstance(fm, dict):
        raise SeedError("frontmatter must be a YAML mapping")
    return fm, body


def validate_frontmatter(md_path: Path, kb_name: str) -> list[str]:
    """Validate one md file against spec §2.3. Return list of errors (empty=ok)."""
    errors: list[str] = []
    text = md_path.read_text(encoding="utf-8", errors="replace")
    if "ContentProducer" in text or "内容由AI" in text:
        errors.append("AIGC metadata marker found (ContentProducer / 内容由AI)")

    parts = split_frontmatter(text)
    if parts is None:
        errors.append("missing YAML frontmatter block")
        return errors
    fm, body = parts

    missing = sorted(
        f for f in REQUIRED_FRONTMATTER
        if f not in fm or fm[f] is None
    )
    if missing:
        errors.append(f"missing required fields: {', '.join(missing)}")

    for forbidden in FORBIDDEN_FIELDS:
        if forbidden in fm:
            errors.append(f"forbidden field present: {forbidden} (phantom)")

    grade = fm.get("grade_level")
    allowed = set(ALLOWED_GRADE_LEVELS)
    if kb_name in SPAN_EXCEPTION_KBS:
        allowed |= SPAN_GRADE_LEVELS
    if grade is not None and grade not in allowed:
        errors.append(
            f"grade_level '{grade}' not in allowed set {sorted(allowed)}"
        )

    modes = fm.get("modes_allowed")
    if modes is not None:
        if not isinstance(modes, list) or not modes:
            errors.append("modes_allowed must be a non-empty list")
        else:
            bad = [m for m in modes if m not in ALLOWED_MODES]
            if bad:
                errors.append(f"modes_allowed contains invalid values: {bad}")

    # Body-only checks: legacy rubric words are warnings, IB/ATL are FAIL.
    for word in IB_ATL_WORDS:
        if word in body:
            errors.append(f"body contains forbidden IB/ATL term: '{word}'")

    warnings: list[str] = []
    for word in RUBRIC_LEGACY_WORDS:
        if word in body:
            warnings.append(f"body contains legacy rubric word: '{word}'")

    # Attach warnings to caller via side channel (keep simple: print).
    if warnings:
        print(f"  [WARNING] {md_path.name}: " + "; ".join(warnings))
    return errors


def validate_manifest_kbs(manifest: dict[str, Any]) -> dict[str, Any]:
    """Cross-check manifest against SoT docs; raise SeedError on fatal issues."""
    kbs: dict[str, Any] = {}
    for entry in manifest["knowledge_bases"]:
        name = entry["name"]
        docs_dir = KB_SOT_DIR / entry["docs_dir"]
        if not docs_dir.is_dir():
            raise SeedError(f"KB {name}: docs_dir not found: {docs_dir}")
        md_files = sorted(docs_dir.glob("*.md"))
        expected = entry["expected_doc_count"]
        if len(md_files) != expected:
            print(
                f"  [WARNING] KB {name}: expected_doc_count={expected} "
                f"but found {len(md_files)} md files (content ramp-up ok, "
                f"count=0 fails)"
            )
        entry["_md_files"] = md_files
        entry["_docs_dir"] = docs_dir
        kbs[name] = entry
    return kbs


# --- Config generation (spec §2.4 + samples contract) ------------------------

def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="microseconds")


def now_space_format() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def build_metadata(kb_name: str) -> dict[str, Any]:
    """Initial metadata.json — only written when the KB is not yet registered."""
    return {
        "name": kb_name,
        "created_at": now_space_format(),
        "description": f"Knowledge base: {kb_name}",
        "version": "1.0",
        "rag_provider": "llamaindex",
        "needs_reindex": True,
    }


def build_kb_config(manifest: dict[str, Any], runtime_config: dict[str, Any] | None) -> dict[str, Any]:
    """Build kb_config.json from manifest while preserving DeepTutor runtime
    state (index_versions / last_indexed_* / status ready). The caller decides
    whether the result differs from the file on disk.
    """
    runtime_config = runtime_config or {}
    existing = runtime_config.get("knowledge_bases", {})
    kbs: dict[str, Any] = {}
    for entry in manifest["knowledge_bases"]:
        name = entry["name"]
        if name in existing and isinstance(existing[name], dict):
            # DeepTutor owns runtime state; keep it untouched.
            kbs[name] = dict(existing[name])
            kbs[name].setdefault("rag_provider", entry["rag_provider"])
        else:
            kbs[name] = {
                "rag_provider": entry["rag_provider"],
                "status": "registered",
            }
    return {"knowledge_bases": kbs}


# --- Runtime helpers ---------------------------------------------------------

def read_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (json.JSONDecodeError, OSError):
        return None


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
    tmp.replace(path)


def clear_kb_index(runtime_kb_dir: Path) -> None:
    """Remove version-* index directories so a subsequent reindex actually
    rebuilds. DeepTutor's reindex is a no-op while an index exists for the
    active embedding config (verified on v1.5.8); raw/ is left untouched.
    """
    for p in runtime_kb_dir.glob("version-*"):
        if p.is_dir():
            shutil.rmtree(p, ignore_errors=True)
            print(f"  [clear] {runtime_kb_dir.name}: removed {p.name}")


def index_content_files(runtime_kb_dir: Path) -> set[str] | None:
    """Ground truth of what is actually in the index: the file names recorded
    in the BM25 corpus (version-*/bm25_retriever/corpus.jsonl). Returns None
    if no index exists on disk yet.
    """
    versions = sorted(runtime_kb_dir.glob("version-*"))
    if not versions:
        return None
    corpus = versions[-1] / "bm25_retriever" / "corpus.jsonl"
    if not corpus.exists():
        return None
    names: set[str] = set()
    for line in corpus.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        fname = rec.get("file_name")
        if fname and not fname.startswith("."):
            names.add(fname)
    return names


def mirror_md_files(src_dir: Path, dst_raw_dir: Path, kb_name: str) -> list[str]:
    """Mirror *.md from SoT dir into runtime KB/raw/. Returns list of files
    that changed (added/modified/removed) since previous sync.
    """
    dst_raw_dir.mkdir(parents=True, exist_ok=True)
    src_files = {p.name: p for p in src_dir.glob("*.md")}
    changed: list[str] = []
    for name, src in src_files.items():
        dst = dst_raw_dir / name
        if not dst.exists() or sha256_file(dst) != sha256_file(src):
            shutil.copy2(src, dst)
            changed.append(name)
    for dst in dst_raw_dir.glob("*.md"):
        if dst.name not in src_files:
            dst.unlink()
            changed.append(dst.name)
    return changed


def load_state() -> dict[str, Any]:
    state = read_json(STATE_FILE)
    return state if isinstance(state, dict) else {}


def save_state(state: dict[str, Any]) -> None:
    write_json(STATE_FILE, state)


# --- DeepTutor API -----------------------------------------------------------

class TutorAPI:
    def __init__(self, api_base: str, timeout: float = 10.0):
        self.api_base = api_base.rstrip("/")
        self.timeout = timeout

    def _request(self, method: str, path: str, *, expect_json: bool = True) -> Any:
        import urllib.request

        url = f"{self.api_base}{path}"
        req = urllib.request.Request(url, method=method)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                payload = resp.read()
        except Exception as exc:  # noqa: BLE001 - surface as SeedError
            raise SeedError(f"API {method} {path} failed: {exc}") from exc
        if not expect_json:
            return payload
        try:
            return json.loads(payload)
        except json.JSONDecodeError as exc:
            raise SeedError(f"API {method} {path} returned non-JSON") from exc

    def health(self) -> dict[str, Any]:
        return self._request("GET", "/api/v1/knowledge/health")

    def list_kbs(self) -> list[dict[str, Any]]:
        return self._request("GET", "/api/v1/knowledge/list")

    def kb_status(self, kb_name: str) -> dict[str, Any]:
        return self._request("GET", f"/api/v1/knowledge/{kb_name}")

    def reindex(self, kb_name: str) -> Any:
        return self._request("POST", f"/api/v1/knowledge/{kb_name}/reindex")

    def test_embeddings(self) -> Any:
        return self._request("POST", "/api/v1/system/test/embeddings")


def wait_ready(api: TutorAPI, timeout: float = 180.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            h = api.health()
            if h.get("status") == "ok":
                return True
        except SeedError:
            pass
        time.sleep(5)
    return False


def restart_container() -> None:
    subprocess.run(
        ["docker", "restart", DOCKER_CONTAINER],
        check=True,
        capture_output=True,
        text=True,
    )


# --- Mode implementations ----------------------------------------------------

def cmd_check(args: argparse.Namespace) -> int:
    manifest = load_manifest(MANIFEST_PATH)
    print("Manifest loaded:", len(manifest["knowledge_bases"]), "KB entries")
    kbs = validate_manifest_kbs(manifest)

    fatal = 0
    for name, entry in kbs.items():
        for md in entry["_md_files"]:
            errs = validate_frontmatter(md, name)
            if errs:
                fatal += 1
                print(f"  [FAIL] {name}/{md.name}:")
                for e in errs:
                    print(f"         - {e}")
            else:
                print(f"  [OK] {name}/{md.name}")

    if fatal:
        print("Frontmatter validation failed — fix before sync.")
        return EXIT_MANIFEST_FAIL

    try:
        api = TutorAPI(args.api_base, args.timeout)
        health = api.health()
    except SeedError as exc:
        print(f"DeepTutor not ready: {exc}")
        return EXIT_NOT_READY
    print(f"DeepTutor health: {health.get('status')} "
          f"(count={health.get('knowledge_bases_count')})")
    if health.get("status") != "ok":
        return EXIT_NOT_READY
    if health.get("knowledge_bases_count", 0) == 0:
        print("[FAIL] KB count = 0 (B22 fail-loud)")
        return EXIT_VERIFY_FAIL

    kbs_api = {kb["name"]: kb for kb in api.list_kbs()}
    for name in kbs:
        status = kbs_api.get(name, {})
        raw = (status.get("statistics") or {}).get("raw_documents", 0)
        if raw == 0:
            print(f"[FAIL] KB {name}: raw_documents = 0 (B22 fail-loud)")
            return EXIT_VERIFY_FAIL
        print(f"  [OK] KB {name}: raw_documents={raw}")

    try:
        api.test_embeddings()
        print("[OK] embedding profile test passed")
    except SeedError as exc:
        print(f"[FAIL] embedding profile: {exc}")
        return EXIT_VERIFY_FAIL
    return EXIT_OK


def cmd_sync(args: argparse.Namespace, force_rebuild: bool = False) -> int:
    manifest = load_manifest(MANIFEST_PATH)
    print("Manifest loaded:", len(manifest["knowledge_bases"]), "KB entries")
    kbs = validate_manifest_kbs(manifest)

    fatal = 0
    for name, entry in kbs.items():
        for md in entry["_md_files"]:
            errs = validate_frontmatter(md, name)
            if errs:
                fatal += 1
                print(f"  [FAIL] {name}/{md.name}: {errs}")
    if fatal:
        print("Frontmatter validation failed — refusing to sync.")
        return EXIT_MANIFEST_FAIL

    KB_RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    state = load_state()
    new_state: dict[str, Any] = {}

    # 1) Mirror md into runtime raw/ + collect per-KB changed set.
    changed_kbs: set[str] = set()
    for name, entry in kbs.items():
        raw_dir = KB_RUNTIME_DIR / name / "raw"
        changed = mirror_md_files(entry["_docs_dir"], raw_dir, name)
        files = {
            p.name: sha256_file(p)
            for p in sorted(raw_dir.glob("*.md"))
        }
        old_files = (state.get(name) or {}).get("files", {})
        new_state[name] = {"files": files, "synced_at": now_iso()}
        if force_rebuild or changed or files != old_files:
            changed_kbs.add(name)
            print(f"  [sync] {name}: changed files: {', '.join(changed) or '(all)'}")

    # 2) Config generation (preserve DeepTutor runtime state).
    runtime_config = read_json(KB_RUNTIME_DIR / "kb_config.json")
    new_config = build_kb_config(manifest, runtime_config)
    config_path = KB_RUNTIME_DIR / "kb_config.json"
    config_changed = force_rebuild or (read_json(config_path) != new_config)
    write_json(config_path, new_config)

    for name, entry in kbs.items():
        meta_path = KB_RUNTIME_DIR / name / "metadata.json"
        if force_rebuild or not meta_path.exists():
            write_json(meta_path, build_metadata(name))
            changed_kbs.add(name)
            print(f"  [config] {name}: metadata.json written")

    # 3) Restart if config changed, then wait readiness.
    if config_changed or force_rebuild:
        print("[restart] config changed — restarting container…")
        try:
            restart_container()
        except subprocess.CalledProcessError as exc:
            print(f"[FAIL] docker restart failed: {exc.stderr or exc}")
            return EXIT_NOT_READY
    api = TutorAPI(args.api_base, args.timeout)
    if config_changed or force_rebuild:
        if not wait_ready(api, args.wait):
            print("[FAIL] DeepTutor did not become ready after restart")
            return EXIT_NOT_READY
        print("[restart] DeepTutor ready")

    # 4) Rebuild changed KBs: clear their index (DeepTutor reindex is a no-op
    #    while an index exists for the active embedding config), then reindex.
    reindex_failures: list[str] = []
    if changed_kbs or force_rebuild:
        targets = set(kbs) if force_rebuild else changed_kbs
        for name in sorted(targets):
            runtime_kb_dir = KB_RUNTIME_DIR / name
            print(f"  [reindex] {name}…")
            clear_kb_index(runtime_kb_dir)
            try:
                api.reindex(name)
            except SeedError as exc:
                print(f"  [FAIL] {name}: reindex request failed: {exc}")
                reindex_failures.append(name)
                continue
            if not wait_reindex_done(api, runtime_kb_dir, name, args.wait):
                print(f"  [FAIL] {name}: reindex did not complete")
                reindex_failures.append(name)
                continue
            print(f"  [reindex] {name}: done")

    save_state(new_state)

    # 5) Verify per-KB doc counts AND actual index contents. raw_documents is
    #    a raw/ directory scan (not the index); ground truth is the BM25
    #    corpus on disk.
    failures: list[str] = []
    for name, entry in kbs.items():
        expected = len(entry["_md_files"])
        runtime_kb_dir = KB_RUNTIME_DIR / name
        try:
            status = api.kb_status(name)
            raw = (status.get("statistics") or {}).get("raw_documents", 0)
        except SeedError as exc:
            print(f"  [FAIL] {name}: verify failed: {exc}")
            failures.append(name)
            continue
        if raw != expected:
            print(f"  [FAIL] {name}: raw_documents={raw} != expected {expected}")
            failures.append(name)
            continue
        expected_md = {p.name for p in entry["_md_files"]}
        indexed = index_content_files(runtime_kb_dir)
        if indexed is None:
            print(f"  [FAIL] {name}: no index found on disk")
            failures.append(name)
            continue
        missing = sorted(expected_md - indexed)
        if missing:
            print(f"  [FAIL] {name}: index missing docs: {', '.join(missing)}")
            failures.append(name)
            continue
        print(f"  [OK] {name}: raw_documents={raw} == {expected}, "
              f"indexed {len(indexed)} md file(s)")

    print("--- summary ---")
    print(f"KBs: {len(kbs)}, reindexed: {sorted(changed_kbs) or '(none)'}, "
          f"restarted: {config_changed or force_rebuild}, "
          f"reindex failures: {reindex_failures or '(none)'}, "
          f"verify failures: {failures or '(none)'}")
    return EXIT_VERIFY_FAIL if (failures or reindex_failures) else EXIT_OK


def wait_reindex_done(api: TutorAPI, runtime_kb_dir: Path, kb_name: str,
                      timeout: float) -> bool:
    """Poll until DeepTutor reports the KB index ready AND the BM25 corpus on
    disk contains every md file in runtime raw/. The corpus-content check is
    the deterministic half: DeepTutor's statistics (needs_reindex /
    rag_initialized) flip synchronously with its own index state (verified on
    v1.5.8), and version-* directory existence alone is not enough — a fresh
    clear-then-reindex can report done before the index files land on disk,
    which is exactly the first-deploy path. Waiting on the actual index
    contents makes that race deterministic-safe. Spec §2.5: keep this in sync
    with verify's Layer-2 (corpus file_name set vs expected md set).
    """
    raw_dir = runtime_kb_dir / "raw"
    expected = ({p.name for p in raw_dir.glob("*.md")}
                if raw_dir.is_dir() else set())
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            status = api.kb_status(kb_name)
        except SeedError:
            time.sleep(5)
            continue
        stats = status.get("statistics") or {}
        ready = not stats.get("needs_reindex", True)
        if ready:
            indexed = index_content_files(runtime_kb_dir)
            if indexed is not None and expected <= indexed:
                return True
        time.sleep(5)
    return False


def cmd_force_rebuild(args: argparse.Namespace) -> int:
    if not args.confirm:
        print("--force-rebuild requires --confirm (destructive: wipes runtime "
              "config and indexes before rebuilding).")
        return EXIT_MANIFEST_FAIL
    if KB_RUNTIME_DIR.exists():
        for child in KB_RUNTIME_DIR.iterdir():
            if child.name == ".gitignore":
                continue
            if child.is_dir():
                shutil.rmtree(child)
            else:
                child.unlink()
        print("[force-rebuild] runtime KB area wiped")
    else:
        print("[force-rebuild] no runtime area to wipe")
    return cmd_sync(args, force_rebuild=True)


def main(argv: list[str] | None = None) -> int:
    if yaml is None:
        print("PyYAML is required (pip install PyYAML>=6.0)", file=sys.stderr)
        return EXIT_MANIFEST_FAIL
    parser = argparse.ArgumentParser(
        description="Phase 7 B21 KB seed mechanism",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "modes:\n"
            "  --check           read-only validation + API status\n"
            "  --sync            full pipeline (default)\n"
            "  --force-rebuild   wipe runtime + full reindex (needs --confirm)"
        ),
    )
    parser.add_argument("--check", action="store_true", help="read-only validation")
    parser.add_argument("--sync", action="store_true", help="full pipeline (default)")
    parser.add_argument("--force-rebuild", action="store_true",
                        help="wipe runtime config + full reindex")
    parser.add_argument("--confirm", action="store_true",
                        help="acknowledge destructive force-rebuild")
    parser.add_argument("--api-base", default=DEFAULT_API_BASE,
                        help=f"DeepTutor API base (default {DEFAULT_API_BASE})")
    parser.add_argument("--timeout", type=float, default=10.0,
                        help="per-request API timeout seconds")
    parser.add_argument("--wait", type=float, default=180.0,
                        help="max seconds to wait for readiness/reindex")
    args = parser.parse_args(argv)

    try:
        if args.check:
            return cmd_check(args)
        if args.force_rebuild:
            return cmd_force_rebuild(args)
        return cmd_sync(args)
    except SeedError as exc:
        print(f"[error] {exc}", file=sys.stderr)
        return EXIT_MANIFEST_FAIL


if __name__ == "__main__":
    sys.exit(main())
