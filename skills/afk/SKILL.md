---
name: afk
description: >-
  Continue the session fully autonomously because the user is leaving for an extended period.
  Use when the user invokes /afk, or explicitly says to keep working unattended while they are
  away, and when an unattended agent's skill (alice) runs it. Not for ordinary turns where the
  user is still around to answer questions.
license: CC-BY-4.0
metadata:
  author: Alexandros Andre Chaaraoui
  source: https://github.com/alexandrosandre/alice-issue-agent
---

# afk

The user is away and cannot answer questions until they return. Work like a principal engineer left in charge: keep the task moving, ground choices in evidence, and don't get stuck on nits or analysis-paralysis. Stopping to ask is almost always wrong — stop early only on hard blockers: destructive or irreversible actions, rules that require explicit permission, or access only the user can grant.

Standing rails, whatever stage the session is in:

- All AGENTS.md rules stay in force — autonomy widens which decisions you take, not what you are allowed to touch.
- Merge authority stays with the user: never merge, and never invoke the merging skills (/lgtm, /yolo).
- Involving other people stays with the user: never @mention, CC, FYI, assign, or request review from anyone, anywhere (PR bodies, comments, issues, automation prompts), and never suggest whom to involve — a mention notifies a real person, in the user's name, about work the user has not approved yet. Leave addressee slots blank; the user routes attention when they return. (An unattended agent's own skill may carve out where it hands over, as `alice` does.)
- Don't hand work back: no task chips for the user to click later — that is the work this run exists to do. Do it, or ledger why not.

## Carry the work forward

Pick up the session wherever it is and take each stage into the next:

- **Designing** — review the design doc, then plan the implementation, then implement.
- **Planning** — review your plan critically, then implement it.
- **Coding** — finish the implementation, then take it through the delivery pipeline via a non-merging shortcut (/ship-it, or /ship-it-lite for low-risk changes). Invoke the shortcut rather than hand-rolling its steps: /create-pr on its own skips the review pass, the half the user cannot start while away. Work landing later needs it run again.

A pipeline step that pauses for user confirmation or finding triage (e.g. /contextual-review) must not stall the session: disposition what is clear and consequential yourself, and carry the rest into the final report.

## Ledger

Keep a ledger from the start of the run, outside the worktree — the session scratchpad is fine — where the pipeline cannot sweep it into a commit. Head it with the run's remaining steps and keep them current: after a compaction, that file is what says where the run had got to.

At any fork where you would normally ask the user which path to take:

1. Record the decision point in the ledger.
2. Analyze each option's pros and cons. Where an experiment can settle it, run one — local benchmarks or prototypes only, never with production data or side effects.
3. Take the winner and keep moving. When evidence is thin, prefer the reversible option.

Ledgered decisions are provisional calls made in the user's absence; the final report is where the user ratifies them. Never record one in a design doc as if the user had made it — flag it in the report instead: a design doc must never be where the user first learns a decision was made.

## When you may stop

When every item you know of is done, ledgered, or genuinely blocked on the user. A "what remains" list in your report is usually work this run should have taken — re-read it and pick the next item first. A prompt arriving mid-run is added scope, not a handoff back.

## Final report

When you stop — done or blocked — report:

- How far you got and what remains, including the PR if one was opened.
- The ledger: one short paragraph per decision, written to be ratified cold — what the product or the user now gets versus before, the options considered, and the evidence behind the winner, in the product's vocabulary, never a label list or harness shorthand (criteria, goldens, findings).
- Anything still blocked on the user, as questions answerable from the report alone — never from the run's transcript.

## Closing

- End your response with a blockquote line: **Skills used:** then each skill name in backticks (this skill: `afk`; include other skills if used).
- If this skill's instructions failed or needed a workaround, update this file.
