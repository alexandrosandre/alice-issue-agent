---
name: ship-it-lite
description: >-
  Use when a low-risk change should become a merge-ready PR without the full
  pipeline's session-review overhead. Does not merge; the author keeps merge
  authority (see /lgtm or /yolo to merge).
license: CC-BY-4.0
metadata:
  author: Alexandros Andre Chaaraoui
  source: https://github.com/alexandrosandre/alice-issue-agent
---
# ship-it-lite

Run through the steps below and finish them. Defer anything needing human confirmation to the final summary.

At the end, summarize how far you got, the pending user decisions, and the findings you skipped.

## Steps

1. Review the changes the review bots have not seen yet, and skip this when there are none: the coding agent's built-in `/code-review` at its highest effort level, no auto-fix (where it has no such command, review the same changes yourself at that depth). Run it from a foreground general-purpose subagent that invokes the review command with this step's arguments and returns every finding; why is in /autoreview Step 5. Where the coding agent has no subagents, invoke it directly. With no target it reviews unpushed commits plus uncommitted edits; while the branch has no PR or the PR is a draft the bots have seen nothing, so fetch `origin/master` and pass it as the target to review the whole branch (local `master` is usually stale here). Fix review findings that are confirmed bugs, regressions, unfulfilled task intent, or AGENTS.md violations in the changed code, and the same mistake wherever else the change repeats it — the bots flag each copy on a later round. Leave nits, refactor preferences, and opportunistic improvements for the final summary; when in doubt, leave it.
2. Commit and push all pending changes on this branch (not only this conversation's). Before pushing, fetch and merge the base branch (the open PR's base, else `origin/master`), so this push carries it and no merge-only push follows it from /create-pr or /autoreview's Startup. If it conflicts, `git merge --abort` and push without it; /create-pr in step 3 then stops on the conflict and reports it.
3. /create-pr — it opens the PR, or refreshes the title/description in place if one is already open.
4. /autoreview

## Closing

- End your response with a blockquote line: **Skills used:** then each skill name in backticks (this skill: `ship-it-lite`; include other skills if used).
- If this skill's instructions failed or needed a workaround, update this file.
