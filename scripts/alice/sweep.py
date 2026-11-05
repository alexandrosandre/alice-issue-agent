#!/usr/bin/env python3
"""Start Alice's sessions on the issues and pull requests that are hers to work.

Runs from .github/workflows/alice-sweep.yml, every 10 minutes and a quiet period after each
request (alice-nudge.yml), and applies the "Selection and dispatch" rules of
docs/design.md: an issue is picked when it is assigned to alice-bot,
quiet for 5 minutes, free of other people's branches and of their pull
requests that address it, and not held back by a label; alice-bot's own pull requests get a
review-comment round once a person's review is the latest word on them (D31), and a merge round
once the latest word is an approval or LGTM from the person reviewing the issue's work (D35).
Only a person's label changes, assignments and @mentions count (D22, D43). A round goes into the
issue's existing session when one is reachable, and starts a new session otherwise or when a
person asked to start over (D38).

--dry-run prints every decision and writes nothing; it is the mode for tests and people.
"""
import argparse
import functools
import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Collection
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

sys.path.insert(0, str(Path(__file__).resolve().parent))
# pylint: disable-next=wrong-import-position
from ledger import linked_issues

AGENT_LOGIN = "alice-bot"
# The fixed step after the triage workflow's agent assigns alice-bot with the workflow's
# GITHUB_TOKEN, which acts as this login. Its assignments are the only bot changes that count (D22).
TRIAGE_ASSIGNMENT_ACTOR = "github-actions[bot]"
# The sweep's own token acts as the same login.
SWEEP_ACTOR = "github-actions[bot]"

SKIP_LABEL = "skip-alice"
WORKING_LABEL = "alice-working"
DONE_LABEL = "alice-done"
STALLED_LABEL = "alice-stalled"
CONTINUE_LABEL = "alice-continue"
RESTART_LABEL = "alice-restart"
# A person's requests to run Alice again: continue from where she stopped, or start over (D36).
REQUEST_LABELS = {CONTINUE_LABEL, RESTART_LABEL}
# Alice's and the sweep's progress labels; a person's request, not their removal, lifts them.
STATUS_LABELS = {DONE_LABEL, STALLED_LABEL}
# Labels whose history the sweep reads, not only their presence (D22).
GATED_LABELS = {SKIP_LABEL} | STATUS_LABELS | REQUEST_LABELS
# Changes that let Alice run. They count only when a person makes them, so a prompt-injected
# session acting as alice-bot can neither resume itself nor lift skip-alice.
PERMISSIVE_LABEL_CHANGES = {
    ("labeled", CONTINUE_LABEL),
    ("labeled", RESTART_LABEL),
    ("unlabeled", SKIP_LABEL),
}
# Removed when a session starts, so neither a stale request nor a leftover label survives it.
CLAIM_REMOVES = (CONTINUE_LABEL, RESTART_LABEL, DONE_LABEL, STALLED_LABEL)

PRIORITY_LABELS = ("P0", "P1", "P2")
# Long enough for a person to finish what they are writing; event-triggered sweeps (alice-nudge.yml)
# run this long after a request, so it is also how soon she starts.
QUIET_PERIOD = timedelta(minutes=5)
STALL_AFTER = timedelta(hours=24)
# Bounds the usage of Alice's accounts and stays under a routine's start rate limit.
MAX_STARTS_PER_SWEEP = 3
MAX_RUNNING = 5
FIRE_TIMEOUT_SECONDS = 60
ACTIVITY_EVENTS = {"commented", "assigned", "unassigned", "renamed", "labeled", "unlabeled"}
# The committer of the commits GitHub writes itself, such as an "Update branch" merge or rebase.
GITHUB_COMMITTER_EMAIL = "noreply@github.com"
# An approval is the reviewer's go, not a request for changes.
ACTIONABLE_REVIEW_STATES = {"commented", "changes_requested"}
# A plain "LGTM" in a review or a comment is a go like an approval (the lgtm skill's trigger).
LGTM = re.compile(r"lgtm[.!]*", re.IGNORECASE)
# A person's @alice-bot in a comment on her issue or PR asks her to act, like alice-continue (D43).
# Not inside another login (@alice-bot-x) or an email address.
MENTION = re.compile(rf"(?<![\w./-])@{AGENT_LOGIN}(?![\w-])", re.IGNORECASE)
# The sweep's reaction on a mention it sent into her running session, so it is sent once. Pick one
# that no other automation acting as the same login adds.
DELIVERED_REACTION = "rocket"
EPOCH = datetime.min.replace(tzinfo=timezone.utc)
# Ends every comment the sweep posts when it starts, or may have started, a session. A refused
# start posts none, so it never counts as a dispatch.
DISPATCH_MARKER = "<!-- alice-sweep:dispatch -->"
# Also on a merge round's start comment, so only a merge round uses up an approval.
MERGE_MARKER = "<!-- alice-sweep:merge -->"
# A person's changes that ask for another run of an issue the sweep already dispatched.
RESUME_SIGNALS = {("labeled", CONTINUE_LABEL), ("labeled", RESTART_LABEL)}
# The session a start comment names; a comment on an unconfirmed start names none.
SESSION_URL = re.compile(r"https://claude\.ai/code/[A-Za-z0-9_]+")

# The Claude Code CLI, and the secret store's command-line client as a placeholder.
# TODO: wire SECRETS_CLI to your secret store's CLI.
CLAUDE_CLI = "claude"
SECRETS_CLI = "secrets-cli"
# Alice's claude.ai sign-ins, one refresh token per account (D38). Outside the alice/ prefix,
# which her own sessions' read-only identity can read: a session must not take its account's
# sign-in.
LOGIN_SECRET = "alice-sweep/claude-login-{account}"
CLAUDE_TIMEOUT_SECONDS = 60
# The sweep warns this long before an account's sign-in chain ends, so a person renews it in time.
LOGIN_RENEWAL_WARNING = timedelta(days=3)

LINKED_WORK_QUERY = """
query($owner: String!, $repo: String!, $number: Int!) {
  repository(owner: $owner, name: $repo) {
    issue(number: $number) {
      linkedBranches(first: 20) { nodes { ref { name } } }
      closedByPullRequestsReferences(first: 20, includeClosedPrs: false) {
        nodes { number author { login } }
      }
    }
  }
}
"""


class FireRefused(Exception):
    """The routine refused the start with a 4xx answer, so no session was created."""


class FireUnconfirmed(Exception):
    """A 5xx answer, a timeout or a lost response: a session may or may not have started."""


class SendUnconfirmed(FireUnconfirmed):
    """No answer from sending into a session: it may or may not have received the round."""


class SessionUnreachable(Exception):
    """The round was not delivered to the session, so a new session can take it."""


@dataclass
class Approval:
    """The go to merge: who gave it, when, and on which commit."""

    at: datetime
    reviewer: str
    # None for a comment until the branch's push history names the commit it saw.
    commit: str | None


@dataclass
class Decision:
    """What the sweep decided for one issue or pull request, and why."""

    number: int
    kind: str
    picked: bool
    reason: str
    # Effective labels (see effective_labels) decide; current ones are what a write can remove.
    labels: set[str] = field(default_factory=set)
    current_labels: set[str] = field(default_factory=set)
    sort_key: tuple = ()
    approval: Approval | None = None
    restart: bool = False
    # The session the round goes into, set by the sweep before dispatch; None starts a new one.
    session: str | None = None
    # Who reviews the work (D24), set by the sweep before dispatch: her cloud session's proxy
    # refuses the permission lookup the rule needs, so the sweep names them.
    reviewers: Collection[str] = ()

    @property
    def fire_text(self) -> str:
        return f"{self.subject}\nReviewers: {', '.join(sorted(self.reviewers)) or 'none'}"

    @property
    def subject(self) -> str:
        if self.approval:
            return (
                f"Merge round on pull request #{self.number}: approved by"
                f" {self.approval.reviewer} at commit {self.approval.commit}"
            )
        if self.kind == "pull request":
            return f"Review-comment round on pull request #{self.number}"
        if self.restart:
            return f"Issue #{self.number}: start over"
        return f"Issue #{self.number}"

    @property
    def resume_text(self) -> str:
        return (
            f"New routine payload from the sweep: {self.fire_text}\n\n"
            "It continues this session (alice skill, Resumed round)."
        )


def parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def is_person(user: dict) -> bool:
    """A human GitHub user: not a bot or app, and not Alice herself."""
    return user["type"] == "User" and user["login"] != AGENT_LOGIN


def drop_restorations(events: list[dict]) -> list[dict]:
    """Drop label removals that the same actor undid right after.

    The sweep puts back the labels it removed when /fire refuses a start; read as two changes,
    the bot's re-add of a person's alice-continue would not count and the request would be lost.
    """
    kept: list[dict] = []
    for event in events:
        name = event["label"]["name"]
        previous = next((e for e in reversed(kept) if e["label"]["name"] == name), None)
        if (
            event["event"] == "labeled"
            and previous is not None
            and previous["event"] == "unlabeled"
            and previous["actor"]["login"] == event["actor"]["login"]
        ):
            kept.remove(previous)
            continue
        kept.append(event)
    return kept


def effective_labels(current: set[str], timeline: list[dict]) -> set[str]:
    """The labels the sweep acts on, counting only a person's permissive changes (D22).

    skip-alice counts while it is on the item or while only a bot or Alice removed it. The status
    labels alice-done and alice-stalled count once set, whoever removes them: only a request lifts
    them (D36). alice-continue and alice-restart count only while on the item and a person put
    them there.
    """
    label_events = drop_restorations([
        event for event in timeline
        if event["event"] in ("labeled", "unlabeled") and event["label"]["name"] in GATED_LABELS
    ])
    replayed: set[str] = set()
    for event in label_events:
        name = event["label"]["name"]
        if event["event"] == "unlabeled" and name in STATUS_LABELS:
            continue
        if (event["event"], name) in PERMISSIVE_LABEL_CHANGES and not is_person(event["actor"]):
            continue
        if event["event"] == "labeled":
            replayed.add(name)
        else:
            replayed.discard(name)
    restrictive = (replayed - REQUEST_LABELS) | (current & (GATED_LABELS - REQUEST_LABELS))
    resume_request = current & replayed & REQUEST_LABELS
    return (current - GATED_LABELS) | restrictive | resume_request


def agent_assignment_counts(timeline: list[dict]) -> tuple[bool, str]:
    """Whether the assignment to alice-bot came from a person or triage's assignment step."""
    assignments = [
        event for event in timeline
        if event["event"] == "assigned" and event["assignee"]["login"] == AGENT_LOGIN
    ]
    if not assignments:
        return False, "nobody"
    actor = assignments[-1]["actor"]
    return is_person(actor) or actor["login"] == TRIAGE_ASSIGNMENT_ACTOR, actor["login"]


def latest_activity(item: dict, timeline: list[dict]) -> datetime:
    """The latest edit, comment, label or assignment change on an issue."""
    times = [parse_time(item["updated_at"])]
    for event in timeline:
        if event["event"] in ACTIVITY_EVENTS:
            times.append(parse_time(event.get("updated_at") or event["created_at"]))
    return max(times)


def referencing_pull_requests(timeline: list[dict], number: int) -> dict[int, str]:
    """Open pull requests that address the issue, with their authors: a line of the description
    declares it ("Fixes #N", "Part of #N"). One that only mentions it, as a follow-up of other
    work, is not its PR, Alice's included, so it takes none of the issue's rounds or reviewers."""
    pull_requests = {}
    for event in timeline:
        if event["event"] != "cross-referenced":
            continue
        source = event["source"]["issue"]
        if ("pull_request" in source and source["state"] == "open"
                and number in linked_issues(source["body"])):
            pull_requests[source["number"]] = source["user"]["login"]
    return pull_requests


def is_start_comment(event: dict) -> bool:
    """A comment the sweep posted when it started, or may have started, a session. Only its own
    count, so nobody can fake a dispatch or point a round at another session."""
    return (
        event["event"] == "commented"
        and event["actor"]["login"] == SWEEP_ACTOR
        and event["body"].rstrip().endswith(DISPATCH_MARKER)
    )


def latest_dispatch(timeline: list[dict], merges_only: bool = False) -> datetime | None:
    """When the sweep last started, or may have started, a session (or a merge round) on it."""
    times = [
        parse_time(event["created_at"]) for event in timeline
        if is_start_comment(event) and (not merges_only or MERGE_MARKER in event["body"])
    ]
    return max(times, default=None)


def latest_session(timelines: list[list[dict]]) -> str | None:
    """The session the sweep's newest start comment names, across an issue and Alice's pull
    requests for it. None when that comment names none: an unconfirmed start may have started a
    session the sweep cannot name, and an older one would miss its work."""
    starts = [
        (parse_time(event["created_at"]), event["body"])
        for timeline in timelines for event in timeline if is_start_comment(event)
    ]
    if not starts:
        return None
    match = SESSION_URL.search(max(starts)[1])
    return match.group(0) if match else None


def resumed_by_person_since(timeline: list[dict], since: datetime) -> bool:
    return any(
        event["event"] in ("labeled", "unlabeled")
        and (event["event"], event["label"]["name"]) in RESUME_SIGNALS
        and is_person(event["actor"])
        and parse_time(event["created_at"]) > since
        for event in timeline
    )


def person_mentions(timeline: list[dict], delivered: Collection[int] = ()) -> list[dict]:
    """A person's comments that @mention Alice since the sweep last started her, and that it did
    not send into a running session (`delivered`): requests she has not seen. One that only says
    LGTM is an approval, not a request. An edited comment does not count: the timeline names its
    author, not who edited it, and alice-bot may edit anyone's comment (D22)."""
    since = latest_dispatch(timeline) or EPOCH
    return [
        event for event in timeline
        if event["event"] == "commented" and is_person(event["actor"])
        and parse_time(event["created_at"]) > since
        and event["updated_at"] == event["created_at"]
        and MENTION.search(event["body"]) and not is_lgtm(event["body"])
        and event["id"] not in delivered
    ]


def is_lgtm(body: str | None) -> bool:
    """LGTM alone, or addressed to her ("@alice-bot LGTM")."""
    return LGTM.fullmatch(MENTION.sub("", body or "").strip()) is not None


def issue_reviewers(
    issue: dict, timeline: list[dict], is_developer: Callable[[str], bool]
) -> set[str]:
    """Who reviews Alice's work on an issue (D24): one area owner, the developer assignee who
    filed it, else the one who assigned her; failing both, every developer assignee. With no
    developer assigned, the developer who filed it or assigned her; else nobody. A support or
    customer-success assignee follows an issue without owning its review."""
    # Only a developer's assignment names the assigner: a later one by Alice, a bot or support
    # would otherwise widen who may approve.
    assigners = [event["actor"]["login"] for event in timeline
                 if event["event"] == "assigned" and event["assignee"]["login"] == AGENT_LOGIN
                 and is_person(event["actor"])]
    author = issue["user"]["login"] if is_person(issue["user"]) else None
    assigned_by = {event["assignee"]["login"]: event["actor"]["login"]
                   for event in timeline if event["event"] == "assigned"}
    # Alice assigns the reviewer she was given. For the filer or her assigner that changes
    # nothing; for a developer the review was handed to, counting it would let her own write
    # decide who reviews.
    assignees = {user["login"] for user in issue["assignees"]
                 if is_person(user) and (assigned_by.get(user["login"]) != AGENT_LOGIN
                                         or user["login"] == author
                                         or user["login"] in assigners)}
    owners = {login for login in assignees if is_developer(login)}
    if author in owners:
        return {author}
    owner_assigners = [login for login in assigners if login in owners]
    if owner_assigners:
        return {owner_assigners[-1]}
    if owners:
        return owners
    if author and is_developer(author):
        return {author}
    developer_assigners = [login for login in assigners if is_developer(login)]
    return {developer_assigners[-1]} if developer_assigners else set()


def agent_pull_requests_declaring(timeline: list[dict], number: int) -> dict[int, str]:
    """Her PRs that declare the issue, closed and merged ones included, with when each first
    mentioned it: a hand-off made on a PR she later closed still names the issue's reviewer,
    and a request from before that mention does not count."""
    declaring: dict[int, str] = {}
    for event in timeline:
        source = event["source"]["issue"] if event["event"] == "cross-referenced" else None
        if (source and "pull_request" in source and source["user"]["login"] == AGENT_LOGIN
                and number in linked_issues(source["body"])):
            declaring.setdefault(source["number"], event["created_at"])
    return declaring


def handed_off(
    reviewers: Collection[str], timelines: list[tuple[str, list[dict]]],
    is_developer: Callable[[str], bool],
) -> set[str]:
    """The issue's reviewers once the review requests on her PRs are read in time order: a
    reviewer who requests another developer's review hands the review to that developer. A
    request a person withdrew later on the same PR hands nothing over, and only people's
    requests count. `reviewers` is who reviews by the issue alone (D24), which Alice's own
    assignments do not change. Each timeline comes with when its PR first named the issue,
    and earlier requests do not count."""
    requests = sorted(
        ((pull_request, event) for pull_request, (named_at, timeline) in enumerate(timelines)
         for event in timeline
         if event["event"] in ("review_requested", "review_request_removed")
         and event["created_at"] >= named_at
         and event.get("requested_reviewer") and is_person(event["requested_reviewer"])
         and is_person(event["actor"])),
        key=lambda pair: pair[1]["created_at"])
    current = set(reviewers)
    for index, (pull_request, event) in enumerate(requests):
        login, actor = event["requested_reviewer"]["login"], event["actor"]["login"]
        withdrawn = any(other["event"] == "review_request_removed"
                        and other["requested_reviewer"]["login"] == login
                        for source, other in requests[index + 1:] if source == pull_request)
        if (event["event"] == "review_requested" and not withdrawn and actor in current
                and login != actor and is_developer(login)):
            current = {login}
    return current


def is_lgtm_review(event: dict) -> bool:
    """A review that only comments, saying LGTM: a go like an approval, not a request."""
    return event["state"] == "commented" and is_lgtm(event["body"])


def latest_approval(timeline: list[dict], reviewers: Collection[str]) -> Approval | None:
    """The latest approval, or plain LGTM in a review or comment, from one of the issue's
    reviewers. A comment names no commit, so its `commit` is None."""
    approval = None
    for event in timeline:
        if (
            event["event"] == "reviewed" and event["user"]["login"] in reviewers
            and (event["state"] == "approved" or is_lgtm_review(event))
        ):
            approval = Approval(
                parse_time(event["submitted_at"]), event["user"]["login"], event["commit_id"])
        elif (
            # An edited comment is no go: alice-bot may edit anyone's comment (D22).
            event["event"] == "commented" and event["actor"]["login"] in reviewers
            and event["updated_at"] == event["created_at"] and is_lgtm(event["body"])
        ):
            approval = Approval(parse_time(event["created_at"]), event["actor"]["login"], None)
    return approval


def priority_rank(labels: set[str]) -> int:
    ranks = [rank for rank, label in enumerate(PRIORITY_LABELS) if label in labels]
    return min(ranks) if ranks else len(PRIORITY_LABELS)


def evaluate_issue(
    issue: dict,
    timeline: list[dict],
    work_by_others: Callable[[], list[str]],
    now: datetime,
    running_pull_requests: Collection[int] = (),
    delivered: Collection[int] = (),
) -> Decision:
    """Decide whether the sweep starts a session on one issue assigned to alice-bot.

    work_by_others is called last, only for an issue every other rule lets through, since it
    costs extra API calls. running_pull_requests are the PRs a review or merge round holds, and
    delivered the mention comments the sweep sent into a running session.
    """
    number = issue["number"]
    current = {label["name"] for label in issue["labels"]}
    labels = effective_labels(current, timeline)

    def skip(reason: str) -> Decision:
        return Decision(number, "issue", False, reason, labels, current)

    counts, assigner = agent_assignment_counts(timeline)
    if not counts:
        return skip(f"assigned to {AGENT_LOGIN} by {assigner}, not by a person or triage")
    if WORKING_LABEL in labels:
        return skip(f"{WORKING_LABEL}: a session is already running")
    rounds = sorted(
        pr for pr, author in referencing_pull_requests(timeline, number).items()
        if author == AGENT_LOGIN and pr in running_pull_requests
    )
    if rounds:
        return skip(f"a round is running on her pull request #{rounds[0]}")
    if SKIP_LABEL in labels:
        if SKIP_LABEL in current:
            return skip(f"{SKIP_LABEL} is set")
        return skip(f"{SKIP_LABEL} still counts: only a bot or {AGENT_LOGIN} removed it")
    held_back = sorted(labels & {DONE_LABEL, STALLED_LABEL})
    mentioned = bool(person_mentions(timeline, delivered))
    if held_back and not labels & REQUEST_LABELS and not mentioned:
        waiting = f"{', '.join(held_back)} without {CONTINUE_LABEL} or {RESTART_LABEL}"
        absent = [label for label in held_back if label not in current]
        if absent:
            return skip(
                f"{waiting} ({', '.join(absent)} still counts: only a person's request lifts it)")
        return skip(waiting)
    # A session that drops alice-working without alice-done must not get itself a new run.
    dispatched_at = latest_dispatch(timeline)
    if dispatched_at and not resumed_by_person_since(timeline, dispatched_at) and not mentioned:
        return skip(
            f"started before; waits for a person to add {CONTINUE_LABEL} or {RESTART_LABEL},"
            f" or to @mention {AGENT_LOGIN}"
        )
    quiet_for = now - latest_activity(issue, timeline)
    if quiet_for < QUIET_PERIOD:
        return skip(f"last activity {int(quiet_for.total_seconds() // 60)} minutes ago")
    others = work_by_others()
    if others:
        return skip(f"someone else is on it: {', '.join(others)}")
    restart = RESTART_LABEL in labels
    if restart:
        reason = "start over requested"
    else:
        reason = "resume requested" if held_back else "ready"
    rank = priority_rank(labels)
    priority = PRIORITY_LABELS[rank] if rank < len(PRIORITY_LABELS) else "unprioritized"
    return Decision(
        number, "issue", True, f"{reason}, {priority}", labels, current,
        sort_key=(1, rank, issue["created_at"]), restart=restart,
    )


def evaluate_review_round(
    pull_request: dict, timeline: list[dict], now: datetime, issue_session_running: bool = False,
    reviewers: Collection[str] = (),
    head_at: Callable[[datetime], str | None] = lambda at: None,
    delivered: Collection[int] = (),
) -> Decision:
    """Decide whether a person's review on one of alice-bot's pull requests starts a round.

    A review with comments or requested changes starts a review-comment round (D31). When the
    latest review is an approval or plain LGTM from one of `reviewers`, the reviewers of the PR's
    issue, it starts a merge round instead (D35). `issue_session_running` is set while the session
    that opened the PR still holds its issue: that session readies the PR before its review
    pipeline ends, so a round would share its branch. A PR whose description declares no issue
    waits for that line.
    """
    number = pull_request["number"]
    current = {label["name"] for label in pull_request["labels"]}
    labels = effective_labels(current, timeline)

    def skip(reason: str) -> Decision:
        return Decision(number, "pull request", False, reason, labels, current)

    if WORKING_LABEL in labels:
        return skip(f"{WORKING_LABEL}: a session is already running")
    if issue_session_running:
        return skip("the session on its issue is still running")
    if not linked_issues(pull_request["body"]):
        # It is then no issue's PR, so no issue session that may still push to it holds it.
        return skip("its description declares no issue")
    if SKIP_LABEL in labels:
        return skip(f"{SKIP_LABEL} counts as set")
    actionable_reviews = [
        (parse_time(event["submitted_at"]), event["user"]["login"]) for event in timeline
        if event["event"] == "reviewed"
        and is_person(event["user"])
        and event["state"] in ACTIONABLE_REVIEW_STATES
        and not is_lgtm_review(event)
    ]
    latest_review = max((at for at, _ in actionable_reviews), default=None)
    # Commits count as an answer whoever pushed them: a person who pushes has taken it over. A
    # base merge does not, nor a commit GitHub writes for "Update branch" (merge or rebase).
    answers = [
        parse_time(event["committer"]["date"]) for event in timeline
        if event["event"] == "committed" and len(event["parents"]) < 2
        and event["committer"]["email"] != GITHUB_COMMITTER_EMAIL
    ] + [
        parse_time(event["created_at"]) for event in timeline
        if event["event"] == "commented" and event["actor"]["login"] == AGENT_LOGIN
    ] + [
        parse_time(event["submitted_at"]) for event in timeline
        if event["event"] == "reviewed" and event["user"]["login"] == AGENT_LOGIN
    ]
    latest_answer = max(answers, default=None)
    unanswered = bool(latest_review) and (not latest_answer or latest_answer < latest_review)
    dispatched_at = latest_dispatch(timeline)
    approval = latest_approval(timeline, reviewers)
    # A person's alice-continue or alice-restart on the PR, added since its last round, or a
    # person's @alice-bot she has not seen, starts one whatever its reviews say: after a person
    # pushed to the branch, or with no review at all. The approver's own mention before their
    # approval gave way to it; anyone else's still asks to be answered first.
    mentions = [
        event for event in person_mentions(timeline, delivered)
        if not approval or parse_time(event["created_at"]) > approval.at
        or event["actor"]["login"] != approval.reviewer
    ]
    resume_requested = (bool(labels & REQUEST_LABELS) and resumed_by_person_since(
        timeline, dispatched_at or EPOCH)) or bool(mentions)
    if approval:
        # The approval merges only as the latest word, any person's comment after it included,
        # with the other people's reviews answered, and never on a request to carry the PR on:
        # those get a review round first, or wait for the reviewer to approve again.
        others_unanswered = any(
            login != approval.reviewer and (not latest_answer or latest_answer < at)
            for at, login in actionable_reviews
        )
        later_comment = any(
            event["event"] == "commented" and is_person(event["actor"])
            and parse_time(event["created_at"]) > approval.at
            for event in timeline
        )
        if (
            (latest_review and approval.at < latest_review) or later_comment
            or others_unanswered or resume_requested
        ):
            approval = None
    if not approval and not latest_review and not resume_requested:
        return skip("no review comments from a person")
    if not resume_requested:
        merge_dispatched_at = latest_dispatch(timeline, merges_only=True)
        if approval and merge_dispatched_at and merge_dispatched_at >= approval.at:
            return skip(f"a merge round was already started for {approval.reviewer}'s approval")
        if not approval and not unanswered:
            return skip("the latest review is answered")
        if not approval and dispatched_at and dispatched_at >= latest_review:
            return skip("a session was already started for the latest review")
    person_activity = [
        parse_time(event["submitted_at"]) for event in timeline
        if event["event"] == "reviewed" and is_person(event["user"])
    ] + [
        parse_time(event["created_at"]) for event in timeline
        if event["event"] in ("commented", "labeled", "unlabeled") and is_person(event["actor"])
    ]
    latest_person_activity = max(person_activity)
    quiet_for = now - latest_person_activity
    if quiet_for < QUIET_PERIOD:
        return skip(f"a person was active {int(quiet_for.total_seconds() // 60)} minutes ago")
    resumed = ", resume requested" if resume_requested else ""
    if approval and approval.commit is None:
        head = head_at(approval.at)
        if head is None:
            return skip(f"no push to the branch before {approval.reviewer}'s LGTM")
        approval.commit = head
    if approval:
        return Decision(
            number, "pull request", True, f"merge round, approved by {approval.reviewer}{resumed}",
            labels, current, sort_key=(0, approval.at.isoformat()), approval=approval,
        )
    return Decision(
        number, "pull request", True, f"review-comment round{resumed}",
        labels, current, sort_key=(0, (latest_review or latest_person_activity).isoformat()),
        restart=resume_requested and RESTART_LABEL in labels,
    )


def latest_agent_activity(timelines: list[list[dict]]) -> datetime:
    """When the running session last showed a sign of life: its start, a comment, a push.

    Pass the item's timeline and those of alice-bot's pull requests for it; their commits count.
    """
    times = []
    for timeline in timelines:
        for event in timeline:
            kind = event["event"]
            if kind == "labeled" and event["label"]["name"] == WORKING_LABEL:
                times.append(parse_time(event["created_at"]))
            elif kind == "commented" and event["actor"]["login"] == AGENT_LOGIN:
                times.append(parse_time(event["created_at"]))
            elif kind == "reviewed" and event["user"]["login"] == AGENT_LOGIN:
                times.append(parse_time(event["submitted_at"]))
            elif kind == "committed":
                times.append(parse_time(event["committer"]["date"]))
            elif (
                kind == "cross-referenced"
                and event["source"]["issue"]["user"]["login"] == AGENT_LOGIN
            ):
                times.append(parse_time(event["created_at"]))
    if not times:
        raise ValueError(f"no {WORKING_LABEL} label event in the timeline")
    return max(times)


def is_stalled(timelines: list[list[dict]], now: datetime) -> bool:
    return now - latest_agent_activity(timelines) >= STALL_AFTER


def start_limit(running: int) -> int:
    return max(0, min(MAX_STARTS_PER_SWEEP, MAX_RUNNING - running))


def kind_of(item: dict) -> str:
    return "pull request" if "pull_request" in item else "issue"


def dispatch(
    decision: Decision,
    github: "GitHub",
    fire: Callable[[str], str],
    send: Callable[[str, str], None],
    log: Callable[[str], None] = print,
) -> str:
    """Claim the item, send its round into the issue's session or start a new one, and say so on
    it. Returns the session URL.

    The label goes on first: neither /fire nor a send has an idempotency key, so the label is the
    duplicate guard. An unreachable session leaves the round to a new one. A 4xx from /fire means
    no session started, so the claim is undone and FireRefused propagates; a 5xx, timeout or lost
    answer from either may hide a delivered round, so the claim stays and FireUnconfirmed
    propagates after a comment says so.
    """
    number = decision.number
    markers = f"{MERGE_MARKER}\n{DISPATCH_MARKER}" if decision.approval else DISPATCH_MARKER
    removed = [label for label in CLAIM_REMOVES if label in decision.current_labels]
    github.add_labels(number, [WORKING_LABEL])
    for label in removed:
        github.remove_label(number, label)
    session_url = None
    try:
        if decision.session:
            try:
                send(decision.session, decision.resume_text)
                session_url = decision.session
            except SessionUnreachable as error:
                log(f"::warning::#{number} her session {decision.session} is unreachable, so a new"
                    f" one starts: {error}")
        resumed = session_url is not None
        if not resumed:
            session_url = fire(decision.fire_text)
    except FireRefused:
        if removed:
            github.add_labels(number, removed)
        github.remove_label(number, WORKING_LABEL)
        raise
    except FireUnconfirmed as error:
        if isinstance(error, SendUnconfirmed):
            outcome = f"may not have received this round: sending it into {decision.session}"
        else:
            outcome = "may not have started: the start request"
        github.comment(
            number,
            f"Alice's session {outcome} got no confirmation ({error}). This {decision.kind} keeps"
            f" `{WORKING_LABEL}` so no second session starts. If Alice posts nothing within 24"
            f" hours, the sweep marks it `{STALLED_LABEL}`; adding `{CONTINUE_LABEL}` then"
            f" starts her again.\n\n{markers}",
        )
        raise
    verb = "continues in her session" if resumed else "started a session"
    if decision.approval:
        message = f"Alice {verb} to merge this approved pull request: {session_url}"
    elif decision.kind == "pull request":
        message = f"Alice {verb} on the review comments: {session_url}"
    else:
        message = f"Alice {verb} on this issue: {session_url}"
    github.comment(number, f"{message}\n\n{markers}")
    return session_url


def delivered_mentions(timeline: list[dict], github: "GitHub") -> set[int]:
    """The mentions since her latest start that the sweep sent into a running session. Raises
    RuntimeError when the reactions cannot be read: the item then waits, since counting the
    mentions either way could start a duplicate round or drop someone's request."""
    return {
        event["id"] for event in person_mentions(timeline) if github.reacted(event["id"])
    }


def deliver_mentions(
    items: list[tuple[int, list[dict]]],
    session: str | None,
    github: "GitHub",
    send: Callable[[str, str], None],
    now: datetime,
    dry_run: bool,
    log: Callable[[str], None],
) -> None:
    """Send each person's @mention made while her session runs into that session, once: the
    sweep's reaction on the comment records the delivery, and shows the person it reached her. A
    send that got no confirmation may have arrived, so it is marked too, as dispatch does."""
    for number, timeline in items:
        try:
            delivered = delivered_mentions(timeline, github)
        except RuntimeError as error:
            log(f"::warning::#{number} mentions wait: their reactions are unreadable: {error}")
            continue
        for mention in person_mentions(timeline, delivered):
            login = mention["actor"]["login"]
            # Like a round, it waits until the person has had time to finish writing.
            if now - parse_time(mention["created_at"]) < QUIET_PERIOD:
                continue
            if session is None:
                log(f"::warning::#{number} {login}'s mention waits: her running session is unknown")
                continue
            if dry_run:
                log(f"#{number} would send {login}'s mention into {session}")
                continue
            text = (
                f"New request from the sweep: {login} mentioned you on #{number} while this"
                f" session runs: {mention['html_url']}\n\nRead it with"
                f" `python3 scripts/alice/issue_text.py {number}` and take it into this run (alice"
                " skill, Requests during a run)."
            )
            try:
                send(session, text)
            except SessionUnreachable as error:
                log(f"::warning::#{number} {login}'s mention not sent into {session}: {error}")
                continue
            except FireUnconfirmed as error:
                log(f"::warning::#{number} {login}'s mention may not have reached {session}:"
                    f" {error}")
            try:
                github.react(mention["id"])
            except RuntimeError as error:
                log(f"::warning::#{number} could not mark {login}'s mention as sent: {error}")
                continue
            log(f"#{number} sent {login}'s mention into {session}")


def mark_stalled(number: int, kind: str, github: "GitHub") -> None:
    github.add_labels(number, [STALLED_LABEL])
    github.remove_label(number, WORKING_LABEL)
    github.comment(
        number,
        f"Alice has neither commented nor pushed for 24 hours, so this {kind} is marked"
        f" `{STALLED_LABEL}` and her running slot is freed. Her session may still be running."
        f" Adding `{CONTINUE_LABEL}` sends her a round in that session; `{RESTART_LABEL}` starts"
        f" her over in a new one.",
    )


def sweep(
    github: "GitHub",
    fire: Callable[[str], str],
    send: Callable[[str, str], None],
    now: datetime,
    dry_run: bool,
    log: Callable[[str], None] = print,
) -> int:
    """Run one sweep; returns the process exit code."""
    running = 0
    pull_requests_of_running_issues: set[int] = set()
    running_pull_requests: set[int] = set()
    assigned_issues = github.open_issues_assigned_to_agent()
    assigned_numbers = {issue["number"] for issue in assigned_issues}
    for item in github.open_items_labeled(WORKING_LABEL):
        number, kind = item["number"], kind_of(item)
        timeline = github.timeline(number)
        timelines = [timeline]
        if kind == "issue":
            agent_pull_requests = [
                pr for pr, author in referencing_pull_requests(timeline, number).items()
                if author == AGENT_LOGIN
            ]
            timelines += [github.timeline(pr) for pr in agent_pull_requests]
        if not is_stalled(timelines, now):
            running += 1
            if kind == "issue":
                pull_requests_of_running_issues.update(agent_pull_requests)
                items = [(number, timeline)] + list(zip(agent_pull_requests, timelines[1:]))
            else:
                running_pull_requests.add(number)
                # A round on her PR runs in its issue's session, so mentions on that issue reach it
                # too; an issue the PR names that is not hers (an epic, say) is left alone.
                items = [(number, timeline)] + [
                    (issue, github.timeline(issue)) for issue in linked_issues(item["body"])
                    if issue in assigned_numbers
                ]
            log(f"#{number} running")
            deliver_mentions(items, latest_session(timelines), github, send, now, dry_run, log)
            continue
        log(f"#{number} stalled: no comment or push from {AGENT_LOGIN} for 24 hours")
        if not dry_run:
            mark_stalled(number, kind, github)

    issues = [(issue, github.timeline(issue["number"])) for issue in assigned_issues]
    pull_requests_of_issue = {
        issue["number"]: [
            pr for pr, author in referencing_pull_requests(timeline, issue["number"]).items()
            if author == AGENT_LOGIN
        ]
        for issue, timeline in issues
    }
    # A PR whose issue is no longer Alice's has no reviewer whose approval she merges on. An
    # issue whose reviewer could not be read starts nothing this sweep: telling her "none"
    # would make her request nobody, and no merge round beats a wrong one.
    reviewers_of_issue = {}
    unknown_reviewers = set()
    pull_request_timelines: dict[int, list[dict]] = {}
    for issue, timeline in issues:
        try:
            declaring = agent_pull_requests_declaring(timeline, issue["number"])
            for pr in declaring:
                if pr not in pull_request_timelines:
                    pull_request_timelines[pr] = github.timeline(pr)
            reviewers_of_issue[issue["number"]] = handed_off(
                issue_reviewers(issue, timeline, github.is_developer),
                [(named_at, pull_request_timelines[pr]) for pr, named_at in declaring.items()],
                github.is_developer)
        except RuntimeError as error:
            log(f"::warning::#{issue['number']} reviewer unknown, so it waits: {error}")
            reviewers_of_issue[issue["number"]] = set()
            unknown_reviewers.add(issue["number"])
    reviewers_of_pull_request = {
        pr: reviewers_of_issue[number]
        for number, prs in pull_requests_of_issue.items() for pr in prs
    }
    issue_timelines = {issue["number"]: timeline for issue, timeline in issues}
    issue_of_pull_request = {
        pr: issue for issue, prs in pull_requests_of_issue.items() for pr in prs
    }
    decisions = []
    for pr in github.open_pull_requests_by_agent():
        try:
            if pr["number"] not in pull_request_timelines:
                pull_request_timelines[pr["number"]] = github.timeline(pr["number"])
            decisions.append(evaluate_review_round(
                pr, pull_request_timelines[pr["number"]], now,
                issue_session_running=pr["number"] in pull_requests_of_running_issues,
                reviewers=reviewers_of_pull_request.get(pr["number"], ()),
                head_at=lambda at, n=pr["number"]: github.head_at(n, at),
                delivered=delivered_mentions(pull_request_timelines[pr["number"]], github),
            ))
        except RuntimeError as error:
            # One PR GitHub would not answer for must not stop the sweep for every other item.
            log(f"::warning::#{pr['number']} pull request skipped: {error}")
    for issue, timeline in issues:
        try:
            delivered = delivered_mentions(timeline, github)
        except RuntimeError as error:
            log(f"::warning::#{issue['number']} issue skipped: its mention reactions are"
                f" unreadable: {error}")
            continue
        decisions.append(evaluate_issue(
            issue, timeline, lambda i=issue, t=timeline: github.work_by_others(i["number"], t), now,
            running_pull_requests=running_pull_requests, delivered=delivered,
        ))
    for decision in decisions:
        if not decision.picked:
            log(f"#{decision.number} {decision.kind} skipped: {decision.reason}")

    picks = sorted((d for d in decisions if d.picked), key=lambda d: d.sort_key)
    limit = start_limit(running)
    log(f"{running} running; up to {limit} new sessions this sweep")
    # Rounds sort before issues, so an issue whose PR got a round in this sweep is seen after it.
    started: set[int] = set()
    held = False
    position = 0
    for decision in picks:
        issue = decision.number if decision.kind == "issue" else (
            issue_of_pull_request.get(decision.number))
        if issue in unknown_reviewers:
            log(f"#{decision.number} {decision.kind} waits: its reviewer could not be read")
            held = True
            continue
        if decision.kind == "issue" and started & set(pull_requests_of_issue[decision.number]):
            log(f"#{decision.number} issue waits: a round on her pull request starts this sweep")
            continue
        position += 1
        if position > limit:
            log(f"#{decision.number} {decision.kind} waits for a free slot: {decision.reason}")
            continue
        started.add(decision.number)
        decision.reviewers = reviewers_of_issue.get(issue, ())
        if not decision.restart:
            timelines = [pull_request_timelines[decision.number]] if issue is None else (
                [issue_timelines[issue]] + [
                    pull_request_timelines[pr] for pr in pull_requests_of_issue[issue]
                    if pr in pull_request_timelines
                ])
            decision.session = latest_session(timelines)
        if dry_run:
            into = f"; into {decision.session}" if decision.session else ""
            reviewers = ", ".join(sorted(decision.reviewers)) or "none"
            log(f"#{decision.number} {decision.kind} would start: {decision.reason}{into};"
                f" reviewers {reviewers}")
            continue
        try:
            session_url = dispatch(decision, github, fire, send, log)
        except FireRefused as error:
            log(f"::error::The routine refused to start #{decision.number}: {error}")
            return 1
        except FireUnconfirmed as error:
            log(f"::warning::#{decision.number} start unconfirmed, no more starts: {error}")
            return 0
        log(f"#{decision.number} {decision.kind} started: {decision.reason}; {session_url}")
    # Held work fails the run, so a lookup that keeps failing shows as a red run instead of work
    # that silently never starts: a held start, or an issue with her PR, whose approval cannot
    # start a merge round without a reviewer. An issue that would start nothing does not.
    return 1 if held or any(pull_requests_of_issue[n] for n in unknown_reviewers) else 0


class Routines:  # pylint: disable=too-few-public-methods
    """Alice's routines, one per Claude account, taking starts in turn so her sessions
    spread over the accounts' usage limits.

    A refused start moves on to the next routine: a refusal means no session started, so another
    routine cannot duplicate one. An unconfirmed start may have created a session and is never
    retried.
    """

    def __init__(self, fires: list[Callable[[str], str]], first: int, log=print):
        self.fires = fires
        self.next = first % len(fires)
        self.log = log

    def __call__(self, text: str) -> str:
        refusal = None
        for attempt in range(len(self.fires)):
            index = (self.next + attempt) % len(self.fires)
            try:
                session_url = self.fires[index](text)
            except FireRefused as error:
                self.log(f"::warning::Routine {index + 1} refused the start: {error}")
                refusal = error
                continue
            self.next = index + 1
            return session_url
        raise refusal


def fire_routine(url: str, token: str, text: str) -> str:
    """POST the routine's /fire endpoint and return the new session's URL.

    https://platform.claude.com/docs/en/api/claude-code/routines-fire
    """
    request = urllib.request.Request(
        url,
        data=json.dumps({"text": text}).encode(),
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "anthropic-version": "2023-06-01",
            "anthropic-beta": "experimental-cc-routine-2026-04-01",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=FIRE_TIMEOUT_SECONDS) as response:
            body = json.load(response)
    except urllib.error.HTTPError as error:
        detail = f"HTTP {error.code}: {error.read().decode(errors='replace')[:500]}"
        if 400 <= error.code < 500:
            raise FireRefused(detail) from error
        raise FireUnconfirmed(detail) from error
    except (urllib.error.URLError, OSError, ValueError) as error:
        raise FireUnconfirmed(f"no answer: {error}") from error
    if "claude_code_session_url" not in body:
        raise FireUnconfirmed(f"answer without a session URL: {json.dumps(body)[:500]}")
    return body["claude_code_session_url"]


class SignInFailed(Exception):
    """An account could not be signed in to claude.ai this sweep."""


class Sessions:  # pylint: disable=too-few-public-methods
    """Sends rounds into Alice's existing cloud sessions (D38), as `send(session_url, text)`.

    Only a claude.ai sign-in of the account that owns a session can send into it (`claude -p
    --cloud`); /fire tokens cannot. Each account is signed in at most once per sweep from the
    refresh token in its LOGIN_SECRET. A sign-in replaces that token and the old one stops
    working, so the new one is stored back before anything uses it; if storing fails, the account
    stays signed out after this sweep until a person runs scripts/alice/sign-in-claude.sh again.
    A session's owner is not recorded: every account is tried until one delivers, since the
    others answer that they cannot reach it.
    """

    def __init__(self, accounts: list[int], log=print, run=subprocess.run):
        self.accounts = accounts
        self.log = log
        self.run = run
        # None once an account's sign-in failed this sweep, so it is not tried again.
        self.config_dirs: dict[int, str | None] = {}

    def __call__(self, session_url: str, text: str) -> None:
        failures = []
        for account in self.accounts:
            config_dir = self._signed_in(account)
            if config_dir is None:
                failures.append(f"account {account} is not signed in")
                continue
            error = self._send(config_dir, session_url, text)
            if error is None:
                return
            failures.append(f"account {account}: {error}")
        raise SessionUnreachable("; ".join(failures))

    def _signed_in(self, account: int) -> str | None:
        if account not in self.config_dirs:
            try:
                self.config_dirs[account] = self._sign_in(account)
            # Anything a sign-in raises leaves the round to a new session; the item is claimed.
            except Exception as error:  # pylint: disable=broad-exception-caught
                self.log(f"::warning::Alice's account {account} could not sign in to claude.ai, so"
                         f" her rounds start new sessions ({error!r}). A sign-in that got as far"
                         f" as claude.ai may have spent the stored token; if this repeats, a person"
                         f" runs scripts/alice/sign-in-claude.sh {account}.")
                self.config_dirs[account] = None
        return self.config_dirs[account]

    def _secret(self, *args: str, value: str | None = None) -> str:
        result = self.run(
            [SECRETS_CLI, *args], input=value, capture_output=True, text=True,
            check=False, timeout=CLAUDE_TIMEOUT_SECONDS,
        )
        if result.returncode != 0:
            raise SignInFailed(f"{SECRETS_CLI} {args[0]}: {result.stderr.strip()[:300]}")
        return result.stdout

    def _sign_in(self, account: int) -> str:
        secret_id = LOGIN_SECRET.format(account=account)
        try:
            stored = json.loads(self._secret("get", secret_id))
            self.log(f"::add-mask::{stored['refresh_token']}")
        except (OSError, subprocess.TimeoutExpired, ValueError, KeyError) as error:
            raise SignInFailed(f"{secret_id}: {error!r}") from error
        config_dir = tempfile.mkdtemp(prefix=f"claude-login-{account}-")
        environment = os.environ | {
            "CLAUDE_CONFIG_DIR": config_dir,
            "CLAUDE_CODE_OAUTH_REFRESH_TOKEN": stored["refresh_token"],
            "CLAUDE_CODE_OAUTH_SCOPES": stored["scopes"],
        }
        try:
            result = self.run(
                [CLAUDE_CLI, "auth", "login"], env=environment, stdin=subprocess.DEVNULL,
                capture_output=True, text=True, check=False, timeout=CLAUDE_TIMEOUT_SECONDS,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise SignInFailed(f"claude auth login: {error}") from error
        if result.returncode != 0:
            output = (result.stdout + result.stderr).strip()
            raise SignInFailed(f"claude auth login: {output[:300]}")
        try:
            with open(os.path.join(config_dir, ".credentials.json"), encoding="utf-8") as file:
                oauth = json.load(file)["claudeAiOauth"]
            self.log(f"::add-mask::{oauth['refreshToken']}")
        except (OSError, ValueError, KeyError) as error:
            raise SignInFailed(f"the sign-in stored no credentials: {error!r}") from error
        try:
            self._secret(
                "put", secret_id,
                value=json.dumps({"refresh_token": oauth["refreshToken"],
                                  "scopes": stored["scopes"]}),
            )
        except (OSError, subprocess.TimeoutExpired, SignInFailed) as error:
            self.log(f"::error::Alice's account {account} signed in, but its new token could not be"
                     f" stored ({error}). After this sweep it stays signed out until a person runs"
                     f" scripts/alice/sign-in-claude.sh {account}.")
        ends = datetime.fromtimestamp(oauth["refreshTokenExpiresAt"] / 1000, timezone.utc)
        if ends - datetime.now(timezone.utc) < LOGIN_RENEWAL_WARNING:
            self.log(f"::warning::Alice's account {account} signs out on {ends:%Y-%m-%d %H:%M} UTC;"
                     f" renew it with scripts/alice/sign-in-claude.sh {account}.")
        return config_dir

    def _send(self, config_dir: str, session_url: str, text: str) -> str | None:
        """None once the session took the message, else the reason it did not. What the CLI
        printed goes to the log only, since SendUnconfirmed's text is posted on the item."""
        try:
            result = self.run(
                [CLAUDE_CLI, "-p", text, "--cloud", session_url, "--output-format", "json"],
                env=os.environ | {"CLAUDE_CONFIG_DIR": config_dir}, stdin=subprocess.DEVNULL,
                capture_output=True, text=True, check=False, timeout=CLAUDE_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired as error:
            raise SendUnconfirmed("claude -p --cloud did not answer in time") from error
        except OSError as error:
            return f"claude -p --cloud could not run: {error}"
        for line in result.stdout.splitlines():
            try:
                answer = json.loads(line)
            except ValueError:
                continue
            if isinstance(answer, dict) and "ok" in answer:
                return None if answer["ok"] else str(answer.get("error"))
        self.log(f"::warning::claude -p --cloud exited {result.returncode} without an answer:"
                 f" {(result.stdout + result.stderr).strip()[:500]}")
        raise SendUnconfirmed("claude -p --cloud gave no answer")


class GitHub:
    """The repository through `gh api`, authenticated by GH_TOKEN."""

    def __init__(self, repository: str):
        self.repository = repository
        self.developers: dict[str, bool] = {}

    def _api(self, *args: str) -> Any:
        result = subprocess.run(["gh", "api", *args], capture_output=True, text=True, check=False)
        if result.returncode != 0:
            raise RuntimeError(f"gh api {' '.join(args)} failed: {result.stderr.strip()}")
        return json.loads(result.stdout) if result.stdout.strip() else None

    def _paginated(self, path: str) -> list[dict]:
        pages = self._api("--paginate", "--slurp", path)
        return [item for page in pages for item in page]

    def open_items_labeled(self, label: str) -> list[dict]:
        return self._paginated(
            f"repos/{self.repository}/issues"
            f"?labels={urllib.parse.quote(label)}&state=open&per_page=100"
        )

    def open_issues_assigned_to_agent(self) -> list[dict]:
        items = self._paginated(
            f"repos/{self.repository}/issues?assignee={AGENT_LOGIN}&state=open&per_page=100"
        )
        return [item for item in items if "pull_request" not in item]

    def open_pull_requests_by_agent(self) -> list[dict]:
        items = self._paginated(
            f"repos/{self.repository}/issues?creator={AGENT_LOGIN}&state=open&per_page=100"
        )
        return [item for item in items if "pull_request" in item]

    def is_developer(self, login: str) -> bool:
        """Admin on the repository, the permission the developers' group holds: the workflow's
        token cannot read org groups but reads a collaborator's permission; a failed read holds
        the issue's starts and rounds for that sweep."""
        if login not in self.developers:
            path = f"repos/{self.repository}/collaborators/{login}/permission"
            self.developers[login] = self._api(path)["permission"] == "admin"
        return self.developers[login]

    def timeline(self, number: int) -> list[dict]:
        """The item's timeline. Its cross-references keep only issues and PRs of this repository:
        another repository's PR shares numbers with ours, and one with no source names none."""
        return [
            event for event in self._paginated(
                f"repos/{self.repository}/issues/{number}/timeline?per_page=100")
            if event["event"] != "cross-referenced" or (
                (source := event["source"]["issue"])
                and source["repository"]["full_name"] == self.repository)
        ]

    def head_at(self, number: int, at: datetime) -> str | None:
        """The commit the PR's branch pointed to at `at`, from the repository's push history,
        newest first; a commit's own date says nothing about when it was pushed."""
        branch = self._api(f"repos/{self.repository}/pulls/{number}")["head"]["ref"]
        pushes = self._paginated(
            f"repos/{self.repository}/activity"
            f"?ref={urllib.parse.quote(f'refs/heads/{branch}', safe='')}&per_page=100"
        )
        return next((push["after"] for push in pushes if parse_time(push["timestamp"]) <= at),
                    None)

    def work_by_others(self, number: int, timeline: list[dict]) -> list[str]:
        """Branches and open pull requests that address the issue and are not alice-bot's. A PR
        addresses it when GitHub links it as closing the issue or its description names it
        with "Part of #N" or a closing keyword (root AGENTS.md); one that only mentions it
        does not."""
        owner, repo = self.repository.split("/")
        linked = self._api(
            "graphql", "-f", f"query={LINKED_WORK_QUERY}",
            "-f", f"owner={owner}", "-f", f"repo={repo}", "-F", f"number={number}",
        )["data"]["repository"]["issue"]
        # GitHub sends a null ref for a linked branch since deleted.
        branches = [
            node["ref"]["name"] for node in linked["linkedBranches"]["nodes"] if node["ref"]
        ]
        # Branches an issue-branch bot creates as issue-<n>-<slug> are not linked.
        branches += [
            ref["ref"].removeprefix("refs/heads/") for ref in self._api(
                f"repos/{self.repository}/git/matching-refs/heads/issue-{number}-"
            )
        ]
        pull_requests = referencing_pull_requests(timeline, number)
        for node in linked["closedByPullRequestsReferences"]["nodes"]:
            # A deleted account's PR has a null author.
            author = node["author"]
            pull_requests[node["number"]] = author["login"] if author else "a deleted account"
        return [f"branch {name}" for name in branches] + [
            f"pull request #{pr} by {author}"
            for pr, author in sorted(pull_requests.items())
            if author != AGENT_LOGIN
        ]

    def add_labels(self, number: int, labels: list[str]) -> None:
        fields = [arg for label in labels for arg in ("-f", f"labels[]={label}")]
        self._api("-X", "POST", f"repos/{self.repository}/issues/{number}/labels", *fields)

    def remove_label(self, number: int, label: str) -> None:
        path = f"repos/{self.repository}/issues/{number}/labels/{urllib.parse.quote(label)}"
        self._api("-X", "DELETE", path)

    def comment(self, number: int, body: str) -> None:
        self._api(
            "-X", "POST", f"repos/{self.repository}/issues/{number}/comments", "-f", f"body={body}"
        )

    def reacted(self, comment_id: int) -> bool:
        reactions = self._paginated(
            f"repos/{self.repository}/issues/comments/{comment_id}/reactions")
        return any(
            reaction["user"]["login"] == SWEEP_ACTOR and reaction["content"] == DELIVERED_REACTION
            for reaction in reactions
        )

    def react(self, comment_id: int) -> None:
        self._api(
            "-X", "POST", f"repos/{self.repository}/issues/comments/{comment_id}/reactions",
            "-f", f"content={DELIVERED_REACTION}",
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dry-run", action="store_true", help="print decisions, write nothing")
    parser.add_argument(
        "--repo", default=os.environ.get("GITHUB_REPOSITORY", "example-org/monorepo"),
        help="owner/name of the repository",
    )
    args = parser.parse_args()

    now = datetime.now(timezone.utc)
    if args.dry_run:
        return sweep(GitHub(args.repo), refuse_to_fire, refuse_to_send, now, dry_run=True)
    # ALICE_ROUTINE_FIRE_URL and ALICE_ROUTINE_TOKEN, then _2, _3... for each further account.
    routines = [
        (os.environ[name], os.environ[name.replace("FIRE_URL", "TOKEN")])
        for name in sorted(os.environ)
        if name.startswith("ALICE_ROUTINE_FIRE_URL") and os.environ[name]
    ]
    if not routines or not all(token for _, token in routines):
        print("::error::Each ALICE_ROUTINE_FIRE_URL* needs its ALICE_ROUTINE_TOKEN*")
        return 1
    # The ten-minute slot picks the first routine, so consecutive sweeps start on different
    # accounts.
    fire = Routines(
        [functools.partial(fire_routine, url, token) for url, token in routines],
        first=int(now.timestamp() // 600),
    )
    # Account n owns routine n and signs in from alice-sweep/claude-login-<n>.
    send = Sessions(list(range(1, len(routines) + 1)))
    return sweep(GitHub(args.repo), fire, send, now, dry_run=False)


def refuse_to_fire(text: str) -> str:
    raise AssertionError(f"a dry run never fires ({text})")


def refuse_to_send(session_url: str, text: str) -> None:
    raise AssertionError(f"a dry run never sends ({session_url}: {text})")


if __name__ == "__main__":
    sys.exit(main())
