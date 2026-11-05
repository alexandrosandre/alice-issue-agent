# Autoreview - Heuristics Reference

## Contents
- [CI Failure Classification](#ci-failure-classification)
- [Review Item Handling Rules](#review-item-handling-rules)
- [Decision Tree](#decision-tree)

---

## CI Failure Classification

### Branch-related - fix locally
Fix automatically when failed logs overlap with PR intent or PR-touched code.

| Signal | Examples |
|--------|----------|
| Compile or syntax error in touched files | `SyntaxError` or `TypeError` in changed files |
| Test failure in touched tests | Assertion or snapshot mismatch near changed behavior |
| Lint or type error in touched files | ESLint, mypy, pyright, or pylint in changed files |
| Missing import or undefined symbol | New import, renamed symbol, moved module |
| Contract mismatch introduced by the PR | Schema, API, model, or migration mismatch |

### Flaky or infra - leave open
Do not patch product code for these. Add a leave-open status item and continue. An unrelated flapping test can be a stale-base failure (Stale base, below).

| Signal | Examples |
|--------|----------|
| Runner provisioning failure | "Could not find a runner", runner lost communication |
| Network or registry timeout | Dependency download timeout, `npm ERR! network` |
| GitHub Actions infrastructure fault | Hosted runner crash, random SIGTERM |
| External outage | Third-party service failure unrelated to changed code |
| Unrelated flapping test | Failing file has no overlap with PR intent or touched code |
| AI review action out of its usage window | An AI review or security-review workflow ends in under a second with no work done, or dies mid-run after billed turns |

AI review actions often hide their error text, so their logs cannot separate an exhausted usage window from a rejected credential, and the window is the common cause. Report it and rerun once it resets. Never ask the user to rotate the token secret on run timing or the secret's age alone.

When the AI review workflows take their token from a pool of accounts, picked the same way on every run of a PR, a rerun lands on the same exhausted account: report which secret the run picked, so the user can take it out of the pool instead of waiting for the reset.

### Ambiguous failures
When unclear after first read:

1. Inspect failed logs: `gh run view <id> --log-failed`.
2. Compare failing paths with `pr_intent` and the PR diff.
3. Clear overlap with the PR's intent or changed contracts -> branch-related.
4. Clear unrelated infra/flaky signal -> leave open.
5. Still ambiguous after one pass -> leave open and report.

### Stale base
A stale-base failure is a failed non-review workflow run (a check with no run stays as SKILL.md Step 3 says) that base may have fixed since the PR's last merge of it. It needs both:
- base has moved (`git rev-list --count HEAD..origin/$BASE_REF` above 0, after Step 3's fetch), and
- the failure is not clearly the branch's. A failure clearly caused by the branch is fixed, never synced. A run of that workflow on base that failed and has passed since (`gh run list --branch "$BASE_REF" --workflow <name> --limit 5`) is evidence that base fixed it. An unrelated flapping test qualifies: base may have fixed or quarantined it.

Runner provisioning failures, network or registry timeouts, GitHub Actions infrastructure faults, external outages and an exhausted AI review account never qualify: a new base cannot change them. On a stale-base failure, if this invocation has not made its stale-base sync, sync base before fixing anything, leave the stale-base failures themselves unfixed this round, and let the next round's checks decide.

---

## Review Item Handling Rules

Apply these rules to review threads, general comments, and review summaries.

### Default
Default to **Leave open and report**. Move an item to **Fix it** only when it meets the main skill's author-specific Fix-it bar and is validated against the codebase, `pr_intent`, the current diff, and `AGENTS.md`.

### Three buckets
- **Fix it**
  - Identify: confirmed bug/regression in PR-touched code, PR intent not fully implemented, PR-introduced `AGENTS.md` violation, branch-related CI failure, or explicit self-review request from the PR author for a code/doc change. Intent-gap fixes must complete work already implied by the PR, not add a new feature.
  - Action: patch it and the same mistake wherever else PR-touched code repeats it (the bots flag each copy on a later round), verify, queue replies/resolutions/seen-state until the pushed commit is visible as PR head.
- **Silently resolve / skip**
  - Identify: informational note, praise, LGTM, status update, duplicate item, outdated item, or WAI/no-op guidance with no implied required change.
  - Action: no code change; resolve review threads when applicable and record seen state. Never reply.
- **Leave open and report**
  - Identify: unclear intent, blocked context, request that conflicts with rules, preexisting/unrelated issue, nit/refactor/style suggestion, or opportunistic improvement that does not advance `pr_intent`.
  - Action: keep unresolved where applicable, optionally post a short human reply where GitHub supports it, and include in the final leave-open report.

### Author-specific bar
- **Self-review**: if the PR author explicitly asks for a code/doc change, fix it. If they ask a question, answer it in the appropriate GitHub surface or final report instead of patching code.
- **Other humans**: fix only concrete bugs/regressions, unmet PR intent, or rule violations. Reply with one line for Fix-it or Leave-open items where GitHub has a suitable comment surface; otherwise include the answer or reason in the final report. Do not reply for silent skips.
- **Bots**: use the same Fix-it bar as other humans, but never reply.

### Triage tag mapping
- `[informational]` maps to **Silently resolve / skip** unless it identifies a concrete PR risk.
- `[question]` maps to Fix-it only for self-review requests that clearly require code/doc changes. Other questions usually map to Leave-open or a short answer without code changes.
- `[actionable]` and `[suggestion]` are hypotheses. Validate them against `pr_intent`, the diff, the codebase, and `AGENTS.md`; do not fix by label alone.

### Handling per item type
- **Review threads**: resolvable with `scripts/github/rest.py resolve-thread`. Resolve a thread only when its item is fully addressed, fixed, and settled; replying does not by itself justify resolving. Questions, points of disagreement, and leave-open items stay unresolved for the author to close. An explicit author dismissal (won't-fix / working-as-intended) settles the item too — resolve that thread even though nothing was fixed.
- **General comments**: not thread-resolvable. Multi-item comments are handled per extracted sub-item; mark the parent fully seen only after every sub-item is dispositioned.
- **Review summaries**: not thread-resolvable and not replyable. Track as `(review_id, submitted_at)`.

### Scope check rule
Scope is anchored on `pr_intent` first, not the moving diff. Use the diff to validate facts, not to expand the PR.

Before classifying as Fix-it, ask:

- Does this item need to be addressed for the PR title/body/linked issues to be true?
- Did the PR introduce or modify the flagged behavior?
- Would ignoring it cause the PR to be a no-op, regress behavior, violate `AGENTS.md`, or hide a fresh bug?

If yes, it may be in scope. If uncertain, leave it open. If the item is merely a nice-to-have, refactor, style preference, unrelated preexisting bug, or broader cleanup, leave it open and report. Files outside `original_file_set` can still be in scope, but only when `pr_intent` genuinely depends on them.

---

## Decision Tree

```text
Failed CI run?
|-- Stale-base failure (see Stale base), no stale-base sync yet this invocation? -> Sync base once
|-- Branch-related by logs + PR intent/diff overlap?
|   |-- Yes -> Fix it
|   `-- No -> Leave open as flaky/infra/unrelated
`-- Still ambiguous -> Leave open and report

Review item?
|-- Resolved/outdated/already seen at current timestamp -> silently skip
|-- Informational/praise/LGTM/WAI with no required change -> silently skip
|-- PR author explicitly asks for code/doc change -> Fix it
|-- PR author asks question -> answer where possible; otherwise final report
|-- Concrete bug/regression, unmet PR intent, or rule violation?
|   |-- Yes -> Fix it
|   `-- No -> Leave open and report
`-- Before acting, validate against codebase, pr_intent, diff, and AGENTS.md
```
