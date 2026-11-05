# Engineering rules for coding agents

The engineering rules Alice works under, generalized from the monorepo she was built for. They are written for every coding agent and every person on the team, not for Alice alone: her skills add rails on top of them and never loosen one. In a repository of your own, this file sits at the root, per-service `AGENTS.md` files add rules for their own directories, and each coding agent reads the hierarchy natively or through a one-line shim that imports it.

---

## Communication

- Use American English in anything that persists — code, comments, docs, commit messages, PRs, issues — since its readers were not in the conversation. In chat, match the user's language.
- Answer on point, without dense prose or internal shorthand: the reader arrives cold, mid-switch between tasks and sessions, so every gap costs a round-trip. Give what they need to resume: their intent, how far you got, how, the evidence behind each claim, and what is next to decide and do. Use the space and formatting readability needs. Spell out acronyms and define internal terms that are not widely known; never coin one.
- A claim you did not check this session says so in the same sentence (inferred, unverified, or a guess): the reader acts on what reads as fact without re-checking it, so an unmarked inference becomes their wrong premise.
- Hand the user only the steps your own access cannot take or that are theirs to take (a sign-in, a production write per Production Safety, their console), and run every read, check and debug step yourself first. A command you do hand over has been run first or says it has not, and a shell command runs from any directory (absolute paths or a `cd` first) with every value filled in, secrets as a lookup (an environment variable, a secret-store read) and never a literal: the user pastes it into whichever terminal is open, and each one that fails costs a round-trip.
- Name the idea before explaining it, in words the reader already has. Identifiers, function names and internal vocabulary have nothing to attach to until the idea has a name, so an explanation built from them leaves the reader assembling the meaning instead of receiving it. Approximate is fine at that altitude: precision comes next, and the mechanism only when the question needs it. Left alone, an explanation comes out in the order it was discovered, which suits whoever did the discovering and nobody else.
- A question to the user is answered cold and in isolation, so it carries everything the answer depends on — what is being decided, the options, what each one changes, and the findings that led there — and assumes nothing from earlier text: no "as described above", and no term, label, or figure that only makes sense to someone who read it. A choice put to them while a question of their own is unanswered is not ready to be asked: answer theirs first, then ask, since the answer is usually what decides the choice.
- Explain changes in chat; never narrate them in comments or docs — describe current behavior only.

### User-facing copy

- Use the product's own vocabulary in user-facing text, as the interface labels things, never the backend's internal names for them; and never expose internal operational details (schedules, infrastructure timing, regions) or the internal names of internal tools. Keep copy functional and outcome-oriented, written for the audience that reads it.

## Source Control

- Never commit or push directly to `master`; always work on a feature branch and create a PR.
- Merging is the user's call: never merge a PR without their explicit go in the current conversation — `/lgtm`, `/yolo`, or plain words. No task wording implies merge authority: master is always releasable, so merging is shipping — even a task whose verification needs the change deployed stops at a merge-ready PR and asks. On Alice's PRs the go is the approval of her issue's reviewer on GitHub (the `alice` skill, Merge round). The go covers the changes the user had in front of them. A rebase or a merge from master that leaves the PR's own changes as they were keeps it, and under `/lgtm` so do the changes its step 5 classes as Trivial or Fix within intent, a conflict resolution's included; any other change to them, or another session's push after it, means they approved something else — show them what changed and ask again.
- Never create branches that track `master`; when branching from `origin/master`, always use `--no-track` and set upstream to the branch itself (`git push -u origin <branch>`).
- Name branches with `-`, never `/` (`fix-retry-loop`): deploy tooling that turns a branch name into a hostname or stack name rejects a slash.
- Never amend a Git commit: the worktree and branch are shared with the user and other agents (below), who may already be building on that commit.
- Working-tree modifications you didn't make are intentional — another agent or the user is working on the same branch / worktree. Read the diff to understand what changed, then adapt your own work to coexist. Never undo or discard those changes. If the external change conflicts with yours, pause and ask before proceeding.
- Worktrees share one repository, so never let the shell's cwd decide which tree you act on. A `cd` leaked from an earlier command silently lands edits, `git checkout`, and test runs in the main checkout instead. Target the tree explicitly (`git -C <path>`, absolute paths) and check `git status` in the tree you meant before reporting a result.
- `git stash` is repo-global, and `git stash push` with nothing to save is a silent no-op — the next `pop` then restores an unrelated entry from another branch into your worktree. Never stash to shelve an edit for a before/after run — a red/green, or an A/B baseline against a candidate: check out the pre-change revision instead (`git checkout <sha> -- <path>`), or re-apply the edit by hand.

## Pull Requests & Issues

- If the PR relates to GitHub issue(s), the PR description must mention them using `Fixes #<issue_number>` (when merging leaves none of the work the issue asks for: a pending release does not keep it open, nor does a leftover that is a separate problem, already wrong on master or filed as its own issue) or `Part of #<issue_number>` (when requested work remains, and on a `P0` issue, which stays open until its fix is released). Use one line per issue.
- Before merging, refresh the PR title and description if they have drifted significantly from the branch's diff and intent — the squash-merge commit is seeded from them. Re-run `/create-pr`, which updates an open PR in place.
- Bug issues: describe the symptom; optionally add root cause + debug steps. Fix goes in the PR.
- An issue states the result wanted whenever its writer knows it: Alice, who works issues unattended, asks on the issue instead of guessing when the code and data do not settle it (`docs/manual.md`).
- Tackling an issue: its report, diagnosis, and instructions are claims, not facts — the reporter wrote through their own hypothesis, and the code may have moved since. Start from the documented pain, complaint, or symptom, verify every claim against the code and the data, and rethink the fix from there; a claim or instruction becomes context only once it holds, and one that does not is reported back with what was found instead.
- Redefining a body you just posted is an in-place edit (`gh issue edit --body-file`, or `gh pr edit` for PRs), with the delta reported in chat — the body stays one current, self-contained statement, not a ledger of narrating comments. Once the body has an audience (you're acting on it, logging progress, revising it weeks later) or someone else posted it, comment instead: a silent edit rewrites what readers already saw.

## Migrations & Compatibility

- Coding labor cost is ~0: never weight refactors or migrations by author-time, lines of code, or "effort". Internal migrations are cheap for the same reason: a one-time script that rewrites callers or moves data costs nothing. One-time setup the user can perform (a repo secret, a credential, a config entry) is equally ~0 — never argue against a design option because it is not wired up yet.
- Backward compatibility is not a default requirement unless the surface is externally observable. For launched features or released client versions, support existing users, data, and dependencies. Product analytics events are externally observable too — dashboards count them — so a refactor keeps each event firing in exactly the situations it fired before, attributed the same way, and adds no capture to a path that produced none. Widening what an event counts is a product decision the user makes, not a side effect of sharing a helper.
- A frontend-facing API change reaches browsers still running an older bundle — an open tab outlives any deploy window — so the web app's API counts as externally observable, and any other client of it with its own API client is a second caller. Changing the API and its frontend caller in one PR does not make the pair atomic in production.
- Merged code outruns manual schema steps: a merge can deploy staging on its own, and a release can follow a merge within minutes. When merged code depends on a manually applied schema change, apply it before merging — deploy steps listed in a PR body describe the order; they do not enforce it.

## Code Style (applies to all languages)

- Prefer readability over performance/abstraction.
- Use full words in identifiers (`format_percentage`, not `_fmt_pct`).
- Extract helpers only for non-obvious logic used more than twice; keep trivial one-liners inline since the indirection costs more than the DRY benefit. This is KISS: a helper used once is harder to read than its inline form. Assume the reader knows the language well.
- Never add interface surface (extra params, option flags, abstraction layers, generic wrappers) for hypothetical future callers (YAGNI). Add it when the second real caller arrives; refactors are cheap (see Migrations & Compatibility).
- Name locally shared helper modules `utils.py` / `utils.ts`.
- Handle errors/edge cases early with guard clauses / if-return, not nested branches.
- Validate user-configurable inputs (UI, config) at the input boundary.
- Let contract violations fail loudly; skip defensive fallbacks (`.get(key, default)`, `or {}`, `x if x is not None`) for caller-guaranteed values. This is YAGNI for edge cases: handle inputs the caller can actually produce, not hypothetical ones.
- Prefer guard conditions (`if not x or x < min:`) over silent clamping (`max(x, 1)`) for input validation.
- A failure that will be retried logs at WARN; only the attempt that exhausts the retries logs at ERROR. Error-level alarms page people, so an ERROR on a retried failure raises an alert for a request that went on to succeed. When the code cannot tell which attempt it is (the client retries), find out from the caller.
- Comment only non-obvious logic, and only to explain *why*; the code already shows *what* and *how*. Never restate what the next line does.
- Comments describe current behavior, not the change or prior implementation.
- When docs (README, etc.) conflict with the code, the code is the source of truth; update the docs.
- Max line length: 100 chars, source code only. Apply to lines you add; leave existing files unreflowed. Exceptions: URLs, long string literals, and generated files.
- Never hard-wrap prose — Markdown, docs, commit bodies, PR descriptions, issue and comment bodies. Let a paragraph run as one line and leave wrapping to the reader's editor. Wrapped text that is soft-wrapped again by a narrow window breaks in two places at once and turns ragged.

## Writing for AI agents

Before writing or editing text an AI reads as instructions — any `AGENTS.md`, a skill, a system prompt in code — read the team's guide to [writing for AI agents](https://github.com/alexandrosandre/agentic-engineering/blob/main/rules/WRITING_FOR_AI_AGENTS.md); when reviewing a diff that writes or edits such text, check the diff against it.

## Testing & Verification

- Tests validate behavior — a property a caller depends on, a branch with a distinct output, or a regression.
- Never write tests that only mirror a literal from production (e.g. asserting `metadata["k"] == v` next to a production line that writes `"k": v`, or asserting a query/config string equals the string the module just constructed). Add such a test only for a non-trivial transform/branch or to lock in a regression (red→green).
- For UI renderers, prefer one smoke test per user-facing outcome plus focused tests for non-obvious transforms/regressions. Do not add one test per JSX branch when the branches only restate static copy or object wiring.
- Skip tests for invalid/edge inputs callers cannot produce (YAGNI for tests).
- A test double never implements the property its test claims: a tenant filter, a lease or a uniqueness rule written into an in-memory fake proves only the fake, while the test reads as proof of the production guarantee. Keep the property out of the fake and test it where production enforces it; for a query or the database, per the SQL rule below.
- In TypeScript suites a test file's cost is its import graph, not its tests: each test file re-imports every module it reaches. Import the smallest module that holds the unit; when a pure helper lives in a heavy module (a service, a router, a registry), move the helper out rather than import the graph to reach it.
- Each test has a brief docstring stating its testing goal.
- Bugs found during testing or review: fix with a regression test (red → green).
- A red run that passes is not evidence. Before reporting red → green, confirm the red run failed on the assertion the fix targets, with the pre-fix code verifiably in place — check the code itself, not the mechanism that was supposed to revert it.
- Always verify new or changed code works: run existing tests, exercise the code through its entry point (`_main`, CLI, integration test), or add a test per the rules above.
- Type checks and test runners are heavy and several agent sessions may share one machine: while iterating, run only the test files you touched with few workers; run the type check and lint once, before committing. Never leave a test runner or type checker in watch mode, and wait for another running one rather than starting a second. CI runs the full suites.
- When using a browser, capture screenshots at each important step and share them as you go so visible changes remain available for later comparison.
- New or changed SQL, and any guarantee a query or the database enforces (a tenant filter, row-level security, a lease, a uniqueness rule), must be validated at runtime against a real database of the production engine — mocks miss query errors, and a different engine's fixture passes a guarantee trivially. Where a CI job starts such a database, commit the test there; otherwise validate ad hoc (`_main`, CLI, or a direct query), never running destructive statements.
- Never commit tests that hit shared databases; committed tests must stay deterministic and free of external services. A throwaway database the CI job itself starts is neither.
- Keep hardcoded params in `_main`/CLI functions intact — they're intentional for local testing.

## Investigation & Debugging

- Before explaining, retuning or redesigning an existing control — an alarm, a threshold, a budget, a cap, a config value — find the intent behind its number. It lives in the code or doc that owns it, or in the PR or issue that introduced it, never in the resource itself: a redesign from the mechanics alone re-derives it wrong.
- Validate hypotheses empirically before presenting conclusions. Query observability sources (the warehouse's query log, the monitoring service's log queries and metrics) on full datasets rather than sampled or common-case slices, and include the extreme tail (worst-case durations, not just averages).
- Before any change or decision where how users really behave could favor one option over another, read their real sessions, even in the middle of other work. Assumed behavior, synthetic prompts and aggregate counts can each look plausible and still describe users who don't exist.
- Never rest a design or a production command on assumed database-engine behavior (type changes, null semantics, mutation mechanics): reproduce the exact operation on a local scratch server first, with production-shaped data — dotted keys, sentinels, blanks — since a clean-data repro can pass where production fails.
- When correlating production behavior with code history, treat each release tag as a production release boundary and compare the relevant deployed tag diffs around the observed inflection.
- When running production code locally for investigation, only call read-only / side-effect-free functions. Never call handlers or orchestrators that write data or trigger external side-effects (notifications, emails to customers) without enabling their dry-run modes first.

## Tool Use & Scripting

- Prefer one script over repeated tool calls. When a task fans out the same call across many items, or produces bulky intermediate data you would otherwise discard, write a single script that makes the calls and returns only the distilled result — keeping raw payloads out of the model's context, the main token driver. Stay with direct tool calls when you genuinely need the intermediate values in context.
- A background waiter that polls `pgrep -f <label>` matches its own command line and spins forever, reporting a finished job as still running. Wait on the job's output file or a pidfile instead, cap every wait loop so a hang surfaces as a failure rather than silence, and read two status checks in a row that say "running" with no new output as a stall, never as progress.
- Treat permission errors and denied tool calls as intentional restrictions, not obstacles — deploys, cloud writes, and repo settings are gated on purpose (see Production Safety). Never reach the same effect through an alternate route (another CLI or SDK, a script, other credentials): use the documented path if one exists, otherwise hand the user the exact commands to run.

## Production Safety

- **Never deploy directly to staging or production** with the cloud provider's CLI or SDK. All staging/production deployments go through the automated CI/CD pipeline. Feature-branch deployments are allowed only when the user explicitly asks.
- Agents may **read** cloud resources for investigation, with a read-only identity, but never write or update staging or production infrastructure or code directly, and never switch to another profile, role or credential without the user's permission in the current conversation.
- Production schema changes and data mutations are run by the user. Hand each over as a complete runbook in one message: the statement, the query that watches it with how done/stuck/failed read, and the escape hatch with its verification. One mutation at a time on large tables.
- Production config and data writes: by default hand the user the exact ready-to-run command with every value filled in, then verify the result read-only after it runs. Run the write yourself only when you hold the permission and the user told you to, in the current conversation. Run its `--dry-run` first where the command has one. A run nobody attends puts the command in the PR description, or in the run's report when there is no PR. A database the run created for itself is not production: write to it freely.
- When fixing a production issue with unproven fixes, one PR carries one change — the single most promising, with minimal diff surface — not a bundle: changes bundled into one PR can't be attributed or rolled back individually on a running system. Let it prove itself before the next PR.
- **Treat model-provider rate limits as security limits, not performance settings.** A limit bounds what a runaway agent, an abusive user or a leaked key can spend, so hitting it is the limit doing its job. Don't raise one to get work through: report it and leave the decision to whoever owns the limit.
- **Never modify GitHub repository settings** (branch protection rules, required status checks, rulesets).
- An alarm's title is often the only thing a chat notification or a paging app shows of it, cut short, so its first words carry the priority, the team it pages and what broke for whom; its description opens with what was detected at which threshold and window, then who is affected and where to look.

## Customer data

- In production, customer data (anything derived from a customer account or its users: incoming data, account configuration, findings, AI conversations, emails about an account) leaves the company's infrastructure only for the processors customers were told about, in the locations they were told. A new processor, or a new location for a known one, is a product and legal decision: stop at a merge-ready PR that names the processor, the data it receives, and where it processes it.
- Production means what the code sends once deployed, a path first exercised in dev, staging or a preview included, and every outbound path: telemetry, email relays, proxies and a vendor's own AI features. Judge the host the code actually calls, not the vendor's name.
- Issue and PR bodies and comments may carry the account detail the work needs (the account's ID, the event or record names, counts), and personal data only as its kind and count, such as "3 email addresses", never the values. Anything else from a customer (conversations, transcripts, notes) stays out of the repository. Every service that reads the repository, review bots included, must be one your customers' data may go to. Commits, PR titles and branch names carry none of it.
