from pathlib import Path
import shutil
import sys
import tempfile
import unittest

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from modules.mod_buff import (
    collect_preview_frames,
    is_bink_file,
    resolve_preview_target,
    stage_bink_for_preview,
)


class PreviewTargetTest(unittest.TestCase):
    def test_invalid_bk2_uses_processed_frames_preview(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            bad_bk2 = tmp_path / "not_bink.bk2"
            bad_bk2.write_bytes(b"not a bink file")
            frame = tmp_path / "frame_0000.png"
            Image.new("RGBA", (4, 4), (255, 0, 0, 255)).save(frame)

            kind, target = resolve_preview_target(str(bad_bk2), str(tmp_path))

            self.assertEqual(kind, "frames")
            self.assertEqual(target, [str(frame)])

    def test_valid_bink_file_is_preferred(self):
        with tempfile.TemporaryDirectory() as tmp:
            bk2 = Path(tmp) / "valid.bk2"
            bk2.write_bytes(b"KB2i" + b"\0" * 32)

            kind, target = resolve_preview_target(str(bk2), None)

            self.assertEqual(kind, "bink")
            self.assertEqual(target, str(bk2))
            self.assertTrue(is_bink_file(str(bk2)))

    def test_collect_preview_frames_sorts_numeric_sequence(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            for name in ["frame_0010.png", "frame_0002.png", "frame_0001.png"]:
                Image.new("RGBA", (2, 2), (0, 0, 0, 255)).save(tmp_path / name)

            frames = collect_preview_frames(str(tmp_path))

            self.assertEqual(
                [Path(frame).name for frame in frames],
                ["frame_0001.png", "frame_0002.png", "frame_0010.png"],
            )

    def test_bink_preview_stages_unicode_path_to_ascii_workspace(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            source_dir = tmp_path / "中文保存目录"
            source_dir.mkdir()
            source_bk2 = source_dir / "阿修罗.bk2"
            source_bk2.write_bytes(b"KB2i" + b"\0" * 2048)
            fake_player = tmp_path / "RADVideo" / "bink2play.exe"
            fake_player.parent.mkdir()
            fake_player.write_bytes(b"fake")

            staged_path, workspace = stage_bink_for_preview(str(source_bk2), str(fake_player))

            try:
                staged_path.encode("ascii")
                self.assertNotIn("中文保存目录", staged_path)
                self.assertNotIn("阿修罗", staged_path)
                self.assertEqual(Path(staged_path).read_bytes(), source_bk2.read_bytes())
                self.assertIsNotNone(workspace)
            finally:
                if workspace:
                    shutil.rmtree(workspace, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
