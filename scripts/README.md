# Scripts

The code around Alice. Two kinds live here: what runs outside her session, in GitHub Actions, and decides what she works on; and the tools her skills call inside it, which turn rules that would otherwise be prose into checks and contracts.

The opinion behind most of them: **what must always or never happen goes in code, not in instructions**. A skill can tell an agent to keep evidence honest, to read the issue without hidden text, or to never push a workflow file; a script or a hook makes the wrong thing fail.

## Outside the session

| File | What it does |
| --- | --- |
| [`alice/sweep.py`](alice/sweep.py) | The dispatcher. Every 10 minutes, and 5 minutes after each request, it picks the issues assigned to `alice-bot` that have been quiet for 5 minutes and that nobody else holds, review rounds on her PRs once a person's review is the latest word, and merge rounds once the latest word is the issue reviewer's approval. It counts only people's label changes, assignments and @mentions, so a prompt-injected session acting as Alice can neither restart itself nor lift `skip-alice`. It claims each item with a label before starting a session (no start call has an idempotency key), sends later rounds into the session that last worked the issue, and bounds her usage at 3 starts per sweep and 5 running. `--dry-run` prints every decision and writes nothing. |
| [`alice/assign_by_type.py`](alice/assign_by_type.py) | The fixed step after the triage agent: assigns Alice a new person-filed issue typed Bug, Enhancement or Chore, never one labeled `skip-alice`, `Epic` and the like. Switched off until the team trusts her with issues nobody chose for her. |
| [`alice/create-labels.sh`](alice/create-labels.sh) | Creates the six labels the sweep reads and writes. |
| [`alice/sign-in-claude.sh`](alice/sign-in-claude.sh) | A person signs one of Alice's Claude accounts in to claude.ai, so the sweep can send rounds into that account's sessions. The token goes to the secret store, under a prefix her own sessions cannot read. |

## Inside the session

| File | What it does |
| --- | --- |
| [`alice/issue_text.py`](alice/issue_text.py) | Prints an issue and its comments as a person sees them on GitHub: from GitHub's own rendering, without HTML comments or invisible format characters, where instructions can hide, and with a count of what it left out. |
| [`alice/risk_level.py`](alice/risk_level.py) | Holds the six risk questions and turns the reviewer's answers into a level and the PR's Risk section. Each requirement is marked from the evidence's tags, so nothing is ticked by hand, and a reason's line break cannot forge a checklist item. |
| [`alice/evidence.py`](alice/evidence.py) | Commits screenshots to the `alice-evidence` branch with git plumbing (never touching the checkout) and prints the URLs a PR embeds; uploads recordings to the shared drive. |
| [`alice/memory.py`](alice/memory.py) | Alice's memory: one-line facts on the `alice-memory` branch, at most 50, each with its date and source. Facts arrive on standard input so no shell expands what an earlier session wrote; invisible characters are refused; concurrent sessions never overwrite each other's lines. |
| [`alice/pre-push`](alice/pre-push) | A git hook that refuses any push whose new commits touch `.github/workflows/**` or `.github/actions/**`, and says to put the change in the PR as a patch. A push ruleset enforces the same on GitHub; the hook makes the refusal clean. |
| [`alice/transcripts.py`](alice/transcripts.py) | The end-of-turn hook that uploads her session transcript, with every credential redacted, to the shared drive; and, for the weekly learning pass, `list`, `download`, and `extract`, which cuts a session into reader-sized parts that keep every turn and every failure whole. |
| [`alice/ledger.py`](alice/ledger.py) | The outcome ledger, from GitHub alone: per PR, merged, closed or reverted within 30 days, review rounds, people's follow-up commits and the declared risk level; per issue, whether it ended in a merged PR, and the merge rate per issue type. |
| [`alice/shared_drive.py`](alice/shared_drive.py) | Placeholder for the shared drive and the secret store. Wire it to yours. |
| [`github/rest.py`](github/rest.py) | Pull-request operations over REST, for Claude Code cloud sessions, whose GitHub proxy refuses GraphQL: view, create, edit, checks, runs, threads, reviews, resolve a thread, request reviewers, and a squash merge pinned to the head the caller checked. |

## Tests

[`tests/`](tests/) holds the tests for all of the above (`pytest scripts/tests`), and they pass against the code as published: the sweep's selection rules, dispatch and failure handling; the risk levels and the Risk section; the issue text filter; the memory's concurrency and refusals; the pre-push hook on real git repositories; the evidence push; the ledger's outcomes; the transcript redaction and extraction. They need Python 3.11+, pytest and git, and no network.

## To run them for real

Replace the placeholders marked `TODO`: the secret store's CLI in `sweep.py` and `sign-in-claude.sh` (and Alice's account emails there), the shared drive in `shared_drive.py`, and the repository (`GH_REPO`, or `--repo`).
