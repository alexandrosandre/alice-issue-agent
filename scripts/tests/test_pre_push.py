"""Tests for Alice's pre-push hook, which refuses pushes that change CI workflow files."""
import shutil
import subprocess
from pathlib import Path

import pytest

HOOK = Path(__file__).resolve().parents[1] / "alice/pre-push"
GIT_IDENTITY = {
    "GIT_AUTHOR_NAME": "Alice", "GIT_AUTHOR_EMAIL": "alice@example.test",
    "GIT_COMMITTER_NAME": "Alice", "GIT_COMMITTER_EMAIL": "alice@example.test",
}


def git(directory, *arguments):
    """Runs git in a test repository; returns the completed process without raising."""
    return subprocess.run(["git", "-C", str(directory), *arguments], capture_output=True,
                          text=True, check=False)


def commit_file(directory, path, content):
    """Writes a file and commits it."""
    (directory / path).parent.mkdir(parents=True, exist_ok=True)
    (directory / path).write_text(content)
    git(directory, "add", path)
    assert git(directory, "commit", "--quiet", "-m", f"change {path}").returncode == 0


@pytest.fixture(name="clone")
def fixture_clone(tmp_path, monkeypatch):
    """A clone of a bare remote whose master already holds a workflow, with the hook installed."""
    for name, value in GIT_IDENTITY.items():
        monkeypatch.setenv(name, value)
    remote = tmp_path / "remote.git"
    clone = tmp_path / "clone"
    git(tmp_path, "init", "--quiet", "--bare", "--initial-branch=master", str(remote))
    git(tmp_path, "clone", "--quiet", str(remote), str(clone))
    git(clone, "checkout", "--quiet", "-b", "master")
    commit_file(clone, ".github/workflows/ci.yml", "on: push\n")
    assert git(clone, "push", "--quiet", "origin", "master").returncode == 0
    hooks = Path(git(clone, "rev-parse", "--git-path", "hooks").stdout.strip())
    shutil.copy(HOOK, clone / hooks / "pre-push")
    git(clone, "checkout", "--quiet", "-b", "alice-1-fix")
    return clone


@pytest.mark.parametrize("path", [".github/workflows/ci.yml", ".github/actions/x/action.yml"])
def test_new_branch_changing_workflow_or_action_files_is_refused(clone, path):
    """A first push of a branch whose commits touch workflow or action files is refused."""
    commit_file(clone, "app.py", "print(1)\n")
    commit_file(clone, path, "changed\n")

    pushed = git(clone, "push", "origin", "alice-1-fix")

    assert pushed.returncode != 0
    assert "refused" in pushed.stderr and path in pushed.stderr


def test_later_push_is_refused_only_for_its_own_workflow_commits(clone):
    """On an existing branch only the commits not yet on the remote are checked."""
    commit_file(clone, "app.py", "print(1)\n")
    assert git(clone, "push", "--quiet", "origin", "alice-1-fix").returncode == 0
    commit_file(clone, "app.py", "print(2)\n")
    assert git(clone, "push", "--quiet", "origin", "alice-1-fix").returncode == 0
    commit_file(clone, ".github/workflows/ci.yml", "on: pull_request\n")
    workflow_commit = git(clone, "rev-parse", "--short=12", "HEAD").stdout.strip()

    pushed = git(clone, "push", "origin", "alice-1-fix")

    assert pushed.returncode != 0
    blocked_lines = [line for line in pushed.stderr.splitlines() if "ci.yml" in line]
    assert blocked_lines == [f"  {workflow_commit} .github/workflows/ci.yml"]


def test_merging_master_that_changed_a_workflow_is_allowed(clone):
    """A clean merge of master's own workflow change is not the branch's change, so it passes."""
    commit_file(clone, "app.py", "print(1)\n")
    assert git(clone, "push", "--quiet", "origin", "alice-1-fix").returncode == 0
    git(clone, "checkout", "--quiet", "master")
    commit_file(clone, ".github/workflows/ci.yml", "on: [push, pull_request]\n")
    # A person's push to master; this bypasses the hook as the ruleset's bypass list does.
    assert git(clone, "push", "--quiet", "--no-verify", "origin", "master").returncode == 0
    git(clone, "checkout", "--quiet", "alice-1-fix")
    assert git(clone, "merge", "--quiet", "--no-edit", "origin/master").returncode == 0

    pushed = git(clone, "push", "origin", "alice-1-fix")

    assert pushed.returncode == 0, pushed.stderr
