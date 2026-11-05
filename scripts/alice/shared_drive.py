#!/usr/bin/env python3
"""The shared drive folder where Alice keeps what is too large or too sensitive for the
repository: her recordings (`evidence.py`) and her session transcripts (`transcripts.py`).

Placeholder. Every teammate can open a file in the folder by its link; Alice's sessions write
only there, with a credential the session reads from the secret store (`read_secret`) and
that can write nothing else. TODO: wire each function to your shared drive's API.
"""
import subprocess

# The folder that holds Alice's recordings and transcripts, by your drive's ID for it.
EVIDENCE_FOLDER = "<EVIDENCE_FOLDER_ID>"
# The secret holding the credential that writes to that folder.
DRIVE_CREDENTIAL_NAME = "alice/evidence-drive-key"
# The secret store's command-line client. TODO: wire to yours.
SECRETS_CLI = "secrets-cli"


def read_secret(secret_id: str) -> str:
    """Returns a secret's value, read with the session's read-only identity. Raises
    subprocess.CalledProcessError when the identity cannot read it."""
    return subprocess.run([SECRETS_CLI, "get", secret_id], capture_output=True, text=True,
                          check=True).stdout.strip()


def upload_file(name: str, data: bytes, mime_type: str) -> str:
    """Creates a file in the evidence folder and returns the link a teammate opens it with.
    Upload resumably: a recording can run past what a single request carries."""
    raise NotImplementedError("TODO: wire to your shared drive's upload API")


def replace_file(file_id: str, data: bytes, mime_type: str) -> None:
    """Replaces the contents of a file in the evidence folder, keeping its ID and link."""
    raise NotImplementedError("TODO: wire to your shared drive's update API")


def list_files(name_prefix: str, modified_since: str | None = None) -> list[dict]:
    """Returns the folder's files whose names start with the prefix, oldest change first, each as
    {"id", "name", "modified", "size"}; with modified_since (YYYY-MM-DD), only the files
    changed since that day."""
    raise NotImplementedError("TODO: wire to your shared drive's listing API")


def download_file(file_id: str) -> bytes:
    """Returns a file's contents."""
    raise NotImplementedError("TODO: wire to your shared drive's download API")
