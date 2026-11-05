#!/usr/bin/env python3
"""Derives a change's risk level from the risk reviewer's answers and renders the PR's
Risk section.

The reviewer answers six questions about what users could experience; this script, not the
reviewer, turns the answers into a level, so the reviewer never sees what its answers cost
(`docs/design.md`, "Risk").

Usage:
  risk_level.py questions                  print the questions and answers for the reviewer
  risk_level.py level ASSESSMENT           print {"level", "title"} as JSON
  risk_level.py render ASSESSMENT [--evidence EVIDENCE]
                                           print the PR's Risk section as Markdown

ASSESSMENT is the reviewer's JSON:
  {
    "answers": {"<question>": {"answer": "<option>" | ["<option>", "<option>", ...],
                               "reason": "<why, citing path:line>"}, ...one per question},
    "riskiest_changes": [{"location": "<path:lines>", "scenario": "<what would break it>"}],
    "residual_risk": "<second pass only>",
    "before_merge": ["<what the PR's reviewer should check, riskiest first>"],
    "after_release": ["<what someone should check once it ships>"]
  }
A list answer means the reviewer could not settle between those options; it counts as the
riskiest of them.

EVIDENCE is alice-verify-change's JSON, where `proves` and `requirement` name keys of
REQUIREMENTS:
  {
    "commit": "<sha verified>",
    "runs": [{"command": "...", "result": "...", "proves": ["<requirement>", ...],
              "settles": ["<a pass-2 before_merge item it settles, its text verbatim>"]}],
    "screenshots": [{"caption": "...", "url": "...", "proves": [...], "settles": [...]}],
    "recordings": [{"caption": "...", "url": "...", "proves": [...], "settles": [...]}],
    "preview": "<url>" | null,        (a preview URL shows the `preview` requirement)
    "not_verified": [{"what": "...", "why": "...", "requirement": "<requirement>"}],
                       (`requirement` is left out when the item proves no requirement)
    "not_applicable": [{"requirement": "<requirement>", "why": "..."}]
  }
"""
import argparse
import json
import sys
from pathlib import Path

LEVELS = ["Low", "Moderate", "Elevated", "High"]

# What each level requires the PR to show beyond green CI, which GitHub shows. The evidence tags
# each run, screenshot or recording with the requirements it proves, so the Risk section marks
# every requirement as shown or not without anyone ticking it by hand.
REQUIREMENTS = {
    "tests": "run the affected test suites, with a test for the changed logic",
    "app_flow": (
        "drive the changed flow on the local stack and show it in screenshots or a recording"
    ),
    "preview": "add a preview link, so a person can try the change",
    "reproduction": "reproduce the problem on master",
    "failing_test": "add a test that fails before the fix and passes after",
    "end_to_end": (
        "run the end-to-end flows on the local stack, before and after, on real read-only data"
    ),
    "independent_check": "have a second agent repeat the check without the author's reasoning",
    "feature_flag": "put the change behind a feature flag, where its area has them",
}
LEVEL_REQUIREMENTS = {
    "Low": [],
    "Moderate": ["tests"],
    "Elevated": ["tests", "app_flow", "preview"],
    "High": ["tests", "reproduction", "failing_test", "end_to_end", "independent_check",
             "feature_flag", "preview"],
}

# Each question's options in order of risk, with the wording the reviewer sees, the level the
# option reaches, and the short label the PR's Risk section shows. Users are the customers using
# the product; for internal tooling (CI, agents, scripts) they are the teammates relying on it.
QUESTIONS = {
    "users_see": {
        "title": "What users see",
        "question": "What does the change alter in what users see or get?",
        "options": {
            "nothing": (
                "nothing changes (comments, docs, tests, refactors that keep behavior)",
                "Low",
                "nothing changes",
            ),
            "text": (
                "only text that is not a control (copy, labels, messages)", "Low", "text only"
            ),
            "indirect": (
                "behavior that users do not see directly (a backend path, a job's internals, "
                "internal tooling)",
                "Moderate",
                "behavior users do not see directly",
            ),
            "interface": ("interface behavior: a control, a layout, an interaction", "Elevated",
                          "interface behavior"),
            "data": (
                "the data we show them: numbers, reports, alerts, records, generated answers",
                "High",
                "the data we show them",
            ),
        },
    },
    "production_data": {
        "title": "Production data",
        "question": (
            "What does the change alter in how production data is read or written? A change "
            "that keeps the same reads and writes answers none."
        ),
        "options": {
            "none": ("none", "Low", "none"),
            "read": ("it reads production data it did not read before, or reads it differently",
                     "High", "reads production data"),
            "written": (
                "it writes production data (a database, the warehouse, object storage, sent "
                "email) or writes it differently",
                "High",
                "writes production data",
            ),
            "schema": ("it changes a schema or needs a migration", "High",
                       "changes a schema"),
        },
    },
    "undo": {
        "title": "Undo",
        "question": "If this change is reverted after release, what remains?",
        "options": {
            "revert_restores": ("a revert restores everything", "Low",
                                "a revert restores everything"),
            "leaves_behind": (
                "something stays behind: written data, sent email, a released client library, "
                "a changed external contract",
                "High",
                "something stays behind",
            ),
        },
    },
    "reach": {
        "title": "Reach",
        "question": (
            "Whose stored or computed results does the change alter (configuration, incoming "
            "data, reports, notifications, alerts, generated answers)? A change only to how the "
            "web app looks or is operated, or only to internal tooling, answers none."
        ),
        "options": {
            "none": ("no customer account's results change", "Low", "no account"),
            "one_account": ("one customer account", "Moderate", "one account"),
            "some_accounts": ("some customer accounts", "High", "some accounts"),
            "all_accounts": ("all customer accounts, or every account using one integration",
                             "High", "all accounts"),
        },
    },
    "noise": {
        "title": "Noise",
        "question": (
            "Does the change alter what customers are told or alerted about: notification "
            "content or timing, alert trigger conditions, emails, alarms?"
        ),
        "options": {
            "no": ("no", "Low", "no"),
            "yes": ("yes", "High", "changes what customers are told"),
        },
    },
    "sensitive_ground": {
        "title": "Sensitive ground",
        "question": "Which sensitive area does the change touch, if any?",
        "options": {
            "none": ("none", "Low", "none"),
            "authentication": ("authentication", "High", "authentication"),
            "billing": ("billing", "High", "billing"),
            "data_isolation": ("data isolation between customer accounts", "High",
                               "data isolation"),
            "ingestion": ("the ingestion pipeline, where a bug loses incoming data", "High",
                          "ingestion"),
            "public_clients": ("the public client libraries and APIs", "High",
                               "the public clients"),
        },
    },
}


class AssessmentError(ValueError):
    """The reviewer's JSON does not follow the contract."""


class EvidenceError(ValueError):
    """The verification evidence does not follow the contract; the session that wrote it fixes
    it, not the reviewer."""


def candidate_options(question_key, answer):
    """Returns the options an answer names: one when settled, two or more when unsettled."""
    options = QUESTIONS[question_key]["options"]
    candidates = answer if isinstance(answer, list) else [answer]
    if isinstance(answer, list) and len(set(answer)) < 2:
        raise AssessmentError(
            f"{question_key}: an unsettled answer lists at least two different options"
        )
    for option in candidates:
        if option not in options:
            raise AssessmentError(
                f"{question_key}: {option!r} is not one of {', '.join(options)}"
            )
    return candidates


def option_level(question_key, option):
    """Returns the level one option of one question reaches."""
    return QUESTIONS[question_key]["options"][option][1]


def riskiest_option(question_key, answer):
    """Returns the option an answer counts as: the riskiest one it names, the later in the
    question's order among options at the same level."""
    order = list(QUESTIONS[question_key]["options"])
    return max(
        candidate_options(question_key, answer),
        key=lambda option: (LEVELS.index(option_level(question_key, option)), order.index(option)),
    )


def is_text(value):
    """Whether a value is non-blank text."""
    return isinstance(value, str) and bool(value.strip())


def one_line(text):
    """The text on one line: a line break inside a list item would start a new item, a forged
    one, in the PR's Risk section."""
    return " ".join(text.split())


def validate_assessment(assessment):
    """Fails loudly on a missing question, an unknown option or a missing reason."""
    answers = assessment.get("answers")
    if not isinstance(answers, dict):
        raise AssessmentError("the assessment has no 'answers' object")
    missing = [key for key in QUESTIONS if key not in answers]
    unknown = [key for key in answers if key not in QUESTIONS]
    if missing or unknown:
        raise AssessmentError(f"answers missing: {missing}; unknown questions: {unknown}")
    for key, entry in answers.items():
        if not is_text(entry.get("reason")):
            raise AssessmentError(f"{key}: every answer gives its reason")
        candidate_options(key, entry.get("answer"))


def derive_level(assessment):
    """Returns the level and the questions that set it: the highest level any answer reaches."""
    validate_assessment(assessment)
    reached = {
        key: option_level(key, riskiest_option(key, entry["answer"]))
        for key, entry in assessment["answers"].items()
    }
    level = max(reached.values(), key=LEVELS.index)
    set_by = [key for key in QUESTIONS if reached[key] == level]
    return level, set_by


def describe_answer(question_key, answer):
    """Renders an answer as its short label; an unsettled one names every option left and the
    one it counts as."""
    options = QUESTIONS[question_key]["options"]
    if not isinstance(answer, list):
        return options[answer][2]
    named = " or ".join(options[option][2] for option in answer)
    return f"{named}, counted as {options[riskiest_option(question_key, answer)][2]}"


def render_questions():
    """Returns the reviewer's questions and options, without the levels they reach."""
    lines = []
    for number, (key, question) in enumerate(QUESTIONS.items(), start=1):
        lines.append(f"{number}. `{key}` ({question['title']}): {question['question']}")
        for option, (wording, _level, _label) in question["options"].items():
            lines.append(f"   - `{option}`: {wording}")
    return "\n".join(lines)


def evidence_items(evidence):
    """Returns the evidence's runs, screenshots and recordings in the order the PR numbers them,
    each as (name, item), e.g. ("run 2", {...})."""
    items = []
    for kind, key in (("run", "runs"), ("screenshot", "screenshots"), ("recording", "recordings")):
        items += [(f"{kind} {number}", item)
                  for number, item in enumerate(evidence.get(key, []), start=1)]
    return items


def validate_evidence(evidence):
    """Fails loudly on a requirement name the level table does not know, a not-verified or
    not-applicable entry without a reason, and a not-applicable entry without a requirement."""
    named = [requirement for _name, item in evidence_items(evidence)
             for requirement in item.get("proves", [])]
    for key in ("not_verified", "not_applicable"):
        for item in evidence.get(key, []):
            if not is_text(item.get("why")):
                raise EvidenceError(f"every {key} entry gives its reason: {item}")
            if key == "not_verified" and not is_text(item.get("what")):
                raise EvidenceError(f"every not_verified entry says what: {item}")
            if key == "not_applicable" or "requirement" in item:
                named.append(item.get("requirement"))
    unknown = sorted(str(name) for name in set(named) - set(REQUIREMENTS))
    if unknown:
        raise EvidenceError(f"evidence names unknown requirements: {unknown}")


def render_requirements(level, evidence):
    """Marks each requirement of the level: not done whenever something it needs was not
    verified, even beside a run that shows part of it; else shown, not applicable or unproven."""
    if not LEVEL_REQUIREMENTS[level]:
        return ["At this risk, the PR must show green CI only."]
    lines = ["At this risk, the PR must:", ""]
    evidence = evidence or {}
    items = evidence_items(evidence)
    for requirement in LEVEL_REQUIREMENTS[level]:
        text = REQUIREMENTS[requirement]
        proofs = [name for name, item in items if requirement in item.get("proves", [])]
        if requirement == "preview" and evidence.get("preview"):
            proofs.append("preview")
        reasons = {key: [one_line(item["why"]) for item in evidence.get(key, [])
                         if item.get("requirement") == requirement]
                   for key in ("not_verified", "not_applicable")}
        if reasons["not_verified"]:
            shown = f" (partly shown in {', '.join(proofs)})" if proofs else ""
            lines.append(f"- ❌ {text}: not done, {'; '.join(reasons['not_verified'])}{shown}")
        elif proofs:
            lines.append(f"- ✅ {text} ({', '.join(proofs)})")
        elif reasons["not_applicable"]:
            lines.append(f"- ➖ {text}: not applicable, {'; '.join(reasons['not_applicable'])}")
        else:
            lines.append(f"- ❌ {text}: no evidence")
    return lines


def render_verification(evidence):
    """Renders what was verified, at which commit, and what was not, numbered as the
    requirements cite it."""
    if evidence is None:
        return ["### What was verified", "", "Nothing yet."]
    lines = [f"### What was verified (commit {evidence['commit'][:12]})", ""]
    items = evidence_items(evidence)
    runs = [f"- {name.capitalize()}: `{item['command']}`: {item['result']}"
            for name, item in items if name.startswith("run")]
    # A person looks at what was shown; the runs stay one click away for the marks citing them.
    if runs:
        lines += ["<details><summary>Runs</summary>", ""] + runs + ["", "</details>", ""]
    for name, item in items:
        if name.startswith("run"):
            continue
        if name.startswith("screenshot"):
            lines.append(f"- {name.capitalize()}: {item['caption']}")
            lines.append(f"  ![{item['caption']}]({item['url']})")
        else:
            lines.append(f"- {name.capitalize()}: [{item['caption']}]({item['url']})")
    if evidence.get("preview"):
        lines.append(f"- Preview: {evidence['preview']}")
    not_verified = evidence.get("not_verified", [])
    if not_verified:
        lines += ["", "**Not verified**", ""]
        lines += [f"- {one_line(item['what'])}: {one_line(item['why'])}"
                  for item in not_verified]
    return lines


def risk_title(level):
    """The level as the PR names it, e.g. "Risk 4 of 4 (High)"."""
    return f"Risk {LEVELS.index(level) + 1} of {len(LEVELS)} ({level})"


def render_risk_section(assessment, evidence=None):
    """Renders the PR's Risk section from the reviewer's answers and the verification evidence."""
    level, set_by = derive_level(assessment)
    if evidence:
        validate_evidence(evidence)
    # At Low every question is at Low, so naming them all says nothing.
    set_by_text = ("" if level == LEVELS[0] else
                   ", set by " + ", ".join(QUESTIONS[key]["title"] for key in set_by))
    lines = ["## Risk", "", f"**{risk_title(level)}**{set_by_text}.", ""]
    lines += render_requirements(level, evidence)
    # An answer at its question's lowest-risk option tells the reader nothing, so it is left out.
    for key, question in QUESTIONS.items():
        entry = assessment["answers"][key]
        if entry["answer"] == next(iter(question["options"])):
            continue
        answer = describe_answer(key, entry["answer"])
        lines += ["", f"### {question['title']}", "",
                  f"{answer[0].upper()}{answer[1:]}. {one_line(entry['reason'])}"]
    # The riskiest changes stay out of the PR: they steer the verification; a reviewer skips them.
    lines += [""] + render_verification(evidence)
    if assessment.get("residual_risk"):
        lines += ["", "### Residual risk", "", one_line(assessment["residual_risk"])]
    before_merge = assessment.get("before_merge", [])
    # A tag names its item's text, not its place, so a rewritten list leaves a stale tag
    # ticking nothing instead of whatever item took its place; Alice tags again from the new list.
    settled = {}
    for name, item in evidence_items(evidence or {}):
        texts = item.get("settles", [])
        if not isinstance(texts, list) or not all(isinstance(text, str) for text in texts):
            raise EvidenceError(f"{name} settles a list of item texts, not {texts!r}")
        for text in texts:
            settled.setdefault(one_line(text), []).append(name)
    if before_merge:
        lines += ["", "### Before merging", ""]
        lines += [f"- [x] {one_line(item)} ({', '.join(settled[one_line(item)])})"
                  if one_line(item) in settled else f"- [ ] {one_line(item)}"
                  for item in before_merge]
    if assessment.get("after_release"):
        lines += ["", "### After release", ""]
        lines += [f"- [ ] {one_line(item)}" for item in assessment["after_release"]]
    return "\n".join(lines) + "\n"


def main():
    """Runs the command-line interface."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("questions", help="print the reviewer's questions")
    level_parser = commands.add_parser("level", help="print the level as JSON")
    level_parser.add_argument("assessment")
    render_parser = commands.add_parser("render", help="print the PR's Risk section")
    render_parser.add_argument("assessment")
    render_parser.add_argument("--evidence")
    arguments = parser.parse_args()

    if arguments.command == "questions":
        print(render_questions())
        return
    assessment = json.loads(Path(arguments.assessment).read_text(encoding="utf-8"))
    try:
        if arguments.command == "level":
            level = derive_level(assessment)[0]
            print(json.dumps({"level": level, "title": risk_title(level)}))
            return
        evidence = (json.loads(Path(arguments.evidence).read_text(encoding="utf-8"))
                    if arguments.evidence else None)
        sys.stdout.write(render_risk_section(assessment, evidence))
    except AssessmentError as error:
        sys.exit(f"Invalid assessment: {error}")
    except EvidenceError as error:
        sys.exit(f"Invalid evidence: {error}")


if __name__ == "__main__":
    main()
