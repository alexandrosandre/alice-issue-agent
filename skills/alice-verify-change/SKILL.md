---
name: alice-verify-change
description: >-
  Functional verification of a branch's change at the risk level alice-assess-risk set
  (1 Low to 4 High): maps the touched surfaces to methods, runs them on the local stack and with
  a headless browser on the company's own test accounts, captures screenshots and recordings as
  PR evidence, and names the commit it verified. Use in Alice's sessions at the verification
  steps of /ship-it's `references/alice-steps.md`, and once more after the pipeline's last
  behavior-changing fix. Not for an interactive browser check by a developer.
license: CC-BY-4.0
metadata:
  author: Alexandros Andre Chaaraoui
  source: https://github.com/alexandrosandre/alice-issue-agent
---

# Verify change

The outcome is evidence a reviewer can trust without re-running it: what was exercised, the exact commands and their results, what it looked like, at which commit; and, just as plainly, what was not verified and why. No PR is handed over before the change was exercised end to end, or says what could not be and why (design Goal, `docs/design.md`).

Read the level from `$RISK_DIR/level.json`, with `RISK_DIR` as alice-assess-risk defines it, and the reviewer's riskiest changes from the newest `$RISK_DIR/assessment-*.json`: where the level's flows reach a change, drive its breaking scenario too, and list one no local flow can reach (a permission on the deployed role, a runtime version) in `not_verified`, one line each, since the riskiest changes stay out of the PR and reach nobody else. Commit before verifying: the evidence names the commit it ran on, and uncommitted work has none.

## Methods per level

Each level requires what `LEVEL_REQUIREMENTS` in `scripts/alice/risk_level.py` lists for it, and the Risk section marks exactly those. At 4 High, a change that alters the interface also shows the changed screens in the end-to-end flows' screenshots, tagged `end_to_end`.
- **1 Low.** Nothing to run here; CI on the PR is the evidence, and /autoreview waits for it.
- **2 Moderate.** The affected suites (commands per service in `AGENTS.md` or the service's own), with a test for the changed logic.
- **3 Elevated.** The changed flow driven on the local stack and looked at: a screenshot of each state the change alters, before and after where the difference is the point, and a recording when the change is an interaction over time. The preview this level also requires is started once, after the PR exists (/ship-it's `references/alice-steps.md`, step E).
- **4 High.** A reproduction on `master`; a test that fails before the fix and passes after, red then green per `AGENTS.md`; the end-to-end flows on the local stack with before/after on real read-only data; every test run listed; the change behind a feature flag where the area already has them; and the independent check below. Capture "before" on the pre-change code: during the reproduction, or by checking out the merge base's version of the changed paths (`git checkout <merge-base> -- <paths>`, never a stash) and restoring them from `HEAD` afterwards. The preview is required as at 3 Elevated.

Map the touched surfaces to flows from the diff: web-app routes from the changed pages and components (a component maps to the pages that import it; app-wide files, stores and styles map to the main pages); API endpoints, background jobs and the ingestion pipeline through their tests and their `_main` or CLI entry points.

## The local stack and the browser

- Start the stack with the repository's local start script, with the test login's automatic sign-in on, so the web app signs in without typing its password. Wait for the line that prints the web app's URL with a capped foreground until-loop: in a cloud session a background waiter dies when the turn ends and a bare `sleep` is refused. The first page can take a minute while the dev server compiles.
- Before saving anything through the local web app, confirm from the script's startup lines that the stack writes to its local copy of the database, not production. If it does not, verify read-only flows only and list the writes under not verified.
- Production writes: only on the company's own test accounts, `<TEST_ACCOUNT_ID>` and `<DEMO_ACCOUNT_ID>`, never on any other account, and only when the change needs a real production write (design D21): through the test login, or as test records (next bullet).
- Ingestion changes: run the ingestion pipeline's dry-run mode on the local stack, which returns what it parsed and would store without storing anything, with a request built for the account. When the web app must show a stored record, send test records to production ingestion for one of those two accounts, under a name that starts with `alice_test_`, never an existing record or real customer data, and say in the evidence which test record you used.
- Drive the web app with headless browser scripts written in the session scratchpad, never in the repo, on the company's own test accounts only: evidence lands in a PR, and a customer's account shows far more than the detail a PR may carry (`AGENTS.md`, Customer data). `<TEST_ACCOUNT_ID>` is the default, with the richer configuration; `<DEMO_ACCOUNT_ID>` carries integrations the first lacks: use it when the change touches one only it has. Use a 1920x1080 viewport, record video for recordings, and fail a flow on console errors: uncaught exceptions, error-boundary traces, API client errors, not the dev server's own chatter.
- Cloud machines are small and have no swap: run one stack and one browser at a time.
- Keep each run's full output in `$RISK_DIR/runs/`; the second risk pass reads it.

## Evidence

Screenshots go to the `alice-evidence` branch and recordings to the shared drive (design D30), through `scripts/alice/evidence.py`; name files with letters, digits, `.`, `_` and `-` only:

```bash
python3 scripts/alice/evidence.py screenshot --pr <n> --commit HEAD shots/*.png   # one embed URL per file
python3 scripts/alice/evidence.py recording --pr <n> --commit HEAD flow.webm      # the drive link
```

Before the PR exists use `--issue <n>`; with neither, keep the files and push them once /create-pr has opened the PR.

Write `$RISK_DIR/evidence.json` in the shape `scripts/alice/risk_level.py`'s docstring gives, with `commit` the full SHA verified, each run, screenshot and recording tagged in `proves` with the requirements it shows, anything the level requires that could not be run in `not_verified` with its `requirement` and the reason (a query over the read limit, a flow that needs a production write outside D21, a stack that would not start), and a requirement that does not apply in `not_applicable` with why. The Risk section marks each requirement from these tags, ❌ for one nothing names, so tag only what a run really shows. Cite no file only your session can open (a script in the scratchpad, `runs/`, the check's notes): give the command and its result instead. Everything in it, commands and captions included, lands in the PR as written, so it follows `AGENTS.md`'s rule for an end user's personal data in a PR (Customer data). Then render the Risk section again (alice-assess-risk, Output). Report to the caller in one line: level, commit, what ran, how many items were not verified.

## Independent check (4 High only)

At 4 High, once the first evidence is written, a second agent checks it without your reasoning: agents grading their own work skew positive (design D34). Launch one subagent with fresh context while the stack runs the evidence commit. Give it only the issue number (with no issue, the task as the user stated it), the stack's URLs, the account the evidence uses, the full SHA of that commit, and the paths of the tests the change added; never the diff's explanation, the PR text, the decision ledger, the Risk section or the evidence. Ask it to:

- read the issue with `python3 scripts/alice/issue_text.py <n>` (REST, which the cloud proxy allows, without the text GitHub hides), or the task statement when there is no issue, and drive the reported scenario on the running stack with a headless browser or the API, plus one variation of it, on that account only, with scripts in its own scratch directory and no edit to the working tree;
- run the added tests at the head, then in a `git worktree` of `git merge-base origin/master HEAD` with those test files copied in, where they must fail;
- answer `agree` or `disagree` per item with the commands it ran and their results, in `$RISK_DIR/independent-check.md`.

Add its commands to `runs`, tagged `independent_check`. On a disagreement, investigate: fix the change and run the check once more, or explain in the PR why the check was wrong. What stays contested goes in `not_verified` with `"requirement": "independent_check"` and the check's finding as `why`, so the Risk section marks the check not done.

## Re-verification

Run once more when a commit after the evidence commit changed what the verified flows run: a fix from the pipeline's later steps (/ship-it's code review, /autoreview, /contextual-review), or a base merge that changed code those flows call. Rerun those flows at the new head, push new screenshots under the new commit, and rewrite `evidence.json` so it names that commit, carrying over the preview URL and the `not_applicable` entries that still hold, and run again the checks that settled a "Before merging" item, with their `settles` tags. Commits that change neither (docs, comments, base changes elsewhere) need none.

## Closing

- End your response with a blockquote line: **Skills used:** then each skill name in backticks (this skill: `alice-verify-change`; include other skills if used).
- If this skill's instructions failed or needed a workaround, update this file.
