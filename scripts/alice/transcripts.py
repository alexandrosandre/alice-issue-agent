#!/usr/bin/env python3
"""Alice's session transcripts, kept in the evidence folder of the shared drive for the weekly
learning pass (design D12, `docs/design.md`).

  transcripts.py hook
      The Stop hook her cloud environment's setup script installs: reads the hook's JSON on
      stdin and uploads the session's transcript as `session-<session id>.jsonl`,
      updating that file when an earlier turn created it, so each session is one file holding its
      whole transcript. It always exits 0: a failed upload must never stop her turn.
  transcripts.py list --since YYYY-MM-DD
      Prints one JSON object per transcript updated since that day: id, name, modified, size.
  transcripts.py download FILE_ID OUT
      Writes that transcript to OUT.
  transcripts.py extract TRANSCRIPT OUT_DIR [--since YYYY-MM-DD]
      Writes what a reader of the session needs into reader-sized parts, OUT_DIR/<name>.part<k>.txt,
      and prints one JSON object per part. Each numbered entry is a turn, a tool call with its
      input, or its result: errors, denials and blocking hooks in full, other results and long
      inputs cut to their first and last CUT characters. Parts break between rounds (each starts
      at a message into the session, such as a sweep round), and inside a round only when it
      alone exceeds READER_BUDGET; a part after the first opens with the session's first request.
      With --since, rounds that ended before that day are left out.
  transcripts.py show TRANSCRIPT NUMBER
      Prints that entry of the extract uncut.

Transcripts carry customer data, so they stay in the drive and the session's machine: never
in a commit, a PR or an issue (`AGENTS.md`, Customer data). Credentials are redacted before the
upload. The drive is reached through `shared_drive.py`, as `evidence.py` reaches it.
"""
import argparse
import json
import os
import re
import subprocess
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
# pylint: disable-next=wrong-import-position
from shared_drive import (DRIVE_CREDENTIAL_NAME, SECRETS_CLI, download_file, list_files,
                          replace_file, upload_file)

PREFIX = "session-"
SESSION_ID = re.compile(r"[A-Za-z0-9_-]+")
# The secrets a session reads: the drive credential and the other alice/* secrets her environment
# reads (a product-analytics read key, a database read login). Each must be readable, or the
# upload stops rather than send one unredacted. TODO: list yours.
SECRET_IDS = (DRIVE_CREDENTIAL_NAME, "alice/analytics-read-key", "alice/database-read-login")
SECRET_VARIABLE = re.compile(r"PASSWORD|SECRET|TOKEN|_KEY$|_URI$")
PRIVATE_KEY = re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----",
                         re.DOTALL)
# A password inside a connection URI (scheme://user:password@host).
URI_PASSWORD = re.compile(r"(://[^:/@\s]+:)[^@\s]+@")
CUT = 500
READER_BUDGET = 1_000_000
# Claude Code's Read tool cuts a line past 2,000 characters, so extract lines stay below it.
LINE_WIDTH = 1_000


def secret_values() -> dict[str, str]:
    """The credentials a session can hold, by name: its secret-looking environment variables, the
    secrets in SECRET_IDS and their secret fields. Raises RuntimeError when one cannot be read."""
    values = {name: value for name, value in os.environ.items()
              if SECRET_VARIABLE.search(name) and len(value) >= 8}
    for secret_id in SECRET_IDS:
        read = subprocess.run([SECRETS_CLI, "get", secret_id], capture_output=True, text=True,
                              check=False)
        if read.returncode != 0:
            raise RuntimeError(f"Cannot read {secret_id} to redact it: {read.stderr.strip()}")
        value = read.stdout.strip()
        # An empty or placeholder value ("None" for a binary secret) would match ordinary text.
        if len(value) < 8:
            continue
        values[secret_id] = value
        # A JSON secret's fields are printed one by one too.
        try:
            fields = json.loads(values[secret_id])
        except ValueError:
            continue
        if isinstance(fields, dict):
            values.update({
                f"{secret_id}:{key}": field for key, field in fields.items()
                if isinstance(field, str) and len(field) >= 8
                and ("private" in key.lower() or SECRET_VARIABLE.search(key))
            })
    return values


def redact_string(text: str, secrets: dict[str, str]) -> str:
    text = PRIVATE_KEY.sub("[redacted private key]", text)
    text = URI_PASSWORD.sub(r"\1[redacted]@", text)
    for name, value in sorted(secrets.items(), key=lambda item: -len(item[1])):
        # A tool printing a JSON secret escapes it once more inside the decoded string, with
        # non-ASCII characters escaped (Python) or kept (JSON.stringify).
        for form in (json.dumps(value)[1:-1], json.dumps(value, ensure_ascii=False)[1:-1], value):
            text = text.replace(form, f"[redacted {name}]")
    return text


def redact_value(value, secrets: dict[str, str]):
    if isinstance(value, str):
        return redact_string(value, secrets)
    if isinstance(value, list):
        return [redact_value(item, secrets) for item in value]
    if isinstance(value, dict):
        return {key: redact_value(item, secrets) for key, item in value.items()}
    return value


def redact(text: str, secrets: dict[str, str]) -> str:
    """The transcript with every credential replaced by its name: a tool result is stored word
    for word, so a printed secret would otherwise reach the shared drive. Each line is decoded
    and its strings redacted, so the result stays valid JSONL; a line that is not JSON is
    redacted as text."""
    lines = []
    # Only "\n" ends a JSONL line: JSON.stringify leaves U+2028 and its kin raw inside strings,
    # where splitlines() would break a line in two.
    for line in text.split("\n"):
        if not line:
            continue
        try:
            lines.append(json.dumps(redact_value(json.loads(line), secrets)))
        except ValueError:
            lines.append(redact_string(line, secrets))
    return "\n".join(lines) + "\n"


def upload_session(session_id: str, transcript: Path) -> None:
    """Writes the redacted transcript to the session's one file, creating it on its first turn."""
    if not SESSION_ID.fullmatch(session_id):
        raise ValueError(f"unexpected session id {session_id!r}")
    data = redact(transcript.read_text(encoding="utf-8"), secret_values()).encode("utf-8")
    name = f"{PREFIX}{session_id}.jsonl"
    existing = [item for item in list_files(name) if item["name"] == name]
    if not existing:
        upload_file(name, data, "application/jsonl")
        return
    replace_file(existing[0]["id"], data, "application/jsonl")


def hook() -> None:
    try:
        event = json.load(sys.stdin)
        upload_session(event["session_id"], Path(event["transcript_path"]))
    except Exception as error:  # pylint: disable=broad-exception-caught
        # A failing hook shows an error on her turn; the learning pass only misses this upload.
        print(f"transcript upload skipped: {error}", file=sys.stderr)


def list_since(since: str) -> list[dict]:
    return list_files(PREFIX, modified_since=since)


def download(file_id: str, out: str) -> None:
    Path(out).write_bytes(download_file(file_id))


def cut(text: str) -> str:
    if len(text) <= 2 * CUT:
        return text
    return f"{text[:CUT]}\n[... {len(text) - 2 * CUT} characters cut ...]\n{text[-CUT:]}"


def result_text(content) -> str:
    if isinstance(content, str):
        return content
    return "\n".join(block.get("text", f"[{block.get('type')}]") for block in content or [])


def entries(transcript: Path) -> list[dict]:
    """The session as numbered entries: time, label, uncut body, and whether it opens a round."""
    found = []

    def add(event, label, body, opens_round=False, keep=False):
        found.append({"number": len(found) + 1, "time": event.get("timestamp", "")[:19],
                      "label": label, "body": body, "opens_round": opens_round, "keep": keep})

    for line in transcript.read_text(encoding="utf-8").split("\n"):
        try:
            event = json.loads(line)
        except ValueError:
            continue
        kind = event.get("type")
        if kind == "attachment":
            attachment = event["attachment"]
            if attachment.get("type") == "hook_blocking_error":
                add(event, f"HOOK BLOCKED {attachment.get('hookName')}",
                    str(attachment.get("blockingError")), keep=True)
            elif attachment.get("type") == "queued_command":
                add(event, "QUEUED MESSAGE", str(attachment.get("prompt")))
            continue
        if kind not in ("user", "assistant") or event.get("isMeta"):
            continue
        content = event["message"]["content"]
        if isinstance(content, str):
            # A system prompt (a task notification, a peer's message) arrives mid-round.
            system = event.get("promptSource") == "system"
            add(event, "NOTICE" if system else "USER", content, opens_round=not system)
            continue
        for block in content:
            block_type = block.get("type")
            if block_type == "text" and kind == "user":
                add(event, "USER", block["text"], opens_round=True)
            elif block_type == "text":
                add(event, "ASSISTANT", block["text"], keep=True)
            elif block_type == "thinking" and block.get("thinking"):
                add(event, "THINKING", block["thinking"], keep=True)
            elif block_type == "tool_use":
                fields = block.get("input") or {}
                add(event, f"TOOL {block.get('name')}", "\n".join(
                    f"{key}: {value if isinstance(value, str) else json.dumps(value)}"
                    for key, value in fields.items()))
            elif block_type == "tool_result":
                if event.get("toolDenialKind"):
                    label = "DENIED"
                elif block.get("is_error"):
                    label = "ERROR"
                else:
                    label = "RESULT"
                add(event, label, result_text(block.get("content")), keep=label != "RESULT")
    return found


def render(entry: dict) -> str:
    body = entry["body"] if entry["keep"] or entry["opens_round"] else cut(entry["body"])
    lines = [line[start:start + LINE_WIDTH] for line in body.split("\n")
             for start in range(0, max(len(line), 1), LINE_WIDTH)]
    return "\n".join([f"#{entry['number']} {entry['time']} {entry['label']}",
                      *(f"  {line}" for line in lines), ""])


def extract(transcript: Path, out_dir: Path, since: str | None) -> list[dict]:
    """Writes the session's reader parts; see the module docstring for how they are cut."""
    found = entries(transcript)
    rounds = []
    for entry in found:
        if entry["opens_round"] or not rounds:
            rounds.append([])
        rounds[-1].append(entry)
    if since:
        rounds = [entries_of_round for entries_of_round in rounds
                  if entries_of_round[-1]["time"] >= since]
    first_request = next((entry for entry in found if entry["opens_round"]), None)
    opening = (f"The session's first request, for context:\n{render(first_request)}\n"
               if first_request else "")

    # Every part but the first also carries the opening request.
    budget = READER_BUDGET - len(opening)
    parts, current, size = [], [], 0
    for entries_of_round in rounds:
        texts = [render(entry) for entry in entries_of_round]
        if current and size + sum(map(len, texts)) > budget:
            parts.append(current)
            current, size = [], 0
        for entry, text in zip(entries_of_round, texts):
            if current and size + len(text) > budget:
                parts.append(current)
                current, size = [], 0
            current.append((entry, text))
            size += len(text)
    if current:
        parts.append(current)

    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for index, part in enumerate(parts, start=1):
        path = out_dir / f"{transcript.stem}.part{index}.txt"
        header = (f"Session {transcript.stem}, part {index} of {len(parts)}, entries "
                  f"#{part[0][0]['number']} to #{part[-1][0]['number']}.\n\n")
        if part[0][0] is not first_request and opening:
            header += opening + "\nThis part:\n\n"
        content = header + "\n".join(text for _, text in part)
        path.write_text(content, encoding="utf-8")
        written.append({"file": str(path), "part": index, "parts": len(parts),
                        "first": part[0][0]["time"], "last": part[-1][0]["time"],
                        "characters": len(content)})
    return written


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("hook")
    commands.add_parser("list").add_argument(
        "--since", required=True, type=lambda value: date.fromisoformat(value[:10]).isoformat(),
        help="a day (YYYY-MM-DD); a timestamp counts from its day")
    download_command = commands.add_parser("download")
    download_command.add_argument("file_id")
    download_command.add_argument("out")
    extract_command = commands.add_parser("extract")
    extract_command.add_argument("transcript", type=Path)
    extract_command.add_argument("out_dir", type=Path)
    extract_command.add_argument(
        "--since", type=lambda value: date.fromisoformat(value[:10]).isoformat())
    show_command = commands.add_parser("show")
    show_command.add_argument("transcript", type=Path)
    show_command.add_argument("number", type=int)
    arguments = parser.parse_args()

    if arguments.command == "hook":
        hook()
    elif arguments.command == "list":
        for item in list_since(arguments.since):
            print(json.dumps(item))
    elif arguments.command == "extract":
        for part in extract(arguments.transcript, arguments.out_dir, arguments.since):
            print(json.dumps(part))
    elif arguments.command == "show":
        print(entries(arguments.transcript)[arguments.number - 1]["body"])
    else:
        download(arguments.file_id, arguments.out)


if __name__ == "__main__":
    main()
