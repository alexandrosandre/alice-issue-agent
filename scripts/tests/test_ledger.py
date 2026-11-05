"""Tests for ledger.py: how an agent PR and its issue are classified."""
from datetime import datetime, timezone
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest

_SCRIPT_PATH = Path(__file__).resolve().parents[1] / 'alice' / 'ledger.py'
_spec = spec_from_file_location('ledger', _SCRIPT_PATH)
ledger = module_from_spec(_spec)
_spec.loader.exec_module(ledger)

AGENT = 'alice-bot'
NOW = datetime(2026, 11, 30, tzinfo=timezone.utc)
ALICE = {'login': AGENT, 'type': 'User'}
ANA = {'login': 'ana', 'type': 'User'}
REVIEW_BOT = {'login': 'review-bot[bot]', 'type': 'Bot'}


def _pull_request(number=10, title='[api] Fix the thing', merged_at='2026-11-02T10:00:00Z',
                  state='closed', created_at='2026-11-01T10:00:00Z', merge_commit_sha='abc1234def'):
    return {'number': number, 'title': title, 'merged_at': merged_at, 'state': state,
            'created_at': created_at, 'merge_commit_sha': merge_commit_sha, 'body': ''}


@pytest.mark.parametrize('body, expected', [
    ('**Risk 3 of 4 (Elevated)** — to judge: the new control\n\n## Risk\n\n'
     '**Risk 3 of 4 (Elevated)**, set by What users see.\n\n## What', 'Elevated'),
    ('## Risk\nSix answers, no level written.', None),
    ('## What\nNothing declared.', None),
])
def test_declared_level(body, expected):
    """The Risk section's "Risk n of 4" title is the declared level; a PR without one declares
    none."""
    assert ledger.declared_level(body).level == expected


def test_linked_issues():
    """Fixes, Closes, Resolves and Part of link an issue when a line declares it, list markers
    and bold included; a bare mention, or the words inside a sentence, do not."""
    body = ('Fixes #12\nPart of #34\ncloses: #56\n- **Resolves #90**\nSee #78 for context.\n'
            '- This does not fix #91; a follow-up.\n- Negation is tracked as part of #92.')

    assert ledger.linked_issues(body) == [12, 34, 56, 90]


def test_review_rounds():
    """A round is a head commit someone else reviewed, bots included; the agent's own reviews
    and people's reviews are told apart."""
    reviews = [
        {'user': REVIEW_BOT, 'commit_id': 'a'},
        {'user': ANA, 'commit_id': 'a'},
        {'user': REVIEW_BOT, 'commit_id': 'b'},
        {'user': ALICE, 'commit_id': 'c'},
    ]

    assert ledger.review_rounds(reviews, AGENT) == (2, 1)


def test_human_follow_up_commits():
    """Only a person's own commits count: not the agent's, not a bot's, not a merge of master,
    and not a commit GitHub could not tie to an account."""
    commits = [
        {'author': ALICE, 'parents': [{}]},
        {'author': ANA, 'parents': [{}]},
        {'author': ANA, 'parents': [{}, {}]},
        {'author': {'login': 'dependency-bot[bot]', 'type': 'Bot'}, 'parents': [{}]},
        {'author': None, 'parents': [{}]},
    ]

    assert ledger.human_follow_up_commits(commits, AGENT) == 1


def test_find_revert_by_revert_pull_request():
    """GitHub's revert button opens a PR whose body says `Reverts owner/repo#n`."""
    revert = {'number': 20, 'title': 'Revert "something else"',
              'body': 'Reverts example-org/monorepo#10', 'merged_at': '2026-11-10T00:00:00Z'}

    assert ledger.find_revert(_pull_request(), [revert], []) == ('#20', revert['merged_at'])


def test_find_revert_by_title():
    """A revert PR with no body still names the original by its title."""
    revert = {'number': 21, 'title': 'Revert "[api] Fix the thing"', 'body': None,
              'merged_at': '2026-11-03T00:00:00Z'}

    assert ledger.find_revert(_pull_request(), [revert], []) == ('#21', revert['merged_at'])


def test_find_revert_by_master_commit():
    """A revert pushed straight to master names the merge commit it reverts."""
    commit = {'sha': 'fedcba9876543210', 'commit': {
        'message': 'Revert "[api] Fix the thing (#10)"\n\nThis reverts commit abc1234.',
        'committer': {'date': '2026-11-05T00:00:00Z'}}}

    assert ledger.find_revert(_pull_request(), [], [commit]) == (
        'fedcba9876', commit['commit']['committer']['date'])


def test_reverted_pull_request_numbers():
    """A revert in the window names the PR it undid however old it is, through the revert
    button's body, a squash title's `(#n)`, or the PR GitHub links to a reverted master commit,
    so a late revert of an older PR is not missed."""
    button = {'number': 30, 'title': 'Revert "something"', 'merged_at': '2026-11-20T00:00:00Z',
              'body': 'Reverts example-org/monorepo#41'}
    squash_title = {'number': 31, 'title': 'Revert "[api] Fix the thing (#42)"', 'body': '',
                    'merged_at': '2026-11-21T00:00:00Z'}
    unmerged = {'number': 32, 'title': 'Revert "x (#43)"', 'body': '', 'merged_at': None}
    commit = {'sha': 'fedcba98', 'commit': {'message': 'Revert "y"\n\nThis reverts commit abc1234.',
                                             'committer': {'date': '2026-11-22T00:00:00Z'}}}

    numbers = ledger.reverted_pull_request_numbers(
        [button, squash_title, unmerged], [commit], lambda sha: [44] if sha == 'abc1234' else [])

    assert numbers == {41, 42, 44}


def test_find_revert_by_squash_title():
    """A revert of a squash merge keeps the merge's `(#n)` at the end of its title, which names
    the PR even when the title no longer matches it exactly."""
    revert = {'number': 22, 'title': 'Revert "[api] Fix the thing (#10)"', 'body': '',
              'merged_at': '2026-11-04T00:00:00Z'}
    mention = {'number': 23, 'title': 'Revert "Port (#10) importer to v2"', 'body': '',
               'merged_at': '2026-11-04T00:00:00Z'}

    assert ledger.find_revert(_pull_request(), [revert], []) == ('#22', revert['merged_at'])
    assert ledger.find_revert(_pull_request(), [mention], []) is None


def test_summarize_leaves_out_prs_opened_before_the_window():
    """A PR listed only because a revert in the window undid it was counted by an earlier run."""
    def outcome(number, older):
        return ledger.PullRequestOutcome(
            number=number, title='t', url='u', created_at='2026-11-01T00:00:00Z',
            outcome='reverted' if older else 'merged', days_to_merge=1.0, review_rounds=1,
            human_reviews=1, human_follow_up_commits=0,
            declared_level=ledger.DeclaredLevel(level=None),
            linked_issues=[], opened_before_window=older)

    summary = ledger.summarize([], [outcome(1, older=False), outcome(2, older=True)])

    assert summary['pull_requests_by_outcome'] == {'merged': 1}


def test_find_revert_ignores_late_and_unmerged_reverts():
    """A revert merged after the 30-day window, or never merged, does not count."""
    late = {'number': 22, 'title': 'Revert "x"', 'body': 'Reverts example-org/monorepo#10',
            'merged_at': '2026-12-20T00:00:00Z'}
    unmerged = {'number': 23, 'title': 'Revert "x"', 'body': 'Reverts example-org/monorepo#10',
                'merged_at': None}

    assert ledger.find_revert(_pull_request(), [late, unmerged], []) is None


@pytest.mark.parametrize('pull_request, reverted_by, expected', [
    (_pull_request(), None, 'merged'),
    (_pull_request(), '#20', 'reverted'),
    (_pull_request(merged_at=None), None, 'closed'),
    (_pull_request(merged_at=None, state='open', created_at='2026-11-20T00:00:00Z'), None,
     'pending'),
    (_pull_request(merged_at=None, state='open', created_at='2026-10-01T00:00:00Z'), None,
     'open'),
])
def test_pull_request_outcome(pull_request, reverted_by, expected):
    """An open PR is pending for its first 30 days and counts as open after them."""
    assert ledger.pull_request_outcome(pull_request, reverted_by, NOW) == expected


@pytest.mark.parametrize('outcomes, state, expected', [
    (['closed', 'merged'], 'closed', 'merged'),
    (['reverted', 'closed'], 'open', 'reverted'),
    (['closed', 'pending'], 'open', 'pending'),
    (['closed'], 'closed', 'closed'),
    ([], 'closed', 'no PR'),
    ([], 'open', 'pending'),
])
def test_issue_outcome(outcomes, state, expected):
    """A merge that held decides the issue; a closed issue without a PR ended in findings."""
    assert ledger.issue_outcome(outcomes, state) == expected


def test_issue_type_prefers_triage_order():
    """An issue with two type labels takes the first in triage's order; none gives None."""
    assert ledger.issue_type([{'name': 'Chore'}, {'name': 'Bug'}, {'name': 'P1'}]) == 'Bug'
    assert ledger.issue_type([{'name': 'Frontend'}]) is None


def test_summarize_counts_decided_issues_only():
    """Merge rates leave pending issues out and group by issue type."""
    issues = [
        ledger.IssueOutcome(1, 'a', 'Bug', [10], 'merged'),
        ledger.IssueOutcome(2, 'b', 'Bug', [11], 'closed'),
        ledger.IssueOutcome(3, 'c', 'Chore', [], 'no PR'),
        ledger.IssueOutcome(4, 'd', 'Bug', [12], 'pending'),
    ]

    summary = ledger.summarize(issues, [])

    assert summary['decided_issues'] == 3
    assert summary['issues_ending_in_merged_pr'] == 1
    assert summary['merge_rate_by_issue_type'] == {
        'Bug': {'merged': 1, 'decided': 2}, 'Chore': {'merged': 0, 'decided': 1}}


def test_the_learning_pass_own_pull_requests_are_not_her_work():
    """An Alice account opens the weekly learning PRs; they never count as her work, whether
    opened in the window or brought back by a revert."""
    issue_work = {'user': ALICE, 'head': {'ref': 'alice-41-fix-retry-loop'}}
    learning = {'user': ALICE, 'head': {'ref': 'alice-learn-from-outcomes-20261109'}}
    teammate = {'user': ANA, 'head': {'ref': 'fix-thing'}}
    assert ledger.is_agent_work(issue_work, AGENT)
    assert not ledger.is_agent_work(learning, AGENT)
    assert not ledger.is_agent_work(teammate, AGENT)
