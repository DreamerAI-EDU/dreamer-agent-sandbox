# Phase 6 Portfolio PDF — Specification (spec only, no renderer)

> Status: frozen at Day 25 kickoff (checklist §2.4 item 3).
> Scope: this document defines WHAT a portfolio PDF must contain and how it
> must behave. It deliberately contains **no renderer implementation** —
> renderer work is out of scope until the spec is approved (time red line).

## 1. Purpose

A shareable, printable snapshot of a student's portfolio showcase. Unlike the
Parent Report (assessment-centric), the Portfolio PDF is **student-facing
showcase** content: achievements, artifacts, and growth highlights.

## 2. Data source

- `portfolio_items` rows for the student (populated by `PortfolioAgent`).
- `share_card` payloads (P5 whitelist) as the serialization contract.

## 3. Required sections

| # | Section | Source | Notes |
|---|---------|--------|-------|
| 1 | Cover | display_name (first name only), brand "Dreamer AI", generated_at | No photo by default |
| 2 | Summary | kid-facing intro line (rewrite_tone output) | Short, ≤ 3 sentences |
| 3 | Highlights | one block per portfolio item | title, kid_label, artifact_summary, competencies_4d badges |
| 4 | Growth notes | growth_note per item | Improvement / consistent / keep-going variants |
| 5 | Footer | brand + date + "Made with Dreamer AI" | No raw internal labels |

## 4. PDPO red line (P5, mandatory)

The rendered PDF MUST NOT contain, in any section:

- `student_id` (or any internal identifier)
- student full name (display_name is first-name-only)
- school name
- raw `internal_label` values (`not_yet`, `developing`, `achieved`, `exemplary`)
  — only kid-facing `kid_label` may appear
- assessment scores or confidence values

The `share_card` blacklist tests in `tests/test_portfolio_agent.py`
(`test_share_card_never_leaks_identity`) are the gate for this section.
A PDF renderer, once implemented, must consume `share_card` payloads only.

## 5. Layout & typography (constraints for future renderer)

- Page size: A4 portrait.
- Language: follows `lang_code` (en / zh-hk / zh-cn); CJK font required.
- Age-band scaling: P1-P3 larger type, fewer items per page.
- Max 6 items per page; overflow paginates.
- Brand colors from the Dreamer AI design kit (not specified here).

## 6. Acceptance criteria (when renderer is greenlit)

1. A4 portrait output, valid PDF (opens in ≥2 viewers).
2. Every section from §3 present with non-empty content for a non-empty portfolio.
3. PDPO red-line scan: rendered text contains none of §4 blacklist terms.
4. Empty portfolio → cover + summary only, no errors.
5. Multi-item portfolio paginates correctly at 6 items/page.
