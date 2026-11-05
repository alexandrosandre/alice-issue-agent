# Autoreview

Babysits a PR hands-free until it is merge-ready: merges the base, readies the draft, waits for CI and the review bots, classifies every CI failure and review item into fix it, silently resolve, or leave open and report, fixes in batches with one push per head, and stops with a drift report.

## Why it exists

Review feedback arrives in three shapes (inline threads, review summaries, general comments), from people and bots, across many rounds; each push restarts every bot. The opinions:

- **Default to leave-open.** Fix only branch-caused CI failures, bugs in PR-touched code, unmet PR intent and rule violations; nits and "consider" suggestions stay with the author, who keeps scope authority.
- **Batch by head SHA, push once**, and review each batch before pushing it: review fixes introduce a real share of the bugs bots later find.
- **Resolve only settled threads.** Replying is not resolving.
- **Corroborated findings get verified**, never dismissed on confidence alone.
- **Cap the rounds on an agent's PR** (five on Alice's), so a runaway loop cannot spend the shared review budget.

## How it fits

`/ship-it`, `/ship-it-lite` and `/lgtm` run it; Alice's review rounds run it after each push.

## To run it

List your review bots' check and workflow names in the skill's Review Bot Checks section, marking the security ones; `scripts/github/rest.py` for GitHub access.

## Canonical home

This is a vendored copy, kept here so Alice is self-standing. The canonical version, used by developers in their own sessions, lives in https://github.com/alexandrosandre/agentic-engineering (`skills/autoreview`). The copy differs only where Alice needs it to.

The instructions are in [SKILL.md](SKILL.md).
