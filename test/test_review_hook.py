import importlib.util
from importlib.machinery import SourceFileLoader
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


HOOK = Path(__file__).resolve().parents[1] / "bin" / "tincan-review-hook"
SPEC = importlib.util.spec_from_loader(
    "tincan_review_hook", SourceFileLoader("tincan_review_hook", str(HOOK))
)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class ReviewParsingTests(unittest.TestCase):
    def test_parses_structured_output(self):
        review = {
            "verdict": "approved",
            "summary": "Looks good.",
            "findings": [],
            "verification": ["npm test (exit 0)"],
        }
        self.assertEqual(MODULE.parse_structured({"structured_output": review}), review)

    def test_parses_json_result_fallback(self):
        review = {
            "verdict": "changes_requested",
            "summary": "One bug.",
            "findings": [],
            "verification": [],
        }
        self.assertEqual(MODULE.parse_structured({"result": json.dumps(review)}), review)

    def test_formats_blocking_finding(self):
        rendered = MODULE.format_review(
            {
                "verdict": "changes_requested",
                "summary": "Boundary failure.",
                "findings": [
                    {
                        "severity": "blocking",
                        "title": "Off by one",
                        "details": "The last item is skipped.",
                        "file": "src/app.ts",
                        "line": 42,
                    }
                ],
                "verification": ["npm test (exit 1)"],
            }
        )
        self.assertIn("BLOCKING Off by one (src/app.ts:42)", rendered)
        self.assertIn("npm test (exit 1)", rendered)

    def test_renders_claude_tool_activity(self):
        output = io.StringIO()
        MODULE.render_claude_event(
            {
                "type": "assistant",
                "message": {
                    "content": [
                        {
                            "type": "tool_use",
                            "name": "Read",
                            "input": {"file_path": "src/app.ts"},
                        }
                    ]
                },
            },
            output,
        )
        self.assertIn('[claude tool] Read {"file_path": "src/app.ts"}', output.getvalue())


class ReviewHookIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        subprocess.run(["git", "init", "-q"], cwd=self.root, check=True)
        subprocess.run(["git", "config", "user.name", "Tincan Test"], cwd=self.root, check=True)
        subprocess.run(["git", "config", "commit.gpgsign", "false"], cwd=self.root, check=True)
        subprocess.run(
            ["git", "config", "user.email", "tincan@example.invalid"],
            cwd=self.root,
            check=True,
        )
        (self.root / "README.md").write_text("test\n")
        subprocess.run(["git", "add", "README.md"], cwd=self.root, check=True)
        subprocess.run(["git", "commit", "-qm", "initial"], cwd=self.root, check=True)
        self.git_dir = self.root / ".git"
        self.run_dir = self.git_dir / "tincan" / "runs" / "test"
        self.run_dir.mkdir(parents=True)
        self.log_path = self.run_dir / "events.log"
        self.log_path.write_text("test\n")
        self.fake_claude = self.git_dir / "fake-claude"
        self.fake_claude.write_text(
            "#!/usr/bin/env python3\n"
            "import json, os\n"
            "review = json.loads(os.environ['FAKE_REVIEW'])\n"
            "print(json.dumps({'type':'system','subtype':'init','session_id':'claude-test'}))\n"
            "print(json.dumps({'type':'assistant','message':{'content':["
            "{'type':'tool_use','name':'Read','input':{'file_path':'README.md'}}]}}))\n"
            "print(json.dumps({'type':'result','subtype':'success','session_id':'claude-test',"
            "'structured_output':review}))\n"
        )
        self.fake_claude.chmod(0o755)

    def tearDown(self):
        self.temp.cleanup()

    def test_change_detection_ignores_unchanged_checkout(self):
        base = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=self.root,
            check=True,
            text=True,
            capture_output=True,
        ).stdout.strip()
        self.assertFalse(MODULE.has_changes(self.root, base))
        (self.root / "new-file.txt").write_text("new\n")
        self.assertTrue(MODULE.has_changes(self.root, base))

    def invoke(self, review):
        (self.root / "README.md").write_text("test\nchanged\n")
        state = {
            "enabled": True,
            "status": "armed",
            "repo": str(self.root),
            "base_commit": subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=self.root,
                check=True,
                text=True,
                capture_output=True,
            ).stdout.strip(),
            "task_label": "test task",
            "task_context": "Make the test change",
            "max_rounds": 3,
            "round": 0,
            "session_id": None,
            "claude_session_id": None,
            "run_dir": str(self.run_dir),
            "log_path": str(self.log_path),
        }
        state_path = self.git_dir / "tincan" / "state.json"
        state_path.write_text(json.dumps(state))
        env = os.environ.copy()
        env["TINCAN_CLAUDE"] = str(self.fake_claude)
        env["FAKE_REVIEW"] = json.dumps(review)
        result = subprocess.run(
            [str(HOOK)],
            cwd=self.root,
            input=json.dumps(
                {
                    "cwd": str(self.root),
                    "session_id": "codex-test",
                    "last_assistant_message": "Implemented and tested.",
                }
            ),
            text=True,
            capture_output=True,
            env=env,
            check=True,
        )
        return json.loads(result.stdout), json.loads(state_path.read_text())

    def test_approval_disarms_gate(self):
        output, state = self.invoke(
            {
                "verdict": "approved",
                "summary": "No blocking problems.",
                "findings": [],
                "verification": ["inspection"],
            }
        )
        self.assertIn("approved", output["systemMessage"])
        self.assertFalse(state["enabled"])
        self.assertEqual(state["status"], "approved")
        self.assertEqual(state["session_id"], "codex-test")
        self.assertEqual(state["claude_session_id"], "claude-test")
        self.assertIn("[claude tool] Read", self.log_path.read_text())

    def test_blocker_continues_codex(self):
        output, state = self.invoke(
            {
                "verdict": "changes_requested",
                "summary": "A bug remains.",
                "findings": [
                    {
                        "severity": "blocking",
                        "title": "Broken edge case",
                        "details": "Handle empty input.",
                        "file": "README.md",
                        "line": 1,
                    }
                ],
                "verification": [],
            }
        )
        self.assertEqual(output["decision"], "block")
        self.assertIn("BLOCKING Broken edge case", output["reason"])
        self.assertTrue(state["enabled"])
        self.assertEqual(state["status"], "changes-requested")

    def test_visible_session_hands_completed_turn_to_paired_claude(self):
        token = "a" * 32
        repo = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=self.root,
            check=True,
            text=True,
            capture_output=True,
        ).stdout.strip()
        sessions = self.git_dir / "tincan" / "pane-sessions"
        sessions.mkdir(parents=True)
        session_path = sessions / f"{token}.json"
        session_path.write_text(
            json.dumps(
                {
                    "enabled": True,
                    "repo": repo,
                    "session_token": token,
                    "status": "awaiting-codex",
                    "handoffs": 0,
                    "round": 0,
                    "max_rounds": 5,
                }
            )
        )
        prompt_path = self.git_dir / "visible-prompt.txt"
        fake_pane = self.git_dir / "fake-pane"
        fake_pane.write_text(
            "#!/usr/bin/env python3\n"
            "import os, pathlib, sys\n"
            "pathlib.Path(os.environ['FAKE_PANE_PROMPT']).write_text(sys.stdin.read())\n"
            "print('sent')\n"
        )
        fake_pane.chmod(0o755)
        environment = os.environ.copy()
        environment["TINCAN_SESSION"] = token
        environment["TINCAN_PANE"] = str(fake_pane)
        environment["FAKE_PANE_PROMPT"] = str(prompt_path)

        result = subprocess.run(
            [str(HOOK)],
            cwd=self.root,
            input=json.dumps(
                {
                    "cwd": str(self.root),
                    "session_id": "visible-codex",
                    "last_assistant_message": "Completed the contained test.",
                }
            ),
            text=True,
            capture_output=True,
            env=environment,
            check=True,
        )

        output = json.loads(result.stdout)
        session = json.loads(session_path.read_text())
        self.assertIn("visible Claude pane", output["systemMessage"])
        self.assertIn("Completed the contained test.", prompt_path.read_text())
        self.assertEqual(session["handoffs"], 1)
        self.assertEqual(session["round"], 1)
        self.assertEqual(session["status"], "awaiting-claude")
        self.assertEqual(session["codex_session_id"], "visible-codex")


if __name__ == "__main__":
    unittest.main()
