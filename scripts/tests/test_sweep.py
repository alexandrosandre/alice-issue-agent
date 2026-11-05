#!/usr/bin/env python3
"""Tests for Alice's sweep: which issues it starts, in what order, and how it claims them."""
import importlib.util
import io
import json
import re
import sys
import tempfile
import unittest
import urllib.error
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts/alice/sweep.py"
WORKFLOW = REPO_ROOT / "workflows/alice-sweep.yml"
SPEC = importlib.util.spec_from_file_location("alice_sweep", SCRIPT)
sweep = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = sweep
SPEC.loader.exec_module(sweep)
ASSIGN_SPEC = importlib.util.spec_from_file_location(
    "alice_assign_by_type", REPO_ROOT / "scripts/alice/assign_by_type.py"
)
assign_by_type = importlib.util.module_from_spec(ASSIGN_SPEC)
ASSIGN_SPEC.loader.exec_module(assign_by_type)

NOW = datetime(2026, 10, 26, 12, 0, tzinfo=timezone.utc)
PERSON = {"login": "dev-one", "type": "User"}
OTHER_PERSON = {"login": "dev-two", "type": "User"}
ALICE = {"login": "alice-bot", "type": "User"}
SUPPORT = {"login": "support-one", "type": "User"}
ACTIONS_BOT = {"login": "github-actions[bot]", "type": "Bot"}
APP_BOT = {"login": "assistant-app[bot]", "type": "Bot"}


def at(hours_ago: float) -> str:
    return (NOW - timedelta(hours=hours_ago)).isoformat().replace("+00:00", "Z")


def assigned(actor: dict, hours_ago: float = 2) -> dict:
    return {
        "event": "assigned", "actor": actor, "assignee": ALICE, "created_at": at(hours_ago),
    }


def label_event(kind: str, name: str, actor: dict, hours_ago: float) -> dict:
    return {"event": kind, "label": {"name": name}, "actor": actor, "created_at": at(hours_ago)}


def comment(actor: dict, hours_ago: float, body: str = "Looks good", comment_id: int = 0) -> dict:
    return {
        "event": "commented", "actor": actor, "created_at": at(hours_ago),
        "updated_at": at(hours_ago), "body": body, "id": comment_id,
        "html_url": f"https://github.com/example-org/monorepo/issues/1#c{comment_id}",
    }


def dispatch_comment(hours_ago: float) -> dict:
    body = "Alice started a session on this issue: https://claude.ai/code/s\n\n"
    body += sweep.DISPATCH_MARKER
    return comment(ACTIONS_BOT, hours_ago, body)


def merge_dispatch_comment(hours_ago: float) -> dict:
    body = ("Alice started a session to merge this approved pull request:"
            " https://claude.ai/code/s")
    markers = f"{sweep.MERGE_MARKER}\n{sweep.DISPATCH_MARKER}"
    return comment(ACTIONS_BOT, hours_ago, f"{body}\n\n{markers}")


def review(
    user: dict, hours_ago: float, state: str = "commented", body: str | None = "Rename this",
    commit_id: str = "c0",
) -> dict:
    return {
        "event": "reviewed", "user": user, "state": state, "submitted_at": at(hours_ago),
        "body": body, "commit_id": commit_id,
    }


def commit(
    hours_ago: float, parents: int = 1, email: str = "alice-bot@example.com", sha: str = "c0",
) -> dict:
    return {
        "event": "committed", "sha": sha, "committer": {"date": at(hours_ago), "email": email},
        "parents": [{"sha": f"p{n}"} for n in range(parents)],
    }


def alice_pull_request_reference(number: int, hours_ago: float, issue: int = 1) -> dict:
    return {
        "event": "cross-referenced", "actor": ALICE, "created_at": at(hours_ago),
        "source": {"issue": {
            "number": number, "pull_request": {}, "state": "open", "user": ALICE,
            "body": f"Fixes #{issue}",
        }},
    }


def item(
    number: int, labels=(), created_hours_ago: float = 48, pull_request: bool = False,
    assignees=(ALICE,), author: dict | None = None,
):
    result = {
        "number": number,
        "labels": [{"name": name} for name in labels],
        "created_at": at(created_hours_ago),
        "updated_at": at(2),
        "assignees": list(assignees),
        "user": author or OTHER_PERSON,
    }
    if pull_request:
        result["pull_request"] = {}
        result["body"] = "Fixes #1"
    return result


OWNER = {"login": "dev-lead", "type": "User"}


def handoff_request(actor: dict, reviewer: dict, hours_ago: float) -> dict:
    return {"event": "review_requested", "actor": actor, "requested_reviewer": reviewer,
            "created_at": at(hours_ago)}


def withdrawal(actor: dict, reviewer: dict, hours_ago: float) -> dict:
    return {**handoff_request(actor, reviewer, hours_ago), "event": "review_request_removed"}


def evaluate(issue: dict, timeline: list[dict], others=()):
    return sweep.evaluate_issue(issue, timeline, lambda: list(others), NOW)


class FakeGitHub:
    """In-memory repository that records every write."""

    def __init__(self, items: list[dict], timelines: dict[int, list[dict]], others=None):
        self.items = {entry["number"]: entry for entry in items}
        self.timelines = timelines
        self.others = others or {}
        self.writes: list[tuple] = []
        self.reactions: set[int] = set()

    def is_developer(self, login):
        return login in {"dev-lead", PERSON["login"], OTHER_PERSON["login"]}

    def open_items_labeled(self, label):
        return [
            entry for entry in self.items.values()
            if label in {name["name"] for name in entry["labels"]}
        ]

    def open_issues_assigned_to_agent(self):
        return [
            entry for entry in self.items.values()
            if "pull_request" not in entry and any(
                event["event"] == "assigned" for event in self.timelines[entry["number"]]
            )
        ]

    def open_pull_requests_by_agent(self):
        return [entry for entry in self.items.values() if "pull_request" in entry]

    def timeline(self, number):
        return self.timelines.get(number, [])

    def head_at(self, _number, _at):
        return "c0"

    def work_by_others(self, number, _timeline):
        return self.others.get(number, [])

    def add_labels(self, number, labels):
        self.writes.append(("add", number, tuple(labels)))

    def remove_label(self, number, label):
        self.writes.append(("remove", number, label))

    def comment(self, number, body):
        self.writes.append(("comment", number, body))

    def reacted(self, comment_id):
        return comment_id in self.reactions

    def react(self, comment_id):
        self.reactions.add(comment_id)
        self.writes.append(("react", comment_id))


def run_sweep(github: FakeGitHub, fire=None, dry_run=False, send=None, reviewers=False):
    """Runs a sweep; the reviewers line of each text is dropped unless `reviewers` asks for it,
    since most tests are about which round starts, not who reviews it."""
    lines: list[str] = []
    fired: list[str] = []

    def shown(text):
        return text if reviewers else re.sub(r"\nReviewers: [^\n]*", "", text)

    def default_fire(text):
        fired.append(shown(text))
        return f"https://claude.ai/code/session_{len(fired)}"

    def default_send(session_url, text):
        lines.append(f"sent {shown(text)!r} into {session_url}")

    code = sweep.sweep(
        github, fire or default_fire, send or default_send, NOW, dry_run, log=lines.append)
    return code, lines, fired


class IssueSelectionTests(unittest.TestCase):
    """Which issues assigned to alice-bot the sweep picks, and why it skips the others."""

    def test_picks_a_quiet_issue_a_person_assigned(self):
        """A person's assignment on an issue quiet for 5 minutes starts a session."""
        decision = evaluate(item(1), [assigned(PERSON)])
        self.assertTrue(decision.picked, decision.reason)

    def test_counts_the_triage_step_but_not_alice_or_other_bots(self):
        """Only a person or triage's assignment step can hand Alice an issue (D22)."""
        self.assertTrue(evaluate(item(1), [assigned(ACTIONS_BOT)]).picked)
        self.assertFalse(evaluate(item(1), [assigned(ALICE)]).picked)
        self.assertFalse(evaluate(item(1), [assigned(APP_BOT)]).picked)

    def test_skip_alice_and_a_running_session_beat_alice_continue(self):
        """alice-continue never overrides skip-alice or alice-working."""
        for blocking in ("skip-alice", "alice-working"):
            timeline = [
                assigned(PERSON),
                label_event("labeled", "alice-continue", PERSON, 1),
                label_event("labeled", blocking, PERSON, 1),
            ]
            decision = evaluate(item(1, labels=("alice-continue", blocking)), timeline)
            self.assertFalse(decision.picked, blocking)

    def test_skip_alice_lifted_only_by_a_person(self):
        """skip-alice still counts after Alice removes it, and stops counting when a person does."""
        added = label_event("labeled", "skip-alice", PERSON, 5)
        by_alice = [assigned(PERSON), added, label_event("unlabeled", "skip-alice", ALICE, 1)]
        by_person = [assigned(PERSON), added, label_event("unlabeled", "skip-alice", PERSON, 1)]
        self.assertFalse(evaluate(item(1), by_alice).picked)
        self.assertTrue(evaluate(item(1), by_person).picked)

    def test_done_and_stalled_resume_only_on_a_persons_continue_or_restart(self):
        """A done or stalled issue waits until a person, not Alice or a bot, adds alice-continue
        or alice-restart; only alice-restart tells the session to start over."""
        for held in ("alice-done", "alice-stalled"):
            base = [assigned(PERSON), label_event("labeled", held, ALICE, 5)]
            for signal in ("alice-continue", "alice-restart"):
                labels = (held, signal)
                for actor, expected in ((PERSON, True), (ALICE, False), (APP_BOT, False)):
                    timeline = base + [label_event("labeled", signal, actor, 1)]
                    decision = evaluate(item(1, labels=labels), timeline)
                    self.assertEqual(decision.picked, expected, (held, signal, actor["login"]))
                    if expected:
                        self.assertEqual(
                            decision.subject.endswith("start over"), signal == "alice-restart")
            self.assertFalse(evaluate(item(1, labels=(held,)), base).picked)

    def test_status_labels_are_alices_so_removing_them_starts_nothing(self):
        """A person removing alice-done or alice-stalled does not restart her: the status labels
        are Alice's and the sweep's, and alice-continue or alice-restart are the requests."""
        for held, setter in (("alice-done", ALICE), ("alice-stalled", ACTIONS_BOT)):
            timeline = [assigned(PERSON), label_event("labeled", held, setter, 5),
                        label_event("unlabeled", held, PERSON, 1)]
            self.assertFalse(evaluate(item(1), timeline).picked, held)

    def test_a_resume_request_put_back_after_a_refused_start_still_counts(self):
        """The sweep's own undo of a refused claim keeps the person's alice-continue alive."""
        timeline = [
            assigned(PERSON),
            label_event("labeled", "alice-done", ALICE, 6),
            label_event("labeled", "alice-continue", PERSON, 5),
            label_event("labeled", "alice-working", ACTIONS_BOT, 4),
            label_event("unlabeled", "alice-continue", ACTIONS_BOT, 4),
            label_event("unlabeled", "alice-done", ACTIONS_BOT, 4),
            label_event("labeled", "alice-continue", ACTIONS_BOT, 4),
            label_event("labeled", "alice-done", ACTIONS_BOT, 4),
            label_event("unlabeled", "alice-working", ACTIONS_BOT, 4),
        ]
        decision = evaluate(item(1, labels=("alice-done", "alice-continue")), timeline)
        self.assertTrue(decision.picked, decision.reason)

    def test_waits_5_minutes_after_the_latest_activity(self):
        """A comment, assignment or edit in the last 5 minutes holds the issue back."""
        recent_comment = [assigned(PERSON), comment(PERSON, 0.05)]
        self.assertFalse(evaluate(item(1), recent_comment).picked)
        self.assertFalse(evaluate(item(1), [assigned(PERSON, hours_ago=0.07)]).picked)
        edited = item(1)
        edited["updated_at"] = at(0.05)
        self.assertFalse(evaluate(edited, [assigned(PERSON)]).picked)
        self.assertTrue(evaluate(item(1), [assigned(PERSON), comment(PERSON, 0.1)]).picked)
        self.assertTrue(evaluate(item(1), [assigned(PERSON, hours_ago=0.1)]).picked)

    def test_someone_elses_branch_or_pull_request_blocks_and_is_checked_last(self):
        """Other people's linked work blocks the issue, and is only looked up when it decides."""
        blocked = evaluate(item(1), [assigned(PERSON)], others=["pull request #7 by dev-one"])
        self.assertFalse(blocked.picked)

        def must_not_be_called():
            raise AssertionError("looked up linked work for an issue skipped earlier")

        sweep.evaluate_issue(item(1, labels=("skip-alice",)), [assigned(PERSON)],
                             must_not_be_called, NOW)

    def test_alice_s_own_pull_requests_are_not_someone_elses_work(self):
        """Only open pull requests by others count as someone else being on the issue."""
        timeline = [alice_pull_request_reference(9, 1)]
        timeline.append({
            "event": "cross-referenced", "actor": PERSON, "created_at": at(1),
            "source": {"issue": {
                "number": 8, "pull_request": {}, "state": "closed", "user": PERSON,
            }},
        })
        self.assertEqual(sweep.referencing_pull_requests(timeline, 1), {9: "alice-bot"})


class RedispatchTests(unittest.TestCase):
    """An item the sweep already started runs again only on a person's signal (D22)."""

    def started_before(self) -> list[dict]:
        return [
            assigned(PERSON, hours_ago=30),
            label_event("labeled", "alice-working", ACTIONS_BOT, 20),
            dispatch_comment(20),
            label_event("unlabeled", "alice-working", ALICE, 10),
        ]

    def test_a_session_dropping_alice_working_does_not_restart_itself(self):
        """alice-working removed without alice-done never makes a started issue pickable."""
        self.assertFalse(evaluate(item(1), self.started_before()).picked)

    def test_a_persons_resume_signal_after_the_start_picks_it_again(self):
        """A person's alice-continue or alice-restart reruns it."""
        signals = {
            signal: ((signal,), [label_event("labeled", signal, PERSON, 1)])
            for signal in ("alice-continue", "alice-restart")
        }
        for name, (labels, events) in signals.items():
            decision = evaluate(item(1, labels=labels), self.started_before() + events)
            self.assertTrue(decision.picked, f"{name}: {decision.reason}")
        bot_continue = [label_event("labeled", "alice-continue", ALICE, 1)]
        timeline = self.started_before() + bot_continue
        decision = evaluate(item(1, labels=("alice-continue",)), timeline)
        self.assertFalse(decision.picked)

    def test_a_signal_older_than_the_start_was_already_used(self):
        """A person's alice-continue from before the last start does not start another run."""
        timeline = [
            assigned(PERSON, hours_ago=30),
            label_event("labeled", "alice-continue", PERSON, 25),
            dispatch_comment(20),
        ]
        self.assertFalse(evaluate(item(1, labels=("alice-continue",)), timeline).picked)

    def test_a_pull_request_restarts_only_on_a_review_newer_than_its_last_round(self):
        """A review round is dispatched once per person review, even if Alice never answered."""
        pull_request = item(5, pull_request=True)
        same_review = [commit(30), review(PERSON, 20), dispatch_comment(19)]
        new_review = same_review + [review(OTHER_PERSON, 1)]
        self.assertFalse(sweep.evaluate_review_round(pull_request, same_review, NOW).picked)
        self.assertTrue(sweep.evaluate_review_round(pull_request, new_review, NOW).picked)

    def test_every_start_comment_marks_the_dispatch(self):
        """Both the started and the unconfirmed comment count as a dispatch for later sweeps."""
        github = FakeGitHub([item(1)], {1: [assigned(PERSON)]})
        run_sweep(github)

        def time_out(_text):
            raise sweep.FireUnconfirmed("timed out")

        unconfirmed = FakeGitHub([item(2)], {2: [assigned(PERSON)]})
        run_sweep(unconfirmed, fire=time_out)
        for fake in (github, unconfirmed):
            body = [write[2] for write in fake.writes if write[0] == "comment"][-1]
            self.assertIsNotNone(sweep.latest_dispatch([comment(ACTIONS_BOT, 0, body)]))


class SessionResumeTests(unittest.TestCase):
    """A round goes into the issue's latest session; a restart or an unreachable one starts a new
    session (D38)."""

    def started(self, hours_ago: float, session: str, actor: dict | None = None) -> dict:
        body = ("Alice started a session on this issue:"
                f" https://claude.ai/code/{session}\n\n")
        return comment(actor or ACTIONS_BOT, hours_ago, body + sweep.DISPATCH_MARKER)

    def review_round(self, issue_labels=(), issue_events=(), pr_events=()):
        """Alice's issue #1 with her PR #20, whose latest word is a person's review."""
        issue = item(1, labels=("alice-done",) + tuple(issue_labels), assignees=(ALICE, PERSON))
        timelines = {
            1: [assigned(PERSON, 30), self.started(29, "session_first"),
                alice_pull_request_reference(20, 28), *issue_events],
            20: [commit(27), *pr_events, review(PERSON, 1)],
        }
        return FakeGitHub([issue, item(20, pull_request=True)], timelines)

    def test_a_round_goes_into_the_latest_session_named_on_the_issue_or_its_pr(self):
        """The newest start comment across the issue and her PR names the session that continues;
        the comment says she continues there."""
        github = self.review_round(pr_events=[self.started(10, "session_second")])
        _, lines, fired = run_sweep(github)
        self.assertEqual(fired, [])
        self.assertIn(
            "sent 'New routine payload from the sweep: Review-comment round on pull"
            " request #20\\n\\nIt continues this session (alice skill, Resumed round).' into"
            " https://claude.ai/code/session_second", lines)
        body = github.writes[-1][2]
        self.assertIn("Alice continues in her session on the review comments:"
                      " https://claude.ai/code/session_second", body)
        self.assertEqual(sweep.latest_session([[comment(ACTIONS_BOT, 0, body)]]),
                         "https://claude.ai/code/session_second")

    def test_only_the_sweeps_own_start_comments_name_the_session(self):
        """A person's comment shaped like a start comment cannot send a round elsewhere."""
        forged = self.started(5, "session_elsewhere", actor=PERSON)
        github = self.review_round(pr_events=[forged])
        _, lines, _ = run_sweep(github)
        self.assertTrue(any(line.endswith("into https://claude.ai/code/session_first")
                            for line in lines), lines)

    def test_a_restart_starts_a_new_session_on_the_issue_or_the_pr(self):
        """alice-restart from a person never resumes, whether on the issue or on her PR."""
        restart_on_issue = FakeGitHub([item(1, labels=("alice-done", "alice-restart"))], {1: [
            assigned(PERSON, 30), self.started(29, "session_first"),
            label_event("labeled", "alice-done", ALICE, 20),
            label_event("labeled", "alice-restart", PERSON, 1),
        ]})
        restart_on_pr = self.review_round()
        restart_on_pr.items[20]["labels"] = [{"name": "alice-restart"}]
        restart_on_pr.timelines[20].append(label_event("labeled", "alice-restart", PERSON, 0.5))
        for name, github, text in (("issue", restart_on_issue, "Issue #1: start over"),
                                   ("pull request", restart_on_pr,
                                    "Review-comment round on pull request #20")):
            _, lines, fired = run_sweep(github)
            self.assertEqual(fired, [text], f"{name}: {lines}")
            self.assertFalse([line for line in lines if line.startswith("sent")], name)

    def test_an_unconfirmed_newest_start_starts_a_new_session(self):
        """After an unconfirmed start the session holding the latest work is unknown, so the round
        is not sent into an older one."""
        unconfirmed = comment(ACTIONS_BOT, 10, "Alice's session may not have started: ...\n\n"
                              + sweep.DISPATCH_MARKER)
        _, lines, fired = run_sweep(self.review_round(pr_events=[unconfirmed]))
        self.assertEqual(fired, ["Review-comment round on pull request #20"], lines)

    def test_a_stalled_session_takes_the_round_after_alice_continue(self):
        """Most stalls (a usage limit, a turn that ended early, a reclaimed machine) leave a session
        that resumes with its context, so a stall does not start a new one."""
        stalled = self.review_round()
        stalled.items[20]["labels"] = [{"name": "alice-stalled"}, {"name": "alice-continue"}]
        stalled.timelines[20] += [
            label_event("labeled", "alice-stalled", ACTIONS_BOT, 0.8),
            label_event("labeled", "alice-continue", PERSON, 0.5),
        ]
        _, lines, fired = run_sweep(stalled)
        self.assertEqual(fired, [], lines)
        self.assertTrue(any(line.endswith("into https://claude.ai/code/session_first")
                            for line in lines), lines)

    def test_an_unreachable_session_leaves_the_round_to_a_new_session(self):
        """An archived session, or no account signed in, starts a new session and warns."""
        def unreachable(_session_url, _text):
            raise sweep.SessionUnreachable("cloud session is archived")

        github = self.review_round()
        _, lines, fired = run_sweep(github, send=unreachable)
        self.assertEqual(fired, ["Review-comment round on pull request #20"])
        self.assertTrue(any("::warning::#20 her session" in line and "archived" in line
                            for line in lines), lines)
        self.assertIn("Alice started a session on the review comments:", github.writes[-1][2])

    def test_an_unconfirmed_send_keeps_the_claim_and_starts_nothing_else(self):
        """No answer from the send may hide a delivered round, like an unconfirmed start."""
        def no_answer(_session_url, _text):
            raise sweep.SendUnconfirmed("no answer from claude -p --cloud: timed out")

        github = self.review_round()
        code, _, fired = run_sweep(github, send=no_answer)
        self.assertEqual((code, fired), (0, []))
        self.assertNotIn(("remove", 20, "alice-working"), github.writes)
        self.assertIn("may not have received this round", github.writes[-1][2])


class TriageAssignmentTests(unittest.TestCase):
    """Which newly triaged issues the fixed triage step assigns to alice-bot (D13, D17)."""

    def issue(self, labels, author=None):
        return {"user": author or PERSON, "labels": [{"name": name} for name in labels]}

    def test_assigns_bug_enhancement_and_chore_issues(self):
        """An issue typed bug, enhancement or chore is Alice's, whatever else it is labeled."""
        for labels in (["Bug", "P1"], ["Enhancement"], ["Chore"], ["Bug", "Frontend"]):
            self.assertIsNone(assign_by_type.refusal(self.issue(labels)), labels)

    def test_off_labels_and_untyped_issues_stay_unassigned(self):
        """Exclusions beat inclusions, and an issue without a type label is off."""
        for labels in (["Bug", "Epic"], ["Bug", "Blocked"], ["Enhancement", "skip-alice"],
                       ["Proposal"], []):
            self.assertIsNotNone(assign_by_type.refusal(self.issue(labels)), labels)

    def test_an_issue_alice_or_a_bot_opens_never_becomes_hers(self):
        """Alice cannot hand herself work by opening an issue, and neither can a bot."""
        for author in (ALICE, APP_BOT, ACTIONS_BOT):
            self.assertIsNotNone(assign_by_type.refusal(self.issue(["Bug"], author)))


class ReviewRoundTests(unittest.TestCase):
    """When a person's review on one of alice-bot's pull requests starts a session (D31)."""

    def test_a_quiet_unanswered_person_review_starts_a_round(self):
        """A person's review newer than Alice's last push or reply, quiet 5 minutes, is picked."""
        timeline = [commit(5), review(PERSON, 1, "changes_requested")]
        decision = sweep.evaluate_review_round(item(5, pull_request=True), timeline, NOW)
        self.assertTrue(decision.picked, decision.reason)
        self.assertIn("pull request #5", decision.fire_text)

    def test_her_pull_request_that_declares_no_issue_takes_no_round(self):
        """A PR of hers whose description lost its issue line, edited by hand say, is no issue's
        PR, so no running issue session would hold a round on its branch: it waits for the line."""
        pull_request = item(5, pull_request=True)
        pull_request["body"] = "Follow-up to #1"
        timeline = [commit(5), review(PERSON, 1, "changes_requested")]
        decision = sweep.evaluate_review_round(pull_request, timeline, NOW)
        self.assertFalse(decision.picked)
        self.assertIn("declares no issue", decision.reason)

    def test_bots_approvals_answered_and_fresh_reviews_do_not_start_a_round(self):
        """Bot reviews, approvals, answered reviews and reviews under 5 minutes old wait."""
        cases = {
            "bot review": [commit(5), review(APP_BOT, 1)],
            "approval": [commit(5), review(PERSON, 1, "approved")],
            "answered": [review(PERSON, 2), comment(ALICE, 1)],
            "fresh": [commit(5), review(PERSON, 0.05)],
            "claimed": [commit(5), review(PERSON, 1)],
        }
        for name, timeline in cases.items():
            labels = ("alice-working",) if name == "claimed" else ()
            pull_request = item(5, labels=labels, pull_request=True)
            decision = sweep.evaluate_review_round(pull_request, timeline, NOW)
            self.assertFalse(decision.picked, name)

    def test_a_stalled_round_resumes_on_a_persons_signal_or_a_new_review(self):
        """After a stalled round, a person's alice-continue starts it again; without one, or when
        a person only removes alice-stalled, it waits; a later review starts a round by itself,
        resumed or not."""
        stalled = [
            commit(30), review(PERSON, 28), dispatch_comment(27),
            label_event("labeled", "alice-stalled", ACTIONS_BOT, 3),
        ]
        cases = {
            "no signal": (stalled, ("alice-stalled",), False),
            "alice-continue": (stalled + [label_event("labeled", "alice-continue", PERSON, 1)],
                               ("alice-stalled", "alice-continue"), True),
            "alice-stalled removed": (
                stalled + [label_event("unlabeled", "alice-stalled", PERSON, 1)], (), False),
            "new review": (stalled + [review(PERSON, 1)], ("alice-stalled",), True),
            "new review after a resumed round": (
                stalled + [label_event("labeled", "alice-continue", PERSON, 20),
                           label_event("unlabeled", "alice-stalled", ACTIONS_BOT, 19),
                           label_event("unlabeled", "alice-continue", ACTIONS_BOT, 19),
                           dispatch_comment(19), commit(18), comment(ALICE, 18),
                           review(PERSON, 1, "changes_requested")],
                (), True),
        }
        for name, (timeline, labels, picked) in cases.items():
            decision = sweep.evaluate_review_round(
                item(5, labels=labels, pull_request=True), timeline, NOW)
            self.assertEqual(decision.picked, picked, f"{name}: {decision.reason}")

    def test_a_persons_alice_continue_on_the_pr_starts_a_round_whatever_its_reviews_say(self):
        """alice-continue added by a person on her PR starts a round after a person pushed to it,
        or with no review at all; added by Alice or a bot, or before the last round, it does not."""
        def continue_by(actor):
            return label_event("labeled", "alice-continue", actor, 1)

        pushed = [commit(5), review(PERSON, 4), commit(3, email="dev-one@example.com")]
        cases = {
            "after a person's push": (pushed + [continue_by(PERSON)], True),
            "no review": ([commit(5), continue_by(PERSON)], True),
            "added by Alice": (pushed + [continue_by(ALICE)], False),
            "added before the last round": (
                [commit(5), label_event("labeled", "alice-continue", PERSON, 3),
                 dispatch_comment(2)], False),
        }
        for name, (timeline, picked) in cases.items():
            decision = sweep.evaluate_review_round(
                item(5, labels=("alice-continue",), pull_request=True), timeline, NOW)
            self.assertEqual(decision.picked, picked, f"{name}: {decision.reason}")
        fresh = [commit(5), label_event("labeled", "alice-continue", PERSON, 0.05)]
        self.assertFalse(sweep.evaluate_review_round(
            item(5, labels=("alice-continue",), pull_request=True), fresh, NOW).picked)

    def test_commits_github_writes_are_not_an_answer_to_the_review(self):
        """Updating the branch after a review, by merge or by rebase, leaves it unanswered."""
        for name, update in {
            "merge": commit(1, parents=2),
            "rebase": commit(1, email=sweep.GITHUB_COMMITTER_EMAIL),
        }.items():
            timeline = [commit(5), review(PERSON, 2), update]
            decision = sweep.evaluate_review_round(item(5, pull_request=True), timeline, NOW)
            self.assertTrue(decision.picked, f"{name}: {decision.reason}")


class MentionTests(unittest.TestCase):
    """A person's @alice-bot on her issue or PR asks her to act, like alice-continue."""

    def handed_back(self, *events):
        return [assigned(PERSON, 30), dispatch_comment(20), comment(ALICE, 10, "Findings")] + list(
            events)

    def test_a_persons_mention_after_her_hand_back_resumes_the_issue(self):
        """Mentioning her after she handed back starts her again, as alice-continue would."""
        timeline = self.handed_back(comment(PERSON, 1, "@alice-bot please also cover the export", 7))
        decision = evaluate(item(1, labels=("alice-done",)), timeline)
        self.assertTrue(decision.picked, decision.reason)
        self.assertIn("resume requested", decision.reason)

    def test_only_a_persons_new_mention_of_her_counts(self):
        """Her own or a bot's mention, one before her latest start, and a longer login start
        nothing."""
        cases = {
            "her own": comment(ALICE, 1, "@alice-bot note to self", 7),
            "a bot's": comment(APP_BOT, 1, "@alice-bot see the review", 7),
            "before her start": comment(PERSON, 25, "@alice-bot also the export?", 7),
            "another login": comment(PERSON, 1, "cc @alice-bot-bot", 7),
        }
        for name, event in cases.items():
            decision = evaluate(item(1, labels=("alice-done",)), self.handed_back(event))
            self.assertFalse(decision.picked, name)

    def test_an_edited_comment_does_not_count_as_a_mention(self):
        """The timeline names a comment's author, not who edited it, and alice-bot may edit any
        comment: an edit that adds her name must not let her resume herself (D22)."""
        edited = comment(PERSON, 1, "@alice-bot do this instead", 7)
        edited["updated_at"] = at(0.5)
        decision = evaluate(item(1, labels=("alice-done",)), self.handed_back(edited))
        self.assertFalse(decision.picked, decision.reason)

    def test_an_edited_lgtm_comment_is_no_go(self):
        """alice-bot may edit a reviewer's comment into "LGTM"; an edited comment never merges."""
        edited = comment(PERSON, 1, "LGTM", 7)
        edited["updated_at"] = at(0.5)
        decision = sweep.evaluate_review_round(
            item(20, pull_request=True), [commit(5, sha="c1"), edited], NOW,
            reviewers={PERSON["login"]}, head_at=lambda at: "c1")
        self.assertNotIn("merge round", decision.reason)

    def test_an_approval_outranks_only_its_own_reviewers_earlier_mention(self):
        """Another person's request before the reviewer's approval is answered before merging."""
        timeline = [
            commit(5, sha="c1"), comment(OTHER_PERSON, 2, "@alice-bot handle the null case", 7),
            review(PERSON, 1, "approved", None, "c1"),
        ]
        decision = sweep.evaluate_review_round(
            item(20, pull_request=True), timeline, NOW, reviewers={PERSON["login"]})
        self.assertTrue(decision.picked, decision.reason)
        self.assertIn("review-comment round", decision.reason)

    def test_a_mention_she_was_sent_mid_run_starts_nothing_after_she_hands_back(self):
        """A mention the sweep delivered into her running session was in front of her; one made
        just before her hand-over and never delivered still resumes her."""
        timeline = self.handed_back(comment(PERSON, 15, "@alice-bot also cover the export", 7))
        delivered = sweep.evaluate_issue(
            item(1, labels=("alice-done",)), timeline, lambda: [], NOW, delivered={7})
        self.assertFalse(delivered.picked, delivered.reason)
        self.assertTrue(evaluate(item(1, labels=("alice-done",)), timeline).picked)

    def test_an_lgtm_that_mentions_her_is_an_approval_and_outranks_earlier_mentions(self):
        """"@alice-bot LGTM" from the reviewer starts a merge round, and so does an approval that
        follows a mention."""
        lgtm = [commit(5, sha="c1"), comment(PERSON, 1, "@alice-bot LGTM", 7)]
        decision = sweep.evaluate_review_round(
            item(20, pull_request=True), lgtm, NOW, reviewers={PERSON["login"]},
            head_at=lambda at: "c1")
        self.assertTrue(decision.picked, decision.reason)
        self.assertIn("merge round", decision.reason)
        after_mention = [
            commit(5, sha="c1"), comment(PERSON, 2, "@alice-bot rename it", 7),
            commit(1.5, sha="c2"), review(PERSON, 1, "approved", None, "c2"),
        ]
        decision = sweep.evaluate_review_round(
            item(20, pull_request=True), after_mention, NOW, reviewers={PERSON["login"]})
        self.assertIn("merge round", decision.reason)

    def test_a_mention_in_her_pull_requests_conversation_starts_a_round(self):
        """A plain comment that mentions her on her PR starts a round without a review."""
        timeline = [commit(5), comment(PERSON, 1, "@alice-bot rename the helper", 7)]
        decision = sweep.evaluate_review_round(item(20, pull_request=True), timeline, NOW)
        self.assertTrue(decision.picked, decision.reason)
        self.assertIn("resume requested", decision.reason)

    def test_a_mention_while_she_runs_is_sent_into_her_session_once(self):
        """The running session gets the mention as a message; the sweep's reaction keeps the
        next sweep from sending it again."""
        issue = item(1, labels=("alice-working",))
        timelines = {1: [
            assigned(PERSON, 3), label_event("labeled", "alice-working", ACTIONS_BOT, 1),
            dispatch_comment(1), comment(PERSON, 0.5, "@alice-bot also check the export", 42),
        ]}
        github = FakeGitHub([issue], timelines)
        _, lines, fired = run_sweep(github)
        self.assertEqual(fired, [])
        self.assertTrue(any(line.startswith("sent 'New request from the sweep: dev-one mentioned")
                            for line in lines), lines)
        self.assertIn(("react", 42), github.writes)
        _, again, _ = run_sweep(github)
        self.assertFalse(any(line.startswith("sent ") for line in again), again)

    def test_a_mention_waits_the_quiet_period_before_reaching_her_session(self):
        """A person may still be writing, so a fresh mention is sent on a later sweep."""
        issue = item(1, labels=("alice-working",))
        timelines = {1: [
            assigned(PERSON, 3), label_event("labeled", "alice-working", ACTIONS_BOT, 1),
            dispatch_comment(1), comment(PERSON, 0.03, "@alice-bot also check the export", 42),
        ]}
        github = FakeGitHub([issue], timelines)
        _, lines, _ = run_sweep(github)
        self.assertFalse(any(line.startswith("sent ") for line in lines), lines)


class MentionDeliveryTests(unittest.TestCase):
    """How the sweep hands a mention to her running session, and what it does when it cannot."""

    def running_round(self):
        pull_request = item(20, labels=("alice-working",), pull_request=True)
        pull_request["body"] = "Fixes #1\nPart of #2"
        timelines = {
            20: [commit(3), label_event("labeled", "alice-working", ACTIONS_BOT, 1),
                 dispatch_comment(1)],
            1: [assigned(PERSON, 5), alice_pull_request_reference(20, 3),
                comment(PERSON, 0.5, "@alice-bot also check the export", 9)],
            2: [comment(PERSON, 0.5, "@alice-bot see the epic", 8)],
        }
        return FakeGitHub([item(1), pull_request], timelines)

    def test_a_mention_on_her_prs_issue_reaches_the_round_but_another_issues_does_not(self):
        """A round on her PR runs in its issue's session; an issue the PR names that is not hers
        (an epic) is left alone."""
        github = self.running_round()
        _, _, fired = run_sweep(github)
        self.assertIn(("react", 9), github.writes)
        self.assertNotIn(("react", 8), github.writes)
        self.assertEqual(fired, [])

    def test_an_unconfirmed_send_is_marked_so_it_is_not_sent_twice(self):
        """A send that got no answer may have arrived, so it is marked as dispatch does."""
        github = self.running_round()

        def unconfirmed(_session, _text):
            raise sweep.SendUnconfirmed("no answer")

        run_sweep(github, send=unconfirmed)
        self.assertIn(("react", 9), github.writes)

    def test_a_delivered_mention_starts_no_round_on_her_pr_after_it_ends(self):
        """A mention passed into a round is not a new request once the round ends."""
        timeline = [commit(5), comment(PERSON, 1, "@alice-bot rename the helper", 7)]
        decision = sweep.evaluate_review_round(
            item(20, pull_request=True), timeline, NOW, delivered={7})
        self.assertFalse(decision.picked, decision.reason)

    def test_unreadable_reactions_hold_the_mention_instead_of_starting_a_round(self):
        """Without the reactions, a mention could be one she already has: it waits."""
        issue = item(1, labels=("alice-done",))
        timelines = {1: [assigned(PERSON, 30), dispatch_comment(20), comment(ALICE, 10, "Done"),
                         comment(PERSON, 1, "@alice-bot also the export", 7)]}
        github = FakeGitHub([issue], timelines)

        def unreadable(_comment_id):
            raise RuntimeError("gh api failed")

        github.reacted = unreadable
        _, lines, fired = run_sweep(github)
        self.assertEqual(fired, [])
        self.assertTrue(any("reactions are unreadable" in line for line in lines), lines)


class DeliveryMarkTests(unittest.TestCase):
    """Which reaction on a comment means the sweep delivered it (GitHub.reacted)."""

    def test_only_the_sweeps_rocket_marks_a_delivery(self):
        """Other automation reacts as the same login with other emoji, and a person may add a rocket
        of their own: neither marks a mention as delivered."""
        github = sweep.GitHub("example-org/monorepo")
        bot = {"login": "github-actions[bot]"}
        cases = {
            "the sweep's rocket": ([{"user": bot, "content": "rocket"}], True),
            "other automation's eyes": ([{"user": bot, "content": "eyes"}], False),
            "a person's rocket": ([{"user": {"login": "dev-one"}, "content": "rocket"}], False),
        }
        for name, (reactions, expected) in cases.items():
            github._paginated = lambda _path, r=reactions: r  # pylint: disable=protected-access
            self.assertEqual(github.reacted(1), expected, name)


class MergeRoundTests(unittest.TestCase):
    """When the approval of the person reviewing an issue's work makes Alice merge her PR (D35)."""

    reviewers = {PERSON["login"]}

    def evaluate(self, timeline, labels=(), head_at=lambda at: "c1"):
        return sweep.evaluate_review_round(
            item(5, labels=labels, pull_request=True), timeline, NOW, reviewers=self.reviewers,
            head_at=head_at)

    def test_the_reviewers_approval_or_plain_lgtm_starts_a_merge_round(self):
        """An approval, a review saying LGTM, or a conversation comment saying LGTM, quiet for 5
        minutes, starts a merge round on the commit it was given on."""
        cases = {
            "approval": [commit(5, sha="c1"), review(PERSON, 1, "approved", None, "c1")],
            "lgtm review": [commit(5, sha="c1"), review(PERSON, 1, "commented", "LGTM", "c1")],
            "lgtm comment": [commit(5, sha="c1"), comment(PERSON, 1, "lgtm!")],
            "approval after answered comments": [
                commit(9), review(PERSON, 8), commit(7, sha="c1"), comment(ALICE, 7),
                review(PERSON, 1, "approved", "Thanks", "c1")],
        }
        for name, timeline in cases.items():
            decision = self.evaluate(timeline)
            self.assertTrue(decision.picked, f"{name}: {decision.reason}")
            self.assertIn("Merge round on pull request #5", decision.fire_text, name)
            self.assertIn("at commit c1", decision.fire_text, name)

    def test_other_peoples_approvals_and_lgtms_start_nothing(self):
        """An approval or LGTM from someone who is not the issue's reviewer starts no round of
        either kind."""
        for name, timeline in {
            "approval": [commit(5), review(OTHER_PERSON, 1, "approved")],
            "lgtm review": [commit(5), review(OTHER_PERSON, 1, "commented", "LGTM")],
            "lgtm comment": [commit(5), comment(OTHER_PERSON, 1, "LGTM")],
        }.items():
            self.assertFalse(self.evaluate(timeline).picked, name)

    def test_the_approval_must_be_the_latest_review_and_starts_one_round(self):
        """Review comments after the approval start a review round instead; a fresh approval
        waits 5 minutes; a merge round already started for it is not started again."""
        approval = [commit(5, sha="c1"), review(PERSON, 2, "approved", None, "c1")]
        later_comments = self.evaluate(approval + [review(OTHER_PERSON, 1, "changes_requested")])
        self.assertTrue(later_comments.picked, later_comments.reason)
        self.assertIn("Review-comment round", later_comments.fire_text)
        self.assertFalse(self.evaluate(approval[:1] + [review(PERSON, 0.05, "approved")]).picked)
        self.assertFalse(self.evaluate(approval + [merge_dispatch_comment(1)]).picked)
        resumed = approval + [dispatch_comment(1.5),
                              label_event("labeled", "alice-continue", PERSON, 1)]
        self.assertTrue(self.evaluate(resumed, labels=("alice-continue",)).picked)


    def test_an_lgtm_comment_approves_the_head_its_branch_had_when_written(self):
        """A comment names no commit: it approves the commit the branch's push history shows at
        the comment's time, whatever later pushes or commit dates say."""
        timeline = [commit(5, sha="c1"), comment(PERSON, 1, "LGTM"), commit(9, sha="c2")]
        asked = []

        def head_at(when):
            asked.append(when)
            return "c1"

        decision = self.evaluate(timeline, head_at=head_at)
        self.assertIn("at commit c1", decision.fire_text)
        self.assertEqual(asked, [sweep.parse_time(timeline[1]["created_at"])])
        self.assertFalse(self.evaluate(timeline, head_at=lambda at: None).picked)

    def test_a_comment_after_the_approval_holds_the_merge(self):
        """Any person's comment after the approval, an objection or not, holds the merge until
        the reviewer approves again."""
        approval = [commit(5, sha="c1"), review(PERSON, 2, "approved", None, "c1")]
        self.assertFalse(self.evaluate(approval + [comment(OTHER_PERSON, 1, "Hold on")]).picked)
        again = approval + [comment(OTHER_PERSON, 1.5, "Hold on"),
                            review(PERSON, 1, "approved", None, "c1")]
        self.assertIn("Merge round", self.evaluate(again).fire_text)

    def test_the_approvers_own_earlier_review_does_not_hold_the_merge(self):
        """The reviewer's own comments before their approval are theirs to waive."""
        timeline = [commit(5), review(PERSON, 3), review(PERSON, 1, "approved", None, "c1")]
        self.assertIn("Merge round", self.evaluate(timeline).fire_text)

    def test_only_an_approval_or_a_comment_review_saying_lgtm_is_a_go(self):
        """A review requesting changes is a request for changes whatever its summary says, and a
        dismissed review is no go."""
        requested = self.evaluate([commit(5), review(PERSON, 1, "changes_requested", "LGTM")])
        self.assertTrue(requested.picked, requested.reason)
        self.assertIn("Review-comment round", requested.fire_text)
        self.assertFalse(self.evaluate([commit(5), review(PERSON, 1, "dismissed", "LGTM")]).picked)

    def test_another_persons_unanswered_changes_request_comes_before_the_merge(self):
        """An approval does not merge over another person's review that Alice has not answered:
        that review gets its round first, and once answered the approval merges."""
        unanswered = self.evaluate([commit(5), review(OTHER_PERSON, 3, "changes_requested"),
                                    review(PERSON, 1, "approved", None, "c1")])
        self.assertTrue(unanswered.picked, unanswered.reason)
        self.assertIn("Review-comment round", unanswered.fire_text)
        answered = self.evaluate([commit(5), review(OTHER_PERSON, 4, "changes_requested"),
                                  comment(ALICE, 3), review(PERSON, 1, "approved", None, "c1")])
        self.assertIn("Merge round", answered.fire_text)
        # The review round that answered it does not use up the approval.
        after_round = self.evaluate([
            commit(6), review(OTHER_PERSON, 5, "changes_requested"),
            review(PERSON, 4, "approved", None, "c1"), dispatch_comment(3.5),
            commit(3), comment(ALICE, 3)])
        self.assertIn("Merge round", after_round.fire_text)

    def test_alice_continue_after_an_approval_starts_a_review_round(self):
        """alice-continue asks Alice to carry the PR on, so it never turns into a merge."""
        timeline = [commit(5), review(PERSON, 2, "approved", None, "c1"),
                    label_event("labeled", "alice-continue", PERSON, 1)]
        decision = self.evaluate(timeline, labels=("alice-continue",))
        self.assertTrue(decision.picked, decision.reason)
        self.assertIn("Review-comment round", decision.fire_text)


class SweepTests(unittest.TestCase):
    """Order, limits, stalls and the claim around /fire."""

    def test_order_is_review_rounds_then_priority_then_age(self):
        """Rounds go first, then P0, P1, P2 and unprioritized issues, oldest first within each."""
        issues = [
            item(10, labels=(), created_hours_ago=500),
            item(11, labels=("P2",), created_hours_ago=100),
            item(12, labels=("P1",), created_hours_ago=50),
            item(13, labels=("P1",), created_hours_ago=60),
            item(14, labels=("P0",), created_hours_ago=10),
        ]
        pull_request = item(20, pull_request=True)
        timelines = {entry["number"]: [assigned(PERSON)] for entry in issues}
        timelines[20] = [commit(5), review(PERSON, 1)]
        github = FakeGitHub(issues + [pull_request], timelines)
        _, lines, _ = run_sweep(github, dry_run=True)
        started = [re.match(r"#(\d+)", line).group(1) for line in lines if "would start" in line]
        waiting = [re.match(r"#(\d+)", line).group(1) for line in lines if "waits" in line]
        self.assertEqual(started, ["20", "14", "13"])
        self.assertEqual(waiting, ["12", "11", "10"])

    def test_no_review_round_on_a_pull_request_whose_issue_session_still_runs(self):
        """A review on a PR the issue's running session opened waits for that session to end."""
        issue = item(1, labels=("alice-working",))
        pull_request = item(20, pull_request=True)
        timelines = {
            1: [label_event("labeled", "alice-working", ACTIONS_BOT, 3),
                alice_pull_request_reference(20, 1)],
            20: [commit(1), review(PERSON, 0.5)],
        }
        _, lines, fired = run_sweep(FakeGitHub([issue, pull_request], timelines))
        self.assertEqual(fired, [])
        self.assertTrue(any(line.startswith("#20 pull request skipped") for line in lines), lines)

    def test_the_reviewer_is_one_area_owner_and_never_support(self):
        """The person whose approval merges a PR is the developer assignee who filed its issue,
        else the developer assignee who assigned Alice, so one person holds the review; failing
        both, any developer assignee; with none assigned, the developer who filed it or assigned
        her, never a support assignee."""
        for name, (assignees, author, assigner, approver, picked) in {
            "assignee": ((ALICE, PERSON), OTHER_PERSON, PERSON, PERSON, True),
            "author is not the reviewer": ((ALICE, PERSON), OTHER_PERSON, PERSON, OTHER_PERSON,
                                           False),
            "author when Alice is alone": ((ALICE,), OTHER_PERSON, PERSON, OTHER_PERSON, True),
            "the owner who filed it": ((ALICE, PERSON, OTHER_PERSON), PERSON, OTHER_PERSON,
                                       PERSON, True),
            "not the other owner": ((ALICE, PERSON, OTHER_PERSON), PERSON, OTHER_PERSON,
                                    OTHER_PERSON, False),
            "the owner who assigned her": ((ALICE, PERSON, OTHER_PERSON), SUPPORT, OTHER_PERSON,
                                           OTHER_PERSON, True),
            "not the owner who did not": ((ALICE, PERSON, OTHER_PERSON), SUPPORT, OTHER_PERSON,
                                          PERSON, False),
            "any owner when no one owner settles it": (
                (ALICE, PERSON, OTHER_PERSON), SUPPORT, ACTIONS_BOT, PERSON, True),
            "the developer who filed it when none is assigned": (
                (ALICE, SUPPORT), OTHER_PERSON, ACTIONS_BOT, OTHER_PERSON, True),
            "the developer who assigned her when none is assigned": (
                (ALICE, SUPPORT), SUPPORT, PERSON, PERSON, True),
            "never support when no developer is assigned": (
                (ALICE, SUPPORT), OTHER_PERSON, ACTIONS_BOT, SUPPORT, False),
            "nobody when no developer filed, assigned or holds it": (
                (ALICE,), SUPPORT, ACTIONS_BOT, SUPPORT, False),
            "not a support assignee's later reassignment": (
                (ALICE, PERSON, OTHER_PERSON), SUPPORT, (OTHER_PERSON, SUPPORT), PERSON, False),
            "never support in an owner's place": (
                (ALICE, PERSON, SUPPORT), OTHER_PERSON, ACTIONS_BOT, SUPPORT, False),
        }.items():
            issue = item(1, labels=("alice-done",), assignees=assignees, author=author)
            timelines = {
                1: [*(assigned(actor, 30 - index) for index, actor in enumerate(
                        assigner if isinstance(assigner, tuple) else (assigner,))),
                    alice_pull_request_reference(20, 20)],
                20: [commit(5), review(approver, 1, "approved")],
            }
            github = FakeGitHub([issue, item(20, pull_request=True)], timelines)
            _, lines, _ = run_sweep(github, dry_run=True)
            self.assertEqual(
                any(line.startswith("#20 pull request would start") for line in lines),
                picked, f"{name}: {lines}")

    def test_an_unreadable_reviewer_starts_no_merge_round_and_the_sweep_goes_on(self):
        """A permission lookup that fails holds that issue's rounds for the sweep, so an
        approval starts nothing, and the rest of the sweep still runs."""
        issue = item(1, labels=("alice-done",), assignees=(ALICE, PERSON), author=SUPPORT)
        timelines = {
            1: [assigned(PERSON, 30), alice_pull_request_reference(20, 20)],
            20: [commit(5), review(PERSON, 1, "approved")],
        }
        github = FakeGitHub([issue, item(20, pull_request=True)], timelines)
        with mock.patch.object(github, "is_developer", side_effect=RuntimeError("403")):
            _, lines, _ = run_sweep(github, dry_run=True)
        self.assertTrue(any("#1 reviewer unknown, so it waits" in line for line in lines), lines)
        self.assertFalse(
            any(line.startswith("#20 pull request would start") for line in lines), lines)

    def test_a_bots_later_reassignment_keeps_the_person_who_assigned_alice(self):
        """A bot assigning Alice again after a person did never widens who may approve: the
        other owner's approval still starts nothing."""
        issue = item(1, labels=("alice-done",), assignees=(ALICE, PERSON, OTHER_PERSON),
                     author=SUPPORT)
        timelines = {
            1: [assigned(OTHER_PERSON, 30), assigned(APP_BOT, 25),
                alice_pull_request_reference(20, 20)],
            20: [commit(5), review(PERSON, 1, "approved")],
        }
        github = FakeGitHub([issue, item(20, pull_request=True)], timelines)
        _, lines, _ = run_sweep(github, dry_run=True)
        self.assertFalse(
            any(line.startswith("#20 pull request would start") for line in lines), lines)

    def test_her_pull_request_that_only_mentions_an_issue_takes_none_of_its_rounds(self):
        """Alice's PR for another issue that mentions this one, say under Out of scope, is not
        this issue's PR: an approval on it starts no merge round with this issue's reviewer."""
        issue = item(1, labels=("alice-done",), assignees=(ALICE, PERSON))
        timelines = {
            1: [assigned(PERSON, 30), alice_pull_request_reference(20, 20, issue=5)],
            20: [commit(5), review(PERSON, 1, "approved")],
        }
        pull_request = item(20, pull_request=True)
        pull_request["body"] = "Fixes #5"
        _, lines, _ = run_sweep(FakeGitHub([issue, pull_request], timelines), dry_run=True)
        self.assertFalse(
            any(line.startswith("#20 pull request would start") for line in lines), lines)

    def test_no_issue_run_while_a_round_runs_on_her_pull_request(self):
        """A request on the issue waits while a review or merge round holds her PR, so two
        sessions never share its branch."""
        issue = item(1, labels=("alice-done", "alice-continue"))
        pull_request = item(20, labels=("alice-working",), pull_request=True)
        timelines = {
            1: [assigned(PERSON, 30), alice_pull_request_reference(20, 20),
                label_event("labeled", "alice-continue", PERSON, 1)],
            20: [commit(5), label_event("labeled", "alice-working", ACTIONS_BOT, 1)],
        }
        _, lines, fired = run_sweep(FakeGitHub([issue, pull_request], timelines))
        self.assertEqual(fired, [])
        self.assertTrue(
            any(line.startswith("#1 issue skipped") and "#20" in line for line in lines), lines)

    def test_a_merge_round_and_an_issue_run_on_the_same_work_never_start_together(self):
        """When a sweep starts a round on her PR, the same sweep does not also start its issue."""
        issue = item(1, labels=("alice-done", "alice-continue"), assignees=(ALICE, PERSON))
        pull_request = item(20, pull_request=True)
        timelines = {
            1: [assigned(PERSON, 30), alice_pull_request_reference(20, 20),
                label_event("labeled", "alice-continue", PERSON, 1)],
            20: [commit(5), review(PERSON, 1, "approved", None, "c0")],
        }
        _, lines, _ = run_sweep(FakeGitHub([issue, pull_request], timelines), dry_run=True)
        started = [line for line in lines if "would start" in line]
        self.assertEqual(len(started), 1, lines)
        self.assertTrue(started[0].startswith("#20"), lines)

    def test_starts_at_most_3_and_keeps_at_most_5_running(self):
        """The start count is capped per sweep and by the sessions already running."""
        self.assertEqual(sweep.start_limit(0), 3)
        self.assertEqual(sweep.start_limit(4), 1)
        self.assertEqual(sweep.start_limit(5), 0)
        running = [item(n, labels=("alice-working",)) for n in range(1, 5)]
        timelines = {n: [label_event("labeled", "alice-working", ACTIONS_BOT, 1)]
                     for n in range(1, 5)}
        waiting = [item(n) for n in (30, 31)]
        timelines.update({n: [assigned(PERSON)] for n in (30, 31)})
        _, _, fired = run_sweep(FakeGitHub(running + waiting, timelines))
        self.assertEqual(fired, ["Issue #30"])

    def test_a_silent_session_is_marked_stalled_and_frees_its_slot(self):
        """24 hours without Alice's comment or push swaps alice-working for alice-stalled."""
        silent = item(1, labels=("alice-working",))
        busy = item(2, labels=("alice-working",))
        timelines = {
            1: [label_event("labeled", "alice-working", ACTIONS_BOT, 30), comment(PERSON, 2)],
            2: [label_event("labeled", "alice-working", ACTIONS_BOT, 30),
                alice_pull_request_reference(40, 29, issue=2)],
            40: [commit(3)],
        }
        github = FakeGitHub([silent, busy], timelines)
        _, lines, _ = run_sweep(github)
        self.assertIn(("add", 1, ("alice-stalled",)), github.writes)
        self.assertIn(("remove", 1, "alice-working"), github.writes)
        self.assertFalse([write for write in github.writes if write[1] == 2])
        self.assertIn("1 running; up to 3 new sessions this sweep", lines)

    def test_the_start_names_the_reviewer_the_session_cannot_look_up(self):
        """Alice's cloud session is refused the permission lookup, so the sweep, which can read
        it, names the issue's reviewer in what it sends; an issue with none says so."""
        timeline = [assigned(PERSON)]
        owned = FakeGitHub([item(1, assignees=(ALICE, PERSON))], {1: timeline})
        _, _, fired = run_sweep(owned, reviewers=True)
        self.assertEqual(fired, ["Issue #1\nReviewers: dev-one"])
        unowned = FakeGitHub([item(1, assignees=(ALICE, SUPPORT), author=SUPPORT)],
                             {1: [assigned(SUPPORT)]})
        _, _, fired = run_sweep(unowned, reviewers=True)
        self.assertEqual(fired, ["Issue #1\nReviewers: none"])

    def test_a_round_on_her_pull_request_names_its_issues_reviewer_too(self):
        """A merge round, sent into her running session, carries the issue's reviewer, whom
        she checks the approval against."""
        issue = item(1, labels=("alice-done",), assignees=(ALICE, PERSON))
        timelines = {
            1: [assigned(PERSON, 30), alice_pull_request_reference(20, 20), dispatch_comment(25)],
            20: [commit(5), review(PERSON, 1, "approved")],
        }
        _, lines, _ = run_sweep(FakeGitHub([issue, item(20, pull_request=True)], timelines),
                                reviewers=True)
        sent = [line for line in lines if line.startswith("sent ")]
        self.assertEqual(len(sent), 1, lines)
        self.assertIn("Merge round on pull request #20", sent[0])
        self.assertIn("\\nReviewers: dev-one\\n", sent[0])

    def test_an_unreadable_reviewer_holds_a_review_round_and_fails_the_run(self):
        """A review round on her PR waits too when its issue's reviewer could not be read, and
        the run fails so a lookup that keeps failing shows as a red run."""
        issue = item(1, labels=("alice-done",), assignees=(ALICE, PERSON))
        timelines = {
            1: [assigned(PERSON, 30), alice_pull_request_reference(20, 20)],
            20: [commit(5), review(PERSON, 1)],
        }
        github = FakeGitHub([issue, item(20, pull_request=True)], timelines)
        with mock.patch.object(github, "is_developer", side_effect=RuntimeError("502")):
            code, lines, fired = run_sweep(github)
        self.assertEqual((code, fired), (1, []))
        self.assertTrue(any("#20 pull request waits: its reviewer could not be read" in line
                            for line in lines), lines)

    def test_an_unreadable_reviewer_on_an_issue_with_her_approved_pr_fails_the_run(self):
        """An approval that cannot start a merge round because the reviewer could not be read
        is held work too, so the run fails."""
        issue = item(1, labels=("alice-done",), assignees=(ALICE, PERSON))
        timelines = {
            1: [assigned(PERSON, 30), alice_pull_request_reference(20, 20)],
            20: [commit(5), review(PERSON, 1, "approved")],
        }
        github = FakeGitHub([issue, item(20, pull_request=True)], timelines)
        with mock.patch.object(github, "is_developer", side_effect=RuntimeError("502")):
            code, _, fired = run_sweep(github)
        self.assertEqual((code, fired), (1, []))

    def test_an_unreadable_reviewer_on_an_issue_that_starts_nothing_keeps_the_run_green(self):
        """Only held work fails the run: a skipped issue whose lookup fails does not."""
        github = FakeGitHub([item(1, labels=("skip-alice",), assignees=(ALICE, PERSON))],
                            {1: [assigned(PERSON)]})
        with mock.patch.object(github, "is_developer", side_effect=RuntimeError("502")):
            code, _, fired = run_sweep(github)
        self.assertEqual((code, fired), (0, []))

    def test_an_unreadable_reviewer_holds_an_issue_start_instead_of_sending_none(self):
        """Alice told "Reviewers: none" would request nobody, so an issue whose reviewer could
        not be read waits for the next sweep."""
        github = FakeGitHub([item(1, assignees=(ALICE, PERSON))], {1: [assigned(PERSON)]})
        with mock.patch.object(github, "is_developer", side_effect=RuntimeError("502")):
            _, lines, fired = run_sweep(github)
        self.assertEqual(fired, [])
        self.assertTrue(any("#1 issue waits: its reviewer could not be read" in line
                            for line in lines), lines)

    def test_claims_before_firing_and_comments_the_session(self):
        """alice-working goes on and the resume labels come off before /fire is called."""
        timeline = [
            assigned(PERSON),
            label_event("labeled", "alice-done", ALICE, 5),
            label_event("labeled", "alice-continue", PERSON, 1),
        ]
        github = FakeGitHub([item(1, labels=("alice-done", "alice-continue"))], {1: timeline})
        order: list[str] = []

        def fire(_text):
            order.append(f"fire after {len(github.writes)} writes")
            return "https://claude.ai/code/session_1"

        code, _, _ = run_sweep(github, fire=fire)
        self.assertEqual(code, 0)
        self.assertEqual(github.writes[:3], [
            ("add", 1, ("alice-working",)),
            ("remove", 1, "alice-continue"),
            ("remove", 1, "alice-done"),
        ])
        self.assertEqual(order, ["fire after 3 writes"])
        self.assertIn("https://claude.ai/code/session_1", github.writes[3][2])

    def test_a_refused_start_undoes_the_claim_and_fails_the_run(self):
        """A 4xx puts the removed labels back, drops alice-working, stops, and exits non-zero."""
        timeline = [
            assigned(PERSON),
            label_event("labeled", "alice-stalled", ACTIONS_BOT, 5),
            label_event("labeled", "alice-continue", PERSON, 1),
        ]
        issues = [item(1, labels=("alice-stalled", "alice-continue")), item(2, created_hours_ago=1)]
        github = FakeGitHub(issues, {1: timeline, 2: [assigned(PERSON)]})
        calls = []

        def refuse(text):
            calls.append(text)
            raise sweep.FireRefused("HTTP 401: authentication_error")

        code, _, _ = run_sweep(github, fire=refuse)
        self.assertEqual(code, 1)
        self.assertEqual([call.split("\n")[0] for call in calls], ["Issue #1"])
        self.assertEqual(github.writes[3:], [
            ("add", 1, ("alice-continue", "alice-stalled")),
            ("remove", 1, "alice-working"),
        ])

    def test_an_unconfirmed_start_keeps_the_claim_and_says_so(self):
        """A 5xx or timeout keeps alice-working, comments that the start is unconfirmed, stops."""
        issues = [item(1, created_hours_ago=9), item(2, created_hours_ago=1)]
        github = FakeGitHub(issues, {1: [assigned(PERSON)], 2: [assigned(PERSON)]})

        def time_out(_text):
            raise sweep.FireUnconfirmed("no answer: timed out")

        code, _, _ = run_sweep(github, fire=time_out)
        self.assertEqual(code, 0)
        self.assertEqual(github.writes[0], ("add", 1, ("alice-working",)))
        self.assertNotIn(("remove", 1, "alice-working"), github.writes)
        self.assertIn("may not have started", github.writes[-1][2])
        self.assertFalse([write for write in github.writes if write[1] == 2])

    def test_a_dry_run_writes_nothing(self):
        """--dry-run reports picks and stalls without labeling, commenting or firing."""
        timelines = {
            1: [assigned(PERSON)],
            2: [label_event("labeled", "alice-working", ACTIONS_BOT, 30)],
        }
        github = FakeGitHub([item(1), item(2, labels=("alice-working",))], timelines)
        _, lines, fired = run_sweep(github, dry_run=True)
        self.assertEqual((github.writes, fired), ([], []))
        self.assertTrue(any("#1 issue would start" in line for line in lines))
        self.assertTrue(any(line.startswith("#2 stalled") for line in lines))


class WorkByOthersTests(unittest.TestCase):
    """Which branches and PRs count as someone else's work on an issue."""

    def test_a_deleted_branch_or_author_does_not_crash_the_sweep(self):
        """GitHub returns null for a linked branch whose ref is gone and for a deleted author."""
        linked = {"data": {"repository": {"issue": {
            "linkedBranches": {"nodes": [{"ref": None}, {"ref": {"name": "fix-chart"}}]},
            "closedByPullRequestsReferences": {"nodes": [{"number": 9, "author": None}]},
        }}}}
        github = sweep.GitHub("example-org/monorepo")
        with mock.patch.object(github, "_api", side_effect=[linked, []]):
            others = github.work_by_others(3, [])
        self.assertEqual(others, ["branch fix-chart", "pull request #9 by a deleted account"])

    def test_a_pull_request_that_only_mentions_the_issue_is_not_someone_elses_work(self):
        """An open PR blocks Alice only when it addresses the issue, by a "Part of #N" or a
        closing "Fixes #N" line; one that merely mentions the issue, say as a follow-up, does
        not."""
        unlinked = {"data": {"repository": {"issue": {
            "linkedBranches": {"nodes": []}, "closedByPullRequestsReferences": {"nodes": []},
        }}}}
        bodies = {
            7: "Fixes #12\n\n## Out of scope\n- The general negation bug: #3.",
            8: "Part of #3\n\n## What\nThe first half.",
            9: "**Fixes #3**, the rest of it.",
        }
        timeline = []
        for number, body in bodies.items():
            reference = alice_pull_request_reference(number, 1)
            reference["source"]["issue"].update(user=PERSON, body=body)
            timeline.append(reference)
        github = sweep.GitHub("example-org/monorepo")
        with mock.patch.object(github, "_api", side_effect=[unlinked, []]):
            others = github.work_by_others(3, timeline)
        self.assertEqual(others, ["pull request #8 by dev-one", "pull request #9 by dev-one"])


class DeveloperTests(unittest.TestCase):
    """Who counts as a developer, the people who review Alice's work."""

    def test_a_developer_is_a_repository_admin_read_once_per_login(self):
        """Admin on the repository makes a developer and write does not; each login's permission
        is read once per sweep."""
        github = sweep.GitHub("example-org/monorepo")
        answers = [{"permission": "admin"}, {"permission": "write"}]
        with mock.patch.object(github, "_api", side_effect=answers) as api:
            self.assertTrue(github.is_developer("dev-one"))
            self.assertFalse(github.is_developer("support-one"))
            self.assertTrue(github.is_developer("dev-one"))
        self.assertEqual(api.call_count, 2)


class TimelineTests(unittest.TestCase):
    """Which events the sweep reads from an item's timeline."""

    def test_only_this_repositorys_references_are_read(self):
        """A PR in another repository that mentions the issue shares numbers with this one's, so
        it must not count as Alice's or someone else's PR here; a reference without a source
        issue (a deleted one) names no PR at all."""
        here = alice_pull_request_reference(9, 4)
        here["source"]["issue"]["repository"] = {"full_name": "example-org/monorepo"}
        elsewhere = alice_pull_request_reference(12, 3)
        elsewhere["source"]["issue"]["repository"] = {"full_name": "example-org/website"}
        deleted = {"event": "cross-referenced", "actor": PERSON, "created_at": at(2),
                   "source": {"issue": None}}
        github = sweep.GitHub("example-org/monorepo")
        events = [assigned(PERSON), here, elsewhere, deleted]
        with mock.patch.object(github, "_paginated", return_value=events):
            timeline = github.timeline(1)
        self.assertEqual(sweep.referencing_pull_requests(timeline, 1), {9: "alice-bot"})
        self.assertEqual(len(timeline), 2)


class FireRoutineTests(unittest.TestCase):
    """How /fire answers map to a started, refused or unconfirmed session."""

    def answer(self, response=None, error=None):
        with mock.patch.object(sweep.urllib.request, "urlopen") as urlopen:
            if error:
                urlopen.side_effect = error
            else:
                urlopen.return_value.__enter__.return_value = io.BytesIO(
                    json.dumps(response).encode()
                )
            return sweep.fire_routine("https://api.example/fire", "token", "Issue #1")

    def http_error(self, code):
        return urllib.error.HTTPError(
            "https://api.example/fire", code, "error", {}, io.BytesIO(b'{"type":"error"}')
        )

    def test_success_returns_the_session_url(self):
        """A 200 answer yields the session URL to comment on the issue."""
        url = self.answer({"type": "routine_fire",
                           "claude_code_session_url": "https://claude.ai/code/session_1"})
        self.assertEqual(url, "https://claude.ai/code/session_1")

    def test_4xx_is_refused_and_5xx_timeouts_and_odd_answers_are_unconfirmed(self):
        """Only a 4xx proves no session started; everything else may hide one."""
        for code in (400, 401, 429):
            with self.assertRaises(sweep.FireRefused):
                self.answer(error=self.http_error(code))
        for error in (self.http_error(500), self.http_error(503),
                      urllib.error.URLError("timed out"), TimeoutError("timed out")):
            with self.assertRaises(sweep.FireUnconfirmed):
                self.answer(error=error)
        with self.assertRaises(sweep.FireUnconfirmed):
            self.answer({"type": "routine_fire"})


class RoutinesTests(unittest.TestCase):
    """How starts spread over Alice's routines, one per agent-platform account."""

    def routines(self, *answers, first=0):
        calls, lines = [], []

        def fire_for(index, answer):
            def fire(_text):
                calls.append(index)
                if isinstance(answer, Exception):
                    raise answer
                return f"https://claude.ai/code/session_{index}_{len(calls)}"
            return fire

        routines = sweep.Routines(
            [fire_for(index, answer) for index, answer in enumerate(answers)], first, lines.append
        )
        return routines, calls, lines

    def test_starts_take_turns_from_the_ten_minute_slots_routine(self):
        """Consecutive starts alternate accounts; the first depends on the ten-minute slot."""
        routines, calls, _ = self.routines("ok", "ok", first=7)
        for _ in range(3):
            routines("Issue #1")
        self.assertEqual(calls, [1, 0, 1])

    def test_a_refused_start_moves_to_the_next_routine_and_warns(self):
        """A refusal started nothing, so the next account takes the start."""
        routines, calls, lines = self.routines(sweep.FireRefused("HTTP 401"), "ok")
        self.assertEqual(routines("Issue #1"), "https://claude.ai/code/session_1_2")
        self.assertEqual(calls, [0, 1])
        self.assertIn("::warning::Routine 1 refused the start: HTTP 401", lines)

    def test_every_routine_refusing_fails_and_an_unconfirmed_start_is_not_retried(self):
        """Only a refusal is safe to retry; an unconfirmed start may already be running."""
        routines, _, _ = self.routines(sweep.FireRefused("401"), sweep.FireRefused("403"))
        with self.assertRaises(sweep.FireRefused):
            routines("Issue #1")
        routines, calls, _ = self.routines(sweep.FireUnconfirmed("timeout"), "ok")
        with self.assertRaises(sweep.FireUnconfirmed):
            routines("Issue #1")
        self.assertEqual(calls, [0])

    def test_main_pairs_each_routine_url_with_its_token(self):
        """Each set ALICE_ROUTINE_FIRE_URL* fires with its own token; unset ones are left out."""
        environ = {
            "ALICE_ROUTINE_FIRE_URL": "https://api/1", "ALICE_ROUTINE_TOKEN": "token-1",
            "ALICE_ROUTINE_FIRE_URL_2": "https://api/2", "ALICE_ROUTINE_TOKEN_2": "token-2",
            "ALICE_ROUTINE_FIRE_URL_3": "", "ALICE_ROUTINE_TOKEN_3": "",
        }
        fired = []

        def fake_sweep(_github, fire, *_args, **_kwargs):
            fire("Issue #1")
            fire("Issue #2")
            return 0

        with mock.patch.dict(sweep.os.environ, environ, clear=True), \
                mock.patch.object(sys, "argv", ["sweep.py"]), \
                mock.patch.object(sweep, "GitHub"), \
                mock.patch.object(sweep, "sweep", fake_sweep), \
                mock.patch.object(sweep, "fire_routine",
                                  lambda url, token, _text: fired.append((url, token)) or url):
            self.assertEqual(sweep.main(), 0)
        self.assertEqual(
            sorted(fired), [("https://api/1", "token-1"), ("https://api/2", "token-2")]
        )


class FakeCommands:  # pylint: disable=too-few-public-methods
    """Plays the secrets and agent CLIs for Sessions: the secret store holds one refresh token
    per account, a sign-in replaces it, and each account owns the sessions listed for it."""

    def __init__(self, owned: dict[int, set[str]], sign_in_fails=(), store_fails=False,
                 answer=None):
        self.secrets = {account: f"refresh-{account}-0" for account in owned}
        self.owned = owned
        self.sign_in_fails = set(sign_in_fails)
        self.store_fails = store_fails
        self.answer = answer
        self.calls: list[tuple[str, ...]] = []

    def __call__(self, args, env=None, input=None, **_kwargs):  # pylint: disable=redefined-builtin
        self.calls.append(tuple(args))
        if args[:2] == [sweep.SECRETS_CLI, "get"]:
            account = int(args[2].rsplit("-", 1)[1])
            secret = {"refresh_token": self.secrets[account], "scopes": "sessions:send"}
            return mock.Mock(returncode=0, stdout=json.dumps(secret), stderr="")
        if args[:2] == [sweep.SECRETS_CLI, "put"]:
            if self.store_fails:
                return mock.Mock(returncode=255, stdout="", stderr="AccessDenied")
            account = int(args[2].rsplit("-", 1)[1])
            self.secrets[account] = json.loads(input)["refresh_token"]
            return mock.Mock(returncode=0, stdout="{}", stderr="")
        account = int(env["CLAUDE_CONFIG_DIR"].split("claude-login-")[1].split("-")[0])
        if args[1:3] == ["auth", "login"]:
            token = env["CLAUDE_CODE_OAUTH_REFRESH_TOKEN"]
            if account in self.sign_in_fails or token != self.secrets[account]:
                return mock.Mock(returncode=1, stdout="Login failed: status code 400", stderr="")
            rotated = f"refresh-{account}-{int(token.rsplit('-', 1)[1]) + 1}"
            oauth = {"refreshToken": rotated, "refreshTokenExpiresAt": 4_102_444_800_000}
            Path(env["CLAUDE_CONFIG_DIR"], ".credentials.json").write_text(
                json.dumps({"claudeAiOauth": oauth}))
            return mock.Mock(returncode=0, stdout="Login successful.", stderr="")
        if isinstance(self.answer, Exception):
            raise self.answer
        if self.answer:
            return self.answer
        session = args[4]
        if session in self.owned[account]:
            answer = {"ok": True, "session_id": session}
        else:
            answer = {"ok": False, "error": f"Session not found: {session}"}
        return mock.Mock(returncode=0, stdout=json.dumps(answer), stderr="")


class SessionsTests(unittest.TestCase):
    """How the sweep signs Alice's accounts in and sends a round into a session (D38)."""

    def setUp(self):
        # The sign-ins' config directories land here instead of the machine's temp directory.
        directory = tempfile.TemporaryDirectory()  # pylint: disable=consider-using-with
        self.addCleanup(directory.cleanup)
        patcher = mock.patch.object(sweep.tempfile, "tempdir", directory.name)
        patcher.start()
        self.addCleanup(patcher.stop)

    def send(self, commands, *sessions):
        lines = []
        send = sweep.Sessions([1, 2], log=lines.append, run=commands)
        for session in sessions:
            send(session, "Review-comment round on pull request #20")
        return lines

    def test_each_account_signs_in_once_and_stores_its_new_token_before_sending(self):
        """A sign-in replaces the stored token, so the replacement is stored before any send, and
        no token ever appears in a command's arguments."""
        commands = FakeCommands({1: {"s1"}, 2: set()})
        self.send(commands, "s1", "s1")
        self.assertEqual(commands.secrets[1], "refresh-1-1")
        steps = [call[1] for call in commands.calls]
        self.assertEqual(steps, ["get", "auth", "put", "-p", "-p"])
        self.assertFalse([call for call in commands.calls if any("refresh-" in a for a in call)])

    def test_a_session_another_account_owns_is_sent_through_that_account(self):
        """The owner is not recorded: "Session not found" moves on to the next account."""
        commands = FakeCommands({1: set(), 2: {"s2"}})
        self.send(commands, "s2")
        sends = [call for call in commands.calls if call[1] == "-p"]
        self.assertEqual(len(sends), 2)

    def test_an_archived_session_or_no_signed_in_account_is_unreachable(self):
        """Neither delivers the round, so the sweep can start a new session for it."""
        archived = mock.Mock(returncode=0, stderr="", stdout=json.dumps(
            {"ok": False, "error": "cloud session s1 is archived and cannot accept new messages"}))
        with self.assertRaisesRegex(sweep.SessionUnreachable, "archived"):
            self.send(FakeCommands({1: {"s1"}, 2: set()}, answer=archived), "s1")
        commands = FakeCommands({1: {"s1"}, 2: set()}, sign_in_fails={1, 2})
        lines = []
        send = sweep.Sessions([1, 2], log=lines.append, run=commands)
        for _ in range(2):
            with self.assertRaises(sweep.SessionUnreachable):
                send("s1", "Issue #1")
        logins = [call for call in commands.calls if call[1:3] == ("auth", "login")]
        self.assertEqual(len(logins), 2, "a failed sign-in is not retried in the same sweep")
        self.assertTrue(any("account 1 could not sign in" in line for line in lines), lines)

    def test_a_sign_in_that_breaks_unexpectedly_leaves_the_round_to_a_new_session(self):
        """Malformed credentials must not crash the sweep after it claimed the item."""
        commands = FakeCommands({1: {"s1"}, 2: set()})

        def no_expiry(args, **kwargs):
            result = commands(args, **kwargs)
            if args[1:3] == ["auth", "login"]:
                path = Path(kwargs["env"]["CLAUDE_CONFIG_DIR"], ".credentials.json")
                path.write_text(json.dumps({"claudeAiOauth": {"refreshToken": "refresh-1-1"}}))
            return result

        with self.assertRaises(sweep.SessionUnreachable):
            sweep.Sessions([1], log=lambda _line: None, run=no_expiry)("s1", "Issue #1")

    def test_the_answer_is_found_after_other_output(self):
        """A warning the CLI prints before its JSON answer does not hide the answer."""
        delivered = mock.Mock(returncode=0, stderr="", stdout='Warning: update available\n'
                              + json.dumps({"ok": True, "session_id": "s1"}))
        self.send(FakeCommands({1: {"s1"}, 2: set()}, answer=delivered), "s1")

    def test_a_send_without_an_answer_is_unconfirmed(self):
        """A timeout or an answer that is not JSON may hide a delivered round."""
        timeout = sweep.subprocess.TimeoutExpired(
            [sweep.CLAUDE_CLI], sweep.CLAUDE_TIMEOUT_SECONDS)
        for answer in (timeout, mock.Mock(returncode=1, stdout="", stderr="crash")):
            with self.assertRaises(sweep.SendUnconfirmed):
                self.send(FakeCommands({1: {"s1"}, 2: set()}, answer=answer), "s1")

    def test_a_token_that_cannot_be_stored_still_sends_and_says_the_account_signs_out(self):
        """The sign-in already replaced the stored token, so this sweep still uses it, and the
        log says a person must sign the account in again."""
        commands = FakeCommands({1: {"s1"}, 2: set()}, store_fails=True)
        lines = self.send(commands, "s1")
        self.assertTrue([call for call in commands.calls if call[1] == "-p"])
        self.assertTrue(any(line.startswith("::error::Alice's account 1 signed in, but its new"
                                            " token could not be stored") for line in lines))


class WorkflowTests(unittest.TestCase):
    """The workflow never starts sessions from unreviewed code or before it is switched on."""

    @classmethod
    def setUpClass(cls):
        cls.workflow = WORKFLOW.read_text()

    def test_live_sweeps_need_master_and_the_switch_or_an_explicit_dispatch(self):
        """Scheduled runs stay dry until ALICE_SWEEP_ENABLED; writes only run master's code."""
        self.assertIn("vars.ALICE_SWEEP_ENABLED == 'true'", self.workflow)
        self.assertIn("github.ref == 'refs/heads/master'", self.workflow)
        self.assertRegex(self.workflow, r"dry_run:\n(?:.*\n)*?\s+default: true")

    def test_a_nudge_waits_out_the_quiet_period(self):
        """A nudged sweep that ran before the quiet period ended would skip the request, leaving
        it to the late schedule."""
        nudge = (REPO_ROOT / "workflows/alice-nudge.yml").read_text()
        wait = int(re.search(r"sleep (\d+)", nudge).group(1))
        self.assertGreater(wait, sweep.QUIET_PERIOD.total_seconds())

    def test_actions_are_pinned_to_commits(self):
        """The token and the routine secret never reach code behind a mutable action tag."""
        mutable_uses = re.findall(
            r"^\s*(?:- )?uses: [^@\n]+@(?![0-9a-f]{40}(?:\s|$))", self.workflow, re.MULTILINE,
        )
        self.assertEqual(mutable_uses, [])


class ReviewerHandOffTests(unittest.TestCase):
    """Who reviews her PR once the issue's reviewer hands it to someone else."""

    def test_the_reviewer_hands_the_review_over_by_requesting_another_developers(self):
        """The issue's reviewer requesting another developer's review of her PR makes that
        developer the reviewer: their approval starts the merge round and the round names
        them. Alice's own review requests, and a non-reviewer's, hand nothing over."""
        author = {"login": "dev-lead", "type": "User"}
        issue = item(1, labels=("alice-done",), assignees=(ALICE, author, PERSON), author=author)

        def merge_round(pull_request_timeline):
            timelines = {1: [assigned(author, 30), alice_pull_request_reference(20, 20),
                             dispatch_comment(25)], 20: pull_request_timeline}
            _, lines, _ = run_sweep(FakeGitHub([issue, item(20, pull_request=True)], timelines),
                                    reviewers=True)
            return [line for line in lines if line.startswith("sent ")]

        handed = merge_round([commit(5), handoff_request(ALICE, author, 4),
                              handoff_request(author, PERSON, 3), review(PERSON, 1, "approved")])
        self.assertEqual(len(handed), 1)
        self.assertIn("Merge round on pull request #20", handed[0])
        self.assertIn("\\nReviewers: dev-one\\n", handed[0])
        self.assertFalse(merge_round([commit(5), handoff_request(ALICE, PERSON, 4),
                                      handoff_request(OTHER_PERSON, PERSON, 3),
                                      review(PERSON, 1, "approved")]))

    def handed(self, reviewers, *events):
        return sweep.handed_off(reviewers, [("", list(events))],
                                lambda login: login != "support-one")

    def test_a_hand_off_replaces_the_reviewers(self):
        """The new reviewer keeps the review whoever else the issue names, and a co-reviewer can
        hand it to the other."""
        self.assertEqual(self.handed({"A", "B", "dev-one"}, handoff_request(
            {"login": "A", "type": "User"}, PERSON, 3)), {"dev-one"})
        self.assertEqual(self.handed({"dev-lead", "dev-one"},
                                     handoff_request(OWNER, PERSON, 3)), {"dev-one"})

    def test_only_a_standing_request_to_a_developer_by_a_reviewer_hands_over(self):
        """A withdrawn request, re-requested or not, a request to support, or one by someone
        who is not the reviewer leaves the review where it was."""
        self.assertEqual(self.handed({"dev-lead"}, handoff_request(OWNER, PERSON, 3),
                                     withdrawal(OWNER, PERSON, 2)), {"dev-lead"})
        self.assertEqual(self.handed({"dev-lead"}, handoff_request(OWNER, PERSON, 4),
                                     handoff_request(OWNER, PERSON, 3),
                                     withdrawal(OWNER, PERSON, 2)), {"dev-lead"})
        self.assertEqual(self.handed({"dev-lead"}, handoff_request(OWNER, SUPPORT, 3)),
                         {"dev-lead"})
        self.assertEqual(self.handed({"dev-lead"},
                                     handoff_request(OTHER_PERSON, PERSON, 3)),
                         {"dev-lead"})

    def test_a_withdrawal_counts_only_on_its_own_pr_and_only_from_a_person(self):
        """Withdrawing a request on one of her PRs, or Alice withdrawing one, leaves a hand-off
        made on another PR standing."""
        def is_developer(_login):
            return True
        handed = sweep.handed_off({"dev-lead"}, [
            ("", [handoff_request(OTHER_PERSON, PERSON, 5), withdrawal(OTHER_PERSON, PERSON, 2)]),
            ("", [handoff_request(OWNER, PERSON, 3)]),
        ], is_developer)
        self.assertEqual(handed, {"dev-one"})
        by_alice = sweep.handed_off({"dev-lead"}, [
            ("", [handoff_request(OWNER, PERSON, 3), withdrawal(ALICE, PERSON, 2)]),
        ], is_developer)
        self.assertEqual(by_alice, {"dev-one"})

    def test_her_assignment_of_the_new_reviewer_changes_no_hand_off(self):
        """Alice assigns the developer the review was handed to, and that assignment does not
        count toward who reviews: the replay starts from the same reviewer, so the hand-off
        holds and a withdrawal still gives the review back."""
        issue = item(1, assignees=(ALICE, OWNER, PERSON), author=SUPPORT)
        timeline = [assigned(APP_BOT, 30),
                    {**assigned(APP_BOT, 30), "assignee": OWNER},
                    {**assigned(ALICE, 2), "assignee": PERSON}]
        reviewers = sweep.issue_reviewers(issue, timeline, FakeGitHub([], {}).is_developer)
        self.assertEqual(reviewers, {"dev-lead"})

        def is_developer(_login):
            return True
        self.assertEqual(
            sweep.handed_off(reviewers, [("", [handoff_request(OWNER, PERSON, 3)])],
                             is_developer),
            {"dev-one"})
        self.assertEqual(
            sweep.handed_off(reviewers, [("", [handoff_request(OWNER, PERSON, 3),
                                                withdrawal(OWNER, PERSON, 1)])], is_developer),
            {"dev-lead"})

    def test_the_filer_she_assigned_stays_the_reviewer(self):
        """Her hand-over assignment of the filer counts, so a developer a person assigns later
        does not take the review from them."""
        issue = item(1, assignees=(ALICE, OWNER, PERSON), author=OWNER)
        timeline = [assigned(APP_BOT, 30), {**assigned(ALICE, 20), "assignee": OWNER},
                    {**assigned(SUPPORT, 2), "assignee": PERSON}]
        self.assertEqual(sweep.issue_reviewers(issue, timeline, FakeGitHub([], {}).is_developer),
                         {"dev-lead"})

    def test_a_request_from_before_her_pr_named_the_issue_hands_nothing_over(self):
        """A review request on her PR from before it first named the issue, as an edit of her
        own description would bring in, does not count for that issue."""
        named_at = at(3)
        self.assertEqual(sweep.handed_off({"dev-lead"}, [
            (named_at, [handoff_request(OWNER, PERSON, 5)])], lambda login: True),
            {"dev-lead"})

    def test_an_unreadable_hand_off_holds_the_issue_and_fails_the_run(self):
        """A developer check that fails while reading a hand-off holds the issue and its PR,
        as an unreadable reviewer does, instead of falling back to the earlier reviewer."""
        author = {"login": "dev-lead", "type": "User"}
        issue = item(1, labels=("alice-done",), assignees=(ALICE, author), author=author)
        timelines = {1: [assigned(author, 30), alice_pull_request_reference(20, 20),
                         dispatch_comment(25)],
                     20: [commit(5), handoff_request(author, PERSON, 3),
                          review(PERSON, 1, "approved")]}
        github = FakeGitHub([issue, item(20, pull_request=True)], timelines)
        checked = github.is_developer

        def is_developer(login):
            if login == PERSON["login"]:
                raise RuntimeError("502")
            return checked(login)

        with mock.patch.object(github, "is_developer", side_effect=is_developer):
            code, lines, fired = run_sweep(github)
        self.assertEqual(code, 1)
        self.assertFalse(fired)
        self.assertFalse([line for line in lines if line.startswith("sent ")])


if __name__ == "__main__":
    unittest.main()
