# Contextual review

Reviews the branch diff against the literal session transcripts, for intent fidelity, design drift and context-dependent bugs that diff-only reviewers cannot catch: did the code do what the user literally asked, did it ship a rejected alternative, were the edge cases discussed actually tested.

## Why it exists

Every other reviewer sees only the diff. This one owns "did we ship what we meant", and stays out of what the others cover (style, lint, security categories, duplication).

## How it fits

`/ship-it` runs it last and triages its findings itself; run on its own, it presents findings and waits for the user's choice.

## To run it

A transcript locator for your coding agents (`tools/transcripts/find-transcripts.py` in https://github.com/alexandrosandre/agentic-engineering).

## Canonical home

This is a vendored copy, kept here so Alice is self-standing. The canonical version, used by developers in their own sessions, lives in https://github.com/alexandrosandre/agentic-engineering (`skills/contextual-review`). The copy differs only where Alice needs it to.

The instructions are in [SKILL.md](SKILL.md).
