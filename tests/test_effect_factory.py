from pathlib import Path
import sys
import unittest

import numpy as np
from PIL import Image, ImageChops, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from modules.mod_buff import EffectFactory


EFFECTS = ("简单 Cut-in", "噪声光环", "秘法火光", "花瓣消散", "无")
REMOVED_EFFECTS = ("疾速冲入", "缩放爆入", "扫光登场", "次元震荡", "暗影突袭", "神圣爆发")


def make_sprite(size=(128, 96)):
    image = Image.new("RGBA", size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.ellipse((38, 12, 90, 64), fill=(130, 88, 230, 255))
    draw.rectangle((50, 48, 78, 84), fill=(170, 72, 220, 255))
    draw.polygon((64, 4, 80, 38, 48, 38), fill=(255, 228, 70, 255))
    return image


def make_padded_crop_sprite(size=(160, 120), crop_box=(34, 22, 126, 98)):
    image = Image.new("RGBA", size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rectangle(crop_box, fill=(42, 36, 68, 220))
    draw.ellipse((58, 34, 102, 78), fill=(130, 88, 230, 255))
    draw.rectangle((70, 72, 90, 94), fill=(170, 72, 220, 255))
    return image


def alpha_bbox(image):
    return image.split()[3].getbbox()


def alpha_area(image):
    alpha = np.array(image.split()[3])
    return int((alpha > 0).sum())


def rgb_sum(image):
    return int(np.array(image.convert("RGBA"))[:, :, :3].sum())


def frame_difference(a, b):
    return int(np.array(ImageChops.difference(a, b).convert("RGBA")).sum())


def mean_alpha_at(image, x, y, radius=4):
    alpha = np.array(image.split()[3])
    h, w = alpha.shape
    x0 = max(0, int(round(x)) - radius)
    x1 = min(w, int(round(x)) + radius + 1)
    y0 = max(0, int(round(y)) - radius)
    y1 = min(h, int(round(y)) + radius + 1)
    return float(alpha[y0:y1, x0:x1].mean())


def mean_rgb_delta_at(image, base, x, y, radius=4):
    arr = np.array(image.convert("RGBA"))[:, :, :3].astype(int)
    base_arr = np.array(base.convert("RGBA"))[:, :, :3].astype(int)
    h, w = arr.shape[:2]
    x0 = max(0, int(round(x)) - radius)
    x1 = min(w, int(round(x)) + radius + 1)
    y0 = max(0, int(round(y)) - radius)
    y1 = min(h, int(round(y)) + radius + 1)
    return float(np.abs(arr[y0:y1, x0:x1] - base_arr[y0:y1, x0:x1]).mean())


def rectangle_corner_alpha(image, inset_ratio=0.03):
    w, h = image.size
    points = (
        (w * inset_ratio, h * inset_ratio),
        (w * (1.0 - inset_ratio), h * inset_ratio),
        (w * inset_ratio, h * (1.0 - inset_ratio)),
        (w * (1.0 - inset_ratio), h * (1.0 - inset_ratio)),
    )
    return min(mean_alpha_at(image, x, y) for x, y in points)


def bounds_corner_alpha(image, bounds, inset_ratio=0.04):
    left, top, right, bottom = bounds
    width = right - left
    height = bottom - top
    points = (
        (left + width * inset_ratio, top + height * inset_ratio),
        (right - width * inset_ratio, top + height * inset_ratio),
        (left + width * inset_ratio, bottom - height * inset_ratio),
        (right - width * inset_ratio, bottom - height * inset_ratio),
    )
    return min(mean_alpha_at(image, x, y) for x, y in points)


def bounds_corner_rgb_delta(image, base, bounds, inset_ratio=0.04):
    left, top, right, bottom = bounds
    width = right - left
    height = bottom - top
    points = (
        (left + width * inset_ratio, top + height * inset_ratio),
        (right - width * inset_ratio, top + height * inset_ratio),
        (left + width * inset_ratio, bottom - height * inset_ratio),
        (right - width * inset_ratio, bottom - height * inset_ratio),
    )
    return min(mean_rgb_delta_at(image, base, x, y) for x, y in points)


class EffectFactoryTest(unittest.TestCase):
    def test_available_effects_only_keeps_requested_modes(self):
        self.assertEqual(EffectFactory.available_effects(), list(EFFECTS))
        for removed in REMOVED_EFFECTS:
            self.assertNotIn(removed, EffectFactory.available_effects())

    def test_requested_effects_generate_fixed_size_frames(self):
        source = make_sprite()

        for effect in EFFECTS:
            with self.subTest(effect=effect):
                frames = EffectFactory.generate(source, effect, frames=18)

                self.assertEqual(len(frames), 18)
                self.assertTrue(all(frame.size == source.size for frame in frames))
                self.assertTrue(any(alpha_bbox(frame) for frame in frames))

    def test_noise_halo_adds_animated_blue_purple_outer_light(self):
        source = make_sprite()
        plain = EffectFactory.generate(source, "无", frames=18)
        frames = EffectFactory.generate(source, "噪声光环", frames=18)

        self.assertGreater(max(rgb_sum(frame) for frame in frames), rgb_sum(plain[8]) + 120000)
        self.assertGreater(max(alpha_area(frame) for frame in frames), alpha_area(plain[8]))
        self.assertGreater(frame_difference(frames[2], frames[9]), 10000)

    def test_arcane_fire_adds_orange_portal_flame_ring(self):
        source = make_sprite()
        plain = EffectFactory.generate(source, "无", frames=18)
        frames = EffectFactory.generate(source, "秘法火光", frames=18)

        best = np.maximum.reduce([np.array(frame.convert("RGBA")) for frame in frames])
        self.assertGreater(max(rgb_sum(frame) for frame in frames), rgb_sum(plain[8]) + 100000)
        self.assertGreater(int(best[:, :, 0].sum()), int(best[:, :, 2].sum()))
        self.assertGreater(max(alpha_area(frame) for frame in frames), alpha_area(plain[8]))

    def test_outer_lights_follow_rectangle_corners_not_circle(self):
        source = make_padded_crop_sprite(size=(128, 96), crop_box=(0, 0, 128, 96))

        for effect in ("噪声光环", "秘法火光"):
            with self.subTest(effect=effect):
                frames = EffectFactory.generate(source, effect, frames=18)

                self.assertGreater(max(rectangle_corner_alpha(frame) for frame in frames), 35.0)

    def test_outer_lights_adapt_to_visible_crop_bounds(self):
        crop_box = (34, 22, 126, 98)
        source = make_padded_crop_sprite(crop_box=crop_box)
        plain = EffectFactory.generate(source, "无", frames=18)

        for effect in ("噪声光环", "秘法火光"):
            with self.subTest(effect=effect):
                frames = EffectFactory.generate(source, effect, frames=18)

                self.assertGreater(
                    max(bounds_corner_rgb_delta(frame, plain[index], crop_box) for index, frame in enumerate(frames)),
                    25.0,
                )

    def test_outer_lights_adapt_to_offset_visible_crop_bounds(self):
        crop_box = (6, 6, 112, 104)
        source = make_padded_crop_sprite(crop_box=crop_box)
        plain = EffectFactory.generate(source, "无", frames=18)

        for effect in ("噪声光环", "秘法火光"):
            with self.subTest(effect=effect):
                frames = EffectFactory.generate(source, effect, frames=18)

                self.assertGreater(
                    max(bounds_corner_rgb_delta(frame, plain[index], crop_box) for index, frame in enumerate(frames)),
                    20.0,
                )

    def test_petal_dissolve_removes_sprite_alpha_and_emits_particles(self):
        source = make_padded_crop_sprite(size=(128, 96), crop_box=(0, 0, 128, 96))
        plain = EffectFactory.generate(source, "无", frames=18)
        frames = EffectFactory.generate(source, "花瓣消散", frames=18)

        self.assertGreater(rectangle_corner_alpha(frames[4]), 10.0)
        self.assertGreater(frame_difference(frames[4], plain[4]), 10000)
        self.assertLess(alpha_area(frames[-1]), alpha_area(plain[8]))
        self.assertGreater(frame_difference(frames[4], frames[14]), 10000)

    def test_petal_dissolve_adapts_particles_to_visible_crop_bounds(self):
        crop_box = (34, 22, 126, 98)
        source = make_padded_crop_sprite(crop_box=crop_box)
        plain = EffectFactory.generate(source, "无", frames=18)
        frames = EffectFactory.generate(source, "花瓣消散", frames=18)

        self.assertGreater(bounds_corner_rgb_delta(frames[4], plain[4], crop_box), 8.0)


if __name__ == "__main__":
    unittest.main()
