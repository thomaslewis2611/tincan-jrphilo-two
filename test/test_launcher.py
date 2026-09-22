from pathlib import Path
import os
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = ROOT / "bin" / "tincan"


class LauncherTests(unittest.TestCase):
    def test_symlinked_launcher_finds_sibling_commands(self):
        with tempfile.TemporaryDirectory() as temporary:
            temporary_path = Path(temporary)
            link = temporary_path / "tincan"
            link.symlink_to(LAUNCHER)
            environment = os.environ.copy()
            environment["TINCAN_WARP_CONFIG_DIR"] = str(temporary_path / "warp")

            result = subprocess.run(
                [str(link), "warp", "--repo", str(ROOT), "--dry-run"],
                text=True,
                capture_output=True,
                env=environment,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("would open warp://", result.stdout)


if __name__ == "__main__":
    unittest.main()
