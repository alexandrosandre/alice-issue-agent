---
name: lgtm
description: >-
  Use when the user invokes /lgtm, or when the PR author replies a plain
  "LGTM" in chat or on a PR review turn (an LGTM from anyone else is a review
  comment, not a trigger): take the branch from wherever it is all the way to
  a conditional self-merge.
compatibility: Requires gh CLI authenticated to GitHub.
license: CC-BY-4.0
metadata:
  author: Alexandros Andre Chaaraoui
  source: https://github.com/alexandrosandre/alice-issue-agent
---
# lgtm

The user has LGTM'd this branch, approving the work for merge. That approval carries you all the way to merge — but it is conditional: CI/CD must be green, real review findings must be addressed, and the approval goes stale if the code changes substantially afterwards.

## Steps

1. First commit any pending work as it stands and note the head SHA: that is what the user approved, and step 5 compares against it. Then review the changes the review bots have not seen yet, and skip the review when there are none: the coding agent's built-in `/code-review` at its highest effort level, no auto-fix (where it has no such command, review the same changes yourself at that depth). Run it from a foreground general-purpose subagent that invokes the review command with this step's arguments and returns every finding; why is in /autoreview Step 5. Where the coding agent has no subagents, invoke it directly. With no target it reviews unpushed commits plus uncommitted edits; while the branch has no PR or the PR is a draft the bots have seen nothing, so fetch `origin/master` and pass it as the target to review the whole branch (local `master` is usually stale here). Fix review findings that are confirmed bugs, regressions, unfulfilled task intent, or AGENTS.md violations in the changed code, and the same mistake wherever else the change repeats it — the bots flag each copy on a later round. Leave nits, refactor preferences, and opportunistic improvements for the final summary; when in doubt, leave it. Commit the fixes in a commit of their own, so step 5 can judge them.
2. Take on from wherever the branch is: commit and push pending changes (all of them, not only this conversation's). Before pushing, fetch and merge the base branch (the open PR's base, else `origin/master`), so this push carries it and no merge-only push follows it from /create-pr or /autoreview's Startup. If it conflicts, `git merge --abort` and push without it. With no PR, /create-pr then stops on the conflict: stop and report it. With a PR, /autoreview's Startup applies its conflict policy. Then /create-pr if there is no PR.
3. /autoreview — it owns base sync, draft-readying, the CI wait, and review triage until the PR is merge-ready. If it stops on something only the user can decide (unreconcilable conflicts, failed or stuck security review, flaky infra), stop and report likewise. Before it, pause the host's PR watcher (auto-fix) with the same check /autoreview's Startup describes, without setting its `auto_fix_paused` (that flag makes /autoreview restore the watcher at its stop); if the switch is declined or fails, stop and report rather than run /autoreview with the watcher on. When it does pause the watcher, say so in one line, so the transcript records the pause through a resume. Keep it paused across every /autoreview run of this /lgtm: switched back on between them, it would act on the PR while you fix and merge it. If this /lgtm paused it and stops without merging, restore it as /autoreview's restore at stop describes.
4. Settle autoreview's leave-open items with the authority the LGTM grants: fix the ones that are clear, consequential bugs/regressions in PR-touched code or unfulfilled PR intent — not improvements or theoretical-only edge cases — and dismiss the rest, listing them with reasoning in the final report. Then resolve every remaining review thread — branch protection blocks merging otherwise, and the user's LGTM covers dismissing them; on a human's thread, add a one-line reason first. If this pass changed anything, review those changes as in step 1 and merge the base branch into them as in step 2 before pushing them, then re-run /autoreview for the new head.
5. Before merging, `git fetch origin master` and check that the PR's head on GitHub (`headRefOid` from `python3 scripts/github/rest.py pr-view <PR>`) is your local `HEAD`; a head you did not push is another session's work, so stop and report it. Then compare the PR's own changes at the approved SHA and at `HEAD`: `git diff --binary $(git merge-base origin/master <sha>) <sha> | grep -v '^index ' | git hash-object --stdin` against the same for `HEAD`. Equal fingerprints mean nothing of the PR's changed and the LGTM stands: they match only when every changed line, its surrounding lines, its position and any binary content are identical, as after a rebase or merge from master that touched only other files, or lines further down than the PR's. Anything else differs and goes to the classification below, including master editing the same file above the PR's lines; that direction is safe, while a fingerprint that matched across a real change would skip the classification, which is why `git patch-id` or a diff stripped of positions do not stand in. Classify what differs (step 1's fixes, step 2's master merge and its conflict resolution, and pushes by /autoreview or step 4); the merge report lists each change the first two classes kept:
   - **Trivial** (typos, comments, lint, test-only, mechanical), leaving production behavior as it was approved: the LGTM stands.
   - **Fix within intent**: a fix for a bug the review or CI found in code the PR adds, that only makes the PR do what its description already says, with no new scope, no change to a decision the PR lists, and no edit to code the PR did not change: the LGTM stands.
   - **Substantial** (anything else, such as a conflict resolution that re-applies the PR onto code master rewrote): the LGTM is stale — **stop without merging** and report what changed so the user can issue a fresh /lgtm.
6. Refresh the PR title and description if they have drifted (`AGENTS.md`, Pull Requests & Issues), then merge: `python3 scripts/github/rest.py pr-merge <PR> <HEAD SHA checked in step 5>`, which works in cloud sessions too (it squash-merges, the only allowed merge method; the pinned SHA makes GitHub refuse the merge if someone pushed after step 5, and then you go back to step 5). No `--admin` — if new unresolved threads caused a rejection, return to step 4; otherwise stop and report.

Report the PR number, the merge result (or why it was withheld), CI fixes made, and findings applied vs. dismissed.

## Notes

- The /lgtm invocation itself is the explicit per-PR merge approval; no further confirmation is needed unless the approval goes stale (step 5).
- In Alice's Merge round (alice skill) the approval is the one her PR's issue reviewer gave on GitHub, and "the user" in the steps above is that reviewer.
- Unlike /yolo, review findings are triaged. Unlike /autoreview alone, the end state is a merge, not a report.

## Closing

- End your response with a blockquote line: **Skills used:** then each skill name in backticks (this skill: `lgtm`; include other skills if used).
- If this skill's instructions failed or needed a workaround, update this file.
