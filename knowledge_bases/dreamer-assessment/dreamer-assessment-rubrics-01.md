---
topic_id: dreamer-assessment-rubrics-01
subject: Assessment
topic: "Dreamer 4D Progress Level Rubric Registry"
dreamer_phase: Design
modes_allowed:
  - contextual
  - direct
  - hybrid
grade_level: P1-M3
kb_name: dreamer-assessment
domain_agent_owner: assessment-agent
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

## The Four Progress Levels

| Level | Label | Meaning | Trigger |
|-------|-------|---------|---------|
| 1 | **Emerging** | Student demonstrates initial awareness but needs significant scaffolding | Completion of Dream phase with rubric score below threshold |
| 2 | **Developing** | Student shows growing competence with occasional guidance | Successful completion of Discover phase tasks |
| 3 | **Proficient** | Student works independently and produces quality output | Successful completion of Design phase deliverables |
| 4 | **Mastering** | Student synthesises, critiques, and creates original work | Successful completion of Deliver phase with debate/position paper |

## Phase-to-Level Mapping

| Dreamer Phase | Target Level | Assessment Focus |
|---------------|-------------|------------------|
| Dream | 1 → 2 | Curiosity, question quality, personal connection to topic |
| Discover | 2 → 3 | Simulation accuracy, code quality, data interpretation |
| Design | 3 → 4 | Design rationale, data-driven iteration, usability testing |
| Deliver | 4 (capstone) | Ethical reasoning, argument quality, synthesis across phases |

## Detailed Scoring Dimensions

### Dimension 1: Conceptual Understanding (CU)

- **1 (Emerging):** Can recall basic facts when prompted
- **2 (Developing):** Can explain concepts in own words with examples
- **3 (Proficient):** Can apply concepts to new, unfamiliar problems
- **4 (Mastering):** Can critique concepts, identify edge cases, and propose extensions

### Dimension 2: Technical Execution (TE)

- **1 (Emerging):** Follows step-by-step instructions with support
- **2 (Developing):** Modifies provided code/designs with guidance
- **3 (Proficient):** Writes original code/designs from specification
- **4 (Mastering):** Designs novel systems and debugs independently

### Dimension 3: Communication & Collaboration (CC)

- **1 (Emerging):** Shares ideas when prompted by teacher/peer
- **2 (Developing):** Presents work with structured format
- **3 (Proficient):** Adapts communication to audience; gives constructive peer feedback
- **4 (Mastering):** Leads discussions, synthesises multiple viewpoints, mentors peers

### Dimension 4: Ethical Reasoning (ER)

- **1 (Emerging):** Recognises that AI has ethical implications
- **2 (Developing):** Identifies specific ethical concerns in given scenarios
- **3 (Proficient):** Evaluates trade-offs and proposes mitigations
- **4 (Mastering):** Articulates a personal ethical framework and applies it consistently

## Composite Scoring Formula

```
Progress_Score = (CU × 0.30) + (TE × 0.25) + (CC × 0.20) + (ER × 0.25)
```

**Advancement Thresholds:**

| Score Range | Recommendation |
|-------------|---------------|
| 1.00 – 1.74 | Remain in current phase |
| 1.75 – 2.49 | Advance to next phase with scaffolding |
| 2.50 – 3.24 | Advance to next phase (standard) |
| 3.25 – 4.00 | Skip-ahead eligible; recommend acceleration |

## Use by the Assessment Agent

The Assessment Agent loads this rubric at initialisation and applies it to student deliverables. Key behaviours:

1. **Dream phase:** Free-text journal entries scored on CU, CC, and ER (TE not applicable)
2. **Discover phase:** Code submissions scored on all four dimensions with TE weighted at 0.35
3. **Design phase:** Design briefs scored on all four dimensions with CU weighted at 0.35
4. **Deliver phase:** Position papers scored on all four dimensions with ER weighted at 0.40

### Override Rules

- A score of 1 in any dimension triggers a mandatory teacher review, regardless of composite
- A student who scores 4 in ER at the Deliver phase earns the **Dreamer 4D Ethical Reasoning Badge**
- Consecutive "Remain in current phase" recommendations (2+) trigger an intervention flag

## Version History

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0 | 2026-08 | Assessment Agent (via DeepTutor) | Initial rubric registry for Dreamer 4D pilot |

> This registry is loaded by the Assessment Agent at startup. Updates require KB re-export and index refresh.
