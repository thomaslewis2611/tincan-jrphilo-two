import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
HOOK = ROOT / "bin" / "tincan-claude-hook"


class ClaudeHookIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.repo_path = Path(self.temporary.name)
        subprocess.run(["git", "init", "-q"], cwd=self.repo_path, check=True)
        self.repo = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=self.repo_path,
            check=True,
            text=True,
            capture_output=True,
        ).stdout.strip()
        self.token = "b" * 32
        sessions = self.repo_path / ".git" / "tincan" / "pane-sessions"
        sessions.mkdir(parents=True)
        self.session_path = sessions / f"{self.token}.json"
        self.prompt_path = self.repo_path / ".git" / "codex-prompt.txt"
        self.args_path = self.repo_path / ".git" / "pane-args.json"
        self.fake_pane = self.repo_path / ".git" / "fake-pane"
        self.fake_pane.write_text(
            "#!/usr/bin/env python3\n"
            "import json, os, pathlib, sys\n"
            "pathlib.Path(os.environ['FAKE_CODEX_PROMPT']).write_text(sys.stdin.read())\n"
            "pathlib.Path(os.environ['FAKE_PANE_ARGS']).write_text(json.dumps(sys.argv[1:]))\n"
        )
        self.fake_pane.chmod(0o755)

    def tearDown(self):
        self.temporary.cleanup()

    def invoke(self, message: str, round_number: int = 1, max_rounds: int = 5):
        self.session_path.write_text(
            json.dumps(
                {
                    "enabled": True,
                    "repo": self.repo,
                    "session_token": self.token,
                    "status": "awaiting-claude",
                    "handoffs": 1,
                    "round": round_number,
                    "max_rounds": max_rounds,
                }
            )
        )
        environment = os.environ.copy()
        environment["TINCAN_SESSION"] = self.token
        environment["TINCAN_PANE"] = str(self.fake_pane)
        environment["FAKE_CODEX_PROMPT"] = str(self.prompt_path)
        environment["FAKE_PANE_ARGS"] = str(self.args_path)
        result = subprocess.run(
            [str(HOOK)],
            cwd=self.repo_path,
            input=json.dumps(
                {
                    "cwd": str(self.repo_path),
                    "session_id": "visible-claude",
                    "last_assistant_message": message,
                }
            ),
            text=True,
            capture_output=True,
            env=environment,
            check=True,
        )
        return json.loads(result.stdout), json.loads(self.session_path.read_text())

    def test_approval_returns_to_codex_and_waits_for_its_summary(self):
        output, session = self.invoke(
            "No blocking findings.\n\nTINCAN_VERDICT: APPROVED"
        )
        pane_args = json.loads(self.args_path.read_text())
        self.assertIn("approved review round 1", output["systemMessage"])
        self.assertIn("No blocking findings.", self.prompt_path.read_text())
        self.assertEqual(pane_args[pane_args.index("--agent") + 1], "codex")
        self.assertTrue(session["enabled"])
        self.assertEqual(session["status"], "awaiting-codex-summary")
        self.assertEqual(session["handoffs"], 2)
        self.assertEqual(session["claude_session_id"], "visible-claude")

    def test_changes_requested_returns_to_codex_and_keeps_loop_open(self):
        output, session = self.invoke(
            "Blocking: empty input fails.\n\nTINCAN_VERDICT: CHANGES_REQUESTED"
        )
        prompt = self.prompt_path.read_text()
        self.assertIn("requested changes in round 1", output["systemMessage"])
        self.assertIn("push back with concrete", prompt)
        self.assertTrue(session["enabled"])
        self.assertEqual(session["status"], "awaiting-codex")
        self.assertEqual(session["last_verdict"], "CHANGES_REQUESTED")

    def test_round_limit_stops_for_human_adjudication(self):
        _output, session = self.invoke(
            "The disagreement remains.\n\nTINCAN_VERDICT: CHANGES_REQUESTED",
            round_number=3,
            max_rounds=3,
        )
        self.assertIn("ask the user to adjudicate", self.prompt_path.read_text())
        self.assertFalse(session["enabled"])
        self.assertEqual(session["status"], "needs-human")

    def test_missing_verdict_fails_closed_to_human(self):
        _output, session = self.invoke("I reviewed the code but forgot the marker.")
        self.assertFalse(session["enabled"])
        self.assertEqual(session["status"], "needs-human")
        self.assertEqual(session["last_verdict"], "missing")


if __name__ == "__main__":
    unittest.main()
