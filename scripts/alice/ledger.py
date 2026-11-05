#!/usr/bin/env python3
"""Alice's outcome ledger: what became of each issue she worked and each PR she opened.

Built from GitHub alone (design: `docs/design.md`, D12), through
repository-scoped REST calls that Claude Code's GitHub proxy also serves (no GraphQL, no search).
Read-only. Per agent PR it records the outcome 30 days on (merged, reverted, closed, or still
open), days to merge, review rounds, human follow-up commits, and the risk level the PR
declared; per issue, whether it ended in a merged PR, and the merge rate per issue type.

Usage:
    python scripts/alice/ledger.py --since 2026-01-01           # text report
    python scripts/alice/ledger.py --since 2026-01-01 --json    # one JSON document
    python scripts/alice/ledger.py --since 2026-01-01 --agent someone   # another author's PRs

An issue is Alice's when it is assigned to her or one of her PRs names it (`Fixes #n`,
`Part of #n`). A PR counts as reverted when a merged PR reverts it, or a master commit reverts
its merge commit, within 30 days of its merge. Besides the PRs opened since `--since`, the ledger
lists the agent's older PRs that a revert in that window undid, so a weekly run that starts where
the last one stopped still sees a revert that came after it; they are marked and left out of the
window's figures and issues, which earlier runs counted.
"""

import argparse
import json
import os
import re
import subprocess
import sys
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, Iterable, List, Optional, Set, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'github'))
# pylint: disable-next=wrong-import-position
from rest import linked_issue_numbers

REPO = os.environ.get('GH_REPO', 'example-org/monorepo')
AGENT = 'alice-bot'
OUTCOME_WINDOW = timedelta(days=30)
# Triage's type labels (D13), in the order a multi-labeled issue is classed by.
ISSUE_TYPES = ['Bug', 'Enhancement', 'Chore', 'Proposal', 'Epic']
LEVELS = ['Low', 'Moderate', 'Elevated', 'High']

_RISK_SECTION = re.compile(r'^#{1,6}\s*Risk\b.*?(?=^#{1,6}\s|\Z)', re.IGNORECASE | re.MULTILINE
                           | re.DOTALL)
_RISK_TITLE = re.compile(r'\bRisk \d of \d \((Low|Moderate|Elevated|High)\)', re.IGNORECASE)
_REVERTS_PR = re.compile(r'\bReverts\s+(?:[\w.-]+/[\w.-]+)?#(\d+)', re.IGNORECASE)
_REVERTS_COMMIT = re.compile(r'This reverts commit ([0-9a-f]{7,40})', re.IGNORECASE)
# A squash merge's title ends in `(#n)`, and a revert keeps it at the end of its own title.
_PR_NUMBER_IN_TITLE = re.compile(r'\(#(\d+)\)"?\s*$')


@dataclass
class DeclaredLevel:
    """The risk level a PR declared in its Risk section, if any."""
    level: Optional[str]


@dataclass
class PullRequestOutcome:
    """One agent PR, 30 days on."""
    number: int
    title: str
    url: str
    created_at: str
    outcome: str  # merged | reverted | closed | open | pending
    days_to_merge: Optional[float]
    review_rounds: int
    human_reviews: int
    human_follow_up_commits: int
    declared_level: DeclaredLevel
    linked_issues: List[int]
    # When it ended: merged or closed (closed_at), and the revert's landing when one undid it.
    closed_at: Optional[str] = None
    reverted_by: Optional[str] = None
    reverted_at: Optional[str] = None
    # Opened before the ledger's window and listed because a revert in it undid the PR.
    opened_before_window: bool = False


@dataclass
class IssueOutcome:
    """One issue Alice worked, and what her PRs for it became."""
    number: int
    title: str
    issue_type: Optional[str]
    pull_requests: List[int] = field(default_factory=list)
    outcome: str = 'no PR'  # merged | reverted | closed | open | pending | no PR


# The learning pass's branches (routines/alice-learn-from-outcomes/PROMPT.md).
LEARNING_PASS_BRANCH = 'alice-learn-from-outcomes-'


def parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace('Z', '+00:00'))


def is_bot(user: Optional[Dict[str, Any]]) -> bool:
    if not user:
        return True
    return user.get('type') == 'Bot' or user['login'].endswith('[bot]')


def is_human(user: Optional[Dict[str, Any]], agent: str) -> bool:
    """A person: not a bot, not the agent, and not a commit GitHub could not tie to an account."""
    return bool(user) and not is_bot(user) and user['login'] != agent


def linked_issues(body: Optional[str]) -> List[int]:
    """The issues a PR body's lines declare with `Fixes #n`, `Closes #n`, `Resolves #n` or
    `Part of #n`, as `scripts/github/rest.py` reads them."""
    return sorted(linked_issue_numbers(body))


def declared_level(body: Optional[str]) -> DeclaredLevel:
    """The risk level the PR's Risk section declares ("Risk n of 4 (Level)"), or None."""
    risk = _RISK_SECTION.search(body or '')
    title = _RISK_TITLE.search(risk.group(0)) if risk else None
    if not title:
        return DeclaredLevel(level=None)
    return DeclaredLevel(level=next(name for name in LEVELS
                                    if name.lower() == title.group(1).lower()))


def review_rounds(reviews: Iterable[Dict[str, Any]], agent: str) -> Tuple[int, int]:
    """Review rounds (distinct head commits someone other than the agent reviewed, bots
    included) and the number of reviews people submitted."""
    others = [review for review in reviews
              if review.get('user') and review['user']['login'] != agent]
    rounds = {review['commit_id'] for review in others if review.get('commit_id')}
    human_reviews = sum(1 for review in others if is_human(review['user'], agent))
    return len(rounds), human_reviews


def human_follow_up_commits(commits: Iterable[Dict[str, Any]], agent: str) -> int:
    """Commits a person added to the agent's PR, not counting merges of another branch in."""
    return sum(1 for commit in commits
               if len(commit.get('parents', [])) < 2 and is_human(commit.get('author'), agent))


def _reverted_numbers(revert_pull_request: Dict[str, Any]) -> Set[int]:
    """The PRs a revert PR names: `Reverts owner/repo#n` in its body, or the `(#n)` its title
    keeps from a squash merge."""
    return {int(number) for number in
            _REVERTS_PR.findall(revert_pull_request.get('body') or '')
            + _PR_NUMBER_IN_TITLE.findall(revert_pull_request['title'])}


def find_revert(pull_request: Dict[str, Any], revert_pull_requests: List[Dict[str, Any]],
                master_commits: List[Dict[str, Any]]) -> Optional[Tuple[str, str]]:
    """What reverted a merged PR within the outcome window, as a PR or commit reference, and
    when it landed."""
    if not pull_request.get('merged_at'):
        return None
    merged_at = parse_time(pull_request['merged_at'])
    deadline = merged_at + OUTCOME_WINDOW
    for candidate in revert_pull_requests:
        if not candidate.get('merged_at'):
            continue
        reverted = _reverted_numbers(candidate)
        title_match = candidate['title'].strip() == f'Revert "{pull_request["title"].strip()}"'
        if (pull_request['number'] in reverted or title_match) and (
                merged_at <= parse_time(candidate['merged_at']) <= deadline):
            return f'#{candidate["number"]}', candidate['merged_at']
    merge_sha = pull_request.get('merge_commit_sha') or ''
    for commit in master_commits:
        committed_at = parse_time(commit['commit']['committer']['date'])
        if not merged_at <= committed_at <= deadline:
            continue
        for reverted_sha in _REVERTS_COMMIT.findall(commit['commit']['message']):
            if merge_sha.startswith(reverted_sha):
                return commit['sha'][:10], commit['commit']['committer']['date']
    return None


def reverted_pull_request_numbers(revert_pull_requests: List[Dict[str, Any]],
                                  master_commits: List[Dict[str, Any]],
                                  pulls_of_commit: Callable[[str], List[int]]) -> Set[int]:
    """The PRs that merged revert PRs and master revert commits undid, as numbers."""
    numbers: Set[int] = set()
    for candidate in revert_pull_requests:
        if candidate.get('merged_at'):
            numbers.update(_reverted_numbers(candidate))
    for commit in master_commits:
        for reverted_sha in _REVERTS_COMMIT.findall(commit['commit']['message']):
            numbers.update(pulls_of_commit(reverted_sha))
    return numbers


def pull_request_outcome(pull_request: Dict[str, Any], reverted_by: Optional[str],
                         now: datetime) -> str:
    """merged, reverted or closed as decided within 30 days; open past them; pending before."""
    if reverted_by:
        return 'reverted'
    if pull_request.get('merged_at'):
        return 'merged'
    if pull_request['state'] == 'closed':
        return 'closed'
    if now - parse_time(pull_request['created_at']) < OUTCOME_WINDOW:
        return 'pending'
    return 'open'


def issue_type(labels: Iterable[Dict[str, Any]]) -> Optional[str]:
    names = {label['name'] for label in labels}
    return next((name for name in ISSUE_TYPES if name in names), None)


def issue_outcome(pull_request_outcomes: List[str], issue_state: str) -> str:
    """The issue's outcome from its PRs': a merge that held wins, then a revert, then work in
    flight, then a close. With no PR, a closed issue ended in findings or an answer (`no PR`),
    and an open one is still being worked (`pending`)."""
    for outcome in ('merged', 'reverted', 'pending', 'open', 'closed'):
        if outcome in pull_request_outcomes:
            return outcome
    return 'no PR' if issue_state == 'closed' else 'pending'


def summarize(issues: List[IssueOutcome], pull_requests: List[PullRequestOutcome]
              ) -> Dict[str, Any]:
    """The report's figures. Rates count decided issues only: pending ones have no outcome yet.
    PRs opened before the window are left out: earlier runs counted them."""
    pull_requests = [pr for pr in pull_requests if not pr.opened_before_window]
    decided = [issue for issue in issues if issue.outcome != 'pending']
    by_type: Dict[str, Counter] = defaultdict(Counter)
    for issue in decided:
        by_type[issue.issue_type or 'no type'][issue.outcome] += 1
    merged_days = [pr.days_to_merge for pr in pull_requests if pr.days_to_merge is not None]
    level_outcomes: Dict[str, Counter] = defaultdict(Counter)
    for pr in pull_requests:
        level_outcomes[pr.declared_level.level or 'undeclared'][pr.outcome] += 1
    return {
        'issues': len(issues),
        'decided_issues': len(decided),
        'issues_ending_in_merged_pr': sum(1 for issue in decided if issue.outcome == 'merged'),
        'merge_rate_by_issue_type': {
            name: {'merged': counts['merged'], 'decided': sum(counts.values())}
            for name, counts in sorted(by_type.items())},
        'pull_requests_by_outcome': dict(Counter(pr.outcome for pr in pull_requests)),
        'median_days_to_merge': sorted(merged_days)[len(merged_days) // 2] if merged_days else None,
        'outcomes_by_declared_level': {
            level: dict(counts)
            # By risk; undeclared PRs last.
            for level, counts in sorted(
                level_outcomes.items(),
                key=lambda entry: (LEVELS.index(entry[0]) if entry[0] in LEVELS else len(LEVELS),
                                   entry[0]))
        },
    }


# ── GitHub ───────────────────────────────────────────────────────────────────────────────────

def github(path: str) -> Any:
    """One REST GET through `gh api`, paginated into a single list when the answer is a list."""
    output = subprocess.run(['gh', 'api', '--paginate', '--slurp', path], check=True,
                            capture_output=True, text=True).stdout
    pages = json.loads(output)
    if pages and isinstance(pages[0], list):
        return [item for page in pages for item in page]
    return pages[0]


def github_or_none(path: str) -> Any:
    """`github(path)`, or None when GitHub refuses it (a 404 or a 422)."""
    try:
        return github(path)
    except subprocess.CalledProcessError:
        return None


def github_pages_until(path: str, since: datetime, key: str = 'created_at'
                       ) -> List[Dict[str, Any]]:
    """Pages of a newest-first list, stopping at the first item older than `since`."""
    items: List[Dict[str, Any]] = []
    page = 1
    while True:
        separator = '&' if '?' in path else '?'
        batch = json.loads(subprocess.run(
            ['gh', 'api', f'{path}{separator}per_page=100&page={page}'], check=True,
            capture_output=True, text=True).stdout)
        items.extend(item for item in batch if parse_time(item[key]) >= since)
        if len(batch) < 100 or parse_time(batch[-1][key]) < since:
            return items
        page += 1


def is_agent_work(pull_request: Dict[str, Any], agent: str) -> bool:
    """A PR the agent opened for an issue: the learning pass's own weekly PRs are not her work,
    though an Alice account opens them."""
    return (pull_request['user']['login'] == agent
            and not pull_request['head']['ref'].startswith(LEARNING_PASS_BRANCH))


def build_ledger(repo: str, agent: str, since: datetime, now: datetime
                 ) -> Tuple[List[IssueOutcome], List[PullRequestOutcome]]:
    all_pull_requests = github_pages_until(
        f'repos/{repo}/pulls?state=all&sort=created&direction=desc', since)
    agent_pull_requests = [pr for pr in all_pull_requests if is_agent_work(pr, agent)]
    revert_pull_requests = [pr for pr in all_pull_requests if pr['title'].startswith('Revert ')]
    master_commits = github(
        f'repos/{repo}/commits?sha=master&since={since.isoformat()}&per_page=100')

    opened_in_window = {pr['number'] for pr in agent_pull_requests}
    reverted = reverted_pull_request_numbers(
        revert_pull_requests, master_commits,
        lambda sha: [pr['number'] for pr in github_or_none(f'repos/{repo}/commits/{sha}/pulls')
                     or []])
    for number in sorted(reverted - opened_in_window):
        # A revert can name an issue, or a commit GitHub no longer has: those find no PR.
        older = github_or_none(f'repos/{repo}/pulls/{number}')
        if older and is_agent_work(older, agent):
            agent_pull_requests.append(older)

    pull_requests: List[PullRequestOutcome] = []
    for pr in agent_pull_requests:
        reverted_by, reverted_at = find_revert(pr, revert_pull_requests, master_commits) or (
            None, None)
        rounds, human_reviews = review_rounds(
            github(f'repos/{repo}/pulls/{pr["number"]}/reviews?per_page=100'), agent)
        commits = github(f'repos/{repo}/pulls/{pr["number"]}/commits?per_page=100')
        days_to_merge = None
        if pr.get('merged_at'):
            elapsed = parse_time(pr['merged_at']) - parse_time(pr['created_at'])
            days_to_merge = round(elapsed.total_seconds() / 86400, 1)
        pull_requests.append(PullRequestOutcome(
            number=pr['number'], title=pr['title'], url=pr['html_url'],
            created_at=pr['created_at'],
            outcome=pull_request_outcome(pr, reverted_by, now),
            days_to_merge=days_to_merge, review_rounds=rounds, human_reviews=human_reviews,
            human_follow_up_commits=human_follow_up_commits(commits, agent),
            declared_level=declared_level(pr.get('body')),
            linked_issues=linked_issues(pr.get('body')), closed_at=pr['closed_at'],
            reverted_by=reverted_by, reverted_at=reverted_at,
            opened_before_window=pr['number'] not in opened_in_window))
    in_window = [pr for pr in pull_requests if not pr.opened_before_window]

    assigned = [issue for issue in github(
        f'repos/{repo}/issues?assignee={agent}&state=all&since={since.isoformat()}&per_page=100')
        if 'pull_request' not in issue]
    issues = {issue['number']: issue for issue in assigned}
    linked: Set[int] = {number for pr in in_window for number in pr.linked_issues}
    for number in linked - issues.keys():
        issue = github(f'repos/{repo}/issues/{number}')
        if 'pull_request' not in issue:
            issues[number] = issue

    outcomes: List[IssueOutcome] = []
    for number, issue in sorted(issues.items()):
        prs = [pr for pr in in_window if number in pr.linked_issues]
        outcomes.append(IssueOutcome(
            number=number, title=issue['title'], issue_type=issue_type(issue['labels']),
            pull_requests=[pr.number for pr in prs],
            outcome=issue_outcome([pr.outcome for pr in prs], issue['state'])))
    return outcomes, pull_requests


# ── Report ───────────────────────────────────────────────────────────────────────────────────

def print_report(since: datetime, agent: str, issues: List[IssueOutcome],
                 pull_requests: List[PullRequestOutcome], summary: Dict[str, Any]):
    print(f'Alice outcome ledger: {agent}, issues and PRs since {since.date()}')
    decided = summary['decided_issues']
    merged = summary['issues_ending_in_merged_pr']
    share = f'{merged / decided:.0%}' if decided else 'n/a'
    print(f'Issues: {summary["issues"]} ({decided} decided); ending in a merged PR: '
          f'{merged}/{decided} ({share})')
    print('Merge rate by issue type (decided issues):')
    for name, counts in summary['merge_rate_by_issue_type'].items():
        print(f'  {name}: {counts["merged"]}/{counts["decided"]}')
    print(f'PRs by outcome: {summary["pull_requests_by_outcome"]}; '
          f'median days to merge: {summary["median_days_to_merge"]}')
    print('PR outcomes by declared risk level:')
    for level, counts in summary['outcomes_by_declared_level'].items():
        print(f'  {level}: {counts}')
    print('\nPRs:')
    for pr in pull_requests:
        level_text = pr.declared_level.level or 'undeclared'
        print(f'  #{pr.number} {pr.outcome}'
              + (f' by {pr.reverted_by}' if pr.reverted_by else '')
              + (' · opened before the window' if pr.opened_before_window else '')
              + f' · level {level_text} · {pr.review_rounds} review rounds'
              f' · {pr.human_reviews} human reviews'
              f' · {pr.human_follow_up_commits} human follow-up commits'
              + (f' · merged in {pr.days_to_merge} d' if pr.days_to_merge is not None else '')
              + f' · issues {pr.linked_issues or "none"} · {pr.title}')
    print('\nIssues:')
    for issue in issues:
        print(f'  #{issue.number} {issue.outcome} · {issue.issue_type or "no type"}'
              f' · PRs {issue.pull_requests or "none"} · {issue.title}')


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--since', required=True, type=datetime.fromisoformat,
                        help='Count issues updated and PRs opened from this date (YYYY-MM-DD).')
    parser.add_argument('--agent', default=AGENT, help='The PR author and issue assignee.')
    parser.add_argument('--repo', default=REPO)
    parser.add_argument('--json', action='store_true')
    arguments = parser.parse_args()
    since = arguments.since.replace(tzinfo=arguments.since.tzinfo or timezone.utc)
    now = datetime.now(timezone.utc)
    issues, pull_requests = build_ledger(arguments.repo, arguments.agent, since, now)
    summary = summarize(issues, pull_requests)
    if arguments.json:
        json.dump({'since': since.isoformat(), 'agent': arguments.agent, 'summary': summary,
                   'pull_requests': [asdict(pr) for pr in pull_requests],
                   'issues': [asdict(issue) for issue in issues]}, sys.stdout, indent=2)
        print()
    else:
        print_report(since, arguments.agent, issues, pull_requests, summary)


if __name__ == '__main__':
    main()
