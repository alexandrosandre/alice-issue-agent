# afk

Keeps a session working unattended: carry the work from whatever stage it is in through the delivery pipeline, decide forks yourself with evidence, keep a ledger of those decisions for the user to ratify, and stop only on hard blockers.

## Why it exists

An agent left alone tends to stop and ask, or hand work back as a list of "next steps". This skill says the opposite: stopping is almost always wrong, a decision is recorded and made, and the final report is where the user ratifies it. Merging and involving other people stay with the user.

## How it fits

Alice's issue run invokes it after the scoping gate; its ledger becomes her PR's "Decisions to check". It hands the code to `/ship-it` (or `/ship-it-lite`). The `alice` skill carves out the one place she may involve people: her hand-over.

## To run it

Nothing beyond the pipeline skills in this folder.

## Canonical home

This is a vendored copy, kept here so Alice is self-standing. The canonical version, used by developers in their own sessions, lives in https://github.com/alexandrosandre/agentic-engineering (`skills/afk`). The copy differs only where Alice needs it to.

The instructions are in [SKILL.md](SKILL.md).
