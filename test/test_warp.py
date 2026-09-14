import os
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
WARP = ROOT / "bin" / "tincan-warp"


class WarpLauncherTests(unittest.TestCase):
    def test_writes_two_real_terminal_panes_for_repo_root(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            repo = base / "repo"
            child = repo / "nested"
            config_dir = base / "warp"
            child.mkdir(parents=True)
            subprocess.run(["git", "init", "-q", str(repo)], check=True)

            environment = os.environ.copy()
            environment["TINCAN_WARP_CONFIG_DIR"] = str(config_dir)
            result = subprocess.run(
                [str(WARP), "--repo", str(child), "--dry-run"],
                text=True,
                capture_output=True,
                env=environment,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            config = (config_dir / "tincan_pair.toml").read_text()
            self.assertIn('split = "horizontal"', config)
            self.assertEqual(config.count(f'directory = "{repo.resolve()}"'), 2)
            self.assertIn("tincan codex-pane", config)
            self.assertIn("tincan claude-pane", config)
            self.assertEqual(config.count("--session"), 2)
            self.assertIn(str(repo.resolve()), config)
            self.assertIn('is_focused = true', config)
            self.assertIn("new_window=true", result.stdout)

    def test_rejects_a_non_git_directory(self):
        with tempfile.TemporaryDirectory() as temporary:
            result = subprocess.run(
                [str(WARP), "--repo", temporary, "--dry-run"],
                text=True,
                capture_output=True,
            )

            self.assertEqual(result.returncode, 2)
            self.assertIn("not inside a Git repository", result.stderr)

    def test_brainstorm_dry_run_writes_brainstorm_workspace(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            repo = base / "repo"
            config_dir = base / "warp"
            subprocess.run(["git", "init", "-q", str(repo)], check=True)
            environment = os.environ.copy()
            environment["TINCAN_WARP_CONFIG_DIR"] = str(config_dir)

            result = subprocess.run(
                [str(WARP), "--repo", str(repo), "--brainstorm", "--dry-run"],
                text=True,
                capture_output=True,
                env=environment,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            config = (config_dir / "tincan_pair.toml").read_text()
            self.assertIn('name = "Tincan Brainstorm"', config)
            self.assertIn('title = "Tincan Brainstorm', config)


if __name__ == "__main__":
    unittest.main()
