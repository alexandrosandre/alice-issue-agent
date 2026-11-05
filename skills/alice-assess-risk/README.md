# Assess risk

An independent risk review of a branch's change. A fresh-context subagent, which never sees the author's reasoning, answers six questions about what users could experience (what they see, production data, undo, reach, noise, sensitive ground). A script, not the reviewer, turns the answers into a risk level from 1 Low to 4 High, and renders the PR's Risk section.

## Why it exists

A reviewer who did not watch the work needs to know how closely to look, and the agent needs to know how much to prove. The opinions:

- **Judge risk by what users could experience**, not by lines changed or files touched. A comment needs nothing; a changed button needs a look and a screenshot; a change to the data customers see needs a reproduction, a red-to-green test and end-to-end runs.
- **The reviewer never sees what its answers cost.** Telling an LLM reviewer the policy shifts its judgments with the evidence unchanged, so the level table lives in `scripts/alice/risk_level.py` and stays out of its prompt.
- **Less of the author's framing judges better.** The reviewer gets the diff, the repository, the issue and the PR text as claims, never the transcript, the decision ledger or a self-assessment.
- **Unsettled answers count as the riskier option**, and the reviewer never estimates a probability of failure.
- **The level never stops the work.** A person always merges, so a higher level means more validation, not a gate.

## How it fits

`/ship-it`'s Alice steps run it twice: after the first working implementation (the answers set the level `alice-verify-change` validates at) and after the last re-verification (it compares the evidence with what the level required, and writes the residual risk and what to check before merging and after release). `/create-pr` pastes its Risk section into the PR.

## To run it

A coding agent that can start a subagent with fresh context and no edit tools, and Python 3 for `scripts/alice/risk_level.py`. The questions' wording is in that script: adapt the sensitive areas and the reach options to your product.

The instructions are in [SKILL.md](SKILL.md).
