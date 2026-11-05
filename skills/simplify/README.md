# Simplify

A fresh-eyes review of the branch's own changed files for what they can lose without changing behavior: code nobody needs yet, logic the repository already has, constructs a cold reader trips on, and work done twice. It fixes what it finds with behavior-preserving rewrites only.

## Why it exists

The contextual review owns "did we ship what we meant"; this pass owns "is the code as written tidy". It never changes behavior, public contracts or code that fast local tests cannot verify, and reports parallel mechanisms (two things serving one goal) instead of merging them, since which one owns the goal is a design decision.

## How it fits

Run before committing, and on request. The engineering rules in `AGENTS.md` (Code Style) set its bar for extracting helpers.

## Canonical home

This is a vendored copy, kept here so Alice is self-standing. The canonical version, used by developers in their own sessions, lives in https://github.com/alexandrosandre/agentic-engineering (`skills/simplify`). The copy differs only where Alice needs it to.

The instructions are in [SKILL.md](SKILL.md).

**Origin.** Written by the author from this repository's engineering rules (`AGENTS.md`, Code Style and Testing & Verification): a branch-only scope, what must not move, four questions in the order they settle each other, targeted verification, and parallel mechanisms reported instead of merged. Coding agents ship cleanup passes of their own; this one shares no text with them.
