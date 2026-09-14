import importlib.machinery
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
HOOK = ROOT / "bin" / "tincan-brainstorm-hook"


def load_hook_module():
    loader = importlib.machinery.SourceFileLoader("tincan_brainstorm_hook", str(HOOK))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


MODULE = load_hook_module()


class BrainstormHookTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name).resolve()
        self.token = "a" * 32
        self.session_path = self.root / f"{self.token}.json"
        self.write_session(
            {
                "enabled": True,
                "mode": "brainstorm",
                "repo": str(self.root),
                "session_token": self.token,
                "status": "awaiting-user",
                "cycle": 0,
            }
        )

    def tearDown(self):
        self.temporary.cleanup()

    def write_session(self, value):
        self.session_path.write_text(json.dumps(value))

    def session(self):
        return json.loads(self.session_path.read_text())

    def stop(self, agent, message):
        return MODULE.handle_stop(
            self.root,
            self.session_path,
            self.token,
            agent,
            {"last_assistant_message": message, "session_id": f"{agent}-session"},
        )

    def test_user_prompt_starts_both_independent_views(self):
        with mock.patch.object(MODULE, "send_to_pane", return_value=None) as send:
            output = MODULE.handle_user_prompt(
                self.root, self.session_path, self.token, "Which domain should I buy?"
            )

        state = self.session()
        self.assertEqual(state["status"], "independent")
        self.assertEqual(state["cycle"], 1)
        self.assertEqual(state["user_prompt"], "Which domain should I buy?")
        self.assertIn("both independent views", output["systemMessage"])
        self.assertIn(
            "roughly 150 words",
            output["hookSpecificOutput"]["additionalContext"],
        )
        self.assertEqual(send.call_args.args[:3], (self.root, self.token, "claude"))
        self.assertIn("same prompt", send.call_args.args[3])
        self.assertIn("roughly 150 words", send.call_args.args[3])

    def test_second_initial_view_cross_shares_without_anchoring_first(self):
        self.write_session(
            {
                **self.session(),
                "status": "independent",
                "cycle": 1,
                "user_prompt": "Choose a direction",
                "initial": {},
            }
        )
        first = self.stop("codex", "Codex initially prefers A.")
        self.assertNotIn("decision", first)

        with mock.patch.object(MODULE, "send_to_pane", return_value=None) as send:
            second = self.stop("claude", "Claude independently prefers B.")

        state = self.session()
        self.assertEqual(state["status"], "reflection")
        self.assertEqual(state["initial"]["codex"], "Codex initially prefers A.")
        self.assertEqual(state["initial"]["claude"], "Claude independently prefers B.")
        self.assertEqual(send.call_args.args[2], "codex")
        self.assertIn("Claude independently prefers B.", send.call_args.args[3])
        self.assertEqual(second["decision"], "block")
        self.assertIn("Codex initially prefers A.", second["reason"])
        self.assertIn("Report only the delta", second["reason"])

    def test_reflections_trigger_codex_synthesis_then_rearm(self):
        self.write_session(
            {
                **self.session(),
                "status": "reflection",
                "cycle": 1,
                "user_prompt": "Choose a direction",
                "initial": {"codex": "A", "claude": "B"},
                "reflections": {},
            }
        )
        first = self.stop("codex", "Codex now prefers A plus one part of B.")
        self.assertNotIn("decision", first)

        with mock.patch.object(MODULE, "send_to_pane", return_value=None) as send:
            second = self.stop("claude", "Claude still prefers B, for this reason.")

        self.assertEqual(self.session()["status"], "synthesis")
        self.assertEqual(send.call_args.args[2], "codex")
        synthesis_prompt = send.call_args.args[3]
        self.assertIn("Codex now prefers A", synthesis_prompt)
        self.assertIn("Claude still prefers B", synthesis_prompt)
        self.assertIn("unresolved disagreement", synthesis_prompt)
        self.assertIn("Compress rather than chronicle", synthesis_prompt)
        self.assertNotIn("decision", second)

        completed = self.stop("codex", "Here is the combined answer, with one disagreement.")
        state = self.session()
        self.assertEqual(state["status"], "awaiting-user")
        self.assertEqual(
            state["synthesis"], "Here is the combined answer, with one disagreement."
        )
        self.assertIn("ready for your next prompt", completed["systemMessage"])

    def test_new_user_prompt_is_blocked_during_active_cycle(self):
        state = self.session()
        state["status"] = "reflection"
        self.write_session(state)

        with mock.patch.object(MODULE, "send_to_pane") as send:
            output = MODULE.handle_user_prompt(
                self.root, self.session_path, self.token, "A second question"
            )

        self.assertEqual(output["decision"], "block")
        self.assertIn("still completing", output["reason"])
        send.assert_not_called()


if __name__ == "__main__":
    unittest.main()
