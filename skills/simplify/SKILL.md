---
name: simplify
description: Reads the branch's own changed code for what it can lose without changing behavior — code nobody needs yet, logic the repository already has, constructs a cold reader trips on, work done twice — and fixes what it finds. Use when cleaning up after implementation, reviewing recent changes, or simplifying code.
license: CC-BY-4.0
metadata:
  author: Alexandros Andre Chaaraoui
  source: https://github.com/alexandrosandre/alice-issue-agent
---

# Simplify

Take what this branch added and make it shorter and plainer, doing exactly what it did before. The yardstick is `AGENTS.md`, Code Style: readability first, then everything else. Edit the code yourself; this skill does not hand back a list.

## 1. Pick the files

Only code the user wrote on this branch is in play. Code that arrived through a merge from `master` is someone else's: listing changes with `gh pr diff`, `git show` or per-commit diffs drags it in, so do not use them.

- Paths or patterns the user named, when they named any.
- Otherwise the union of `git diff --name-only HEAD` (not yet committed) and, after `git fetch --quiet origin master`, `git diff --name-only origin/master...HEAD` (the branch since it forked, as GitHub shows a PR).
- No changes in git: the files edited earlier in this session.

Skip lockfiles, build output and vendored code, and anything under the experiments folder. Nothing left: say so and stop.

## 2. Know what must not move

Before editing, read enough around each change to know what other code relies on: what a function takes and returns, what it writes or sends, what it raises. All of that stays exactly as it is, and so does any public interface. Leave alone code whose behavior fast local tests cannot confirm: infrastructure templates, access policies, deploy scripts, client configuration, SQL whose shape was tuned. If the simpler version needs one of these to change, ask the user instead of editing.

## 3. Ask four questions of every hunk

In this order, because an earlier answer often settles a later one: code that should not exist needs no better name.

**Does it need to exist?**
- An option, parameter, flag or layer no current caller uses goes; it returns with the second real caller. Hardcoded values in `_main` or CLI entry points are for local testing: keep them.
- A guard for a value the caller already guarantees (`.get(key, default)`, `or {}`, `x if x is not None`) goes, so a broken contract fails loudly.
- Unused imports and variables, debug prints and commented-out code from iterating go.
- A new knob, guard or retry that serves a goal something existing already serves is two mechanisms for one goal. Which one owns the goal is the user's decision: leave both and name the pair in the report.

**Does the repository already have it?**
- Search the shared modules, the nearest `utils` and the neighboring files before keeping a new function; call the one that exists.
- A helper earns its place only for non-obvious logic used more than twice. One caller: inline it. A one-liner such as `a / b * 100` stays inline however often it repeats.
- A literal the code already names (a constant, an enum member) uses the name.

**Can a reader follow it cold?**
- Names in full words that say what the value is (`format_percentage`, not `_fmt_pct`).
- Edge cases first, with guard clauses and early returns, so the main path is not nested; a nested conditional expression becomes `if` statements; a bad input is rejected, not quietly clamped.
- A comment stays only when it explains why; one that repeats the code or tells the story of the change goes.
- Reach another module through its interface, not its internals, and do not leak your own.

**Does it do work for nothing?** Only where the leaner version reads as well:
- The same read, query or API call made twice, or once per item where one call covers all items.
- A whole file or collection loaded for one item.
- A write repeated on every loop pass, tick or event when the value rarely changes.

## 4. Verify

Run the linter of each service you touched and the tests for the modules you changed, not the whole suite. Fix what fails before you finish.

## 5. Report

A few lines: the files you edited, each simplification with its reason in one sentence, the lint and test results, and every pair of mechanisms for one goal you left in place. If the code was already clean, say that.

## Closing

- End your response with a blockquote line: **Skills used:** then each skill name in backticks (this skill: `simplify`; include other skills if used).
- If this skill's instructions failed or needed a workaround, update this file.
