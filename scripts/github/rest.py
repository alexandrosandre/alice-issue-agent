#!/usr/bin/env python3
"""GitHub pull-request operations for the PR skills, over REST.

Claude Code cloud sessions (CLAUDE_CODE_REMOTE=true) reach GitHub through Anthropic's proxy,
which refuses GraphQL, so `gh pr ...`, `gh issue list` and `gh api graphql` fail there while
`gh api` REST works. The proxy adds REST routes for the GraphQL-only operations: review-thread
state, thread resolution and ready-for-review (`/pulls/{n}/ccr/...`). Locally those three
operations use GraphQL; everything else is the same REST call in both places, and every command
prints the same JSON shape in both places.

The proxy also serves `/pulls/{n}/ccr/auto_merge`, which nothing here calls: `pr-merge` merges
now, pinned to the head the caller checked, and only /lgtm runs it.

Usage: python3 scripts/github/rest.py <command> [args]   (run with --help for the list)
The repository comes from GH_REPO (owner/name) or the `origin` remote.
"""
import argparse
import json
import os
import re
import subprocess
import sys

# A line declares the link (AGENTS.md, one line per issue), after a list marker or bold;
# the same words inside a sentence, a quote or a parenthesis ("does not fix #N") do not.
LINKED_ISSUE_PATTERN = re.compile(
    r"^[ \t]*(?:[-*+][ \t]+)?(?:\*\*|__)?(?:fix(?:e[sd])?|close[sd]?|resolve[sd]?|part of)"
    r"[ \t]*:?[ \t]*#(\d+)",
    re.IGNORECASE | re.MULTILINE,
)

GRAPHQL_REVIEW_THREADS = """
query($owner: String!, $name: String!, $number: Int!, $endCursor: String) {
  repository(owner: $owner, name: $name) {
    pullRequest(number: $number) {
      reviewThreads(first: 100, after: $endCursor) {
        nodes {
          id
          isResolved
          isOutdated
          path
          line
          comments(first: 1) { nodes { databaseId } }
        }
        pageInfo { hasNextPage endCursor }
      }
    }
  }
}
"""

GRAPHQL_RESOLVE_THREAD = """
mutation($threadId: ID!) {
  resolveReviewThread(input: {threadId: $threadId}) { thread { isResolved } }
}
"""


def is_cloud_session():
    return os.environ.get("CLAUDE_CODE_REMOTE") == "true"


def parse_repository(remote_url):
    """Return `owner/name` from a git remote URL (SSH, HTTPS, or the cloud session's proxy)."""
    path = re.sub(r"\.git$", "", remote_url.strip().rstrip("/"))
    segments = re.split(r"[/:]", path)
    return f"{segments[-2]}/{segments[-1]}"


def repository():
    if os.environ.get("GH_REPO"):
        return os.environ["GH_REPO"]
    remote = subprocess.run(
        ["git", "remote", "get-url", "origin"], capture_output=True, text=True, check=True
    )
    return parse_repository(remote.stdout)


def current_branch():
    return subprocess.run(
        ["git", "branch", "--show-current"], capture_output=True, text=True, check=True
    ).stdout.strip()


def gh(arguments, payload=None):
    result = subprocess.run(
        ["gh", *arguments],
        input=json.dumps(payload) if payload is not None else None,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        sys.exit(f"gh {' '.join(arguments)} failed: {result.stderr.strip() or result.stdout}")
    return result.stdout


def api(path, method="GET", payload=None):
    arguments = ["api", "-X", method, path]
    if payload is not None:
        arguments += ["--input", "-"]
    output = gh(arguments, payload)
    return json.loads(output) if output.strip() else None


def api_list(path, items=".[]"):
    """Every item of a paginated REST list; `items` is the jq path to the page's items."""
    output = gh(["api", "--paginate", path, "--jq", items])
    return [json.loads(line) for line in output.splitlines() if line.strip()]


# Shape normalization: pure functions.


def pull_state(pull):
    if pull.get("merged") or pull.get("merged_at"):
        return "MERGED"
    return pull["state"].upper()


def mergeable_state(mergeable):
    """REST `mergeable` is null while GitHub computes it; gh reports that as UNKNOWN."""
    if mergeable is None:
        return "UNKNOWN"
    return "MERGEABLE" if mergeable else "CONFLICTING"


def linked_issue_numbers(body):
    numbers = []
    for match in LINKED_ISSUE_PATTERN.finditer(body or ""):
        number = int(match.group(1))
        if number not in numbers:
            numbers.append(number)
    return numbers


def normalize_pull(pull, linked_issues):
    """A REST pull request in the field names of `gh pr view --json`."""
    return {
        "number": pull["number"],
        "url": pull["html_url"],
        "title": pull["title"],
        "body": pull["body"] or "",
        "state": pull_state(pull),
        "isDraft": pull["draft"],
        "mergeable": mergeable_state(pull.get("mergeable")),
        "headRefName": pull["head"]["ref"],
        "headRefOid": pull["head"]["sha"],
        "baseRefName": pull["base"]["ref"],
        "author": {"login": pull["user"]["login"]},
        "linkedIssues": linked_issues,
    }


def check_run_state(check_run):
    """The `state` `gh pr checks` shows: the conclusion once completed, else the status."""
    if check_run["status"] == "completed":
        return check_run["conclusion"].upper()
    return check_run["status"].upper()


def normalize_checks(check_runs, statuses):
    checks = [
        {"name": run["name"], "state": check_run_state(run), "link": run["details_url"]}
        for run in check_runs
    ]
    checks += [
        {"name": status["context"], "state": status["state"].upper(), "link": status["target_url"]}
        for status in statuses
    ]
    return sorted(checks, key=lambda check: check["name"].lower())


def normalize_run(run):
    """A REST workflow run in the field names of `gh run list --json`."""
    return {
        "databaseId": run["id"],
        "name": run["name"],
        "status": run["status"],
        "conclusion": run["conclusion"] or "",
        "url": run["html_url"],
        "headSha": run["head_sha"],
    }


def normalize_comment(comment):
    return {
        "databaseId": comment["id"],
        "author": {"login": comment["user"]["login"]},
        "authorType": comment["user"]["type"],
        "body": comment["body"],
        "createdAt": comment["created_at"],
        "updatedAt": comment["updated_at"],
        "url": comment["html_url"],
    }


def threads_from_ccr(ccr_threads, review_comments):
    """Thread state from the proxy's `ccr/review_threads` route.

    Observed shape: a JSON array of `{"resolved", "outdated", "path", "line", "comment_ids"}`.
    The root comment is the listed comment that replies to nothing; `comment_ids` order was not
    observed with replies.
    """
    in_reply_to = {comment["id"]: comment.get("in_reply_to_id") for comment in review_comments}
    threads = []
    for thread in ccr_threads:
        roots = [cid for cid in thread["comment_ids"] if not in_reply_to.get(cid)]
        threads.append(
            {
                "rootCommentId": min(roots or thread["comment_ids"]),
                "isResolved": thread["resolved"],
                "isOutdated": thread["outdated"],
                "path": thread["path"],
                "line": thread["line"],
            }
        )
    return threads


def threads_from_graphql(nodes):
    return [
        {
            "rootCommentId": node["comments"]["nodes"][0]["databaseId"],
            "isResolved": node["isResolved"],
            "isOutdated": node["isOutdated"],
            "path": node["path"],
            "line": node["line"],
        }
        for node in nodes
    ]


def attach_comments(threads, review_comments):
    """Each thread with its root comment and replies, oldest first, from the REST comments."""
    by_root = {}
    for comment in sorted(review_comments, key=lambda comment: comment["id"]):
        root = comment.get("in_reply_to_id") or comment["id"]
        by_root.setdefault(root, []).append(normalize_comment(comment))
    return [{**thread, "comments": by_root.get(thread["rootCommentId"], [])} for thread in threads]


def trim_issue_comment(comment):
    return {
        "id": comment["id"],
        "user": {"login": comment["user"]["login"], "type": comment["user"]["type"]},
        "body": comment["body"],
        "created_at": comment["created_at"],
        "updated_at": comment["updated_at"],
        "html_url": comment["html_url"],
    }


def trim_review(review):
    return {
        "id": review["id"],
        "user": {"login": review["user"]["login"], "type": review["user"]["type"]},
        "state": review["state"],
        "body": review["body"],
        "submitted_at": review.get("submitted_at"),
        "commit_id": review["commit_id"],
        "html_url": review["html_url"],
    }


# Commands.


def open_pull_number(repo, branch):
    owner = repo.split("/")[0]
    pulls = api_list(f"repos/{repo}/pulls?state=open&head={owner}:{branch}&per_page=100")
    return pulls[0]["number"] if pulls else None


def resolve_number(repo, number):
    if number:
        return number
    branch = current_branch()
    found = open_pull_number(repo, branch)
    if not found:
        sys.exit(f"No open pull request for branch {branch}.")
    return found


def view_pull(repo, number):
    pull = api(f"repos/{repo}/pulls/{number}")
    linked = [
        {"number": issue, "title": api(f"repos/{repo}/issues/{issue}")["title"]}
        for issue in linked_issue_numbers(pull["body"])
    ]
    return normalize_pull(pull, linked)


def review_threads(repo, number):
    review_comments = api_list(f"repos/{repo}/pulls/{number}/comments?per_page=100")
    if is_cloud_session():
        threads = threads_from_ccr(
            api_list(f"repos/{repo}/pulls/{number}/ccr/review_threads"), review_comments
        )
    else:
        threads = threads_from_graphql(graphql_thread_nodes(repo, number))
    return attach_comments(threads, review_comments)


def graphql_thread_nodes(repo, number):
    owner, name = repo.split("/")
    output = gh(
        [
            "api", "graphql", "--paginate",
            "-f", f"query={GRAPHQL_REVIEW_THREADS}",
            "-F", f"owner={owner}", "-F", f"name={name}", "-F", f"number={number}",
            "--jq", ".data.repository.pullRequest.reviewThreads.nodes[]",
        ]
    )
    return [json.loads(line) for line in output.splitlines() if line.strip()]


def resolve_thread(repo, number, root_comment_id):
    if is_cloud_session():
        api(f"repos/{repo}/pulls/{number}/ccr/comments/{root_comment_id}/resolve", "POST")
        return
    # Thread node IDs are looked up at resolve time, never cached (they change as threads move).
    for node in graphql_thread_nodes(repo, number):
        if node["comments"]["nodes"][0]["databaseId"] == root_comment_id:
            gh(["api", "graphql", "-f", f"query={GRAPHQL_RESOLVE_THREAD}",
                "-f", f"threadId={node['id']}"])
            return
    sys.exit(f"No review thread starts with comment {root_comment_id} on #{number}.")


def mark_ready(repo, number):
    if is_cloud_session():
        api(f"repos/{repo}/pulls/{number}/ccr/ready_for_review", "POST")
    else:
        gh(["pr", "ready", str(number), "--repo", repo])


def read_file(path):
    with open(path, encoding="utf-8") as file:
        return file.read()


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n", maxsplit=1)[0])
    commands = parser.add_subparsers(dest="command", required=True)

    find = commands.add_parser(
        "pr-for-branch", help="print the open PR's number for a branch, or nothing"
    )
    find.add_argument("branch", nargs="?")

    view = commands.add_parser("pr-view", help="PR fields as `gh pr view --json` names them")
    view.add_argument("number", nargs="?", type=int, help="default: the current branch's open PR")

    create = commands.add_parser(
        "pr-create", help="open a draft PR for the current (pushed) branch; prints its URL"
    )
    create.add_argument("--title-file", required=True)
    create.add_argument("--body-file", required=True)
    create.add_argument("--base", default="master")

    edit = commands.add_parser("pr-edit", help="replace a PR's title and body; prints its URL")
    edit.add_argument("number", type=int)
    edit.add_argument("--title-file", required=True)
    edit.add_argument("--body-file", required=True)

    for name, help_text in [
        ("pr-ready", "mark a draft PR ready for review"),
        ("checks", "check runs and commit statuses on the PR head, as `gh pr checks` states"),
        ("runs", "workflow runs on the PR head, as `gh run list --json` names them"),
        ("threads", "review threads with resolved/outdated state and their comments"),
        ("comments", "general (issue) comments on the PR"),
        ("reviews", "review summaries on the PR"),
    ]:
        command = commands.add_parser(name, help=help_text)
        command.add_argument("number", nargs="?", type=int)

    resolve = commands.add_parser("resolve-thread", help="resolve the thread a comment starts")
    resolve.add_argument("number", type=int)
    resolve.add_argument("root_comment_id", type=int)

    reviewers = commands.add_parser("request-reviewers", help="request review from people")
    reviewers.add_argument("number", type=int)
    reviewers.add_argument("logins", nargs="+")

    merge = commands.add_parser(
        "pr-merge", help="squash-merge a PR only while its head is the given commit"
    )
    merge.add_argument("number", type=int)
    merge.add_argument("head_sha")

    args = parser.parse_args()
    repo = repository()
    result = None

    if args.command == "pr-for-branch":
        number = open_pull_number(repo, args.branch or current_branch())
        print(number or "")
        return
    if args.command == "pr-create":
        pull = api(
            f"repos/{repo}/pulls",
            "POST",
            {
                "title": read_file(args.title_file).strip(),
                "body": read_file(args.body_file),
                "head": current_branch(),
                "base": args.base,
                "draft": True,
            },
        )
        print(pull["html_url"])
        return
    if args.command == "pr-edit":
        pull = api(
            f"repos/{repo}/pulls/{args.number}",
            "PATCH",
            {"title": read_file(args.title_file).strip(), "body": read_file(args.body_file)},
        )
        print(pull["html_url"])
        return
    if args.command == "resolve-thread":
        resolve_thread(repo, args.number, args.root_comment_id)
        return
    if args.command == "request-reviewers":
        api(f"repos/{repo}/pulls/{args.number}/requested_reviewers", "POST",
            {"reviewers": args.logins})
        return
    if args.command == "pr-merge":
        # GitHub refuses the merge when the head moved past head_sha, as `--match-head-commit` does.
        result = api(f"repos/{repo}/pulls/{args.number}/merge", "PUT",
                     {"merge_method": "squash", "sha": args.head_sha})
        print(result["sha"])
        return

    number = resolve_number(repo, args.number)
    if args.command == "pr-view":
        result = view_pull(repo, number)
    elif args.command == "pr-ready":
        mark_ready(repo, number)
        return
    elif args.command == "checks":
        sha = api(f"repos/{repo}/pulls/{number}")["head"]["sha"]
        result = normalize_checks(
            api_list(f"repos/{repo}/commits/{sha}/check-runs?per_page=100", ".check_runs[]"),
            api(f"repos/{repo}/commits/{sha}/status")["statuses"],
        )
    elif args.command == "runs":
        sha = api(f"repos/{repo}/pulls/{number}")["head"]["sha"]
        runs = api_list(f"repos/{repo}/actions/runs?head_sha={sha}&per_page=100",
                        ".workflow_runs[]")
        result = [normalize_run(run) for run in runs]
    elif args.command == "threads":
        result = review_threads(repo, number)
    elif args.command == "comments":
        comments = api_list(f"repos/{repo}/issues/{number}/comments?per_page=100")
        result = [trim_issue_comment(comment) for comment in comments]
    elif args.command == "reviews":
        reviews = api_list(f"repos/{repo}/pulls/{number}/reviews?per_page=100")
        result = [trim_review(review) for review in reviews]
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
