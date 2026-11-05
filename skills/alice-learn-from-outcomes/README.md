# Alice's dream

Alice's weekly learning pass. It reads what became of every PR she opened (merged ones too, for the steering and pushback in their reviews; closed and reverted ones for her mistakes), her raw session transcripts for where she was blocked, stalled or repeated an error, and her memory, then lands the rules, checks and memory edits that would have prevented what went wrong, as one PR.

## Why it exists

A green session only means it did not crash. What she is worth shows in what the team did with her work, and merge rate alone misleads: a large share of rejected agent PRs fail for reasons outside the agent. The opinions:

- **Merged PRs teach too.** A reviewer's correction, a withheld merge, a person finishing her work in follow-up commits is negative feedback that merged.
- **Read sessions whole.** A reader judging a session from part of it misjudges it; only bulky tool output is shortened.
- **Prefer a check to a rule.** Prose only advises; a script, test or hook makes the mistake fail. A rule is for the judgment calls no check can decide, at the narrowest scope.
- **Generalize before proposing.** One incident proves something happened once; a correction that landed at once is not a missing rule; a rule already on file that was broken always gets a fix.
- **Test each option**, and retire rules as checks take them over, one commit each.
- **The user reviews outcomes, not questions.** The pass decides every case, lands each edit as its own commit, and the user drops or swaps commits.

## How it fits

Runs weekly as the `routines/alice-learn-from-outcomes` routine. Reads `scripts/alice/ledger.py`, `transcripts.py` and `memory.py`; edits the `alice*` skills, the pipeline skills she runs, and her scripts. It applies to Alice the team's own memory-and-rules consolidation pass ("dream", in https://github.com/alexandrosandre/agentic-engineering); the steps it borrows are written out in the skill so this repository stands alone.

## To run it

The transcript upload hook installed in her cloud environment (`scripts/alice/transcripts.py hook`), the shared drive stub wired, and a scheduled routine with the same read-only identity Alice has.

The instructions are in [SKILL.md](SKILL.md).
