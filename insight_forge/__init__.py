"""Insight Forge — cross-session ARA-style learner.

This package only houses the CLI entry point. The actual pipeline,
classifier rules, eval harness, and proposers live in `scripts/` and
`harness/` to keep the layout script-oriented (the project's house style).

The CLI is a thin dispatcher — it shells out to the existing scripts so
that running them directly stays the documented, supported way.
"""
__version__ = "0.1.0"
