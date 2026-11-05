# ship-it-lite

The low-risk version of `/ship-it`: local review, commit and push, `/create-pr`, `/autoreview`, without the session-aware contextual review.

## Why it exists

Not every change earns the session-review pass; a typo fix or a config bump should still get the review bots and CI without the overhead.

## How it fits

`/afk` picks it for low-risk changes. Alice's issue runs use `/ship-it`, since her Alice steps hang off it.

## Canonical home

This is a vendored copy, kept here so Alice is self-standing. The canonical version, used by developers in their own sessions, lives in https://github.com/alexandrosandre/agentic-engineering (`skills/ship-it-lite`). The copy differs only where Alice needs it to.

The instructions are in [SKILL.md](SKILL.md).
