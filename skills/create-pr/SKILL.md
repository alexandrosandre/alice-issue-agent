---
name: create-pr
description: Create a draft PR following project conventions. Use when asked to create a pull request, open a PR, or prepare a branch for review.
license: CC-BY-4.0
metadata:
  author: Alexandros Andre Chaaraoui
  source: https://github.com/alexandrosandre/alice-issue-agent
---
# Create PR

## When to Use
- Use when a user asks to create a pull request.
- Use when preparing a draft PR after completing work on a branch.

If there are pending changes (not committed), commit them before proceeding.

Create a pull request by following these steps:

1. Fetch and merge origin/master so the branch is current and mergeable:
   ```bash
   git fetch origin master
   git merge origin/master --no-edit
   ```
   If the merge introduces conflicts, stop and tell the user.

2. Detect GitHub issue number from branch name or chat history if applicable.

3. Write the PR title and a brief functional-level description, then create the PR — or, if the branch already has an open PR, update it in place. GitHub goes through `scripts/github/rest.py`, which works in cloud sessions too (they refuse GraphQL and `gh pr`). Detect which:
   ```bash
   BRANCH=$(git branch --show-current)
   EXISTING_PR=$(python3 scripts/github/rest.py pr-for-branch "$BRANCH")
   ```
   It prints only an open PR's number, never a closed or merged one's.
   - When writing PR descriptions, PR comments, or issue comments, do not assume the reader shares the context of the chat session. Lead with what was proven or decided, keep only the details useful to a reviewer coming in cold, and strip session-internal debugging ephemera.
   - Organize the description in `##` sections: **What** (the change, at the level of behavior), **Why** (the problem and what checking it found), **Risk**, **Decisions to check** (calls made without the user: the options weighed and why the winner, and approaches tried and dropped), **Out of scope** (what was left alone on purpose, problems already on master among them, with `path:line`). Those sections organize the brief functional-level description; they do not license a long one — each stays at the level of behavior, not a line-by-line walk through the diff.
   - **Risk** exists when /ship-it left `risk-section.md` in `RISK_DIR`, as alice-assess-risk resolves it; otherwise omit it. Copy it in unedited: it is the independent reviewer's and the verifier's record, which a human reviewer checks against the diff. The description opens, above the issue references, with `title` from `$RISK_DIR/level.json` in bold, followed on the same line by one sentence naming the intent the reviewer should judge, such as the decision the change rests on. **How to revert**, under the Risk section, is yours to write from the risk review's undo answer; a Risk section with no Undo heading means a plain revert restores everything the change itself wrote; when users can save new values through the change, also say what of those a revert leaves in place.
   - The title names this PR's contribution relative to `origin/master`.
   - The PR title MUST start with project scope(s) in square brackets, followed by a space and description: `[api] <short description>`, or `[api, shared] <short description>` for multiple scopes. The scopes are the repository's top-level areas (for example `api`, `web`, `backend`, `shared`, `clients`, `devops`, `agents`); pick the dominant area, or list several when significant changes span them. Check the title against the repository's title regex before creating the PR.
   - Issue references (`Fixes #N` / `Part of #N` per the Pull Requests & Issues rules in `AGENTS.md`) go at the top of the description, one line per issue. When `$RISK_DIR/evidence.json` holds a preview URL, the line after them is `Preview: <url>`; each recording it holds follows, with or without a preview, as a `Recording: [<caption>](<url>)` line, so a reviewer finds them without reading the Risk section. When it holds screenshots, the last of those lines ends with "(screenshots below)"; with neither a preview nor a recording, the line is "Screenshots below". After those lines, when `$RISK_DIR/share_url` holds a link (an Alice PR), the next one is `Use GitHub reviews to ask, comment or approve; or ask live: <link>`.
   - Use only the changes made in this branch, ignoring changes from merges from master. You should talk about the PR diff.
   - **Schema changes**: if a table or view definition changed, include the migration statements in the PR body.
   - **Infrastructure-as-code changes**: Ask for a manual infra run only for a deployment that nothing else reaches, naming that deployment; the reader runs every step listed, so a step the pipeline already takes costs them a needless deploy. A template the deploy pipeline deploys needs no step. A template only a person deploys gets the exact ready-to-run command for each stack and environment the change targets, written after reading the script that owns it: some are unfit to rerun as they stand, so a script name alone is not a step.
   - **Deploy steps**: If the PR requires a specific deploy order (e.g., infra before code, run migrations before deploy, coordinate two services' deploys), add a "Deploy steps" section to the PR body listing the ordered steps.
   - When updating an existing PR, first fetch its current body (the `body` field of `python3 scripts/github/rest.py pr-view "$EXISTING_PR"`), then regenerate the title, the functional summary, and any diff-derived schema-migration / infrastructure / `Deploy steps` sections from the current diff (so a changed diff never leaves stale migration or deploy text behind). Carry over only the free-form human-written prose from that fetched body that is not one of those generated sections.
   - Write the title to `<git-dir>/pr-title.txt` and the description to `<git-dir>/pr-body.md` (`git rev-parse --absolute-git-dir`) — with a file-writing tool or a quoted (`<<'EOF'`) heredoc, both keep backticks and quotes literal. Never inline generated text into a shell string: double quotes expand backticks and `$(...)`, and single quotes break on the first apostrophe. A session isolated to a worktree cannot write the shared git directory; it writes both files to its scratchpad directory instead and sets `PR_FILE_DIR` below to that directory rather than to `--absolute-git-dir`.
   ```bash
   PR_FILE_DIR="$(git rev-parse --absolute-git-dir)"   # pr-title.txt and pr-body.md written above
   if [ -n "$EXISTING_PR" ]; then
     git push
     PR_URL=$(python3 scripts/github/rest.py pr-edit "$EXISTING_PR" \
       --title-file "$PR_FILE_DIR/pr-title.txt" --body-file "$PR_FILE_DIR/pr-body.md")
   else
     git push -u origin "$BRANCH"
     PR_URL=$(python3 scripts/github/rest.py pr-create \
       --title-file "$PR_FILE_DIR/pr-title.txt" --body-file "$PR_FILE_DIR/pr-body.md")
   fi
   ```

4. Print the GitHub link to the new PR and open it in a browser:
   ```bash
   echo "$PR_URL"
   ```
   ```bash
   PR_NUMBER=$(echo "$PR_URL" | grep -oE '/pull/[0-9]+' | grep -oE '[0-9]+')
   gh pr view "$PR_NUMBER" --web 2>&1 || echo "PR URL: $PR_URL"
   ```
   - Skip the open step on headless environments.

## Closing

- End your response with a blockquote line: **Skills used:** then each skill name in backticks (this skill: `create-pr`; include other skills if used).
- If this skill's instructions failed or needed a workaround, update this file.
