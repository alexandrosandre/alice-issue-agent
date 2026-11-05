---
name: contextual-review
description: >-
  Reviews changed code against the session transcripts for intent fidelity, design drift, and
  context-dependent bugs diff-only reviewers cannot catch. Use when the user requests
  /contextual-review, before /autoreview for risky or intent-heavy changes, or after /autoreview
  when its fixes may have changed the intended scope.
license: CC-BY-4.0
metadata:
  author: Alexandros Andre Chaaraoui
  source: https://github.com/alexandrosandre/alice-issue-agent
---

# Contextual Review

Behavioral review of the branch diff against the literal session transcripts. Dispatches a single reviewer subagent that reads the transcripts and the diff together, returns severity-tagged findings, and presents them to the user for triage. Invoked on its own, it never auto-fixes.

The name "contextual" is deliberate: this skill complements diff-only reviewers (the coding agent's built-in `/code-review`, the AI security review, the third-party review bots) by adding the one thing they cannot have: session context. Do not rename it to `/code-review`; that collides with the coding agent's built-in command and with the CI review workflow that invokes it.

## Why this skill, and what it does NOT do

Our PRs already get automated reviews from several bots (the checks `/autoreview` waits on are under its Review Bot Checks).

Plus the repository's test gate script (run by `/test`) gates on the linters, the type checks, the infrastructure-template linter, and the test suites.

The PR reviewers see only the PR diff, and the test gate exercises behavior without knowing the session intent. None of them have **session context** — they don't know what the user actually asked for, which alternatives were rejected, what constraints were added mid-session, or which edge cases were discussed.

This skill fills that single gap: it reviews the diff against the **literal session transcripts**, looking for **bugs, intent mismatches, and bad designs**.

**Out of scope** (other reviewers cover these — do not address them here):

- Style, formatting, naming conventions, import order
- Lint findings (line length, unused imports, broad `except`, missing type hints, etc.)
- Type-check findings
- Security categories (SQLi, XSS, secrets/credentials, auth, ReDoS, prompt injection, deserialization, etc.)
- Generic best practices and language idioms
- Code duplication / DRY violations
- Dead code, unreachable branches, unused parameters
- Low-information or redundant comments
- Performance issues visible from the diff (N+1, blocking I/O in hot paths, etc.)
- Reuse opportunities (existing utilities elsewhere in the codebase)
- Premature abstraction visible from the diff alone (no session evidence of single-use case)
- Plan/design-doc refinement (the doc itself, not whether the code drifted from it)

See also the workflow position at the bottom of this file.

## Phase 1: Locate Transcripts

Run the shared transcript locator from the root of the checkout the session started in (it matches transcripts by that directory's name), or pass `--workspace <that checkout>`:

```bash
TRANSCRIPT_PATHS=$(find-transcripts.py)
```

The locator (`tools/transcripts/find-transcripts.py` in https://github.com/alexandrosandre/agentic-engineering) is the canonical one; the other skills that read sessions use it too. It finds the session files of each coding agent the team uses, drops trivial sessions, and caps the result (10 most recent sessions, 1 MB cumulative). Output is one absolute path per line, oldest-first.

### No transcripts available

If `TRANSCRIPT_PATHS` is empty, stop and tell the user:

> `/contextual-review` needs session transcripts to perform intent-vs-implementation review. Without them, this skill is mostly redundant with the PR bots. Skip and proceed.

Without transcripts, present the message and stop; the PR bots can still review the diff if the user proceeds separately.

## Phase 2: Determine Diff Scope

1. If the user provided an explicit scope (paths, patterns, or a natural-language area after `/contextual-review`), use that scope.
2. Otherwise, refresh `origin/master`, then collect changed files from both sources and deduplicate:
   - Base ref: `git fetch --quiet origin master`
   - Uncommitted (staged + unstaged): `git diff --name-only HEAD`
   - Committed on branch: `git diff --name-only origin/master...HEAD` (triple-dot matches GitHub PR diff semantics from the merge-base).
3. Skip lockfiles, build output and vendored code, and experiment folders.
4. If the scope resolves to zero files, report and stop.

Store as `REVIEW_SCOPE` (file list + combined diff text where it fits in the subagent prompt; otherwise the file list plus per-file hunks).

## Phase 3: Dispatch Reviewer Subagent

One general-purpose subagent. Pass in the prompt:

- `TRANSCRIPT_PATHS` (the full list, oldest-first)
- `REVIEW_SCOPE` (file list + diff)
- Reading instructions: read transcripts in chronological order; treat `role=user` as the source of truth and use nearby `role=assistant` only for context; ignore system reminders, attached skill bodies, tool chatter, and prompt scaffolding unless the user explicitly endorsed them; when a decision evolves across sessions, the latest stance wins.

Reviewer prompt (copy verbatim into the subagent task; this is the contract):

> **You are reviewing changed code against the literal session intent.** Read full files (not just diff hunks) to understand call sites and side effects. Build a mental model of what the code *should* do (per transcripts) vs what it *does* (per code).
>
> **First, recall the agent rules that apply hierarchically to every directory touched by the diff** — most of what would constitute a finding is encoded there. Walk from the workspace root down to each affected file, picking up every applicable rule along the way (workspace-wide, then service-local, then file-type-specific). The applicable rules cover culture, coding values (fail-fast, no premature abstraction, regression-test discipline, verification, etc.), language style, and per-area patterns; they are the source of truth for everything below.
>
> **Apply tone/output conventions from those rules to your own findings.** Plus one skill-specific rule: **cite transcript evidence verbatim** when a finding turns on session context.
>
> **Scope of what to flag:** rules from the agent rules above whose enforcement requires call-site, contract, or session context to decide correctly. Examples: a `.get(key, default)` on a value the call-site evidence shows is guaranteed by the caller contract (fail-fast violation); a new helper introduced for a single discussed use case (premature abstraction); a bug fix without a regression test for the exact scenario the user described; new SQL not run against a real DB in this session.
>
> **Plus three checks not in the rules** — these are intent/design-level findings only this skill can make:
>
> 1. **Intent fidelity** — does the code do what the user literally asked, in their own words? Did we ship a rejected alternative? Did we drop a constraint added mid-session?
> 2. **Test-coverage of discussed edges** — were edge cases mentioned in the transcripts actually tested?
> 3. **Design-doc drift** — if the repository's design docs have one for this area, does the code contradict it?
>
> **Do NOT flag any of the following topics** — other reviewers (static checkers, post-PR bots, `/simplify`, `/design-review`) cover them:
>
> - Style, formatting, naming conventions, import order
> - Lint findings (line length, unused imports, broad `except`, missing type hints, etc.)
> - Type-check findings
> - Security categories: SQL/NoSQL/command injection, XSS, CSRF, SSRF, secrets/credentials in code, auth/authz gaps, ReDoS, prompt injection, unsafe deserialization, weak crypto, path traversal
> - Generic best practices and language idioms (e.g. "use list comprehension", "prefer `const`", "use async/await")
> - Code duplication / DRY violations
> - Dead code, unreachable branches, unused parameters
> - Low-information or redundant comments
> - Performance issues visible from the diff alone (N+1 queries, blocking I/O in hot paths, etc.)
> - Reuse opportunities (existing utilities elsewhere in the codebase)
> - Premature abstraction visible from the diff alone (only flag if the session shows a single discussed use case)
> - Plan/design-doc refinement of the doc itself (drift between code and an existing doc IS in scope; refining the doc is not)
>
> **Severity:**
>
> - **Blocker** — must fix before PR (bug, broken intent, broken invariant, fail-fast violation on critical path)
> - **Important** — should fix before PR (real-consequence design issue, missing regression test, unvalidated SQL, missing monitoring on a new serverless function)
> - **Nit** — optional (small intent drift, minor design preference)
>
> Return findings as a structured list: `severity`, `category` (`bug` / `intent` / `design`), `file:line`, `what`, `why_it_matters` (cite transcript evidence verbatim where the finding turns on session context; cite the rule file/line where the finding turns on a codified rule), `suggested_direction`. Do **NOT** edit files.

## Phase 4: Present and Gate

Inside a `/ship-it` run, `/ship-it` triages the findings against its own bar (its step 5) and this gate does not apply; it applies when this skill is invoked on its own.

The parent agent receives the structured findings, groups them by severity, and presents them to the user. For each Blocker/Important finding citing transcript context, include the verbatim user quote so the user can verify the call. For findings citing a codified rule, include the rule file/line.

End with an explicit confirmation gate.

```
How would you like to proceed?
1. Fix all
2. Fix Blockers + Important only
3. Fix specific items (specify numbers)
4. No changes — review complete
```

Do not modify any code until the user confirms. After applying any fix that touches code, run targeted verification appropriate to the changed area; use `/test` when the user requests the full project gate or when the risk warrants it.

## Workflow Position

The standard user-visible workflow remains `code → /lgtm → merge` (or `/ship-it` for a reviewed, merge-ready PR without the merge). Run on its own, `/contextual-review` sits outside that automatic flow (`/ship-it` runs it as its last step): it is an explicit, session-aware review pass that users can invoke whenever they want changed code checked against the literal transcript intent. Prefer it before `/autoreview` for risky or intent-heavy changes; use it after `/autoreview` only as an extra confidence pass when autoreview's fixes may have changed the intended scope.

The contextual and fresh-eyes review styles are complementary by design:

> **`/contextual-review` (this skill, explicitly invoked)**: contextual review with full session transcripts. Catches bugs, intent mismatches, and design issues. Invoked on its own, findings are presented for user triage and nothing is auto-fixed; inside `/ship-it`, `/ship-it` triages them.
>
> **`/simplify`** (the agent runs it before each commit, and on request): fresh-eyes review of the diff alone, without session context. Fixes code nobody needs yet, logic the repository already has, constructs a cold reader trips on, and work done twice. Behavior-preserving rewrites only — never functional changes.
>
> The contextual pass owns "did we ship what we meant"; the fresh-eyes pass owns "is the code as written tidy". Running both maximizes coverage without overlap.

## Closing

- End your response with a blockquote line: **Skills used:** then each skill name in backticks (this skill: `contextual-review`; include other skills if used).
- If this skill's instructions failed or needed a workaround, update this file.
