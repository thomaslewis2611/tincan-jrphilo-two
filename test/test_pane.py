import importlib.machinery
import importlib.util
from pathlib import Path
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
PANE = ROOT / "bin" / "tincan-pane"


def load_pane_module():
    loader = importlib.machinery.SourceFileLoader("tincan_pane", str(PANE))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


PANE_MODULE = load_pane_module()


class PaneControlTests(unittest.TestCase):
    def test_prompt_encoding_submits_single_line(self):
        self.assertEqual(PANE_MODULE.encoded_prompt("hello"), b"hello\r")

    def test_multiline_prompt_uses_bracketed_paste(self):
        encoded = PANE_MODULE.encoded_prompt("first\nsecond")
        self.assertEqual(encoded, b"\x1b[200~first\nsecond\x1b[201~\r")

    def test_codex_uses_automatic_approval_review_and_branch_guidance(self):
        repo = ROOT.resolve()
        with mock.patch.object(PANE_MODULE, "run_agent", return_value=0) as run_agent:
            result = PANE_MODULE.run_codex(repo, "a" * 32)

        self.assertEqual(result, 0)
        args = run_agent.call_args.args
        self.assertEqual(args[:3], (repo, "a" * 32, "codex"))
        self.assertEqual(args[3][:3], ["codex", "--approve-for-me", "-c"])
        self.assertIn(
            "Do not implement directly on the repository's default branch",
            args[3][3],
        )
        self.assertIn("AGENTS.md", args[3][3])
        self.assertIn("Preserve all existing changes", args[3][3])

    def test_claude_uses_auto_permission_mode(self):
        repo = ROOT.resolve()
        with (
            mock.patch.object(PANE_MODULE, "session_state", return_value={}),
            mock.patch.object(PANE_MODULE, "run_agent", return_value=0) as run_agent,
        ):
            result = PANE_MODULE.run_claude(repo, "a" * 32)

        self.assertEqual(result, 0)
        self.assertEqual(
            run_agent.call_args.args,
            (repo, "a" * 32, "claude", ["claude", "--permission-mode", "auto"]),
        )

    def test_send_delivers_prompt_to_repo_socket(self):
        class FakeSocket:
            def __init__(self):
                self.sent = b""
                self.connected_to = None

            def connect(self, path):
                self.connected_to = path

            def sendall(self, data):
                self.sent += data

            def recv(self, _size):
                return b'{"ok": true}\n'

            def close(self):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                self.close()

        client = FakeSocket()
        repo = ROOT.resolve()
        with mock.patch.object(PANE_MODULE.socket, "socket", return_value=client):
            result = PANE_MODULE.send_prompt(
                repo, "hello Claude", 0, "a" * 32, "codex"
            )

        self.assertEqual(result, 0)
        self.assertEqual(client.sent, b'{"prompt": "hello Claude"}\n')
        self.assertEqual(
            client.connected_to,
            str(PANE_MODULE.control_socket_path(repo, "a" * 32, "codex")),
        )


if __name__ == "__main__":
    unittest.main()
