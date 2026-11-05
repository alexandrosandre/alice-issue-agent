---
name: test
description: Run tests and iteratively fix failures. Use before creating a PR, after code changes, or when tests are failing.
license: CC-BY-4.0
metadata:
  author: Alexandros Andre Chaaraoui
  source: https://github.com/alexandrosandre/alice-issue-agent
---
# Test Fix Loop

## When to Use
- Use when tests fail and you need to iteratively fix issues.
- Use when validating changes before creating a PR.

The repository's test gate script (name yours) covers the packages and apps a branch modified: for those it runs what the CI gate runs, the type checks, the linters and the affected suites. A check it cannot run locally (one that needs a deployed stack or paid model calls) it names and skips, so run that one by its own skill when the branch touches it.

1. Run the test gate script to identify failures.
2. If there are failures, read the script to understand what it does.
3. For each failure:
   - Fix the issue in the code.
   - Re-run only the specific test/linter that failed (do not run the full script).
4. Once each failure passes on its own re-run, run the script once more: it exits at the first failed check, so later checks may not have run, and a fix can break an earlier one. Fix what that run finds as in step 3, and report a failure you cannot fix in code (the environment, a flaky test, one already failing on master) instead of looping on it. Then stop: the PR's CI runs the full suites.

## Closing

- End your response with a blockquote line: **Skills used:** then each skill name in backticks (this skill: `test`; include other skills if used).
- If this skill's instructions failed or needed a workaround, update this file.
