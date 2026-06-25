import subprocess
import tempfile
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from modules.mod_buff import build_hidden_bk2


class RadCommandTest(unittest.TestCase):
    def test_radvideo_uses_binkc_compressor_command(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            frames = root / "frames"
            frames.mkdir()
            (frames / "frame_0000.png").write_bytes(b"fake")
            rad = root / "radvideo64.exe"
            rad.write_bytes(b"fake exe")
            output = root / "out.bk2"
            captured = {}

            def fake_run(cmd, **kwargs):
                captured["cmd"] = cmd
                captured["kwargs"] = kwargs
                output.write_bytes(b"K" * 2048)
                return subprocess.CompletedProcess(cmd, 0, "", "")

            with patch("builtins.print"), patch("modules.mod_buff.subprocess.run", side_effect=fake_run):
                self.assertTrue(build_hidden_bk2(str(frames), str(output), str(rad)))

            self.assertEqual(captured["cmd"][1], "binkc")
            self.assertEqual(Path(captured["cmd"][2]).name, "files.lst")
            self.assertEqual(captured["cmd"][3], str(output.resolve()))
            self.assertEqual(captured["kwargs"]["cwd"], str(rad.parent.resolve()))


if __name__ == "__main__":
    unittest.main()
