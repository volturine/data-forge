---
name: explain-code
description: Explain code clearly with analogies, ASCII diagrams, and step-by-step walkthroughs. Use when a user asks for code explanations, architecture summaries, or learning-oriented breakdowns.
---

Follow this workflow to explain code:

1. **State the goal** — one sentence on what the code achieves
2. **Start with an analogy** — compare to something concrete and familiar
3. **Draw a diagram** — use ASCII art to show flow, structure, or relationships
4. **Walk through the code** — step-by-step, in execution order
5. **Call out a gotcha** — likely misunderstanding, edge case, or limitation
6. **Summarize in one line** — reinforce the core idea

Guidelines:

- Keep it conversational and concise
- Use no more than one diagram unless the user asks for more depth
- Use concrete names from the code (functions, variables, modules)
- For complex concepts, layer at most two analogies
- If code is incomplete, state assumptions explicitly

## Output format (strict)

Use this exact structure:

1. **Goal** — one sentence
2. **Analogy** — 1-2 sentences
3. **Diagram** — ASCII art
4. **Walkthrough** — 3-7 bullets in execution order
5. **Gotcha** — one sentence
6. **One-line summary** — one sentence

## Example output

Goal: Convert a list of numbers into their squares and keep only evens.

Analogy: Think of a conveyor belt that stamps each item, then a bouncer who only lets even-numbered tickets through.

Diagram:
```
input -> map(square) -> filter(is_even) -> output
```

Walkthrough:
- Read the input list
- Square each number in order
- Check each squared value for evenness
- Keep the even squares
- Return the filtered list

Gotcha: Squaring negative numbers makes them positive, which can surprise people expecting sign preservation.

One-line summary: It maps numbers to squares and filters the results to even values.
