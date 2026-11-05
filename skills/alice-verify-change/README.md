# Verify change

Functional verification at the level `alice-assess-risk` set: map the touched surfaces to methods, run them on the local stack and with a headless browser, capture screenshots and recordings, and write evidence that names the commit it verified. At 4 High, a second agent repeats the check without the author's reasoning.

## Why it exists

Her PR's reviewer did not watch her work and has no local stack of hers to try it on, so the PR must carry evidence a reviewer can trust without re-running it. The opinions:

- **No PR is handed over before the change was exercised end to end**, or says plainly what could not be and why. "Not verified" is always present.
- **Evidence names its commit.** A fix after verifying means verifying again; docs and comments do not.
- **Nothing is ticked by hand.** Each run, screenshot and recording is tagged with the requirements it proves, and the Risk section marks each requirement from those tags.
- **Agents grading their own work skew positive**, so at the highest level a fresh agent drives the reported scenario and checks that the new tests fail at the merge base.
- **Evidence comes from the company's own test accounts**, since a customer's account shows far more than a PR may carry.

## How it fits

Called by `/ship-it`'s Alice steps after the code review's fixes, and again after the pipeline's last behavior-changing fix. It writes `evidence.json`, which `scripts/alice/risk_level.py` renders into the Risk section, and pushes media through `scripts/alice/evidence.py`.

## To run it

A local stack that starts against a local copy of the database (so saves never reach production), with an automatic sign-in for a test login; a headless browser; the `alice-evidence` branch for screenshots and a shared drive folder for recordings (`scripts/alice/shared_drive.py` is the stub to wire); and two test accounts in production that the test login may write.

The instructions are in [SKILL.md](SKILL.md).
