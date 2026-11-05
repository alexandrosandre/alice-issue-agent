#!/usr/bin/env python3
"""Prints an issue and its comments as a person sees them on GitHub.

  issue_text.py <issue number>

HTML comments and invisible format characters (zero-width, bidirectional and Unicode tag
characters) never show on GitHub, yet reach an agent that reads the raw body, so instructions
can hide there. The text comes from GitHub's own HTML rendering (`body_html`), which leaves hidden
comments out wherever Markdown puts them, with each link's address after its text and the format
characters removed; a last line counts what was left out and where, without quoting it. The
repository comes from GH_REPO (owner/name).
"""
import html.parser
import json
import os
import re
import subprocess
import sys
import unicodedata

# Asks the REST API for each body as written and as GitHub renders it.
FULL_BODIES = "Accept: application/vnd.github.full+json"
# The sweep ends its own comments with these markers, merge before dispatch (scripts/alice/sweep.py,
# MERGE_MARKER and DISPATCH_MARKER); they carry no text.
SWEEP_MARKERS = ("<!-- alice-sweep:dispatch -->", "<!-- alice-sweep:merge -->")
SWEEP_ACTOR = "github-actions[bot]"
BLOCK_TAGS = {"p", "div", "br", "li", "tr", "pre", "blockquote", "hr", "table", "details",
              "summary", "h1", "h2", "h3", "h4", "h5", "h6"}


class HtmlText(html.parser.HTMLParser):
    """The text of GitHub's rendered HTML, with each link's address after its text, since the
    address is often what an issue points at (a site, a recording, a thread)."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.open_links: list[tuple[str, int]] = []
        self.inside_pre = 0

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag == "pre":
            self.inside_pre += 1
        if tag in BLOCK_TAGS:
            self.parts.append("\n")
        if tag == "li":
            self.parts.append("- ")
        if tag == "a":
            self.open_links.append((attributes.get("href") or "", len(self.parts)))
        if tag == "img":
            self.parts.append(f"[image {attributes.get('alt') or ''}: {attributes.get('src')}]")
        if tag == "input" and attributes.get("type") == "checkbox":
            self.parts.append("[x]" if "checked" in attributes else "[ ]")

    def handle_endtag(self, tag):
        if tag == "a" and self.open_links:
            href, start = self.open_links.pop()
            if href and href != "".join(self.parts[start:]).strip():
                self.parts.append(f" ({href})")
        if tag == "pre":
            self.inside_pre -= 1
        if tag in ("td", "th"):
            self.parts.append(" | ")
        if tag in BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data):
        # GitHub's HTML puts line breaks between tags; outside code they are layout, not text,
        # and would split a table row over lines.
        if not self.inside_pre and not data.strip() and "\n" in data:
            return
        self.parts.append(data)

    def text(self) -> str:
        return re.sub(r"\n{3,}", "\n\n", "".join(self.parts)).strip()


def visible_text(raw: str, rendered: str) -> tuple[str, int, int]:
    """The text of GitHub's rendering without format characters, the hidden comments the source
    had, and how many format characters were removed."""
    parser = HtmlText()
    # GitHub sends null for an empty body.
    parser.feed(rendered or "")
    parser.close()
    rendered = parser.text()
    # A `<!--` the rendering still shows is visible text, such as one inside code.
    comments = max(0, (raw or "").count("<!--") - rendered.count("<!--"))
    hidden = sum(1 for character in rendered if unicodedata.category(character) == "Cf")
    text = "".join(c for c in rendered if unicodedata.category(c) != "Cf")
    return text.strip(), comments, hidden


def render(issue: dict, comments: list[dict]) -> str:
    """The issue and its comments as text, ending with what was left out, if anything."""
    removed = []

    def clean(raw, rendered, where):
        text, html_comments, hidden = visible_text(raw, rendered)
        if html_comments or hidden:
            removed.append(f"{where}: {html_comments} HTML comments, {hidden} invisible characters")
        return text

    # A title is plain text, so GitHub shows it as written.
    title = clean(issue["title"], html.escape(issue["title"]), "title")
    parts = [f"# #{issue['number']} {title}",
             f"Opened by {issue['user']['login']} on {issue['created_at']}, {issue['state']}.",
             clean(issue["body"], issue["body_html"], "body")]
    for comment in comments:
        where = f"comment by {comment['user']['login']} on {comment['created_at']}"
        raw = comment["body"]
        # Only the sweep's own markers are exempt: one anyone else writes is hidden text.
        if comment["user"]["login"] == SWEEP_ACTOR:
            raw = (raw or "").rstrip()
            for marker in SWEEP_MARKERS:
                raw = raw.removesuffix(marker).rstrip()
        parts += [f"## Comment by {comment['user']['login']} on {comment['created_at']}",
                  clean(raw, comment["body_html"], where)]
    if removed:
        parts.append("Removed, as GitHub does not show it: " + "; ".join(removed) + ".")
    return "\n\n".join(parts)


def main():
    if len(sys.argv) != 2 or not sys.argv[1].isdigit():
        sys.exit(__doc__)
    repository = os.environ.get("GH_REPO", "example-org/monorepo")
    number = sys.argv[1]
    issue = json.loads(subprocess.run(
        ["gh", "api", "-H", FULL_BODIES, f"repos/{repository}/issues/{number}"],
        check=True, capture_output=True, text=True).stdout)
    comment_lines = subprocess.run(
        ["gh", "api", "-H", FULL_BODIES, "--paginate",
         f"repos/{repository}/issues/{number}/comments?per_page=100", "--jq", ".[]"],
        check=True, capture_output=True, text=True).stdout.splitlines()
    comments = [json.loads(line) for line in comment_lines if line]
    print(render(issue, comments))


if __name__ == "__main__":
    main()
