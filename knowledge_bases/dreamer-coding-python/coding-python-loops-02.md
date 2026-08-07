---
topic_id: coding-python-loops-02
subject: Computer Science
topic: "Python Loops: Simulating Game Mechanics with Iteration"
dreamer_phase: Discover
modes_allowed:
  - contextual
  - direct
  - hybrid
grade_level: P4-P6
kb_name: dreamer-coding-python
domain_agent_owner: creation-agent
ib_atl_skills:
  - thinking-critical
  - thinking-transfer
ethical_ai_tags:
  - transparency
---

# Python Loops: Simulating Game Mechanics with Iteration

## Discover Phase: Building Core Understanding

In the Dream phase, you imagined games with loot tables and probability. Now in the Discover phase, you'll build the simulation yourself. Loops are the engine that powers these simulations — they let your code repeat actions automatically.

### Why Loops?

Imagine writing code to simulate 1000 dice rolls without loops. You'd need 1000 lines of `print(random.randint(1, 6))`. Loops let you write it once and run it as many times as you want.

### The Two Loop Types

```python
# For loop — when you know how many times to repeat
for i in range(5):
    print(f"Roll {i+1}: {random.randint(1, 6)}")

# While loop — when you repeat until a condition is met
health = 100
while health > 0:
    damage = random.randint(10, 30)
    health -= damage
    print(f"Took {damage} damage. Health: {health}")
```

### Activity: Build a Loot Drop Simulator

Write a Python program that:

1. Simulates a boss fight where the player defeats the boss 100 times
2. Each victory rolls for loot using the fractions from the Dream phase loot table
3. Counts and reports how many times each item dropped

**Starter Code:**

```python
import random

drop_counts = {"common_currency": 0, "sword": 0, "shield": 0, "legendary_gem": 0}

for attempt in range(1, 101):
    # Slot 1: always currency
    drop_counts["common_currency"] += 1

    # Slot 2: 50/50 sword or shield
    if random.random() < 0.5:
        drop_counts["sword"] += 1
    else:
        drop_counts["shield"] += 1

    # Slot 3: 1/10 legendary gem
    if random.random() < 0.1:
        drop_counts["legendary_gem"] += 1

print("After 100 boss kills:")
for item, count in drop_counts.items():
    print(f"  {item}: {count}")
```

### Reflection Questions

1. Run your simulation 3 times. Do you get the same counts each time? Why or why not?
2. What would you change to simulate 10,000 kills instead of 100?
3. How could you verify that the `1/10` legendary gem probability is working correctly?

### Bridge to Design Phase

Once you can simulate game mechanics, the Design phase asks: how do you balance them? What makes a loot drop feel exciting vs. frustrating? Python loops give you the data — the Design phase gives you the judgment to interpret it.

### Teacher Notes

- Discover phase: students build working models to test Dream phase intuitions
- Cross-reference: thinking-transfer — applying fractions from Dream to Python code
- Transparency tag: students see how probability works in code, demystifying "random" game mechanics
