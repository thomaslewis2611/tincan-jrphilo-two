import importlib.machinery
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
POOL_EXEC = ROOT / "bin" / "tincan-pool-exec"


def load_pool_exec_module():
    loader = importlib.machinery.SourceFileLoader("tincan_pool_exec", str(POOL_EXEC))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    loader.exec_module(module)
    return module


MODULE = load_pool_exec_module()


class PoolExecArgumentTests(unittest.TestCase):
    def test_pool_exec_subcommand_parses_prompt(self):
        args = MODULE.parse_args(["pool-exec", "-p", "do something"])
        self.assertEqual(args.prompt, "do something")
        self.assertFalse(args.continue_run)
        self.assertFalse(args.dry_run)
        self.assertEqual(args.max_rounds, 5)
        self.assertEqual(args.repo, ".")

    def test_pool_exec_subcommand_parses_file_and_continue(self):
        args = MODULE.parse_args(
            ["pool-exec", "--repo", "/tmp/repo", "-f", "prompt.txt", "--continue"]
        )
        self.assertEqual(args.file, "prompt.txt")
        self.assertTrue(args.continue_run)
        self.assertEqual(args.repo, "/tmp/repo")

    def test_pool_exec_dry_run_flag(self):
        args = MODULE.parse_args(["pool-exec", "--dry-run", "-p", "hi"])
        self.assertTrue(args.dry_run)

    def test_pool_exec_skip_codex(self):
        args = MODULE.parse_args(["pool-exec", "-p", "hi", "--skip-codex"])
        self.assertTrue(args.skip_codex)
        self.assertFalse(args.skip_claude)

    def test_pool_exec_skip_claude(self):
        args = MODULE.parse_args(["pool-exec", "-p", "hi", "--skip-claude"])
        self.assertTrue(args.skip_claude)
        self.assertFalse(args.skip_codex)

    def test_pool_exec_no_skip_flags_default_false(self):
        args = MODULE.parse_args(["pool-exec", "-p", "hi"])
        self.assertFalse(args.skip_codex)
        self.assertFalse(args.skip_claude)

    def test_pool_exec_continue_dest_not_python_keyword(self):
        # args.continue is a Python keyword, so the dest must be continue_run
        args = MODULE.parse_args(["pool-exec", "--continue"])
        self.assertFalse(hasattr(args, "continue"))
        self.assertTrue(hasattr(args, "continue_run"))
        self.assertTrue(args.continue_run)

    def test_pool_review_subcommand(self):
        args = MODULE.parse_args(["pool-review", "--repo", "/tmp/repo"])
        self.assertEqual(args.func.__name__, "cmd_pool_review")
        self.assertEqual(args.repo, "/tmp/repo")


class PoolExecStateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.state_dir = self.root / "tincan"
        subprocess.run(["git", "init", "-q"], cwd=self.root, check=True)
        subprocess.run(
            ["git", "config", "user.email", "tincan@example.invalid"],
            cwd=self.root,
            check=True,
        )
        subprocess.run(["git", "config", "user.name", "Tincan"], cwd=self.root, check=True)

    def tearDown(self):
        self.temp.cleanup()

    def test_load_state_returns_empty_dict_for_missing(self):
        self.assertEqual(MODULE.load_state(self.state_dir), {})

    def test_save_and_load_state_roundtrip(self):
        state = {"poolside_mode": True, "poolside_round": 1}
        MODULE.save_state(self.state_dir, state)
        loaded = MODULE.load_state(self.state_dir)
        self.assertEqual(loaded, state)

    def test_dry_run_shows_pool_mode(self):
        state = {
            "poolside_mode": True,
            "base_commit": "abc123",
            "poolside_round": 2,
            "poolside_status": "approved",
        }
        state_dir = self.root / ".git" / "tincan"
        MODULE.save_state(state_dir, state)
        result = subprocess.run(
            [str(POOL_EXEC), "pool-exec", "--repo", str(self.root), "--dry-run"],
            text=True,
            capture_output=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("pool_mode: True", result.stdout)
        self.assertIn("base:      abc123", result.stdout)
        self.assertIn("round:     2", result.stdout)
        self.assertIn("status:    approved", result.stdout)

    def test_dry_run_shows_unarmed_mode(self):
        result = subprocess.run(
            [str(POOL_EXEC), "pool-exec", "--repo", str(self.root), "--dry-run"],
            text=True,
            capture_output=True,
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("pool_mode: False", result.stdout)
        self.assertIn("status:    not started", result.stdout)


class PoolExecHelperTests(unittest.TestCase):
    def test_review_schema_has_required_fields(self):
        schema = MODULE.REVIEW_SCHEMA
        self.assertEqual(schema["type"], "object")
        self.assertIn("verdict", schema["properties"])
        self.assertIn("summary", schema["properties"])
        self.assertIn("findings", schema["properties"])
        self.assertIn("verification", schema["properties"])
        self.assertEqual(schema["required"], ["verdict", "summary", "findings", "verification"])

    def test_format_findings_empty(self):
        self.assertEqual(MODULE.format_findings([]), "(no findings were reported)")

    def test_format_findings_blocking(self):
        findings = [
            {
                "severity": "blocking",
                "title": "SQL injection",
                "details": "Query is built via string concatenation.",
                "file": "src/db.py",
                "line": 42,
            }
        ]
        rendered = MODULE.format_findings(findings)
        self.assertIn("[BLOCKING] SQL injection (src/db.py:42)", rendered)
        self.assertIn("Query is built via string concatenation.", rendered)

    def test_format_findings_suggestion(self):
        findings = [
            {
                "severity": "suggestion",
                "title": "Use list comprehension",
                "details": "Could be more concise.",
                "file": "src/util.py",
                "line": 10,
            }
        ]
        rendered = MODULE.format_findings(findings)
        self.assertIn("[SUGGESTION] Use list comprehension (src/util.py:10)", rendered)

    def test_blocking_findings_filters(self):
        findings = [
            {"severity": "blocking", "title": "A", "details": "", "file": None, "line": None},
            {"severity": "suggestion", "title": "B", "details": "", "file": None, "line": None},
            {"severity": "blocking", "title": "C", "details": "", "file": None, "line": None},
        ]
        blockers = MODULE.blocking_findings(findings)
        self.assertEqual(len(blockers), 2)
        self.assertEqual(blockers[0]["title"], "A")
        self.assertEqual(blockers[1]["title"], "C")

    def test_followup_prompt_includes_findings_and_reviews(self):
        prompt = MODULE.followup_prompt(
            findings_text="1. [BLOCKING] Bug (src/app.py:10): fix this",
            codex_review="Codex found an issue",
            claude_review="verdict=changes_requested summary=agreed",
        )
        self.assertIn("Address these review findings", prompt)
        self.assertIn("1. [BLOCKING] Bug (src/app.py:10): fix this", prompt)
        self.assertIn("Original Codex review:", prompt)
        self.assertIn("Codex found an issue", prompt)
        self.assertIn("Original Claude review:", prompt)
        self.assertIn("verdict=changes_requested summary=agreed", prompt)


class CodexReviewParsingTests(unittest.TestCase):
    def test_parse_codex_review_no_findings(self):
        # "No actionable defects found" text has no codex finding format markers
        text = "The only change is a new file. No actionable defects were found."
        findings = MODULE.parse_codex_review(text)
        self.assertEqual(findings, [])

    def test_parse_codex_review_finds_blocking_and_suggestion(self):
        text = (
            "- [P1] Critical security flaw — src/app.py:42\n"
            "  The password is hardcoded in the source.\n"
            "- [P3] Consider using a context manager — src/util.py:10\n"
            "  A with-statement would be cleaner."
        )
        findings = MODULE.parse_codex_review(text)
        self.assertEqual(len(findings), 2)
        self.assertEqual(findings[0]["severity"], "blocking")
        self.assertEqual(findings[0]["title"], "Critical security flaw")
        self.assertEqual(findings[0]["file"], "src/app.py")
        self.assertEqual(findings[0]["line"], 42)
        self.assertEqual(findings[0]["details"], "The password is hardcoded in the source.")
        self.assertEqual(findings[1]["severity"], "suggestion")
        self.assertEqual(findings[1]["title"], "Consider using a context manager")
        self.assertEqual(findings[1]["file"], "src/util.py")
        self.assertEqual(findings[1]["line"], 10)


class PoolExecDryRunIntegrationTests(unittest.TestCase):
    def test_tincan_launcher_dispatches_pool_exec(self):
        """The launcher should route `tincan pool-exec --dry-run` correctly."""
        launcher = ROOT / "bin" / "tincan"
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary)
            subprocess.run(["git", "init", "-q", str(repo)], check=True)
            result = subprocess.run(
                [str(launcher), "pool-exec", "--repo", str(repo), "--dry-run"],
                text=True,
                capture_output=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("pool_mode", result.stdout)


class PoolExecRunIdExtractionTests(unittest.TestCase):
    def test_run_pool_exec_extracts_run_id_from_events(self):
        """run_pool_exec should extract a runId from pool's JSONL output."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            subprocess.run(["git", "init", "-q", str(root)], check=True)
            fake_pool = root / "fake-pool"
            fake_pool.write_text(
                "#!/usr/bin/env python3\n"
                "import json, sys\n"
                "print(json.dumps({'type': 'reasoning', 'reasoning': 'starting'}))\n"
                "print(json.dumps({'type': 'exit', 'args': {'success': True}}))\n"
            )
            fake_pool.chmod(0o755)
            with mock.patch.dict(
                os.environ, {"TINCAN_POOL": str(fake_pool)}
            ):
                rc, stdout, run_id = MODULE.run_pool_exec(root, "test prompt", continue_run=False)
            self.assertEqual(rc, 0)
            self.assertIn("reasoning", stdout)
            # No runId in the event stream → run_id should be None
            self.assertIsNone(run_id)

    def test_run_pool_exec_with_continue_flag(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            subprocess.run(["git", "init", "-q", str(root)], check=True)
            fake_pool = root / "fake-pool"
            fake_pool.write_text(
                "#!/usr/bin/env python3\n"
                "import json, sys\n"
                "print(json.dumps({'type': 'exit', 'args': {'success': True}}))\n"
            )
            fake_pool.chmod(0o755)
            with mock.patch.dict(
                os.environ, {"TINCAN_POOL": str(fake_pool)}
            ):
                with mock.patch.object(
                    MODULE.subprocess, "run"
                ) as mock_run:
                    mock_run.return_value = mock.Mock(
                        returncode=0, stdout="", stderr=""
                    )
                    MODULE.run_pool_exec(root, "prompt", continue_run=True)
                    args = mock_run.call_args.args[0]
                    self.assertIn("--continue", args)


if __name__ == "__main__":
    unittest.main()
