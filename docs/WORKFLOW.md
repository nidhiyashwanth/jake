# Agent workflow

- **Source:** harness-engineering continuity and scope guidance.
- **Applicability:** every planning, documentation, and implementation session.
- **Expiry:** revisit when the collaboration model or repository automation changes.

## Clock in

1. Read `AGENTS.md`, `PROGRESS.md`, and `DECISIONS.md`.
2. Inspect `feature-list.json` and `task.md`; confirm that the same single package is `active` in both.
3. Run the relevant verification gate before changing files.
4. Select the single next action from `PROGRESS.md`; park adjacent ideas.

## Scope control

WIP is 1. A package moves from `not_started` to `active`, then remains active until its exact verification command passes. Only then may the next package start. Research, refactoring, cleanup, and product implementation are separate work items; do not bundle them because they are nearby. The detailed package board is `task.md`; `feature-list.json` is the executable WIP gate.

## Decisions and state

Record durable choices in append-only `DECISIONS.md` with the reason and rejected alternative. Record current status, checks, blockers, and the next action in `PROGRESS.md`. Do not use chat history as the only handoff.

## Research changes

Keep each market, product, architecture, and compliance fact in one canonical numbered document. When a conclusion changes, update the source document, the README route, and a decision entry if the change affects execution. Preserve dates and evidence boundaries; do not silently convert research assumptions into implementation facts.

## Git checkpoints

The first clean harness baseline is published as one atomic checkpoint after verification. Later product work uses a feature branch, focused commits, and a reviewable diff. Never mix unrelated work into a checkpoint. A push is not proof that the content is verified.

## Clock out

1. Finish the active unit or record a concrete blocker.
2. Run the relevant static/runtime/E2E gate. For harness-only changes, run the harness gate; for product changes, run all three layers defined in `docs/VERIFICATION.md`.
3. Update `PROGRESS.md`, feature evidence, and new decisions.
4. Remove temporary files and leave one executable next action.
5. Confirm the working tree is clean once Git is initialized.
