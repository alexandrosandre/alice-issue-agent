# Create PR

Opens a draft PR, or refreshes an open one in place, with the project's title convention and a functional-level description in fixed sections: What, Why, Risk, Decisions to check, Out of scope.

## Why it exists

A PR description is read cold, by people and by review bots, and becomes the squash commit. It leads with what was proven or decided, regenerates every diff-derived section on each refresh so stale migration or deploy text never survives, and writes generated text through files so the shell never expands it.

## How it fits

`/ship-it` runs it. In Alice's PRs it opens with the risk title and the intent to judge, and carries the Risk section, the preview and recording lines, and the ask-live link that her steps leave in `RISK_DIR`.

## To run it

Your repository's PR title regex and scopes; `scripts/github/rest.py`.

## Canonical home

This is a vendored copy, kept here so Alice is self-standing. The canonical version, used by developers in their own sessions, lives in https://github.com/alexandrosandre/agentic-engineering (`skills/create-pr`). The copy differs only where Alice needs it to.

The instructions are in [SKILL.md](SKILL.md).
