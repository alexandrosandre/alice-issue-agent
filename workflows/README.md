# Workflows

The two GitHub Actions workflows that start Alice. They go in `.github/workflows/` of the repository she works on.

| Workflow | What it does |
| --- | --- |
| [`alice-sweep.yml`](alice-sweep.yml) | Runs [`scripts/alice/sweep.py`](../scripts/alice/sweep.py) every 10 minutes and on dispatch. Only `master`'s code runs with the write token and the routine secrets; scheduled and nudged runs write only while the repository variable `ALICE_SWEEP_ENABLED` is `true`, and a manual dispatch is a dry run unless unchecked. A concurrency group keeps sweeps from overlapping, since two could claim the same issue. |
| [`alice-nudge.yml`](alice-nudge.yml) | Waits out the quiet period after a person's activity on an issue assigned to her or on her PR (assignment, label, edit, comment, review, an @mention of `@alice-bot`) or after triage finishes, then dispatches `master`'s sweep. It holds no secret: it only dispatches. |

## Why two workflows

The schedule alone was too slow: GitHub runs scheduled workflows late, often by many minutes, so a request could wait half an hour. Starting the sweep from the event itself would run it before the person finished typing. The nudge waits 5 minutes plus a margin after every event, with no debounce, so the sweep after the last event finds the quiet period over; the sweep's concurrency group folds the dispatches into one run, and the 10-minute schedule stays as the fallback. A test in [`scripts/tests/test_sweep.py`](../scripts/tests/test_sweep.py) keeps the nudge's wait longer than the sweep's quiet period.

## Why the sweep runs in Actions, not in her session

The sweep reads the records that decide what Alice may do: who assigned her, who added `alice-continue`, who approved. An approval gate holds only if the agent cannot write the records it reads, so the gate runs outside her session, with its own token, and counts only people's changes.

## To wire it up

- Secrets: `ALICE_ROUTINE_FIRE_URL` and `ALICE_ROUTINE_TOKEN` (and `_2`, `_3`… per extra account), and the credential for the sweep's secret-store access (`ALICE_SWEEP_SECRETS_ACCESS`), which no pull-request workflow may load.
- Variables: `ALICE_SWEEP_ENABLED`, and `ALICE_AUTO_ASSIGN_ENABLED` for the triage step.
- Your own issue-triage workflow, which is not shipped here: it labels new issues and runs [`scripts/alice/assign_by_type.py`](../scripts/alice/assign_by_type.py) as its last step. Put its name in `alice-nudge.yml`'s `workflow_run` trigger (marked `TODO`). [`ci-agents/issue-triage`](https://github.com/alexandrosandre/agentic-engineering/tree/main/ci-agents/issue-triage) in the companion repository is an example.
- The `TODO` step in `alice-sweep.yml` that gives the sweep its secret-store access.
- A push ruleset restricting `.github/workflows/**` and `.github/actions/**` to people, so Alice's user cannot change these files, and a CI job that runs `scripts/tests` on the PRs that change them.
- Rename `master` if your default branch is named otherwise, and keep every third-party action pinned to a commit SHA.
