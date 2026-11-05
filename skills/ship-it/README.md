# ship-it

Takes finished work to a fully reviewed, merge-ready PR in one pass: a local code review at the highest effort, commit and push with the base merged in, `/create-pr`, `/autoreview` until CI and the review bots settle, and `/contextual-review` against the session's intent. It never merges.

## Why it exists

Review bots, CI and a session-aware review each catch what the others cannot, and running them by hand in the right order is where steps get skipped. The bar it fixes against is narrow on purpose: confirmed bugs, regressions, unfulfilled intent and rule violations, plus the same mistake wherever the change repeats it; nits and refactors go to the summary.

## How it fits

`/afk` invokes it. In Alice's sessions it also runs `references/alice-steps.md`: the two risk-review passes, functional verification and re-verification, the preview, the description refresh and the live-questions link. Developers' sessions never load that file, since a developer at the keyboard tests on their own stack and decides how.

## Canonical home

This is a vendored copy, kept here so Alice is self-standing. The canonical version, used by developers in their own sessions, lives in https://github.com/alexandrosandre/agentic-engineering (`skills/ship-it`). The copy differs only where Alice needs it to.

The instructions are in [SKILL.md](SKILL.md).
