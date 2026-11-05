# Routine prompt: Alice learn-from-outcomes

The routine `alice-learn-from-outcomes` in Alice's cloud environment runs the block below, verbatim. When it changes here, update the routine too.

```markdown
Alice learn-from-outcomes run, unattended: nobody answers questions during it.

1. In the repository checkout, create a fresh branch off `origin/master`: `git fetch origin master && git switch -c alice-learn-from-outcomes-<YYYYMMDD> --no-track origin/master` (today's date), and push it with `git push -u origin <branch>` when you commit. Its PR bases on master; this session reaches GitHub over REST only, so open it with `python3 scripts/github/rest.py pr-create`.
2. Read `skills/alice-learn-from-outcomes/SKILL.md` on that branch and follow it. Everything else the run must and must not do (no merge, no deploy, no reviewer or assignee, no customer data in the PR) is in that skill and the repo's `AGENTS.md`.
3. End with the skill's summary.
```
