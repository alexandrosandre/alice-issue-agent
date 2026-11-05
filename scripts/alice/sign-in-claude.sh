#!/bin/bash
# Signs one of Alice's Claude accounts in to claude.ai for the sweep, which sends her rounds into
# her existing sessions with it (docs/design.md, D38). Stores the sign-in's refresh token in the
# secret store as alice-sweep/claude-login-<account>, never printing it; the sweep replaces it at
# each use. A sign-in lasts a fixed number of days, and the sweep warns in its log three days before
# it ends.
#
# Usage: bash scripts/alice/sign-in-claude.sh <account>
#   account 1 owns routine 1 (ALICE_ROUTINE_FIRE_URL), account 2 routine 2 (..._2).
# Sign in as that account in the browser that opens; any other account is refused.
#
# TODO: wire `secrets-cli` to your secret store's CLI, and list your Alice accounts' emails below.
set -euo pipefail
account=${1:?usage: sign-in-claude.sh <account number>}
case "$account" in
    1) expected=alice-bot@example.com ;;
    2) expected=alice-bot+2@example.com ;;
    *) echo "Alice has accounts 1 and 2." >&2; exit 1 ;;
esac
secret_id="alice-sweep/claude-login-$account"
# A config directory of its own keeps this sign-in apart from the person's own.
export CLAUDE_CONFIG_DIR="$HOME/.claude-alice-sign-in-$account-$(date +%s)"
mkdir -p "$CLAUDE_CONFIG_DIR"
trap 'rm -rf "$CLAUDE_CONFIG_DIR"' EXIT

claude auth login
email=$(claude auth status | python3 -c 'import json,sys; print(json.load(sys.stdin)["email"])')
# The browser is usually signed in as the person running this; storing their sign-in would hand
# it to the sweep.
if [ "$email" != "$expected" ]; then
    echo "Signed in as $email, not $expected: nothing stored. Sign in as $expected." >&2
    exit 1
fi
credentials=$(cat "$CLAUDE_CONFIG_DIR/.credentials.json")

secret=$(python3 -c '
import json, sys
oauth = json.load(sys.stdin)["claudeAiOauth"]
print(json.dumps({"refresh_token": oauth["refreshToken"], "scopes": " ".join(oauth["scopes"])}))
' <<< "$credentials")
printf '%s' "$secret" | secrets-cli put "$secret_id" > /dev/null
ends=$(python3 -c '
import datetime, json, sys
ends_ms = json.load(sys.stdin)["claudeAiOauth"]["refreshTokenExpiresAt"]
ends = datetime.datetime.fromtimestamp(ends_ms / 1000, datetime.timezone.utc)
print(ends.strftime("%Y-%m-%d %H:%M UTC"))
' <<< "$credentials")
echo "Stored $email's sign-in as Alice's account $account ($secret_id). It ends on $ends."
