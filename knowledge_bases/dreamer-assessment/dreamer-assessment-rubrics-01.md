---
topic_id: dreamer-assessment-rubrics-01
subject: Assessment
topic: "Dreamer 4D Progress Level Rubric Registry"
dreamer_phase: Design
modes_allowed:
  - contextual
  - direct
  - hybrid
grade_level: P1-S3
kb_name: dreamer-assessment
ib_atl_skills:
  - thinking-critical
  - communication-exchange
  - self-management-reflection
ethical_ai_tags:
  - transparency
  - fairness-awareness
---

# Dreamer 4D Progress Level Rubric Registry

## Purpose

This document defines the progress level rubric that the Assessment Agent uses to evaluate student work and recommend advancement across the Dreamer 4D journey. It is a living registry — updated as new KB topics and assessment patterns emerge.

**Label contract (frozen):** the only valid internal labels are **Not Yet / Developing / Achieved / Exemplary** (`auto_marking` enforces this four-value set). Kid-facing and parent-facing wording is produced downstream by the Kid-Safe `label_soften` layer — this registry always uses internal labels and never renders softened variants itself.

## The Four Progress Levels

| Level | Internal Label | Meaning | Trigger |
|-------|---------------|---------|---------|
| 1 | **Not Yet** | Student demonstrates initial awareness but needs significant scaffolding | Completion of Dream phase with rubric score below threshold |
| 2 | **Developing** | Student shows growing competence with occasional guidance | Successful completion of Discover phase tasks |
| 3 | **Achieved** | Student works independently and produces quality output | Successful completion of Design phase deliverables |
| 4 | **Exemplary** | Student synthesises, critiques, and creates original work | Successful completion of Deliver phase with debate/position paper |

## Phase-to-Level Mapping

| Dreamer Phase | Target Label Path | Assessment Focus |
|---------------|-------------------|------------------|
| Dream | Not Yet → Developing | Curiosity, question quality, personal connection to topic |
| Discover | Developing → Achieved | Simulation accuracy, code quality, data interpretation |
| Design | Achieved → Exemplary | Design rationale, data-driven iteration, usability testing |
| Deliver | Exemplary (capstone) | Ethical reasoning, argument quality, synthesis across phases |

## Detailed Scoring Dimensions

### Dimension 1: Conceptual Understanding (CU)

- **1 (Not Yet):** Can recall basic facts when prompted
- **2 (Developing):** Can explain concepts in own words with examples
- **3 (Achieved):** Can apply concepts to new, unfamiliar problems
- **4 (Exemplary):** Can critique concepts, identify edge cases, and propose extensions

### Dimension 2: Technical Execution (TE)

- **1 (Not Yet):** Follows step-by-step instructions with support
- **2 (Developing):** Modifies provided code/designs with guidance
- **3 (Achieved):** Writes original code/designs from specification
- **4 (Exemplary):** Designs novel systems and debugs independently

### Dimension 3: Communication & Collaboration (CC)

- **1 (Not Yet):** Shares ideas when prompted by teacher/peer
- **2 (Developing):** Presents work with structured format
- **3 (Achieved):** Adapts communication to audience; gives constructive peer feedback
- **4 (Exemplary):** Leads discussions, synthesises multiple viewpoints, mentors peers

### Dimension 4: Ethical Reasoning (ER)

- **1 (Not Yet):** Recognises that AI has ethical implications
- **2 (Developing):** Identifies specific ethical concerns in given scenarios
- **3 (Achieved):** Evaluates trade-offs and proposes mitigations
- **4 (Exemplary):** Articulates a personal ethical framework and applies it consistently

## Composite Scoring Formula

```
Progress_Score = (CU × 0.30) + (TE × 0.25) + (CC × 0.20) + (ER × 0.25)
```

**Score-to-Label Bands:**

| Score Range | Internal Label | Recommendation |
|-------------|---------------|----------------|
| 1.00 – 1.74 | Not Yet | Remain in current phase |
| 1.75 – 2.49 | Developing | Advance to next phase with scaffolding |
| 2.50 – 3.24 | Achieved | Advance to next phase (standard) |
| 3.25 – 4.00 | Exemplary | Skip-ahead eligible; recommend acceleration |

## Use by the Assessment Agent

The Assessment Agent loads this rubric at initialisation and applies it to student deliverables. Key behaviours:

1. **Dream phase:** Free-text journal entries scored on CU, CC, and ER (TE not applicable)
2. **Discover phase:** Code submissions scored on all four dimensions with TE weighted at 0.35
3. **Design phase:** Design briefs scored on all four dimensions with CU weighted at 0.35
4. **Deliver phase:** Position papers scored on all four dimensions with ER weighted at 0.40

`auto_marking` output contract: `{internal_label, confidence, evidence_text, rubric_id}` with `internal_label` restricted to the four frozen labels above; results with `confidence < 0.45` are not written to `progress_snapshots`.

### Override Rules

- A score of 1 (Not Yet) in any dimension triggers a mandatory teacher review, regardless of composite
- A student who scores 4 (Exemplary) in ER at the Deliver phase earns the **Dreamer 4D Ethical Reasoning Badge**
- Consecutive "Remain in current phase" recommendations (2+) trigger an intervention flag

## Version History

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0 | 2026-08 | Assessment Agent (via DeepTutor) | Initial rubric registry for Dreamer 4D pilot |
| 2.0 | 2026-08-22 | Dreamer curriculum team | Labels aligned to frozen four-value set (Not Yet / Developing / Achieved / Exemplary); removed phantom agent ownership field; label_soften boundary documented |

> This registry is loaded by the Assessment Agent at startup. Updates require KB re-export and index refresh.
