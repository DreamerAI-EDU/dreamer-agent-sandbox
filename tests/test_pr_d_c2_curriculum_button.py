"""PR-D-c2 — "My AI Course" button / course-mode frame flag.

Scope: PR-D-c2_scope_v0.1 §2 (frame contract) / §3 (UI behaviour) /
§5 (hard checks HC-c2-1..HC-c2-5).

The repo has no JS test runner (frontend/package.json ships dev / build /
lint only), so the frontend half of these hard checks is pinned the way this
repo already pins frontend contracts (see test_b26_zh_cn_guard.py): read the
real source files, assert the contract, cross-check it against the relay's
own constants in auth/ws_chat.py. Nothing here imports or executes frontend
code — run-time behaviour is covered by the staging integration pass
(scope §6).

  HC-c2-1  one whitelisted flag value, on both sides of the wire
  HC-c2-2  the flag is top level, never nested, and carries no identifier
  HC-c2-3  exiting course mode stops the flag (mode is not sticky)
  HC-c2-4  a plain chat frame is unchanged
  HC-c2-5  this file is in the ci.yml pytest manifest
"""

from __future__ import annotations

import os
import re

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(REPO_ROOT, "frontend", "src")

MODE_MODULE = os.path.join(SRC, "lib", "curriculumMode.ts")
CHAT_WS = os.path.join(SRC, "lib", "chatWs.ts")
STREAM = os.path.join(SRC, "lib", "stream.ts")
CHAT_PAGE = os.path.join(SRC, "pages", "ChatPage.tsx")
STUDENT_HOME = os.path.join(SRC, "pages", "StudentHomePage.tsx")
I18N = os.path.join(SRC, "lib", "i18n.tsx")
TYPES = os.path.join(SRC, "lib", "types.ts")
WS_CHAT = os.path.join(REPO_ROOT, "auth", "ws_chat.py")
CI_YML = os.path.join(REPO_ROOT, ".github", "workflows", "ci.yml")

FLAG_KEY = "dibi_mode"
FLAG_VALUE = "curriculum"

# The module that owns the literal, then every file that must import it.
CALLERS = (CHAT_WS, STREAM, CHAT_PAGE, STUDENT_HOME)

FRAME_RE = re.compile(r"const frame = \{(.*?)\n    \};", re.S)
FRAME_KEYS = ("type", "capability", "content", "language", "session_id", "message_id")


def _read(path: str) -> str:
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def _ts_const(path: str, name: str) -> str:
    m = re.search(rf"export const {name}\s*=\s*'([^']*)'", _read(path))
    assert m, f"{name} is not declared in {os.path.basename(path)}"
    return m.group(1)


def _frame_body() -> str:
    m = FRAME_RE.search(_read(CHAT_WS))
    assert m, "the startTurn frame literal was not found in chatWs.ts"
    return m.group(1)


# ── HC-c2-1 ─────────────────────────────────────────────────────────────

def test_hc_c2_1_single_whitelisted_flag_value():
    """The flag has exactly one value, and the relay whitelists the same one."""
    assert _ts_const(MODE_MODULE, "DIBI_MODE_FLAG") == FLAG_KEY
    assert _ts_const(MODE_MODULE, "DIBI_MODE_CURRICULUM") == FLAG_VALUE

    ws = _read(WS_CHAT)
    assert f'_CURRICULUM_MODE_FLAG = "{FLAG_KEY}"' in ws
    assert f'_CURRICULUM_MODE_VALUE = "{FLAG_VALUE}"' in ws
    assert "mode == _CURRICULUM_MODE_VALUE" in ws, (
        "the relay must compare against its whitelist constant, not a literal"
    )

    # the wire frame builder imports the contract instead of spelling it out
    assert (
        "import { DIBI_MODE_CURRICULUM, DIBI_MODE_FLAG } from './curriculumMode';"
        in _read(CHAT_WS)
    )

    # no second value anywhere: the literal is declared once, in the contract
    # module, and never re-typed at a call site.
    for path in CALLERS:
        src = _read(path)
        assert f"'{FLAG_KEY}'" not in src and f'"{FLAG_KEY}"' not in src, (
            f"{os.path.basename(path)} hardcodes the flag key — import it from curriculumMode.ts"
        )
        for m in re.finditer(rf"{FLAG_KEY}\s*[:=]\s*'([^']*)'", src):
            assert m.group(1) == FLAG_VALUE, (
                f"{os.path.basename(path)} assigns a second flag value {m.group(1)!r}"
            )


# ── HC-c2-2 ─────────────────────────────────────────────────────────────

def test_hc_c2_2_flag_is_top_level_and_carries_no_identifier():
    frame = _frame_body()

    keys = re.findall(r"^ {6}([a-z_]+):", frame, re.M)
    assert keys == list(FRAME_KEYS), f"frame keys changed: {keys}"

    flag_lines = [ln for ln in frame.splitlines() if "[DIBI_MODE_FLAG]" in ln]
    assert len(flag_lines) == 1, f"expected exactly one flag spread, got {flag_lines}"
    assert "curriculumMode ?" in flag_lines[0], flag_lines[0]
    assert "DIBI_MODE_CURRICULUM" in flag_lines[0], flag_lines[0]

    # top level only: never inside a nested object (the engine layer is
    # extra="forbid" and would drop the whole turn), and never an identifier
    # the client has no business sending.
    lowered = frame.lower()
    assert "config" not in lowered, "the flag must not ride inside a nested object"
    assert "week" not in lowered, "no week on the wire — the server decides it"
    assert "slug" not in lowered
    assert "student_id" not in lowered


# ── HC-c2-3 ─────────────────────────────────────────────────────────────

def test_hc_c2_3_exit_stops_the_flag_and_clears_the_url_mode():
    page = _read(CHAT_PAGE)

    m = re.search(r"const exitCurriculumMode = \(\) => \{(.*?)\n  \};", page, re.S)
    assert m, "the course-mode exit handler was not found in ChatPage.tsx"
    body = m.group(1)
    assert "setCurriculumMode(false)" in body
    assert "next.delete(CURRICULUM_MODE_QUERY)" in body
    assert "setSearchParams(next, { replace: true })" in body, (
        "the URL mode must be rewritten too, or a reload re-enters course mode"
    )

    # the mode rides on BOTH stream paths — a normal turn and the F5
    # mount-resume — so no frame can leave without it while in mode.
    assert "{ student: mask, resumeFromMount: true, curriculumMode }" in page
    assert "{ student: profile.student, curriculumMode }" in page
    assert "curriculumMode?: boolean;" in _read(STREAM), (
        "the stream seam must forward the mode to the frame builder"
    )

    # the chrome that makes the mode visible and exitable
    assert "COURSE_COPY[lang].badge" in page
    assert "COURSE_COPY[lang].exit" in page
    assert "onClick={exitCurriculumMode}" in page


# ── HC-c2-4 ─────────────────────────────────────────────────────────────

def test_hc_c2_4_plain_chat_frame_is_unchanged():
    frame = _frame_body()
    assert "...(curriculumMode ?" in frame, "the flag must be conditional, never unconditional"

    ws = _read(CHAT_WS)
    assert "const curriculumMode = ctx.curriculumMode === true;" in ws, (
        "an absent context must not arm course mode"
    )

    # the mode is armed only by the exact whitelisted URL value
    assert "return value === DIBI_MODE_CURRICULUM;" in _read(MODE_MODULE)
    assert (
        "isCurriculumModeParam(searchParams.get(CURRICULUM_MODE_QUERY))" in _read(CHAT_PAGE)
    )


# ── HC-c2-5 ─────────────────────────────────────────────────────────────

def test_hc_c2_5_this_file_is_in_the_ci_manifest():
    assert "tests/test_pr_d_c2_curriculum_button.py" in _read(CI_YML), (
        "new test files must be listed in the ci.yml pytest manifest (repo guard)"
    )


# ── the door ────────────────────────────────────────────────────────────

def test_welcome_door_enters_course_mode_and_holds_back_p1_p3():
    home = _read(STUDENT_HOME)
    assert "copy.kidCourseBtn" in home
    assert "${CURRICULUM_MODE_QUERY}=${DIBI_MODE_CURRICULUM}" in home, (
        "the button must arm the mode through the contract constants"
    )
    assert "student.age_band !== 'P1-P3'" in home, (
        "P1-P3 must not be offered the door: the relay only fails open to the "
        "band persona for those weeks (scope §4)"
    )

    # the band driving that guard comes from the authenticated API, never the URL
    assert "age_band: string;" in _read(TYPES)

    i18n = _read(I18N)
    assert i18n.count("kidCourseBtn:") == 4, "kidCourseBtn needs the type + 3 languages"
    assert i18n.count("kidCourseBtnDesc:") == 4, (
        "kidCourseBtnDesc needs the type + 3 languages"
    )
