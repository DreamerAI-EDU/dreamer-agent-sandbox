"""
Dreamer AI — Codex CLI Exit Criteria Trials
4 verification scenarios to validate OpenRouter LLM integration.

Scenarios:
  1. UI Change   — Generate a React lesson card component
  2. New Feature — Generate student progress tracking backend
  3. Bug Fix     — Generate buggy code, then fix it via LLM
  4. Write Tests — Generate pytest suite for existing API
"""

import os
import sys
import asyncio

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from codex_cli import generate_code, is_available

OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output_trials")


async def trial_1_ui_change() -> bool:
    """Generate a React component for a lesson card."""
    system = (
        "You are a senior frontend engineer. Generate production-ready React components. "
        "Output ONLY the JSX/TSX code. No explanation, no markdown fences."
    )
    prompt = (
        "Generate a React functional component called 'LessonCard' (TypeScript).\n"
        "Props: id (string), title (string), gradeLevel (number 1-12), "
        "duration (number in minutes), learningObjectives (string[]), "
        "onStart (() => void).\n"
        "Requirements:\n"
        "- Use Tailwind CSS classes for styling\n"
        "- Show grade level as a colored badge (K-5: green, 6-8: blue, 9-12: purple)\n"
        "- Show duration as 'XX min'\n"
        "- List up to 3 learning objectives with check icons\n"
        "- Include a 'Start Lesson' button that calls onStart\n"
        "- Export as default"
    )
    try:
        code = await generate_code(prompt, system_prompt=system, temperature=0.3)
        code = _strip_fences(code, "tsx")
        path = os.path.join(OUTPUT_DIR, "LessonCard.tsx")
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        with open(path, "w") as f:
            f.write(code)
        ok = all(kw in code for kw in ["LessonCard", "export default", "onStart"])
        print(f"  [UI Change] {'PASS' if ok else 'FAIL'} — {path} ({len(code)} chars)")
        return ok
    except Exception as e:
        print(f"  [UI Change] FAIL — {e}")
        return False


async def trial_2_new_feature() -> bool:
    """Generate student progress tracking backend module."""
    system = (
        "You are a backend engineer building an education platform. "
        "Generate production-ready Python code. "
        "Output ONLY the Python code. No explanation, no markdown fences."
    )
    prompt = (
        "Generate a Python module 'progress_tracker.py' for tracking student lesson progress.\n\n"
        "Requirements:\n"
        "- Class 'ProgressTracker' with SQLite backend (sqlite3)\n"
        "- Table 'progress' with columns: id TEXT PK, student_id TEXT, lesson_id TEXT, "
        "status TEXT (not_started/in_progress/completed), score REAL, "
        "started_at TEXT, completed_at TEXT\n"
        "- Methods: start_lesson(student_id, lesson_id), complete_lesson(student_id, lesson_id, score), "
        "get_progress(student_id) -> list of dicts, get_stats(student_id) -> dict with "
        "total_lessons, completed, average_score\n"
        "- Use parameterized queries (no SQL injection)\n"
        "- Type hints throughout\n"
        "- Docstrings for all public methods"
    )
    try:
        code = await generate_code(prompt, system_prompt=system, temperature=0.2)
        code = _strip_fences(code, "python")
        path = os.path.join(OUTPUT_DIR, "progress_tracker.py")
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        with open(path, "w") as f:
            f.write(code)
        ok = all(kw in code for kw in ["class ProgressTracker", "start_lesson", "complete_lesson", "get_progress"])
        if ok:
            compile(code, path, "exec")
        print(f"  [New Feature] {'PASS' if ok else 'FAIL'} — {path} ({len(code)} chars)")
        return ok
    except Exception as e:
        print(f"  [New Feature] FAIL — {e}")
        return False


async def trial_3_bug_fix() -> bool:
    """Generate buggy code, then fix it via LLM feedback."""
    system = (
        "You are a senior engineer. Generate complete Python code. "
        "Output ONLY the Python code. No explanation, no markdown fences."
    )
    # Generate initial buggy version
    buggy_prompt = (
        "Generate a Python function 'calculate_average' that takes a list of numbers "
        "and returns the average.\n"
        "IMPORTANT: Deliberately introduce a bug — do NOT handle the case where the "
        "input list is empty. It should raise ZeroDivisionError when given [].\n"
        "Also include a function 'parse_grades' that takes a comma-separated string "
        "of grades and returns a list of floats. Do NOT handle invalid input (non-numeric)."
    )
    try:
        code = await generate_code(buggy_prompt, system_prompt=system, temperature=0.2)
        code = _strip_fences(code, "python")
        path = os.path.join(OUTPUT_DIR, "grade_utils_buggy.py")
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        with open(path, "w") as f:
            f.write(code)

        has_bug = "ZeroDivisionError" not in code and "empty" not in code.lower()
        print(f"  [Bug Fix - Generate] Buggy code: {path} ({len(code)} chars)")

        # Now fix it
        fix_prompt = (
            "Fix the following Python code. The function calculate_average raises "
            "ZeroDivisionError when given an empty list — add proper handling (return 0.0 "
            "or None). The parse_grades function crashes on non-numeric input — add "
            "try/except to skip invalid entries and log a warning.\n\n"
            f"```python\n{code}\n```"
        )
        fixed = await generate_code(fix_prompt, system_prompt=system, temperature=0.1)
        fixed = _strip_fences(fixed, "python")
        fix_path = os.path.join(OUTPUT_DIR, "grade_utils_fixed.py")
        with open(fix_path, "w") as f:
            f.write(fixed)

        ok = any(kw in fixed for kw in ["ZeroDivisionError", "ValueError", "return 0", "return None", ": 0.0", "empty"])
        if ok and has_bug:
            compile(code, path, "exec")
            compile(fixed, fix_path, "exec")
        print(f"  [Bug Fix - Fixed] {'PASS' if ok else 'FAIL'} — {fix_path} ({len(fixed)} chars)")
        return ok and has_bug
    except Exception as e:
        print(f"  [Bug Fix] FAIL — {e}")
        return False


async def trial_4_write_tests() -> bool:
    """Generate pytest test suite for an API spec."""
    system = (
        "You are a QA engineer writing pytest test suites. "
        "Generate production-ready test code. "
        "Output ONLY the Python code. No explanation, no markdown fences."
    )
    prompt = (
        "Generate a pytest test file 'test_lesson_api.py' for a Flask lesson management API.\n\n"
        "API endpoints to test:\n"
        "- GET /api/lessons — returns JSON list of lessons (200)\n"
        "- GET /api/lessons/<id> — returns single lesson or 404\n"
        "- POST /api/lessons — creates lesson, returns 201 with JSON body {title, grade_level}\n"
        "- PUT /api/lessons/<id> — updates lesson, returns 200 or 404\n"
        "- DELETE /api/lessons/<id> — deletes lesson, returns 204 or 404\n\n"
        "Requirements:\n"
        "- Use pytest fixtures for Flask test client\n"
        "- Use pytest.mark.parametrize for edge cases\n"
        "- Test both success and error paths\n"
        "- Test at least 2 edge cases per endpoint\n"
        "- Include a fixture that seeds test data\n"
        "- Use descriptive test function names (test_<verb>_<scenario>_<expected>)"
    )
    try:
        code = await generate_code(prompt, system_prompt=system, temperature=0.2)
        code = _strip_fences(code, "python")
        path = os.path.join(OUTPUT_DIR, "test_lesson_api.py")
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        with open(path, "w") as f:
            f.write(code)
        ok = all(kw in code for kw in ["def test_", "pytest", "fixture", "client", "assert"])
        if ok:
            compile(code, path, "exec")
        print(f"  [Write Tests] {'PASS' if ok else 'FAIL'} — {path} ({len(code)} chars)")
        return ok
    except Exception as e:
        print(f"  [Write Tests] FAIL — {e}")
        return False


def _strip_fences(code: str, lang: str = "") -> str:
    """Strip markdown code fences if present."""
    code = code.strip()
    if code.startswith("```"):
        lines = code.split("\n")
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        code = "\n".join(lines).strip()
    return code


async def main():
    if not is_available():
        print("OPENROUTER_API_KEY not set — cannot run trials")
        sys.exit(1)

    print("=" * 60)
    print("Dreamer AI — Codex CLI Exit Criteria Trials (4 scenarios)")
    print("=" * 60)

    results = {}
    results["UI Change"] = await trial_1_ui_change()
    results["New Feature"] = await trial_2_new_feature()
    results["Bug Fix"] = await trial_3_bug_fix()
    results["Write Tests"] = await trial_4_write_tests()

    passed = sum(1 for v in results.values() if v)
    total = len(results)

    print("\n" + "=" * 60)
    print("RESULTS")
    print("=" * 60)
    for name, ok in results.items():
        print(f"  {'✅' if ok else '❌'} {name}")
    print(f"\n  Passed: {passed}/{total}")

    if passed < total:
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
