import importlib.util
from pathlib import Path
import subprocess
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from modules import mod_buff


class VideoSupportTest(unittest.TestCase):
    def test_moviepy_flag_matches_installed_environment(self):
        expected = importlib.util.find_spec("moviepy") is not None

        self.assertEqual(mod_buff.HAS_MOVIEPY, expected)

    def test_video_dependency_smoke_command_passes(self):
        launcher = Path(__file__).resolve().parents[1] / "single_page_launcher.py"

        result = subprocess.run(
            [sys.executable, str(launcher), "--smoke-video-deps"],
            timeout=5,
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)


if __name__ == "__main__":
    unittest.main()
