#!/usr/bin/env python3
"""Alice's memory: one-line facts she learned on earlier issues, kept as MEMORY.md on the
`alice-memory` branch (design D41, `docs/design.md`).

  memory.py show                    print the memory file as it is
  memory.py add --source "#N"       remember the fact on stdin as "- FACT (YYYY-MM-DD, #N)",
                                    from issue or PR N
  memory.py remove                  forget the line holding the fact on stdin, given bare or as
                                    `show` prints the line

The fact comes on stdin, from a quoted heredoc (<<'EOF'), so no shell ever expands text that
came from an earlier session. Quote the source: an unquoted #N starts a shell comment.

Each change is one commit built on the branch's latest tip with git plumbing, so sessions running
at once never overwrite each other's lines and the checkout is never touched.
"""
import argparse
import re
import subprocess
import sys
import tempfile
import unicodedata
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
# pylint: disable-next=wrong-import-position
from evidence import commit_on_tip, fetch_branch_tip, push_onto_branch

MEMORY_BRANCH = "alice-memory"
MEMORY_FILE = "MEMORY.md"
# A cap keeps the file short enough to read whole at every session start: adding past it means
# choosing a line to drop first.
MAX_LINES = 50
MAX_FACT_LENGTH = 300
HEADER = ("# Alice's memory\n\nFacts Alice learned on earlier issues, each a claim to check before "
          "relying on it (`alice` skill, Memory).\n")
SOURCE = re.compile(r"#\d+")
# Alice's lines end in their date and source; a line a person wrote by hand may not.
DATED_LINE = re.compile(r"- (?P<fact>.+) \(\d{4}-\d{2}-\d{2}, #\d+\)")


def read_file(tip):
    """Returns the memory file's lines at a branch tip exactly as written, or the header's while
    the branch or its file does not exist."""
    if tip is None:
        return HEADER.split("\n")
    path = f"{tip}:{MEMORY_FILE}"
    if subprocess.run(["git", "cat-file", "-e", path], capture_output=True, check=False).returncode:
        return HEADER.split("\n")
    # Not evidence.git(), which strips the output and would drop the file's final newline.
    return subprocess.run(["git", "show", path], check=True, capture_output=True,
                          text=True).stdout.split("\n")


def line_fact(line):
    """Returns the fact a remembered line holds, without its date and source."""
    dated = DATED_LINE.fullmatch(line)
    return dated.group("fact") if dated else line[2:]


def added(file_lines, fact, source, today):
    """Returns the file's lines with the fact appended, refusing a duplicate, a full memory or a
    fact that is not one visible line."""
    if not fact.strip() or fact.splitlines() != [fact] or len(fact) > MAX_FACT_LENGTH:
        raise ValueError(f"a fact is one line of at most {MAX_FACT_LENGTH} characters")
    # Format characters display as nothing on GitHub yet reach every later session.
    if any(unicodedata.category(character) in ("Cc", "Cf") for character in fact):
        raise ValueError("a fact carries no invisible characters")
    if not SOURCE.fullmatch(source):
        raise ValueError(f"the source is #<issue or PR number>, got {source!r}")
    facts = [line for line in file_lines if line.startswith("- ")]
    if any(line_fact(line) == fact for line in facts):
        raise ValueError("that fact is already remembered")
    if len(facts) >= MAX_LINES:
        raise ValueError(f"memory holds {MAX_LINES} lines: remove the least useful one first")
    kept = file_lines[:-1] if file_lines and not file_lines[-1] else file_lines
    return kept + [f"- {fact} ({today.isoformat()}, {source})", ""]


def removed(file_lines, fact):
    """Returns the file's lines without the line holding the fact: any line equal to it, or a
    `- ` line holding it without its date and source. Every other line stays as written."""
    if not fact.strip():
        raise ValueError("name the fact or line to remove")
    kept = [line for line in file_lines
            if line != fact and not (line.startswith("- ") and line_fact(line) == fact)]
    if len(kept) == len(file_lines):
        raise ValueError(f"no remembered line holds {fact!r}")
    return kept


def change_memory(apply, message, remote="origin"):
    """Applies a change to the file's lines on the branch's latest tip and pushes it."""
    def build(tip):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / MEMORY_FILE
            path.write_text("\n".join(apply(read_file(tip))))
            return commit_on_tip(tip, {MEMORY_FILE: path}, message)

    push_onto_branch(remote, MEMORY_BRANCH, build)


def main():
    """Runs the command-line interface."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("show", help="print the memory file as it is")
    add_parser = commands.add_parser("add", help="remember the fact on stdin")
    add_parser.add_argument("--source", required=True)
    commands.add_parser("remove", help="forget the fact on stdin")
    arguments = parser.parse_args()
    fact = sys.stdin.read().removesuffix("\n") if arguments.command != "show" else None

    try:
        if arguments.command == "show":
            print("\n".join(read_file(fetch_branch_tip("origin", MEMORY_BRANCH))))
        elif arguments.command == "add":
            today = date.today()
            # The message leaves the fact out, so a removed line does not live on in it.
            change_memory(lambda lines: added(lines, fact, arguments.source, today),
                          f"Remember a fact from {arguments.source}")
        else:
            change_memory(lambda lines: removed(lines, fact), "Forget a fact")
    except ValueError as error:
        sys.exit(str(error))


if __name__ == "__main__":
    main()
