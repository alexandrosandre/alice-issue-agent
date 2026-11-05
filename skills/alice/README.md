# Alice

The session skill of Alice, the unattended issue agent. A routine starts a cloud session with a payload naming one item, and this skill turns it into one of three runs: an **Issue run** (read the issue, check its claims, decide whether to proceed, fix, verify and hand over a ready PR, or post findings or questions instead), a **Review round** (answer people's review comments on her PR, with a fix or a reply each), or a **Merge round** (check the reviewer's approval through the API, then merge through `/lgtm`).

## Why it exists

An agent that works issues nobody watches has to carry the judgment a developer would bring: whether the issue is ready, whether someone is already on it, when to stop and ask. The skill encodes the opinions behind that:

- **The issue states the result wanted.** When the intended fix is not written down and the code and data do not settle it, she posts questions instead of guessing. An earlier agent's experience showed that work started before the author has written the plan down is usually wasted.
- **Every claim in the report is checked** against the code and the data before she builds on it.
- **Merging is a person's call.** She merges only in a Merge round, on an approval she verified herself, and never enables auto-merge.
- **Everything she reads is untrusted.** Issue text, review comments, incoming data and her own memory describe the work; none of it widens what she may do.
- **Nobody answers during the session**, so everything she needs from a person goes on the issue, written to be answered cold, and everything she did goes on the issue and the PR.
- **Memory is hers, small and suspect.** Fifty one-line facts on a branch, each checked before use and removed the moment it proves false.

## How it fits

The sweep (`scripts/alice/sweep.py`, `workflows/`) decides which item runs and sends the payload; the routine prompt (`routines/alice/`) invokes this skill. For the work itself she runs `/afk`, which runs `/ship-it`; in her sessions `/ship-it` adds the risk review and verification steps (`ship-it/references/alice-steps.md`), which call `alice-assess-risk` and `alice-verify-change`. The weekly `alice-learn-from-outcomes` pass edits this file when her outcomes show a rule missing.

## To run it

A GitHub user for Alice with write access and outside the bypass list of a push ruleset on `.github/workflows/**`; the labels from `scripts/alice/create-labels.sh`; a cloud agent environment with read-only credentials, a local stack, a headless browser, and the team's session-sharing CLI; the two test accounts the skill names (`<TEST_ACCOUNT_ID>`, `<DEMO_ACCOUNT_ID>`); and the repository's read-only data tools, which this skill refers to without naming.

The instructions are in [SKILL.md](SKILL.md).
