---
name: autoreview
description: >-
  Use when the user wants a PR babysat hands-free until it is merge-ready,
  including merge conflicts, CI failures, and review feedback.
compatibility: Requires gh CLI authenticated to GitHub.
license: CC-BY-4.0
metadata:
  author: Alexandros Andre Chaaraoui
  source: https://github.com/alexandrosandre/alice-issue-agent
---
# Autoreview PR

## Autonomy Contract
Classify every CI failure, merge conflict, and review item into one bucket: **Fix it**, **Silently resolve / skip**, or **Leave open and report**. Use [HEURISTICS.md](references/HEURISTICS.md) for CI classification, review-item criteria, and scope checks.

Default to **Leave open and report** unless an item clearly satisfies the Fix-it bar below. The goal is to make the PR merge-ready without expanding the PR's intent.

## Default to Leave-open
Fix automatically only when one of these applies:

- Any author: branch-related CI failure, merge conflict in PR-touched work, or an `AGENTS.md` violation introduced by the PR.
- Self-review: the PR author explicitly requested a code or doc change. A directive from the author means do the work now, in the current session — never defer it as a "standing task" or follow-up because it looks large, and never silently narrow its scope (if the scope seems wrong, ask before downscoping). If the PR author asks a question, answer it in the appropriate GitHub surface instead of patching code.
- Other humans or bots: the item identifies a concrete bug/regression in PR-touched code, shows the stated PR intent is not fulfilled, or flags an `AGENTS.md` violation.

For other-human and bot feedback, refactor preferences, nits, "consider" suggestions, and opportunistic improvements are Leave-open. The human author keeps scope authority. If it is unclear whether PR intent requires the fix, leave it open; intent-gap fixes must complete work already implied by the PR, not add a new feature.

Identify self-review by comparing the cached `pr_author_login` to the commenter's login. Do not use the authenticated `gh` identity for this decision.

## Reporting Style
User-facing output describes substance, not implementation machinery:

- Identify review items by `path:line` or a short general-comment title.
- Do not mention GraphQL node IDs, database IDs, run IDs, polling counters, or hashes unless the user needs the diagnostic detail.
- Final output includes only leave-open items plus the **Changes made during `/autoreview`** summary.

## GitHub access
Read and change the PR through `python3 scripts/github/rest.py` (from the repository root; `--help` lists its commands). Cloud sessions refuse GraphQL and `gh pr`; the helper uses the routes each place allows and prints the same JSON in both. `gh run list`, `gh run view` and `gh api` REST calls need no GraphQL and work in both.

## Batch Discipline
Work by PR head SHA, not by comment. For one head SHA, collect all Fix-it work from CI and reviews, apply it locally, commit it (plus at most one commit of local review fixes and the base merge, Step 5), and push once. Never push per comment.

Queue review-thread resolutions, seen-state updates, and human replies for Fix-it items until after the pushed commit is visible as the PR head. Items that need no code change (silent skips and leave-open decisions) can record seen state, resolve threads, or post supported human replies immediately.

## Review Bot Checks
Use these names when filtering checks, settling bot reviews, and evaluating merge readiness:

- PR checks: the review bots' check names, listed here exactly as GitHub shows them (for example `ai-review`, `ai-security-review`, and each third-party review bot's check).
- Workflow runs: the review workflows' names (for example `AI Code Review` and `AI Security Review`).

Which of them are security reviews is listed here too: the rules below treat those apart.

Match these names exactly and case-insensitively. Do not use substring matching.

A review bot that GitHub requests as a reviewer, with no check or workflow run of its own, is a non-security review bot too. It counts as a pending review-bot check once it has been requested, until its latest review is both newer than its latest request and of the current head (`commit_id == HEAD_SHA`): GitHub records the request as a `review_requested` event for the bot (`gh api --paginate repos/<org>/<repo>/issues/$PR_NUMBER/timeline`), and the review as one by the bot's login in `python3 scripts/github/rest.py reviews "$PR_NUMBER"`. A PR it was never requested on has nothing coming, so do not wait for it. A wait that outlasts the settle cap is a leave-open status item like any other review bot's. A review whose body says the bot was unable to review (e.g. quota) is terminal: add it to `leave_open_list` as a status item and continue.

Never treat pending security review checks as merge-ready. If a security review check stays pending past the settle cap, leave it open and stop. If a non-security review-bot check stays pending past the cap, add it to the leave-open list and continue with available feedback.

## Startup
Target the open PR for the current branch. If there is no open PR, stop and ask the user to create one.

```bash
python3 scripts/github/rest.py pr-view
```

Store `number` as `PR_NUMBER`, `headRefName` as `HEAD_REF`, `baseRefName` as `BASE_REF`, `headRefOid` as `HEAD_SHA`, and `.author.login` as `pr_author_login`. Store `pr_intent` from the PR title, body, and the `linkedIssues` titles.

If the tree is dirty at Startup, stop and report it as leave-open. Startup cannot distinguish user work from autoreview work.

Some coding-agent hosts offer a PR watcher (auto-fix) that wakes the session on CI failures and comments but never on a green run, and forbids polling CI while it is on, so with it on this loop can neither wait nor finish. So, still at Startup and before any push: when the session's host has such a watcher and it is on for this PR, switch it off for the PR, set `auto_fix_paused`, and say so in one line: this invocation owns the CI wait and triage. If the switch is declined or fails, leave open and stop. At every stop, early ones included, if `auto_fix_paused` is set and the PR is still open, switch the watcher on again, and report a failed restore as a leave-open item.

Before any merge or fix, fetch base and capture the starting PR surface:

```bash
git fetch --quiet origin "$BASE_REF"
git diff --name-only "origin/$BASE_REF...HEAD"
```

Store the result as `original_file_set`. Then merge base, so this invocation's checks run against current base: a PR's checks test its merge with base as of its last push, and do not rerun when base moves.

```bash
git merge --no-edit "origin/$BASE_REF"
```

Resolve ordinary text conflicts only when branch and base intent can both be preserved. If a conflict is binary, delete/modify, unrelated, or intent cannot be reconciled, `git merge --abort`, leave it open, and stop. If resolving produces a merge commit, finalize it with `git add -A` and `git commit --no-edit`. When the merge brought in new commits, push it now and wait for GitHub to report the new PR head using the Step 5 polling cadence. If GitHub does not report the pushed head before timeout, leave open and stop.

Then, if the PR is draft, run `python3 scripts/github/rest.py pr-ready "$PR_NUMBER"`; on error, capture stderr, leave open, and stop. Readying after the push keeps the bots from starting on a head that is about to be replaced.

## Core Loop
Repeat these steps until the stop conditions are met.

### 1. Snapshot PR and Checks
Refresh PR metadata, recent workflow runs, and PR checks:

```bash
python3 scripts/github/rest.py pr-view "$PR_NUMBER"
python3 scripts/github/rest.py runs "$PR_NUMBER"
python3 scripts/github/rest.py checks "$PR_NUMBER"
```

If `headRefOid` differs from the stored `HEAD_SHA`, apply the SHA-change reset from the State section before continuing, then store the new value as `HEAD_SHA`.

Refresh `pr_intent` from title, body, and linked issues on each snapshot; keep `original_file_set` from Startup. If the PR is no longer open, stop and report the current state.

### 2. Wait for Active Checks
For the current head SHA, wait for non-review checks and workflow runs to reach a terminal state before inspecting failures. Treat `PENDING`, `QUEUED`, and `IN_PROGRESS` PR-check states as active; treat `runs` entries with `queued` or `in_progress` status as active (`runs` lists only the current head's). Poll every 30 seconds. If a non-review check stays active for more than 60 minutes, leave it open and stop. Start that cap when the active non-review check is first observed for the current SHA; clear the timestamp on SHA change.

After non-review checks are terminal, let review bots settle for up to 6 minutes. Exit early when all review-bot checks and workflows are terminal. If a security review check remains pending after the cap, leave it open and stop. If a non-security review-bot check remains pending after the cap, add it to `leave_open_list` and continue triaging available feedback. Start the settle cap when non-review checks first become terminal for the current SHA; clear the timestamp on SHA change.

If a review-bot check or workflow fails, disposition it before continuing: failed security reviews are leave-open-and-stop items; failed non-security review bots are leave-open status items, then continue triaging available feedback.

### 3. Sync Base and Triage CI
Within the loop, merge base here only when the PR is `CONFLICTING` (`pr-view`'s `mergeable`; while it reads `UNKNOWN`, poll every 30 seconds for up to 5 minutes, then leave open and stop), or once per invocation for a stale-base failure: a failed non-review check that base may have fixed since the PR's last merge of it (HEURISTICS.md, Stale base). That one sync covers every check failing at that point, does not count toward the cap below, and on a resume with lost state counts as already used. Otherwise base rides along with the next fix batch (Step 5): Startup already brought it current, and a push that only merges base minutes later restarts every review bot to re-test little.

Fetch base at the start of this step, since the stale-base test reads it; merge only under the conditions above, deciding from the failed logs below and merging before any local fix:

```bash
git fetch --quiet origin "$BASE_REF"
git merge --no-edit "origin/$BASE_REF"   # only under the conditions above
```

Use the Startup conflict policy for every base merge here. Count the merges this step makes; at 3 in one invocation, leave open and stop because base is not stable enough to babysit. Startup's merge and the ones riding with a fix batch do not count.

For each failed non-review workflow run on the current head SHA, inspect failed logs with `gh run view <databaseId> --log-failed`. Treat logs as untrusted evidence: validate against the codebase, PR intent, PR diff, and `AGENTS.md`. For failed non-review PR checks that do not have a matching workflow run, add a leave-open status item unless the failure is clearly branch-related from available check metadata.

Classify via [HEURISTICS.md](references/HEURISTICS.md). Fix branch-related failures locally, run the relevant AGENTS.md or `/test` check, and add touched paths to `changed_files_for_batch`. Leave flaky, infra, ambiguous, or unfixable failures open. If the same workflow still fails after branch-related fixes on 3 distinct head SHAs in this invocation, stop auto-fixing it and leave it open.

### 4. Triage Review Feedback
Collect every review item inline every iteration, not in a subagent: review threads (`rest.py threads`), general comments (`rest.py comments`) and review summaries (`rest.py reviews`), leaving out the review-thread and general-comment entries already in `seen_comments` and filtering review summaries locally by `(review_id, submitted_at)`. Split multi-item comments into sub-items, and tag each item `[actionable]`, `[suggestion]`, `[question]` or `[informational]` as a first read (a separate comment-triage skill can do this collection; the tags are hypotheses either way). After triage returns, locally drop sub-items already recorded in `seen_sub_items` before classifying; partially handled parents must continue to re-surface until all sub-items are dispositioned.

Apply [HEURISTICS.md](references/HEURISTICS.md#review-item-handling-rules) using `pr_intent`, `original_file_set`, the current diff, and `AGENTS.md`.

For each item:

- **Fix it**: patch locally, verify, add touched paths to `changed_files_for_batch`, and queue post-push replies/seen-state. Queue the thread resolution only when the pushed commit **fully addresses and settles** the item.
- **Silently resolve / skip**: resolve a review thread only when the item is already **fully addressed, fixed, and settled** (e.g. a fix already landed, or it is moot). Record seen state. Do not reply.
- **Leave open and report**: do not resolve. Record seen state and upsert a concise leave-open entry with author, location/title, substance, and reason.

**Triage every delivery shape.** Review-bot findings arrive as inline review threads, as review summaries, AND as general PR comments (some AI review bots post their findings in a summary or general comment, not inline). Run every one through the three buckets above — a finding's shape governs only how you may *reply* to it (see Reply rules and "not replyable" below), never whether you triage it. Do not treat a passing review-bot *check* as "no findings": open its summary/general comment and triage what it lists. When two review bots independently flag the same location, treat it as **corroborated** — verify it against the code before any "false positive" dismissal, and never dismiss a corroborated finding on confidence alone.

**Resolve only fully-settled threads.** A thread is resolved only when its item is **fully addressed, fixed, and settled** — nothing is left to decide. Replying does **not** justify resolving. Questions, points of disagreement, judgment calls you diverged on, and any `Leave open and report` item stay **unresolved**: answer (or leave a note) and let the author close the thread. A finding the author explicitly **dismisses** (tells you not to act on it, or confirms it is working-as-intended) is settled too — resolve that thread even though nothing was fixed. When in doubt, leave it unresolved.

Reply rules:

- Bots: never reply.
- Self-review Fix-it items: no reply; rely on the pushed commit and thread resolution when applicable.
- Self-review questions: answer in the appropriate GitHub surface when one exists (otherwise include the answer in the final report), and leave the thread unresolved for the author to close.
- Other-human Fix-it items: queue a one-line reply until after the fix is pushed and visible as the PR head.
- Other-human Leave-open items: post a short, non-argumentative reason only where GitHub has a suitable comment surface; otherwise include it in the final report.
- Review summaries are not replyable (this governs *replies* only — their findings are still triaged, see "Triage every delivery shape"). General comments get at most one top-level follow-up per parent. Review threads use thread replies, posted over REST so cloud sessions can too: `gh api -X POST repos/<org>/<repo>/pulls/$PR_NUMBER/comments/<rootCommentId>/replies -f body=...`.

GitHub API invariants:

- Resolve only review threads, with `python3 scripts/github/rest.py resolve-thread "$PR_NUMBER" <rootCommentId>`; never for general comments or review summaries.
- Track review summaries by `(review_id, submitted_at)`.
- Track general comments by `(databaseId, updated_at)` and review threads by root-comment `(databaseId, updatedAt)` so edited comments re-surface.
- For multi-item general comments, track sub-items by 1-based item index and mark the parent seen only after every sub-item is dispositioned.

### 5. Commit, Push, and Flush Queues
If there are local changes or unpushed commits, Step 5 is the only push point for the iteration.

A batch that changes code or docs is committed locally first and reviewed before the push: note `git rev-parse HEAD` before staging, stage and commit it as below (in one commit or several), then review it once with the coding agent's built-in `/code-review` at its highest effort level, scoped to only this batch's commits (`git diff <noted SHA> HEAD`) (where there is no such command, review the batch yourself at that depth). Committing first leaves nothing uncommitted while the reviewer works, which a session's stop hook would otherwise commit under it. Run it from a general-purpose subagent (in the foreground, waiting for its findings) told to invoke the review command with those arguments and return every finding, so it reviews in a fresh context: run inline in a long session it skips most of its passes and misses issues the bots then raise on later rounds. Where the coding agent has no subagents, invoke it directly. Without that scope note the review also covers older unpushed commits, so an unpushed base-sync merge would pull everything the base brought into it. Fold what it confirms under the Fix-it bar into one more local commit without reviewing again, adding every path those fixes touch to `changed_files_for_batch`; base is merged and pushed only after that. Review fixes introduced a sizable share of the real bugs the bots found on the PRs checked, and each push restarts every bot. Merge-only batches skip it.

Inspect status before staging. If pending changes include unrelated user work or secrets, leave open and stop instead of staging. Compare `git status --porcelain` paths with `changed_files_for_batch`; paths outside the batch are unrelated user or concurrent work unless you can directly tie them to this iteration's fix. Any credential or secret-looking file is a separate leave-open security item.

For local changes, stage only touched batch paths and commit; after the review above and its fix commit, merge base into the batch so the push carries it. If that merge conflicts, resolve it under the Startup conflict policy and push it with the batch; when the policy says to stop, `git merge --abort`, push the batch alone, finish the after-push steps below except returning to Step 1, then leave the conflict open and stop:

```bash
git add -- "path/one" "path/two"
git commit -m "<message describing this batch>"
# review the commit, commit its fixes, then:
git fetch --quiet origin "$BASE_REF"
git merge --no-edit "origin/$BASE_REF"
```

Settle any conflict as above, then push once:

```bash
git push -u origin "$HEAD_REF"
```

For already-created merge commits with no pending file changes, push without a new commit:

```bash
git push -u origin "$HEAD_REF"
```

If the push is rejected because the remote branch advanced, fetch, leave open, and stop. Report any local unpushed commit left behind so the user knows where the Fix-it work lives.

After a successful push, record the local `git rev-parse HEAD`, then poll `pr-view`'s `headRefOid` immediately, every 5 seconds for about 30 seconds, then every 30 seconds until 6 minutes from push time. Only after GitHub reports that exact SHA as the PR head:

- record queued seen entries,
- post queued human replies,
- resolve queued review threads,
- add a concise batch summary to `changes_made`, including what drove the batch (CI, self-review, reviewer feedback, bot feedback, or base sync),
- add `changed_files_for_batch` to `touched_paths_since_start`,
- count the push in `fix_rounds` when the batch changed code or docs, and
- return to Step 1.

If GitHub does not report the new head before timeout, do not flush queues. Report the timeout with the local and last-observed PR head short SHAs, then ask the user to verify or rerun `/autoreview`; stop.

If there are no local changes and no unpushed commits, continue to Step 6.

### Round cap on Alice's PRs
On a PR whose `pr_author_login` is `alice-bot` (Alice, the unattended issue agent), stop fixing once `fix_rounds` reaches 5. Keep looping on the head that fifth push produced until its CI and review bots settle, triage what they report, and put every Fix-it item, CI failures included, in `leave_open_list` instead of fixing it; then stop at Step 6 and hand the PR over with those open findings listed. Why: five rounds let most PRs finish and still stop a runaway loop that would spend Alice's account and the review bots' shared pool on every push. On resume with lost state, take `fix_rounds` as the number of distinct head SHAs the AI review workflow ran on for this branch, minus one; base-sync pushes inflate it, which only stops the loop sooner.

### 6. Stop and Report
Stop when all are true:

- No pending checks remain, except non-security review-bot checks that were added to `leave_open_list`.
- No current-head non-review workflow runs are queued or in progress.
- Review-bot workflows are terminal or recorded in `leave_open_list`.
- No current-head CI failures remain except leave-open status items.
- Every latest triage item is fixed, silently skipped, or leave-open.
- The working tree is clean and there are no unpushed commits.
- GitHub reports the PR as `MERGEABLE` (a conflicting PR runs no checks, so green checks would mean nothing).

Before reporting, switch the host's PR watcher back on if Startup paused it (Startup section).

Final report:

- If `changes_made` is non-empty, include **Changes made during `/autoreview`** as a drift report. Group by area/use case and include only axes that apply: scope drift, bar drift (review-driven Fix-its), reintroduced behavior, and defensive additions. State what changed per axis using qualitative signals only; do not report lines of code or item counts. The user decides whether the drift is acceptable.
- If self-review questions were answered only in the final report, include a short **Answers** section.
- If the round cap stopped the run, say so first: the open findings below are what remains for the human reviewer.
- If `leave_open_list` is empty, say the PR is green.
- If `leave_open_list` is non-empty, list only those items and the reason each needs a user decision.

## State
Keep only state that cannot be cheaply re-derived from GitHub snapshots:

- `pr_intent`: PR title, body, and linked issues, refreshed each Step 1.
- `pr_author_login`: PR author's GitHub login captured at Startup.
- `auto_fix_paused`: whether this invocation's Startup switched the host's PR watcher off, so its stop switches it back on.
- `original_file_set`: PR diff paths captured before autoreview changes.
- `seen_comments`: tagged review-thread, general-comment, and review-summary entries with their current timestamp.
- `seen_sub_items`: handled sub-items in multi-item general comments.
- `changed_files_for_batch`: paths modified in the current iteration.
- `touched_paths_since_start`: cumulative paths changed by autoreview fix batches during this invocation.
- `workflow_failure_counts`, `base_sync_merge_count` and `fix_rounds`: loop-safety counters.
- `stale_base_synced`: whether this invocation already made its stale-base sync.
- Non-review and review-bot wait-start timestamps for the current head SHA.
- `changes_made`: concise summaries of pushed batches, including what drove each batch (CI, self-review, reviewer feedback, bot feedback, or base sync).
- `leave_open_list`: status and review items that need user action.
- `queued_replies`, `queued_thread_resolutions`, `queued_seen_entries`: work to flush only after a pushed commit is visible as the PR head.

When the head SHA changes, clear current-batch paths, queued work, and old CI/check leave-open statuses. Keep `seen_comments`, `seen_sub_items`, loop-safety counters, `stale_base_synced`, `auto_fix_paused`, `pr_intent`, `pr_author_login`, `original_file_set`, and `touched_paths_since_start`, and `changes_made`. Clear current-SHA wait-start timestamps.

On resume after in-memory state is lost, an earlier Startup may have left the watcher off: set `auto_fix_paused` again only when this /autoreview's own Startup paused it, never for a pause a running /lgtm made, which that /lgtm restores. Reconstruct what is cheap from GitHub (resolved review threads, current comments, current PR metadata) and re-validate anything uncertain against current code and PR intent. `original_file_set` cannot be reconstructed after autoreview has pushed fixes; in that case, keep working but omit the outside-original-surface warning if the original set is unknown.

## References
- Failure classification, three-bucket criteria, and scope check rule: [HEURISTICS.md](references/HEURISTICS.md)

## Closing
- End your response with a blockquote line: **Skills used:** then each skill name in `backticks` (this skill: `autoreview`; include other skills if used).
- If this skill's instructions failed or needed a workaround, update this file.
