# Test

Runs the repository's test gate and fixes failures iteratively, re-running only the failing check until it passes, then the gate once more.

## Why it exists

The gate exits at the first failure, so later checks may never have run, and a fix can break an earlier one. A failure that is not the code's (the environment, a flaky test, one already failing on master) is reported, not looped on.

## How it fits

Used by the pipeline skills when a check fails locally, and by `alice-verify-change` at 2 Moderate and above.

## To run it

A test gate script that runs, for the paths a branch changed, what CI runs.

## Canonical home

This is a vendored copy, kept here so Alice is self-standing. The canonical version, used by developers in their own sessions, lives in https://github.com/alexandrosandre/agentic-engineering (`skills/test`). The copy differs only where Alice needs it to.

The instructions are in [SKILL.md](SKILL.md).
