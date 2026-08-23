---
topic_id: ethical-ai-bias-01
subject: AI Ethics
topic: "AI Bias: Where Does It Come From and How Do We Fix It?"
dreamer_phase: Deliver
modes_allowed:
  - contextual
  - direct
  - hybrid
grade_level: P4-P6
kb_name: dreamer-ethical-ai
ib_atl_skills:
  - thinking-critical
  - communication-exchange
  - social-collaboration
ethical_ai_tags:
  - fairness-awareness
  - transparency
  - bias-detection
---

# AI Bias: Where Does It Come From and How Do We Fix It?

## Deliver Phase: Debate, Defend, and Decide

You've explored AI concepts (Dream), built simulations (Discover), and analyzed game balance data (Design). Now in the Deliver phase, you confront the most important question: **what happens when the data itself is unfair?**

### What Is AI Bias?

AI bias occurs when a machine learning system produces results that are systematically prejudiced due to flawed assumptions in the training data or algorithm.

It's not that the AI is "evil." It's that the AI learned from data that reflects human biases — and then amplifies them at scale.

### Three Sources of AI Bias

| Source | What Happens | Real-World Example |
|--------|-------------|-------------------|
| **Training Data Bias** | The data doesn't represent everyone equally | A hiring AI trained on 10 years of resumes from a company that historically hired mostly men will learn to prefer male-coded language |
| **Measurement Bias** | What you measure isn't what you think you're measuring | An AI that predicts "good employees" based on hours logged favors people who stay late — disadvantaging parents and caregivers |
| **Feedback Loop Bias** | The AI's decisions shape future data, reinforcing the bias | A predictive policing AI sends more officers to neighborhoods it already flagged, generating more arrest data, which it then uses to justify sending even more officers |

### Case Study: The COMPAS Debate

In 2016, ProPublica investigated COMPAS, an AI system used by US courts to predict whether a defendant would re-offend. Their analysis found:

- The algorithm was **equally accurate** for Black and White defendants overall (about 61%)
- But the **types of errors differed dramatically**:
  - Black defendants were **twice as likely** to be falsely labeled "high risk" but not re-offend
  - White defendants were **twice as likely** to be falsely labeled "low risk" but then re-offend

**The Core Ethical Question:** If an AI is equally "accurate" but distributes its errors unequally across racial groups — is it fair?

### Activity: Bias Audit Simulation

**Scenario:** You are an ethics auditor. A school district has deployed an AI that predicts which students are "at risk" of dropping out. You receive this data:

| Group | Total Students | Flagged "At Risk" | Actually Dropped Out | False Positives | False Negatives |
|-------|---------------|-------------------|---------------------|-----------------|-----------------|
| Group A | 1,000 | 300 | 100 | 220 | 20 |
| Group B | 1,000 | 150 | 100 | 70  | 20 |

**Your Task:**

1. Calculate the false positive rate and false negative rate for each group
2. Determine whether the algorithm treats both groups fairly
3. Write a 200-word recommendation to the school district

### Deliverable: Ethical Position Paper

Write a 400-500 word position paper that:

1. Explains one source of AI bias using a concrete example
2. Argues whether COMPAS-style risk assessment AI should be used in criminal justice
3. Proposes one concrete safeguard that should be required before deploying any high-stakes AI

### Debate Format

After writing, students participate in a structured debate:

- **Proposition:** "AI risk assessment tools should be used in schools to identify at-risk students"
- **Format:** 2-minute opening statements, 1-minute rebuttals, closing arguments
- **Grading rubric:** Evidence quality, counter-argument engagement, ethical reasoning depth

### Teacher Notes

- Deliver phase: students synthesize Dream/Discover/Design learning into ethical arguments
- Cross-reference: thinking-critical (audit analysis), communication-exchange (debate), social-collaboration (group debate)
- All three ethical_ai_tags active: fairness-awareness, transparency, bias-detection
- This topic is designed to be uncomfortable — that's the point. The Deliver phase exists to teach students that building AI isn't enough; they must also decide what should and should not be built.
