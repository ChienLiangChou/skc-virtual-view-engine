# Kevin Repo Working Rules

## Core operating rules
- Understand the task before changing anything.
- Inspect relevant files, folders, and existing patterns first.
- Prefer the smallest safe change over broad refactors.
- Keep unrelated files untouched.
- Explain what changed and why.

## Planning rules
- Separate confirmed facts, assumptions, and unknowns.
- When requirements are unclear, state the uncertainty clearly instead of pretending certainty.
- Prefer reusable workflows over one-off hacks.
- If a task mixes business logic and code, preserve business rules first.

## Implementation rules
- Follow existing repo conventions before introducing new abstractions.
- Reuse existing utilities and patterns where reasonable.
- Do not rename, reorganize, or refactor broadly unless it is necessary for the requested task.
- Avoid hidden side effects.

## Validation rules
- Run the narrowest relevant validation first.
- If you cannot run validation, say exactly what could not be checked.
- Mention risks, edge cases, and likely regression areas.

## Output rules
For implementation tasks, respond in this order:
1. Objective
2. Facts found
3. Plan
4. Changes made
5. Validation
6. Risks
7. Next action

For research or planning tasks, respond in this order:
1. Objective
2. Confirmed facts
3. Assumptions
4. Recommended workflow
5. Risks or gaps
6. Final recommendation

## Guardrails
- Do not invent tools, files, or capabilities that do not exist.
- Do not modify external systems unless explicitly asked.
- Do not overstate confidence.
- Prefer clarity and precision over hype.
