---
name: alice-assess-risk
description: >-
  Independent risk review of a branch's change: a fresh-context reviewer answers six questions
  about what users could experience, and a script turns the answers into the risk level
  (1 Low to 4 High), which sets what the PR must prove, and the PR's Risk section. Use in Alice's
  sessions at the risk-review steps of /ship-it's `references/alice-steps.md`: after the first
  working implementation, and again after the last re-verification. Not for code review
  (/code-review, /autoreview) or for running the validation (alice-verify-change).
license: CC-BY-4.0
metadata:
  author: Alexandros Andre Chaaraoui
  source: https://github.com/alexandrosandre/alice-issue-agent
---

# Assess risk

The level sets how much validation the change gets; it never stops the work, since a person always merges (design D5, `docs/design.md`, "Risk"). The reviewer answers questions about users and never sees what its answers cost: telling an LLM reviewer the policy shifts its judgments with the evidence unchanged. `scripts/alice/risk_level.py` holds the questions, the level each answer reaches, and the JSON contracts (its docstring); this file does not restate them.

## State

Everything lives in `RISK_DIR`, outside the worktree so nothing commits it, and per branch so a checkout that switches branches never hands one PR another's files. alice-verify-change, /ship-it and /create-pr resolve it the same way, with this command:

```bash
branch="$(git branch --show-current)"
[ -n "$branch" ] || { echo "Detached HEAD: check out the PR's branch first." >&2; exit 1; }
RISK_DIR="$(git rev-parse --absolute-git-dir)/risk-review/$branch"
# A session isolated to its worktree cannot write the shared git directory (/create-pr).
mkdir -p "$RISK_DIR" 2>/dev/null || RISK_DIR="<your scratchpad directory>/risk-review/$branch"
```

It holds:
- `assessment-1.json`, `assessment-2.json`: the reviewer's answers, per pass;
- `level.json`: the latest pass's level;
- `evidence.json` and `runs/`: written by alice-verify-change;
- `risk-section.md`: the PR's Risk section.

The first pass starts from an empty folder (`rm -rf "$RISK_DIR" && mkdir -p "$RISK_DIR"`), so a branch that already ran /ship-it once never mixes in the earlier run's evidence.

## The two passes

1. **After the first working implementation.** The answers set the level alice-verify-change validates at.
2. **After the re-verification that follows the pipeline's last behavior-changing fix.** The reviewer also gets the evidence, compares it with what the level required, and writes the residual risk and what to check before merging and after release. If this pass's level is higher than pass 1's, run alice-verify-change at the new level before hand-over, then render again.

## Run the reviewer

Write its inputs to `$RISK_DIR/input-<pass>/`:
- `diff.patch`: the branch against its merge base with `origin/master` (fetch first), uncommitted and untracked files included;
- `issue.md`: the linked issue's title, body and every comment, when there is one, from `python3 scripts/alice/issue_text.py <n>`, which drops the HTML comments and invisible characters GitHub hides from people, so instructions hidden there never reach the reviewer;
- `pr.md`: the PR description without the line that opens with `**Risk ` (the risk level), the line with the "ask live" link (it opens Alice's session, the reasoning this review must not see), its `## Risk` and its `## Decisions to check` sections, when a PR exists;
- pass 2 only: `evidence.json` and `runs/`.

Launch one subagent with fresh context and no edit tools (a read-only planning subagent where your coding agent offers one). Its prompt is `references/reviewer-prompt.md` verbatim, with `{{QUESTIONS}}` replaced by the output of `python3 scripts/alice/risk_level.py questions`, `{{INPUTS}}` by the input paths, and `{{PASS}}` by 1 or 2. Give it nothing else: no transcript, no decision ledger, no self-assessment, no level table. Assessing with less of the author's framing discriminated better, and a classifier did worse when it saw the agent's prose (design references).

Save the JSON it returns as `$RISK_DIR/assessment-<pass>.json`, then:

```bash
python3 scripts/alice/risk_level.py level "$RISK_DIR/assessment-<pass>.json" > "$RISK_DIR/level.json"
```

When the script answers `Invalid assessment: ...`, send that line back to the same reviewer and save its corrected JSON; never edit its answers yourself. `Invalid evidence: ...` is about `evidence.json`, which the session writes: fix it there (alice-verify-change, Evidence).

## Output

Render the Risk section from the latest assessment, with the evidence once it exists; alice-verify-change renders again each time it rewrites the evidence:

```bash
if [ -f "$RISK_DIR/evidence.json" ]; then
  python3 scripts/alice/risk_level.py render "$RISK_DIR/assessment-<latest>.json" \
    --evidence "$RISK_DIR/evidence.json" > "$RISK_DIR/risk-section.md"
else
  python3 scripts/alice/risk_level.py render "$RISK_DIR/assessment-<latest>.json" \
    > "$RISK_DIR/risk-section.md"
fi
```

What callers use:
- `level.json` (`{"level", "title"}`): `/create-pr` opens the description with `title` ("Risk 4 of 4 (High)") and, on the same line, one sentence naming the intent the reviewer should judge, such as the decision the change rests on. The level tells the reviewer how closely to look; the review bots read the code either way.
- `risk-section.md`: `/create-pr` pastes it verbatim as the description's `## Risk` section, replacing any earlier one.
- To the caller, one line: pass, level, and the questions that set it (the level line of `risk-section.md`; none at 1 Low, where every question sits at its lowest option).

## Closing

- End your response with a blockquote line: **Skills used:** then each skill name in backticks (this skill: `alice-assess-risk`; include other skills if used).
- If this skill's instructions failed or needed a workaround, update this file.
