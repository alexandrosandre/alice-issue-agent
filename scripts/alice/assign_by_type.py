#!/usr/bin/env python3
"""Assign alice-bot to a newly triaged issue when its labels make it hers (D13, D17).

Runs as the fixed step after the triage agent in your issue-triage workflow (not shipped here), with
the workflow's GITHUB_TOKEN: its assignments act as github-actions[bot], the one bot assignment
Alice's sweep counts (docs/design.md, D22).
"""
import json
import os
import subprocess
import sys

AGENT_LOGIN = "alice-bot"
# A type switches Alice on only once it is listed here (D13).
ON_LABELS = {"Bug", "Enhancement", "Chore"}
OFF_LABELS = {"Proposal", "Epic", "Blocked", "skip-alice"}


def refusal(issue: dict) -> str | None:
    """Why the issue is not Alice's by type, or None when it is."""
    author = issue["user"]
    # Only a person's issue becomes hers on its own: an issue Alice or a bot opens never does.
    if author["login"] == AGENT_LOGIN or author["type"] != "User":
        return f"opened by {author['login']}, not by a person"
    labels = {label["name"] for label in issue["labels"]}
    off = labels & OFF_LABELS
    if off:
        return f"labeled {', '.join(sorted(off))}"
    if not labels & ON_LABELS:
        return "not typed Bug, Enhancement or Chore"
    return None


def gh_api(*args: str) -> str:
    return subprocess.run(["gh", "api", *args], capture_output=True, text=True, check=True).stdout


def main() -> int:
    issue_path = f"repos/{os.environ['GITHUB_REPOSITORY']}/issues/{os.environ['ISSUE_NUMBER']}"
    reason = refusal(json.loads(gh_api(issue_path)))
    if reason:
        print(f"Not assigned to {AGENT_LOGIN}: {reason}.")
        return 0
    gh_api("-X", "POST", f"{issue_path}/assignees", "-f", f"assignees[]={AGENT_LOGIN}")
    print(f"Assigned to {AGENT_LOGIN}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
