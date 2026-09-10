"""Structured red-line scanners for P-series negative scans (W6 fix, #47).

Why this exists
---------------
The P-series negative scans used to run naked substring checks over the whole
``json.dumps(response)`` blob, numeric tokens included (``"0.9"``, ``"0.95"``).
API timestamps are ISO-8601 **with microseconds**
(``datetime.now(timezone.utc).isoformat()``), so any wall-clock second whose
last digit is ``0`` and microsecond whose first digit is ``9`` renders a
``...:50.912345+00:00`` fragment containing the substring ``0.9``. With 2-3
timestamps per payload that is a ~2-3% chance per run of a *false* red on a
perfectly clean response (main run 34485104556 was exactly this).

A scanner that cries wolf erodes trust in CI red until real reds get skipped,
so numeric red-line tokens are matched **structurally** from here on:

* text tokens    -> substring match against string leaves only, after ISO
                    timestamps have been stripped from the leaf
* numeric tokens -> every number in the serialised payload is parsed and
                    compared with a tolerance, so ``0.9`` can never be "found"
                    inside a microsecond fragment or an unrelated longer number

The scanners keep full teeth: a leaked ``confidence: 0.95`` field, a
``"score 0.9"`` string, or a ``rub-internal-001`` id are all still caught.
"""

from __future__ import annotations

import json
import math
import re
from typing import Any, Iterator, Sequence

__all__ = [
    "ISO_TS_RE",
    "scan_payload",
    "strip_iso_timestamps",
]

# ISO-8601 date-time, with or without microseconds, with or without offset.
ISO_TS_RE = re.compile(
    r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?"
)

# A decimal number standing on its own: not glued to a preceding digit/dot and
# not continued by another digit. ``\d+`` on the left also excludes the ``0.9``
# inside ``0.912345`` (that fragment is stripped with its timestamp anyway).
_DECIMAL_RE = re.compile(r"(?<![\d.])[-+]?\d+\.\d+(?![\d])")

_NUM_ABS_TOL = 1e-9


def strip_iso_timestamps(text: str) -> str:
    """Replace ISO-8601 timestamps with a placeholder.

    Microsecond fragments are noise for red-line scanning: they are clock
    digits, not grading data.
    """
    return ISO_TS_RE.sub("<timestamp>", text)


def iter_strings(value: Any) -> Iterator[str]:
    """Yield every string leaf of a JSON-like structure (dicts/lists/scalars)."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from iter_strings(item)
    elif isinstance(value, (list, tuple, set)):
        for item in value:
            yield from iter_strings(item)


def _text_leaks(value: Any, tokens: Sequence[str]) -> list[str]:
    leaked: list[str] = []
    for leaf in iter_strings(value):
        clean = strip_iso_timestamps(leaf)
        for token in tokens:
            if token in clean and token not in leaked:
                leaked.append(token)
    return leaked


def _numeric_leaks(value: Any, tokens: Sequence[float]) -> list[float]:
    blob = strip_iso_timestamps(json.dumps(value, ensure_ascii=False, default=str))
    numbers = [float(m) for m in _DECIMAL_RE.findall(blob)]
    leaked: list[float] = []
    for token in tokens:
        want = float(token)
        if any(math.isclose(n, want, rel_tol=0.0, abs_tol=_NUM_ABS_TOL) for n in numbers):
            if token not in leaked:
                leaked.append(token)
    return leaked


def scan_payload(
    payload: Any,
    *,
    text_tokens: Sequence[str] = (),
    numeric_tokens: Sequence[float] = (),
) -> list[Any]:
    """Return the red-line tokens leaked by ``payload`` (empty list == clean).

    ``text_tokens`` are matched on string leaves with timestamps stripped;
    ``numeric_tokens`` are matched numerically against the serialised payload.
    """
    return [*_text_leaks(payload, text_tokens), *_numeric_leaks(payload, numeric_tokens)]
