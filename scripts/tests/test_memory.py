"""Tests for Alice's memory: lines added and removed on the memory branch, sessions at once."""
import importlib.util
import subprocess
import sys
from datetime import date
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "alice/memory.py"
SPEC = importlib.util.spec_from_file_location("memory", SCRIPT)
memory = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = memory
SPEC.loader.exec_module(memory)

GIT_IDENTITY = {
    "GIT_AUTHOR_NAME": "Alice", "GIT_AUTHOR_EMAIL": "alice@example.test",
    "GIT_COMMITTER_NAME": "Alice", "GIT_COMMITTER_EMAIL": "alice@example.test",
}
TODAY = date(2026, 10, 31)


def run_git(directory, *arguments):
    """Runs git in a test repository and returns its stripped stdout."""
    return subprocess.run(["git", "-C", str(directory), *arguments], check=True,
                          capture_output=True, text=True).stdout.strip()


def current_file():
    """The memory file's lines at the remote branch's tip."""
    return memory.read_file(memory.fetch_branch_tip("origin", memory.MEMORY_BRANCH))


def test_two_sessions_add_and_remove_lines_without_losing_each_others(tmp_path, monkeypatch):
    """Each change builds on the branch's latest tip, so every session's line lands, removing one
    leaves the others, and a line a person wrote stays as written."""
    remote = tmp_path / "remote.git"
    run_git(tmp_path, "init", "--quiet", "--bare", str(remote))
    first, second = tmp_path / "first", tmp_path / "second"
    run_git(tmp_path, "clone", "--quiet", str(remote), str(first))
    run_git(tmp_path, "clone", "--quiet", str(remote), str(second))
    for name, value in GIT_IDENTITY.items():
        monkeypatch.setenv(name, value)

    def change(clone, apply):
        monkeypatch.chdir(clone)
        memory.change_memory(apply, "change")

    change(first, lambda lines: lines + ["- never run X on staging", ""])
    change(second, lambda lines: memory.added(lines, "the stack compiles slowly", "#1", TODAY))
    change(first, lambda lines: memory.added(lines, "pushes need the noreply address", "#2",
                                             TODAY))
    change(second, lambda lines: memory.removed(lines, "- the stack compiles slowly "
                                                       "(2026-10-31, #1)"))

    assert [line for line in current_file() if line.startswith("- ")] == [
        "- never run X on staging", "- pushes need the noreply address (2026-10-31, #2)"]
    assert run_git(remote, "rev-list", "--count", memory.MEMORY_BRANCH) == "4"


@pytest.mark.parametrize(("fact", "source", "message"), [
    ("two\nlines", "#1", "one line"),
    ("a fact\n", "#1", "one line"),
    ("a hidden\u200bfact", "#1", "invisible"),
    ("a fact", "4242", "the source is"),
])
def test_a_fact_that_is_not_one_visible_line_or_lacks_a_source_is_refused(fact, source, message):
    """A fact is one line a person reading the file sees whole, with the issue it came from."""
    with pytest.raises(ValueError, match=message):
        memory.added([], fact, source, TODAY)


def test_a_duplicate_or_a_fact_past_the_cap_is_refused():
    """Facts never repeat, and a full memory makes room before it takes another."""
    with pytest.raises(ValueError, match="already remembered"):
        memory.added(["- a fact (2026-10-01, #1)"], "a fact", "#2", TODAY)
    full = [f"- fact {number} (2026-10-01, #1)" for number in range(memory.MAX_LINES)]
    with pytest.raises(ValueError, match="remove the least"):
        memory.added(full, "one more", "#2", TODAY)


def test_removing_a_fact_no_line_holds_is_refused():
    """A typo in a removal fails loudly instead of leaving the wrong line in place."""
    with pytest.raises(ValueError, match="no remembered line"):
        memory.removed(["- a fact (2026-10-01, #1)"], "a fcat")
    with pytest.raises(ValueError, match="name the fact"):
        memory.removed(["# Alice's memory", "", "- a fact (2026-10-01, #1)", ""], "")


def test_any_line_can_be_removed_and_the_rest_stays_byte_for_byte(tmp_path, monkeypatch):
    """A line a person wrote in another form is removable too, and a removal keeps every other
    line and the final newline as written."""
    remote = tmp_path / "remote.git"
    clone = tmp_path / "clone"
    run_git(tmp_path, "init", "--quiet", "--bare", str(remote))
    run_git(tmp_path, "clone", "--quiet", str(remote), str(clone))
    for name, value in GIT_IDENTITY.items():
        monkeypatch.setenv(name, value)
    monkeypatch.chdir(clone)
    written = ["# Alice's memory", "", "* never run X", "- a fact (2026-10-01, #1)", ""]
    memory.change_memory(lambda lines: written, "by hand")

    memory.change_memory(lambda lines: memory.removed(lines, "* never run X"), "remove")

    tip = memory.fetch_branch_tip("origin", memory.MEMORY_BRANCH)
    assert run_git(clone, "show", f"{tip}:{memory.MEMORY_FILE}") + "\n" == (
        "# Alice's memory\n\n- a fact (2026-10-01, #1)\n")
    assert memory.read_file(tip)[-1] == ""
