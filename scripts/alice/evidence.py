#!/usr/bin/env python3
"""Stores verification evidence where a pull request can show it (design D30,
`docs/design.md`).

  evidence.py screenshot (--pr N | --issue N) --commit SHA FILE...
      Commits the screenshots to the `alice-evidence` branch under <pr-N|issue-N>/<sha>/<name>
      with git plumbing, so the working tree, the index and the checked-out branch are never
      touched, pushes it, and prints one embed URL per file. Embed them as
      ![caption](<url>): GitHub renders this blob URL inline in a private repository's PR, where
      a raw.githubusercontent.com link does not.

  evidence.py recording (--pr N | --issue N) --commit SHA FILE
      Uploads the recording to the evidence folder of the shared drive (`shared_drive.py`) and
      prints the file's link.
"""
import argparse
import mimetypes
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
# pylint: disable-next=wrong-import-position
from shared_drive import upload_file

REPOSITORY = os.environ.get("GH_REPO", "example-org/monorepo")
EVIDENCE_BRANCH = "alice-evidence"
PUSH_ATTEMPTS = 3
SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
COMMIT_SHA = re.compile(r"^[0-9a-f]{40}([0-9a-f]{24})?$")


def evidence_path(target, commit, file_name):
    """Returns where a file lives on the evidence branch; names must be URL-safe as they are."""
    if not COMMIT_SHA.match(commit):
        raise ValueError(f"commit must be a full SHA, got {commit!r}")
    if not SAFE_NAME.match(file_name):
        raise ValueError(f"rename {file_name!r} to letters, digits, '.', '_' and '-' only")
    return f"{target}/{commit}/{file_name}"


def embed_url(path):
    """Returns the URL a PR description embeds to show a file of the evidence branch inline."""
    return f"https://github.com/{REPOSITORY}/blob/{EVIDENCE_BRANCH}/{path}?raw=true"


def git(*arguments, environment=None, stdin=None):
    """Runs git in the current repository and returns its stripped stdout."""
    return subprocess.run(
        ["git", *arguments], check=True, capture_output=True, text=True,
        env=environment, input=stdin,
    ).stdout.strip()


def fetch_branch_tip(remote, branch):
    """Fetches a branch and returns its tip, or None while the branch does not exist."""
    if not git("ls-remote", "--heads", remote, branch):
        return None
    tracking_ref = f"refs/remotes/{remote}/{branch}"
    git("fetch", "--quiet", remote, f"+refs/heads/{branch}:{tracking_ref}")
    return git("rev-parse", tracking_ref)


def commit_on_tip(parent, files_by_path, message):
    """Builds a commit adding the files on top of parent, or an orphan when None, in a private
    index."""
    with tempfile.TemporaryDirectory() as directory:
        environment = {**os.environ, "GIT_INDEX_FILE": str(Path(directory) / "index")}
        if parent:
            git("read-tree", parent, environment=environment)
        else:
            git("read-tree", "--empty", environment=environment)
        for path, source in files_by_path.items():
            blob = git("hash-object", "-w", str(source))
            git("update-index", "--add", "--cacheinfo", f"100644,{blob},{path}",
                environment=environment)
        tree = git("write-tree", environment=environment)
    parent_arguments = ["-p", parent] if parent else []
    return git("commit-tree", tree, *parent_arguments, "-m", message)


def push_onto_branch(remote, branch, build_commit):
    """Pushes the commit build_commit makes from the branch's current tip (None while the branch
    does not exist), rebuilding it on the new tip when another session pushed in between."""
    for attempt in range(1, PUSH_ATTEMPTS + 1):
        new_tip = build_commit(fetch_branch_tip(remote, branch))
        pushed = subprocess.run(
            ["git", "push", "--quiet", remote, f"{new_tip}:refs/heads/{branch}"],
            capture_output=True, text=True, check=False,
        )
        if pushed.returncode == 0:
            return
        print(f"Push attempt {attempt} refused: {pushed.stderr.strip()}", file=sys.stderr)
    raise RuntimeError(f"could not push to {branch} after {PUSH_ATTEMPTS} attempts")


def push_screenshots(target, commit, files, remote="origin"):
    """Pushes the screenshots to the evidence branch and returns their embed URLs in order."""
    names = [Path(file).name for file in files]
    shared = sorted({name for name in names if names.count(name) > 1})
    if shared:
        raise ValueError(f"screenshots share a name, so one would replace another: "
                         f"{', '.join(shared)}; rename them")
    files_by_path = {evidence_path(target, commit, Path(file).name): Path(file) for file in files}
    message = f"Evidence for {target} at {commit[:12]}"
    push_onto_branch(remote, EVIDENCE_BRANCH,
                     lambda tip: commit_on_tip(tip, files_by_path, message))
    return [embed_url(path) for path in files_by_path]


def upload_recording(target, commit, file):
    """Uploads a recording to the evidence folder and returns its link."""
    source = Path(file)
    mime_type = mimetypes.guess_type(source.name)[0]
    if not mime_type:
        raise ValueError(f"unknown media type for {source.name}")
    return upload_file(f"{target}-{commit[:12]}-{source.name}", source.read_bytes(), mime_type)


def main():
    """Runs the command-line interface."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("screenshot", "recording"):
        command = commands.add_parser(name)
        owner = command.add_mutually_exclusive_group(required=True)
        owner.add_argument("--pr", type=int)
        owner.add_argument("--issue", type=int)
        command.add_argument("--commit", required=True,
                             help="the commit the evidence verified (any revision)")
        command.add_argument("files", nargs="+" if name == "screenshot" else 1)
    arguments = parser.parse_args()

    target = f"pr-{arguments.pr}" if arguments.pr else f"issue-{arguments.issue}"
    commit = git("rev-parse", "--verify", f"{arguments.commit}^{{commit}}")
    if arguments.command == "screenshot":
        print("\n".join(push_screenshots(target, commit, arguments.files)))
    else:
        print(upload_recording(target, commit, arguments.files[0]))


if __name__ == "__main__":
    main()
