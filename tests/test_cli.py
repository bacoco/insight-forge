"""Tests for insight_forge.cli — the console-scripts entry point.

The CLI is a dispatcher; we test that it correctly routes subcommands to
the underlying scripts and surfaces help / version / doctor output.
"""
from __future__ import annotations

import io
import sys
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

import pytest

from insight_forge import __version__
from insight_forge.cli import main, _exec_script


def _capture(argv):
    """Run cli.main with stdout/stderr captured."""
    out = io.StringIO()
    err = io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        rc = main(argv)
    return rc, out.getvalue(), err.getvalue()


def test_version_via_flag():
    rc, out, err = _capture(["--version"])
    assert rc == 0
    assert __version__ in out


def test_help_short_circuits():
    rc, out, _ = _capture(["--help"])
    assert rc == 0
    assert "scan" in out and "eval" in out and "propose" in out


def test_unknown_subcommand_returns_error():
    rc, _, err = _capture(["wishful-thinking"])
    assert rc != 0
    assert "unknown command" in err


def test_default_subcommand_is_scan():
    """Calling `insight-forge` with no args should dispatch to `scan` (run.py).
    We mock the dispatcher so we don't actually run the pipeline here."""
    with patch("insight_forge.cli._exec_script") as exec_mock:
        exec_mock.return_value = 0
        rc = main([])
    assert rc == 0
    assert exec_mock.called
    args, _ = exec_mock.call_args
    assert args[0] == "run.py"


def test_eval_dispatches_to_run_evals():
    with patch("insight_forge.cli._exec_script") as exec_mock:
        exec_mock.return_value = 0
        rc = main(["eval", "--verify-contracts"])
    assert rc == 0
    args, _ = exec_mock.call_args
    assert args[0] == "run_evals.py"
    assert args[1] == ["--verify-contracts"]


def test_propose_dispatches_to_propose_rules():
    with patch("insight_forge.cli._exec_script") as exec_mock:
        exec_mock.return_value = 0
        rc = main(["propose", "--dry-run"])
    assert rc == 0
    args, _ = exec_mock.call_args
    assert args[0] == "propose_rules.py"
    assert args[1] == ["--dry-run"]


def test_validate_evidence_dispatches():
    with patch("insight_forge.cli._exec_script") as exec_mock:
        exec_mock.return_value = 0
        rc = main(["validate-evidence", "--evals"])
    assert rc == 0
    args, _ = exec_mock.call_args
    assert args[0] == "validate_evidence.py"


def test_passthrough_args_preserved():
    """Flags after the subcommand must reach the underlying script untouched.
    This is the contract that lets us avoid redefining every script's flags."""
    with patch("insight_forge.cli._exec_script") as exec_mock:
        exec_mock.return_value = 0
        main(["eval", "--fixture", "simple_success", "--json"])
    args, _ = exec_mock.call_args
    assert args[1] == ["--fixture", "simple_success", "--json"]


def test_doctor_runs_and_returns_int():
    """doctor is implemented inline (not a subprocess) — verify it runs and
    produces a status report. Exit code depends on the local environment."""
    rc, out, _ = _capture(["doctor"])
    assert isinstance(rc, int)
    assert "environment diagnostic" in out


def test_exec_script_returns_2_for_missing_script(tmp_path, monkeypatch):
    """If a script is missing, the dispatcher should return exit code 2,
    not crash."""
    # Repoint SCRIPTS at a directory with no files so the resolution fails
    monkeypatch.setattr("insight_forge.cli.SCRIPTS", tmp_path)
    rc = _exec_script("nonexistent.py", [])
    assert rc == 2
