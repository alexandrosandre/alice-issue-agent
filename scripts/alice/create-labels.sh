#!/bin/bash
# Create or update the labels Alice's sweep reads and writes
# (docs/design.md, "Selection and dispatch"). Safe to rerun:
# --force updates an existing label's color and description in place.
set -euo pipefail

REPO="${1:?usage: create-labels.sh <owner/repo>}"

create_label() {
    gh label create "$1" --repo "$REPO" --color "$2" --description "$3" --force
}

create_label "skip-alice" "b60205" \
    "Alice never works this issue, even when assigned. Only a person's removal lifts it."
create_label "alice-working" "0e8a16" \
    "Alice's session is running on this issue or pull request."
create_label "alice-done" "5319e7" \
    "Alice handed over or posted findings. Add alice-continue or alice-restart to run her again."
create_label "alice-stalled" "fbca04" \
    "No comment or push from Alice for 24 hours. Add alice-continue to start her again."
create_label "alice-continue" "1d76db" \
    "A person asks Alice to continue from where she stopped."
create_label "alice-restart" "006b75" \
    "A person asks Alice to start over: a new branch, her earlier PR closed."
