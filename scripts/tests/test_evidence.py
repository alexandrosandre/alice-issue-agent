"""Tests for the evidence helpers: branch paths and the evidence-branch push."""
import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "alice/evidence.py"
SPEC = importlib.util.spec_from_file_location("evidence", SCRIPT)
evidence = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = evidence
SPEC.loader.exec_module(evidence)

SHA = "0123456789abcdef0123456789abcdef01234567"
GIT_IDENTITY = {
    "GIT_AUTHOR_NAME": "Alice", "GIT_AUTHOR_EMAIL": "alice@example.test",
    "GIT_COMMITTER_NAME": "Alice", "GIT_COMMITTER_EMAIL": "alice@example.test",
}


def run_git(directory, *arguments):
    """Runs git in a test repository and returns its stripped stdout."""
    return subprocess.run(["git", "-C", str(directory), *arguments], check=True,
                          capture_output=True, text=True).stdout.strip()


def test_evidence_path_names_target_and_commit_and_refuses_unsafe_names():
    """Paths group evidence by PR and verified commit, and refuse names a URL would mangle."""
    path = evidence.evidence_path("issue-812", SHA, "after-save.png")
    assert path == f"issue-812/{SHA}/after-save.png"
    assert evidence.embed_url("pr-9/x.png") == (
        "https://github.com/example-org/monorepo/blob/alice-evidence/pr-9/x.png?raw=true"
    )
    with pytest.raises(ValueError, match="rename"):
        evidence.evidence_path("pr-9", SHA, "after save.png")
    with pytest.raises(ValueError, match="full SHA"):
        evidence.evidence_path("pr-9", "HEAD", "after.png")


def test_screenshots_reach_the_evidence_branch_without_touching_the_checkout(
        tmp_path, monkeypatch):
    """The first push creates an orphan branch, the next one adds to it, and the checkout,
    its index and its branch stay as they were."""
    remote = tmp_path / "remote.git"
    clone = tmp_path / "clone"
    run_git(tmp_path, "init", "--quiet", "--bare", str(remote))
    run_git(tmp_path, "clone", "--quiet", str(remote), str(clone))
    for name, value in GIT_IDENTITY.items():
        monkeypatch.setenv(name, value)
    (clone / "app.txt").write_text("app\n")
    run_git(clone, "add", "app.txt")
    run_git(clone, "commit", "--quiet", "-m", "app")
    run_git(clone, "push", "--quiet", "origin", "HEAD:refs/heads/master")
    (clone / "staged.txt").write_text("work in progress\n")
    run_git(clone, "add", "staged.txt")
    head_before = run_git(clone, "rev-parse", "HEAD")
    first = tmp_path / "before.png"
    second = tmp_path / "after.png"
    first.write_bytes(b"png one")
    second.write_bytes(b"png two")
    monkeypatch.chdir(clone)

    urls = evidence.push_screenshots("pr-7", SHA, [first])
    evidence.push_screenshots("pr-7", SHA, [second])

    assert urls == [evidence.embed_url(f"pr-7/{SHA}/before.png")]
    files = run_git(remote, "ls-tree", "-r", "--name-only", "alice-evidence").splitlines()
    assert files == [f"pr-7/{SHA}/after.png", f"pr-7/{SHA}/before.png"]
    assert run_git(remote, "rev-list", "--count", "alice-evidence") == "2"
    assert run_git(clone, "rev-parse", "HEAD") == head_before
    assert run_git(clone, "status", "--porcelain") == "A  staged.txt"


def test_screenshots_sharing_a_name_are_refused(tmp_path, monkeypatch):
    """Two files with one name would land on one path and the first would be lost silently."""
    monkeypatch.chdir(tmp_path)  # outside any repository, so nothing can reach a remote
    for folder in ("before", "after"):
        (tmp_path / folder).mkdir()
        (tmp_path / folder / "home.png").write_bytes(b"png")
    with pytest.raises(ValueError, match="home.png"):
        evidence.push_screenshots(
            "pr-7", SHA, [tmp_path / "before/home.png", tmp_path / "after/home.png"])
