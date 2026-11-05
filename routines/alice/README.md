# Alice routine

The cloud-agent routine behind Alice, the unattended issue agent. The sweep, which runs 5 minutes after each request to her and every 10 minutes besides ([`workflows/alice-sweep.yml`](../../workflows/alice-sweep.yml), [`scripts/alice/sweep.py`](../../scripts/alice/sweep.py)), fires it to start a cloud session on an issue assigned to `alice-bot`, and sends the issue's later rounds (review comments, answers, merges) into that session while it can reach it; a restart, an unreachable session or a round after an unconfirmed start fires it again (design D38). Each session follows the [`alice`](../../skills/alice/SKILL.md) skill.

## Why a routine, and why this prompt

The prompt is deliberately short: it names who she is, what the payload means, which part of it to trust (only the sweep's fixed lines), and hands over to the skill. Everything that can change lives in the skill, which is versioned and reviewed with the code; the routine's saved prompt changes almost never.

| | |
| --- | --- |
| Platform | A Claude Code routine on Alice's own Claude account (D2), in a cloud environment of her own (D16) |
| Trigger | API only, from the sweep; no schedule. Later rounds arrive as messages in the session, sent with a sign-in of the account (`scripts/alice/sign-in-claude.sh`) |
| Model | The strongest available model |
| Connectors | None (D26) |
| Generates | A ready pull request with review requested, or findings and questions on the issue |
| Source | [PROMPT.md](PROMPT.md) (the routine's instructions, verbatim) |

## Installing it

Signed in to claude.ai as Alice: create a Claude Code routine named `Alice` with [PROMPT.md](PROMPT.md) as its instructions, your repository, Alice's cloud environment, no connectors, the platform's own PR auto-fix off (D38 rejects it: it wakes on bots' comments too and skips the quiet period), and an API trigger. Store the trigger's URL and token as the repository secrets `ALICE_ROUTINE_FIRE_URL` and `ALICE_ROUTINE_TOKEN`; the sweep starts sessions only once the repository variable `ALICE_SWEEP_ENABLED` is `true`, and triage assigns Alice only once `ALICE_AUTO_ASSIGN_ENABLED` is `true` too (D39). Then run `scripts/alice/sign-in-claude.sh 1` so the sweep can send later rounds into the account's sessions, and again when its log warns that the sign-in ends.

Each further Alice account gets the same routine, with GitHub connected as `alice-bot`, its secrets suffixed `_2`, `_3`…, one line per secret in the sweep step of `workflows/alice-sweep.yml`, and its own sign-in. The sweep starts sessions on the routines in turn, spreading her runs over the accounts' usage limits.

The cloud environment needs: no GitHub token of its own (so Claude Code's GitHub proxy acts as the account's connected GitHub user, `alice-bot`); read-only credentials for every data source; the test login for the two test accounts; the coding agent's built-in memory switched off (she keeps her own, D41); and a setup script that installs the local stack's dependencies, a headless browser, the session-sharing CLI, and the end-of-turn hook that uploads her transcript (`scripts/alice/transcripts.py hook`).
