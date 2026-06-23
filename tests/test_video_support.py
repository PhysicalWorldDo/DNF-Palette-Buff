import importlib.util
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from modules import mod_buff


class VideoSupportTest(unittest.TestCase):
    def test_moviepy_flag_matches_installed_environment(self):
        expected = importlib.util.find_spec("moviepy") is not None

        self.assertEqual(mod_buff.HAS_MOVIEPY, expected)


if __name__ == "__main__":
    unittest.main()
