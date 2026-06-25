import subprocess
import tempfile
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from modules.mod_buff import build_hidden_bk2


class RadCommandTest(unittest.TestCase):
    def assert_ascii_path(self, path):
        try:
            str(path).encode("ascii")
        except UnicodeEncodeError as exc:
            raise AssertionError(f"path is not ASCII: {path}") from exc

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
                Path(cmd[3]).write_bytes(b"K" * 2048)
                return subprocess.CompletedProcess(cmd, 0, "", "")

            with patch("builtins.print"), patch("modules.mod_buff.subprocess.run", side_effect=fake_run):
                self.assertTrue(build_hidden_bk2(str(frames), str(output), str(rad)))

            self.assertEqual(captured["cmd"][1], "binkc")
            self.assertEqual(Path(captured["cmd"][2]).name, "files.lst")
            self.assertEqual(Path(captured["cmd"][3]).name, "output.bk2")
            self.assertEqual(captured["kwargs"]["cwd"], str(rad.parent.resolve()))
            self.assertTrue(output.exists())
            self.assertGreater(output.stat().st_size, 1024)

    def test_radvideo_stages_unicode_paths_in_ascii_workspace(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            frames = root / "工具箱" / "frames"
            frames.mkdir(parents=True)
            (frames / "frame_0000.png").write_bytes(b"fake")
            rad = root / "RADVideo" / "radvideo64.exe"
            rad.parent.mkdir()
            rad.write_bytes(b"fake exe")
            output = root / "喵呜汪" / "out.bk2"
            output.parent.mkdir()
            captured = {}

            def fake_run(cmd, **kwargs):
                captured["cmd"] = cmd
                captured["kwargs"] = kwargs
                Path(cmd[3]).write_bytes(b"K" * 2048)
                return subprocess.CompletedProcess(cmd, 0, "", "")

            with patch("builtins.print"), patch("modules.mod_buff.subprocess.run", side_effect=fake_run):
                self.assertTrue(build_hidden_bk2(str(frames), str(output), str(rad)))

            self.assert_ascii_path(captured["cmd"][2])
            self.assert_ascii_path(captured["cmd"][3])
            self.assertNotIn("工具箱", captured["cmd"][2])
            self.assertNotIn("喵呜汪", captured["cmd"][3])
            self.assertTrue(output.exists())
            self.assertGreater(output.stat().st_size, 1024)


if __name__ == "__main__":
    unittest.main()
