---
name: grill-me
description: Interview the user relentlessly about a plan or design until reaching shared understanding, resolving each branch of the decision tree. Use when user wants to stress-test a plan, get grilled on their design, or mentions "grill me".
---

Interview the user about every critical aspect of their plan until you reach a shared understanding. Walk down each branch of the design tree, resolving dependencies between decisions one-by-one.

## Boundaries
- Keep the interview focused on the specific scope requested by the user (do not grill the entire repo if asked about a single function).
- Adapt interview depth to task complexity: ask only high-impact questions for small features (3–5 questions) and go deeper only for major architectural changes.

## How to ask questions
- Use the **question** tool for every question you ask. Never pose questions as plain text in your response — always use the interactive multiple-choice popup so the user can quickly select an answer or type a custom one.
- Ask **one question at a time** and wait for the user's answer before moving to the next question.
- Provide 2–4 concrete multiple-choice options representing realistic directions (the user can always write a custom answer).

## Flow
1. After receiving an answer, briefly acknowledge the decision (1 sentence max), then immediately ask the next question via `question`.
2. If a question can be answered by exploring the codebase or `SPEC/`, explore them yourself instead of asking the user.
3. Continue until all critical branches of the design tree are resolved.
4. When finished, output a concise summary of all decisions made so it can be used as an implementation spec.
