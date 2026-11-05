# Alice learn-from-outcomes routine

A weekly scheduled run that is "dream" for Alice: it reads what became of every PR she opened (merged ones for the steering and pushback in their reviews, closed and reverted ones for her mistakes), her raw session transcripts for where she was blocked, stalled or repeated an error, and her memory, and lands the rules, checks and memory edits that would have prevented what went wrong as one PR. Procedure: [`skills/alice-learn-from-outcomes/`](../../skills/alice-learn-from-outcomes/SKILL.md); data: [`scripts/alice/ledger.py`](../../scripts/alice/ledger.py), [`transcripts.py`](../../scripts/alice/transcripts.py), [`memory.py`](../../scripts/alice/memory.py); design: [`docs/design.md`](../../docs/design.md) D12.

## Why it exists

An unattended agent that does not learn repeats its mistakes at the rate it works. People correct Alice in reviews, finish her work in follow-up commits, close her PRs, and revert her merges; each of those is a signal, and none of them reaches her next session unless something reads them and changes her instructions or her tools. Running weekly keeps each pass small enough to review in one sitting, and the week window means consecutive runs neither overlap nor leave a gap.

| | |
| --- | --- |
| Platform | A scheduled cloud-agent routine in Alice's cloud environment, owned by the person who reviews its PRs |
| Schedule | Weekly, Monday |
| Model | The strongest available model, high effort |
| Connectors | None (D26) |
| Generates | One PR (`[agents] Alice learns from outcomes — <date>`) when there is something to land, and a summary in the run's session every run |
| Source | [PROMPT.md](PROMPT.md) (task prompt, verbatim) |

## Why it runs in Alice's cloud environment

Her transcripts sit in the shared drive folder whose write credential only her environment reads; her memory is a branch, and her PRs and issues are on GitHub's REST API, which a cloud session reaches. A cloud routine also runs while every laptop sleeps.

## Installing it

Create it from the owner's account, which can use Alice's cloud environment, with no connectors: name `alice-learn-from-outcomes`, a weekly schedule, your repository, [PROMPT.md](PROMPT.md)'s block as the prompt. Its PRs and summaries are the owner's.
