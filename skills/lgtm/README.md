# lgtm

Takes a branch from wherever it is to a conditional self-merge on the author's LGTM: review, push, `/autoreview` to merge-ready, settle what it left open, then merge only if nothing substantial changed since the approval.

## Why it exists

An approval is for the code the approver saw. The skill fingerprints the PR's own changes at the approved commit and at the head; when they differ, it classes each change as trivial, a fix within intent, or substantial, and a substantial change makes the approval stale. The merge is pinned to the checked head, so a push after the check makes GitHub refuse it.

## How it fits

Alice's Merge round runs it with the issue reviewer's GitHub approval as the go and the approved commit as the SHA it compares against. It is the only way she merges.

## Canonical home

This is a vendored copy, kept here so Alice is self-standing. The canonical version, used by developers in their own sessions, lives in https://github.com/alexandrosandre/agentic-engineering (`skills/lgtm`). The copy differs only where Alice needs it to.

The instructions are in [SKILL.md](SKILL.md).
