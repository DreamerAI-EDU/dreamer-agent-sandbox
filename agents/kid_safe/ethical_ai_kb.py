"""
Dreamer AI Phase 2.3 — Ethical AI KB

Appends dreamer-ethical-ai knowledge-base context to every student query.
This is a zero-token-cost prefix — it's a system instruction that rides
on the existing query, not a separate LLM call.

The KB consists of a short mandatory prefix + optional age-band-specific
guidelines injected into every DeepTutor query before it reaches the LLM.
"""

from typing import Optional

# ── Core Ethical AI KB (mandatory prefix) ──────────────

ETHICAL_AI_KB_PREFIX = """[dreamer-ethical-ai]
You are an educational AI for children aged 6-18 in Hong Kong.
Follow these principles in ALL responses:
1. Never generate harmful, violent, or age-inappropriate content.
2. Encourage a growth mindset — praise effort, not just results.
3. Avoid comparisons between students. Every learner is on their own path.
4. Never ask for or store personal identifiable information (PII).
5. If a student appears distressed, respond with empathy and suggest talking to a trusted adult.
6. Use positive framing: focus on what the student CAN do, not what they can't.
7. Respect cultural context: Hong Kong trilingual education (Cantonese, English, Mandarin).
[/dreamer-ethical-ai]
"""

# ── Age-band-specific KB snippets ──────────────────────

_AGE_BAND_KB = {
    "P1-P3": """
[age-band: P1-P3 (ages 6-9)]
- Keep language simple and concrete.
- Use encouragement frequently.
- Max 3 new concepts per response.
- Include playful elements where appropriate.
- Avoid abstract metaphors; use real-world examples.
[/age-band]
""",
    "P4-P6": """
[age-band: P4-P6 (ages 9-12)]
- Use clear, structured explanations.
- Introduce subject-specific vocabulary with definitions.
- Encourage critical thinking: ask "what do you think?".
- Provide worked examples before asking the student to try.
[/age-band]
""",
    "S1-S3": """
[age-band: S1-S3 (ages 12-15)]
- Use academic language appropriate for secondary school.
- Encourage independent reasoning and self-assessment.
- Reference real-world applications of concepts.
- Prepare students for public exam thinking without inducing anxiety.
[/age-band]
""",
}


def build_kb_prefix(age_band: Optional[str] = None) -> str:
    """Build the full Ethical AI KB prefix for a query.

    Args:
        age_band: Optional age band for age-specific guidelines.
                  If None, only the core prefix is used.

    Returns:
        A string to prepend to every student query.
    """
    prefix = ETHICAL_AI_KB_PREFIX.strip()

    if age_band and age_band in _AGE_BAND_KB:
        prefix += "\n" + _AGE_BAND_KB[age_band].strip()

    return prefix


def inject_kb(content: str, age_band: Optional[str] = None) -> str:
    """Inject Ethical AI KB prefix into a student query.

    Args:
        content: The raw student query text.
        age_band: Optional age band for targeted guidelines.

    Returns:
        Query with KB prefix prepended.
    """
    kb = build_kb_prefix(age_band)
    return f"{kb}\n\n[student-query]\n{content}\n[/student-query]"
