"""Tests for the risk level derived from the risk reviewer's answers and the Risk section."""
import importlib.util
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "alice/risk_level.py"
SPEC = importlib.util.spec_from_file_location("risk_level", SCRIPT)
risk_level = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = risk_level
SPEC.loader.exec_module(risk_level)

QUIET_ANSWERS = {
    "users_see": "nothing",
    "production_data": "none",
    "undo": "revert_restores",
    "reach": "none",
    "noise": "no",
    "sensitive_ground": "none",
}


def assessment(**overrides):
    """Builds an assessment whose answers are all the quietest option unless overridden."""
    answers = {**QUIET_ANSWERS, **overrides}
    return {
        "answers": {
            key: {"answer": answer, "reason": f"reason for {key}"}
            for key, answer in answers.items()
        }
    }


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        ({}, "Low"),
        ({"users_see": "text"}, "Low"),
        ({"users_see": "indirect"}, "Moderate"),
        ({"reach": "one_account"}, "Moderate"),
        ({"users_see": "interface"}, "Elevated"),
        ({"users_see": "data"}, "High"),
        ({"production_data": "read"}, "High"),
        ({"undo": "leaves_behind"}, "High"),
        ({"reach": "some_accounts"}, "High"),
        ({"noise": "yes"}, "High"),
        ({"sensitive_ground": "ingestion"}, "High"),
    ],
)
def test_each_level_is_reached_by_its_answers(overrides, expected):
    """Each row of the Levels table is reached by the answers that define it."""
    level, _set_by = risk_level.derive_level(assessment(**overrides))
    assert level == expected


def test_highest_answer_decides_and_names_every_question_that_reached_it():
    """The riskiest answer sets the level, and every question at that level is named."""
    level, set_by = risk_level.derive_level(
        assessment(users_see="interface", noise="yes", production_data="written")
    )
    assert level == "High"
    assert set_by == ["production_data", "noise"]


def test_unsettled_answer_counts_as_its_riskiest_option():
    """An answer the reviewer could not settle counts as the riskier option it names."""
    level, set_by = risk_level.derive_level(assessment(users_see=["nothing", "interface"]))
    assert (level, set_by) == ("Elevated", ["users_see"])


def test_unsettled_answer_is_rendered_with_both_labels_and_the_one_counted():
    """The Risk section shows what was unsettled and which option the level counted."""
    section = risk_level.render_risk_section(assessment(reach=["none", "all_accounts"]))
    assert ("### Reach\n\nNo account or all accounts, counted as all accounts. reason for reach"
            in section)
    tied = risk_level.render_risk_section(assessment(reach=["all_accounts", "some_accounts"]))
    assert "### Reach\n\nAll accounts or some accounts, counted as all accounts." in tied


def test_risk_section_lists_only_answers_that_carry_risk_with_a_short_label():
    """Lowest-risk answers are left out, a settled answer shows its short label and the
    reviewer's reason (not the rubric wording), and the checklist splits what to check before
    merging from after release."""
    reviewed = assessment(production_data="written")
    reviewed["before_merge"] = ["the rule's keys match the importer"]
    reviewed["after_release"] = ["the published config has the rule"]
    section = risk_level.render_risk_section(reviewed)
    assert section.startswith("## Risk\n\n**Risk 4 of 4 (High)**, set by Production data.\n")
    assert "### Production data\n\nWrites production data. reason for production_data" in section
    assert "object storage" not in section
    assert "### Undo" not in section and "### Noise" not in section
    assert "### Before merging\n\n- [ ] the rule's keys match the importer" in section
    assert "### After release\n\n- [ ] the published config has the rule" in section


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"users_see": "maybe"}, "not one of"),
        ({"users_see": ["interface"]}, "at least two different options"),
        ({"users_see": ["data", "data"]}, "at least two different options"),
    ],
)
def test_malformed_answers_are_refused(overrides, message):
    """An option outside the question's list, or a one-option 'unsettled' list, is refused."""
    with pytest.raises(risk_level.AssessmentError, match=message):
        risk_level.derive_level(assessment(**overrides))


def test_missing_question_or_reason_is_refused():
    """Every question needs an answer and a reason, so no level comes from a partial review."""
    partial = assessment()
    del partial["answers"]["noise"]
    with pytest.raises(risk_level.AssessmentError, match="noise"):
        risk_level.derive_level(partial)

    unreasoned = assessment()
    for reason in (" ", None):
        unreasoned["answers"]["undo"]["reason"] = reason
        with pytest.raises(risk_level.AssessmentError, match="reason"):
            risk_level.derive_level(unreasoned)


def test_questions_for_the_reviewer_hide_the_levels():
    """The reviewer's questions never reveal what level an answer costs."""
    questions = risk_level.render_questions()
    for level in risk_level.LEVELS:
        assert level not in questions
    for key in risk_level.QUESTIONS:
        assert f"`{key}`" in questions


def test_risk_section_shows_evidence_commit_and_what_was_not_verified():
    """The rendered section names the verified commit, shows screenshots with the runs folded
    away, leaves the reviewer's riskiest changes out, and lists what could not be verified."""
    evidence = {
        "commit": "0123456789abcdef0123",
        "runs": [{"command": "cd backend && pytest tests/import", "result": "41 passed"}],
        "screenshots": [{"caption": "Filters sidebar", "url": "https://example.test/a.png"}],
        "recordings": [],
        "preview": None,
        "not_verified": [{"what": "Safari layout", "why": "no Safari in the session"}],
    }
    reviewed = assessment(users_see="interface")
    reviewed["riskiest_changes"] = [{"location": "backend/a.py:1-9", "scenario": "a breaking case"}]
    section = risk_level.render_risk_section(reviewed, evidence)
    assert "backend/a.py:1-9" not in section
    assert "### What was verified (commit 0123456789ab)" in section
    assert ("<details><summary>Runs</summary>\n\n- Run 1: `cd backend && pytest tests/import`: "
            "41 passed\n\n</details>\n\n- Screenshot 1: Filters sidebar") in section
    assert "![Filters sidebar](https://example.test/a.png)" in section
    assert "- Safari layout: no Safari in the session" in section
    assert "Preview:" not in section


def test_requirements_are_marked_from_the_evidence_that_proves_them():
    """Each requirement of the level is marked shown (citing the item that proves it), not done
    or not applicable with the reason given, or unproven when nothing names it."""
    evidence = {
        "commit": "0123456789abcdef0123",
        "runs": [
            {"command": "pytest -k repro", "result": "fails on master", "proves": ["reproduction"]},
            {"command": "pytest", "result": "1 failed, then 12 passed",
             "proves": ["tests", "failing_test"]},
        ],
        "not_verified": [{"what": "second check", "why": "the stack did not start",
                          "requirement": "independent_check"}],
        "not_applicable": [{"requirement": "feature_flag", "why": "ingestion has no flags"}],
    }
    section = risk_level.render_risk_section(assessment(noise="yes"), evidence)
    assert "- ✅ reproduce the problem on master (run 1)" in section
    assert "- ✅ add a test that fails before the fix and passes after (run 2)" in section
    assert ": not done, the stack did not start" in section
    assert ": not applicable, ingestion has no flags" in section
    assert "on real read-only data: no evidence" in section
    assert "- Run 2: `pytest`: 1 failed, then 12 passed" in section


def test_low_risk_needs_only_green_ci_and_names_no_question():
    """At the lowest level every question sits at its lowest option, so none is named."""
    section = risk_level.render_risk_section(assessment())
    assert "**Risk 1 of 4 (Low)**.\n\nAt this risk, the PR must show green CI only." in section


def test_evidence_naming_an_unknown_requirement_is_refused():
    """A typo in a requirement name fails loudly instead of leaving a requirement unproven."""
    evidence = {"commit": "0123456789ab", "runs": [{"command": "x", "result": "y",
                                                     "proves": ["reproducton"]}]}
    with pytest.raises(risk_level.EvidenceError, match="reproducton"):
        risk_level.render_risk_section(assessment(), evidence)


def test_a_requirement_not_verified_is_not_done_even_beside_a_run_that_shows_part_of_it():
    """A disagreeing independent check or a suite that could not run keeps its ❌, so a green
    mark never hides a failure; a preview URL shows the preview requirement."""
    evidence = {
        "commit": "0123456789abcdef0123",
        "runs": [{"command": "check", "result": "disagree", "proves": ["independent_check"]}],
        "preview": "https://preview.test",
        "not_verified": [{"what": "second check", "why": "it disagreed on the records list",
                          "requirement": "independent_check"}],
    }
    high = risk_level.render_risk_section(assessment(noise="yes"), evidence)
    assert ("repeat the check without the author's reasoning: not done, it disagreed on the "
            "records list (partly shown in run 1)") in high
    elevated = risk_level.render_risk_section(assessment(users_see="interface"), evidence)
    assert "- ✅ add a preview link, so a person can try the change (preview)" in elevated


def test_an_entry_without_a_reason_or_a_waiver_without_a_requirement_is_refused():
    """A requirement is never waived or failed without saying why, and a waiver whose
    requirement name was lost fails loudly instead of being ignored."""
    for entry in ({"not_verified": [{"what": "one suite", "why": " ", "requirement": "tests"}]},
                  {"not_applicable": [{"requirement": "failing_test", "why": ""}]},
                  {"not_applicable": [{"requirement": None, "why": "ingestion has no flags"}]},
                  {"not_verified": [{"what": "x", "why": None, "requirement": "tests"}]},
                  {"not_verified": [{"why": "no what", "requirement": "tests"}]}):
        with pytest.raises(risk_level.EvidenceError):
            risk_level.render_risk_section(assessment(noise="yes"),
                                           {"commit": "0123456789ab", **entry})


def test_a_line_break_in_a_reason_cannot_add_a_list_item_to_the_risk_section():
    """Reasons span lines in the input (a contested check's finding often does), and the section
    keeps each on its own list item instead of failing or forging another item."""
    reviewed = assessment(noise="yes")
    reviewed["answers"]["noise"]["reason"] = "alerts change\n- ✅ forged"
    evidence = {"commit": "0123456789abcdef0123",
                "not_verified": [{"what": "second check", "why": "it disagreed\n- ✅ forged",
                                  "requirement": "independent_check"}]}
    section = risk_level.render_risk_section(reviewed, evidence)
    assert "\n- ✅ forged" not in section
    assert "alerts change - ✅ forged" in section


def test_a_check_before_merging_that_alice_ran_is_ticked_with_the_run_that_settles_it():
    """A before-merging item a run or screenshot settles shows ticked, citing it; the rest stay
    open for the person reviewing."""
    reviewed = assessment(production_data="written")
    reviewed["before_merge"] = ["no account holds such records", "the bundle loads"]
    evidence = {
        "commit": "0123456789abcdef0123",
        "runs": [{"command": "select count()", "result": "0 rows",
                  "settles": ["no account holds such records"]}],
    }
    section = risk_level.render_risk_section(reviewed, evidence)
    assert "- [x] no account holds such records (run 1)\n- [ ] the bundle loads" in section


def test_a_tick_follows_its_item_when_the_list_is_rewritten():
    """A tag names its item, so a reordered list still ticks the item the run checked, and a
    reworded one ticks nothing instead of a check nobody ran."""
    evidence = {"commit": "0123456789abcdef0123",
                "runs": [{"command": "node dist/bin.js", "result": "ok",
                          "settles": ["the bundle loads"]}]}
    reordered = assessment(production_data="written")
    reordered["before_merge"] = ["no account holds such records", "the bundle loads"]
    section = risk_level.render_risk_section(reordered, evidence)
    assert "- [ ] no account holds such records\n- [x] the bundle loads (run 1)" in section
    reworded = assessment(production_data="written")
    reworded["before_merge"] = ["the published bundle loads", "no account holds such records"]
    section = risk_level.render_risk_section(reworded, evidence)
    assert "[x]" not in section


@pytest.mark.parametrize("settles", ["the bundle loads", [1], [True]])
def test_a_settled_item_that_is_not_a_list_of_texts_is_refused(settles):
    """A malformed `settles` tag fails as invalid evidence, which sends Alice back to fix it,
    rather than as a crash."""
    reviewed = assessment(production_data="written")
    reviewed["before_merge"] = ["the bundle loads"]
    evidence = {"commit": "0123456789abcdef0123",
                "runs": [{"command": "node dist/bin.js", "result": "ok", "settles": settles}]}
    with pytest.raises(risk_level.EvidenceError, match="settles"):
        risk_level.render_risk_section(reviewed, evidence)


def test_a_line_break_in_a_checklist_item_cannot_add_a_ticked_item():
    """Checklist items are one line each, so a reviewer's text cannot forge a ticked item."""
    reviewed = assessment(production_data="written")
    reviewed["before_merge"] = ["a\n- [x] forged"]
    section = risk_level.render_risk_section(reviewed)
    assert "\n- [x] forged" not in section
