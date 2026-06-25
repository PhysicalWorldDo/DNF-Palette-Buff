import os
import sys
import threading
import subprocess
import shutil
import glob
import tempfile
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, colorchooser
from io import BytesIO
import numpy as np
from PIL import Image, ImageTk, ImageDraw, ImageFilter, ImageChops, ImageGrab, ImageOps
import json
import math
import random  # 【新增】需要用到随机数
from tkinter import simpledialog
import colorsys
import time
import concurrent.futures

from common import Config, check_path_safety, get_resource_path


_VIDEO_IMPORT_ERROR = ""


def get_video_file_clip_class():
    global _VIDEO_IMPORT_ERROR
    errors = []
    try:
        from moviepy.editor import VideoFileClip
        _VIDEO_IMPORT_ERROR = ""
        return VideoFileClip
    except Exception as exc:
        errors.append(f"moviepy.editor: {exc}")

    try:
        from moviepy.video.io.VideoFileClip import VideoFileClip
        _VIDEO_IMPORT_ERROR = ""
        return VideoFileClip
    except Exception as exc:
        errors.append(f"moviepy.video.io.VideoFileClip: {exc}")

    _VIDEO_IMPORT_ERROR = " | ".join(errors)
    return None


def get_video_dependency_error():
    return _VIDEO_IMPORT_ERROR or "moviepy is not available"


def validate_video_dependencies():
    VideoFileClip = get_video_file_clip_class()
    if VideoFileClip is None:
        raise RuntimeError(get_video_dependency_error())

    try:
        import imageio_ffmpeg

        ffmpeg_path = imageio_ffmpeg.get_ffmpeg_exe()
    except Exception as exc:
        raise RuntimeError(f"imageio_ffmpeg: {exc}") from exc

    if not os.path.exists(ffmpeg_path):
        raise RuntimeError(f"ffmpeg executable is missing: {ffmpeg_path}")

    return True


HAS_MOVIEPY = get_video_file_clip_class() is not None

PREVIEW_IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".bmp")


def _frame_sort_key(path):
    name = os.path.basename(path)
    digits = "".join(filter(str.isdigit, name))
    return (int(digits) if digits else 0, name.lower())


def collect_preview_frames(source_path):
    if not source_path:
        return []

    if os.path.isdir(source_path):
        frames = glob.glob(os.path.join(source_path, "frame_*.png"))
        if not frames:
            frames = [
                os.path.join(source_path, name)
                for name in os.listdir(source_path)
                if os.path.splitext(name)[1].lower() in PREVIEW_IMAGE_EXTENSIONS
            ]
        return [os.path.abspath(path) for path in sorted(frames, key=_frame_sort_key)]

    if os.path.isfile(source_path):
        ext = os.path.splitext(source_path)[1].lower()
        if ext in PREVIEW_IMAGE_EXTENSIONS:
            return [os.path.abspath(source_path)]

    return []


def is_bink_file(path):
    if not path or not os.path.isfile(path):
        return False
    try:
        with open(path, "rb") as f:
            header = f.read(4)
    except OSError:
        return False
    return header.startswith(b"BIK") or header.startswith(b"KB2")


def resolve_preview_target(generated_file, processed_path):
    if generated_file and os.path.exists(generated_file):
        if is_bink_file(generated_file):
            return "bink", os.path.abspath(generated_file)

    frames = collect_preview_frames(processed_path)
    if frames:
        return "frames", frames

    if generated_file and os.path.exists(generated_file):
        return "invalid_bink", os.path.abspath(generated_file)

    return "missing", generated_file


# --- 核心构建函数 ---
def _is_ascii_path(path):
    try:
        os.fspath(path).encode("ascii")
        return True
    except UnicodeEncodeError:
        return False


def _create_rad_ascii_workspace(tool_path):
    drive, _ = os.path.splitdrive(os.path.abspath(tool_path))
    candidates = []
    if drive:
        candidates.append(os.path.join(drive + os.sep, "DNFPaletteBuffRadTemp"))
    candidates.extend([
        r"C:\DNFPaletteBuffRadTemp",
        os.path.join(tempfile.gettempdir(), "DNFPaletteBuffRadTemp"),
    ])

    last_error = None
    for base in candidates:
        if not _is_ascii_path(base):
            continue
        try:
            os.makedirs(base, exist_ok=True)
            return tempfile.mkdtemp(prefix="rad_", dir=base)
        except OSError as exc:
            last_error = exc

    raise OSError(f"无法创建 RAD 专用 ASCII 临时目录: {last_error}")


def build_hidden_bk2(image_folder, output_bk2, tool_path, status_callback=None):
    def log(msg):
        if status_callback: status_callback(msg)
        print(msg)

    # 路径处理
    image_folder = os.path.abspath(image_folder)
    output_bk2 = os.path.abspath(output_bk2)
    tool_path = os.path.abspath(tool_path)

    if not os.path.exists(tool_path):
        log(f"❌ 错误：找不到工具: {tool_path}")
        return False

    # 整理图片
    log("⚙️ 正在整理图片序列...")
    pngs = glob.glob(os.path.join(image_folder, "*.png"))
    if not pngs:
        log(f"❌ 错误：文件夹为空: {image_folder}")
        return False

    needs_rename = False
    for p in pngs:
        if "frame_" not in os.path.basename(p): needs_rename = True; break
    
    if needs_rename:
        try: pngs.sort(key=lambda x: int(''.join(filter(str.isdigit, os.path.basename(x))) or 0))
        except: pngs.sort()
        for index, old_path in enumerate(pngs):
            new_name = f"frame_{index:04d}.png"
            new_path = os.path.join(image_folder, new_name)
            if old_path != new_path:
                try: os.rename(old_path, new_path)
                except: pass
    
    pngs = glob.glob(os.path.join(image_folder, "frame_*.png"))
    pngs.sort()

    # RAD 对中文路径支持不稳定；所有输入序列、列表文件和临时输出都放到 ASCII 工作目录。
    rad_workspace = _create_rad_ascii_workspace(tool_path)
    staged_pngs = []
    try:
        for index, img in enumerate(pngs):
            staged_path = os.path.join(rad_workspace, f"frame_{index:04d}.png")
            shutil.copy2(os.path.abspath(img), staged_path)
            staged_pngs.append(staged_path)

        list_file_path = os.path.join(rad_workspace, "files.lst")
        with open(list_file_path, "w", encoding="ascii") as f:
            for img in staged_pngs:
                f.write(os.path.abspath(img) + "\n")

        temp_output_bk2 = os.path.join(rad_workspace, "output.bk2")

        # 构造命令
        tool_name = os.path.basename(tool_path).lower()
        tool_dir = os.path.dirname(tool_path)
        cmd = [tool_path]
        if "radvideo" in tool_name:
            cmd.append("binkc")

        cmd.append(list_file_path)
        cmd.append(temp_output_bk2)

        # 【修改点2】参数调整
        cmd.append("/Z3000")   # 告诉它处理Alpha (DNF需要)
        #cmd.append("/Z10000")  # 【关键】禁止弹出"没有Alpha"的警告，没有就强制按没有处理
        cmd.append("/O")       # 覆盖
        cmd.append("/#")       # 静默退出

        debug_cmd_str = " ".join([f'"{x}"' if " " in x else x for x in cmd])
        log(f"🚀 正在执行...")

        startupinfo = None
        if os.name == 'nt':
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = subprocess.SW_HIDE

        result = subprocess.run(cmd, capture_output=True, text=True, startupinfo=startupinfo, cwd=tool_dir or None)

        if os.path.exists(temp_output_bk2) and os.path.getsize(temp_output_bk2) > 1024:
            os.makedirs(os.path.dirname(output_bk2), exist_ok=True)
            shutil.copy2(temp_output_bk2, output_bk2)
            log(f"✅ 成功！视频已生成")
            return True
        else:
            log(f"❌ 生成失败。")
            error_msg = f"RAD工具执行失败。\n工作目录：\n{tool_dir}\n\n手动命令：\n{debug_cmd_str}\n\n输出: {result.stdout} {result.stderr}"
            print(error_msg)
            messagebox.showerror("生成失败", error_msg) 
            return False

    except Exception as e:
        log(f"❌ 异常: {e}")
        return False
    finally:
        try:
            shutil.rmtree(rad_workspace, ignore_errors=True)
        except Exception:
            pass
        
        
class EffectFactory:
    EFFECT_MODES = ("简单 Cut-in", "噪声光环", "秘法火光", "花瓣消散", "无")

    @staticmethod
    def available_effects():
        return list(EffectFactory.EFFECT_MODES)

    # --- 工具: 缓动函数 ---
    
    # 减速曲线 (用于入场：快 -> 慢)
    @staticmethod
    def _ease_out_expo(t):
        return 1.0 if t == 1.0 else 1.0 - math.pow(2.0, -10.0 * t)

    # 加速曲线 (用于退场：慢 -> 快)
    @staticmethod
    def _ease_in_expo(t):
        return 0.0 if t == 0.0 else math.pow(2.0, 10.0 * (t - 1.0))

    @staticmethod
    def _smoothstep(edge0, edge1, x):
        t = np.clip((x - edge0) / (edge1 - edge0), 0.0, 1.0)
        return t * t * (3.0 - 2.0 * t)

    @staticmethod
    def _fract(x):
        return x - np.floor(x)

    @staticmethod
    def _mix(a, b, t):
        return a * (1.0 - t) + b * t

    # --- 工具: 左右渐变蒙版 (常驻) ---
    @staticmethod
    def _create_side_fade_mask(w, h):
        fade_ratio = 0.2 
        fade_w = int(w * fade_ratio)
        if fade_w < 1: fade_w = 1
        
        # 0(透) -> 255(实)
        grad_left = np.linspace(0, 255, fade_w)
        # 255(实) -> 0(透)
        grad_right = np.linspace(255, 0, fade_w)
        
        center_w = w - (fade_w * 2)
        if center_w < 0: center_w = 0
        grad_center = np.full(center_w, 255.0)
        
        base_line = np.concatenate([grad_left, grad_center, grad_right])
        
        # 修正长度误差
        if len(base_line) < w:
            base_line = np.append(base_line, np.zeros(w - len(base_line)))
        elif len(base_line) > w:
            base_line = base_line[:w]
            
        mask_2d = np.tile(base_line, (h, 1))
        return Image.fromarray(mask_2d.astype(np.uint8), mode="L")

    @staticmethod
    def _paste_clipped(canvas, image, x, y):
        left = max(0, x)
        top = max(0, y)
        right = min(canvas.width, x + image.width)
        bottom = min(canvas.height, y + image.height)
        if right <= left or bottom <= top:
            return

        crop_box = (left - x, top - y, right - x, bottom - y)
        cropped = image.crop(crop_box)
        canvas.paste(cropped, (left, top), cropped)

    @staticmethod
    def _scale_rgba(image, scale):
        if abs(scale - 1.0) < 0.001:
            return image

        new_w = max(1, int(round(image.width * scale)))
        new_h = max(1, int(round(image.height * scale)))
        return image.resize((new_w, new_h), Image.Resampling.LANCZOS)

    @staticmethod
    def _multiply_alpha(image, factor):
        if factor >= 0.999:
            return image

        result = image.copy()
        r, g, b, a = result.split()
        a_arr = np.array(a).astype(float)
        a_arr = np.clip(a_arr * max(0.0, min(1.0, factor)), 0, 255)
        result.putalpha(Image.fromarray(a_arr.astype(np.uint8), mode="L"))
        return result

    @staticmethod
    def _paste_centered(canvas, image, offset_x=0, offset_y=0, scale=1.0, alpha=1.0):
        image = EffectFactory._scale_rgba(image, scale)
        image = EffectFactory._multiply_alpha(image, alpha)
        paste_x = (canvas.width - image.width) // 2 + int(offset_x)
        paste_y = (canvas.height - image.height) // 2 + int(offset_y)
        EffectFactory._paste_clipped(canvas, image, paste_x, paste_y)

    @staticmethod
    def _apply_side_fade(canvas, side_mask_arr):
        if side_mask_arr is None:
            return canvas

        r, g, b, a = canvas.split()
        a_arr = np.array(a).astype(float)
        new_a_arr = (a_arr * side_mask_arr) / 255.0
        canvas.putalpha(Image.fromarray(new_a_arr.astype(np.uint8), mode="L"))
        return canvas

    @staticmethod
    def _shader_uv(size):
        w, h = size
        y_grid, x_grid = np.mgrid[0:h, 0:w]
        uv_x = ((x_grid + 0.5) * 2.0 - w) / max(1.0, float(h))
        uv_y = (h - (y_grid + 0.5) * 2.0) / max(1.0, float(h))
        return uv_x.astype(float), uv_y.astype(float)

    @staticmethod
    def _alpha_bounds(image):
        bbox = image.split()[3].getbbox()
        if bbox:
            return bbox
        return (0, 0, image.width, image.height)

    @staticmethod
    def _rect_border_fields(size, bounds=None, inset_ratio=0.025):
        w, h = size
        y_grid, x_grid = np.mgrid[0:h, 0:w]
        if bounds is None:
            bounds = (0, 0, w, h)

        raw_left, raw_top, raw_right, raw_bottom = bounds
        bounds_w = max(1.0, float(raw_right - raw_left))
        bounds_h = max(1.0, float(raw_bottom - raw_top))
        min_dim = max(1.0, float(min(bounds_w, bounds_h)))
        inset_px = min_dim * inset_ratio
        left = raw_left + inset_px
        right = raw_right - inset_px
        top = raw_top + inset_px
        bottom = raw_bottom - inset_px
        if right <= left:
            left, right = raw_left, raw_right
        if bottom <= top:
            top, bottom = raw_top, raw_bottom
        cx = (left + right) * 0.5
        cy = (top + bottom) * 0.5
        half_w = (right - left) * 0.5
        half_h = (bottom - top) * 0.5

        qx = np.abs((x_grid + 0.5) - cx) - half_w
        qy = np.abs((y_grid + 0.5) - cy) - half_h
        outside = np.sqrt(np.maximum(qx, 0.0) ** 2 + np.maximum(qy, 0.0) ** 2)
        inside = np.minimum(np.maximum(qx, qy), 0.0)
        signed_dist = outside + inside
        border_dist = np.abs(signed_dist) / min_dim

        d_left = np.abs((x_grid + 0.5) - left)
        d_right = np.abs((x_grid + 0.5) - right)
        d_top = np.abs((y_grid + 0.5) - top)
        d_bottom = np.abs((y_grid + 0.5) - bottom)
        nearest = np.argmin(np.stack([d_top, d_right, d_bottom, d_left]), axis=0)

        top_phase = np.clip(((x_grid + 0.5) - left) / max(1.0, right - left), 0.0, 1.0)
        right_phase = 1.0 + np.clip(((y_grid + 0.5) - top) / max(1.0, bottom - top), 0.0, 1.0)
        bottom_phase = 2.0 + np.clip((right - (x_grid + 0.5)) / max(1.0, right - left), 0.0, 1.0)
        left_phase = 3.0 + np.clip((bottom - (y_grid + 0.5)) / max(1.0, bottom - top), 0.0, 1.0)
        phase = np.choose(nearest, [top_phase, right_phase, bottom_phase, left_phase]) / 4.0
        return border_dist, phase

    @staticmethod
    def _hash33(x, y, z):
        x = EffectFactory._fract(x * 0.1031)
        y = EffectFactory._fract(y * 0.11369)
        z = EffectFactory._fract(z * 0.13787)
        dot_value = x * (y + 19.19) + y * (x + 19.19) + z * (z + 19.19)
        x = x + dot_value
        y = y + dot_value
        z = z + dot_value
        return (
            -1.0 + 2.0 * EffectFactory._fract((x + y) * z),
            -1.0 + 2.0 * EffectFactory._fract((x + z) * y),
            -1.0 + 2.0 * EffectFactory._fract((y + z) * x),
        )

    @staticmethod
    def _snoise3(x, y, z):
        k1 = 0.333333333
        k2 = 0.166666667

        i_x = np.floor(x + (x + y + z) * k1)
        i_y = np.floor(y + (x + y + z) * k1)
        i_z = np.floor(z + (x + y + z) * k1)
        i_sum = i_x + i_y + i_z

        d0_x = x - (i_x - i_sum * k2)
        d0_y = y - (i_y - i_sum * k2)
        d0_z = z - (i_z - i_sum * k2)

        e_x = (d0_x - d0_y >= 0.0).astype(float)
        e_y = (d0_y - d0_z >= 0.0).astype(float)
        e_z = (d0_z - d0_x >= 0.0).astype(float)

        i1_x = e_x * (1.0 - e_z)
        i1_y = e_y * (1.0 - e_x)
        i1_z = e_z * (1.0 - e_y)
        i2_x = 1.0 - e_z * (1.0 - e_x)
        i2_y = 1.0 - e_x * (1.0 - e_y)
        i2_z = 1.0 - e_y * (1.0 - e_z)

        d1_x = d0_x - (i1_x - k2)
        d1_y = d0_y - (i1_y - k2)
        d1_z = d0_z - (i1_z - k2)
        d2_x = d0_x - (i2_x - k1)
        d2_y = d0_y - (i2_y - k1)
        d2_z = d0_z - (i2_z - k1)
        d3_x = d0_x - 0.5
        d3_y = d0_y - 0.5
        d3_z = d0_z - 0.5

        h0 = np.maximum(0.6 - (d0_x * d0_x + d0_y * d0_y + d0_z * d0_z), 0.0)
        h1 = np.maximum(0.6 - (d1_x * d1_x + d1_y * d1_y + d1_z * d1_z), 0.0)
        h2 = np.maximum(0.6 - (d2_x * d2_x + d2_y * d2_y + d2_z * d2_z), 0.0)
        h3 = np.maximum(0.6 - (d3_x * d3_x + d3_y * d3_y + d3_z * d3_z), 0.0)

        g0 = EffectFactory._hash33(i_x, i_y, i_z)
        g1 = EffectFactory._hash33(i_x + i1_x, i_y + i1_y, i_z + i1_z)
        g2 = EffectFactory._hash33(i_x + i2_x, i_y + i2_y, i_z + i2_z)
        g3 = EffectFactory._hash33(i_x + 1.0, i_y + 1.0, i_z + 1.0)

        n0 = h0**4 * (d0_x * g0[0] + d0_y * g0[1] + d0_z * g0[2])
        n1 = h1**4 * (d1_x * g1[0] + d1_y * g1[1] + d1_z * g1[2])
        n2 = h2**4 * (d2_x * g2[0] + d2_y * g2[1] + d2_z * g2[2])
        n3 = h3**4 * (d3_x * g3[0] + d3_y * g3[1] + d3_z * g3[2])
        return 31.316 * (n0 + n1 + n2 + n3)

    @staticmethod
    def _extract_alpha(color):
        max_value = np.clip(color.max(axis=2), 0.0, 1.0)
        safe = max_value > 1e-5
        rgb = np.zeros_like(color)
        rgb[safe] = color[safe] / max_value[safe, None]

        rgba = np.zeros((*max_value.shape, 4), dtype=np.uint8)
        rgba[:, :, :3] = np.clip(rgb * 255.0, 0, 255).astype(np.uint8)
        rgba[:, :, 3] = np.clip(max_value * 255.0, 0, 255).astype(np.uint8)
        return Image.fromarray(rgba, mode="RGBA")

    @staticmethod
    def _noise_halo_layer(size, time_value, bounds=None):
        w, h = size
        border_dist, phase = EffectFactory._rect_border_fields(size, bounds=bounds)
        n0 = EffectFactory._snoise3(phase * 4.2, border_dist * 13.0, np.full((h, w), time_value * 0.5)) * 0.5 + 0.5
        noise_width = EffectFactory._mix(0.018, 0.04, n0)
        v0 = 1.0 / (1.0 + border_dist * 70.0)
        v0 *= EffectFactory._smoothstep(noise_width * 2.4, 0.0, border_dist)
        cl = np.cos(phase * math.tau + time_value * 2.0) * 0.5 + 0.5

        moving = EffectFactory._fract(0.16 - time_value * 0.18)
        phase_delta = np.abs(EffectFactory._fract(phase - moving + 0.5) - 0.5)
        v1 = 1.5 / (1.0 + phase_delta * phase_delta * 700.0 + border_dist * 90.0)
        v2 = EffectFactory._smoothstep(0.085, 0.0, border_dist)
        v3 = EffectFactory._smoothstep(0.052, 0.0, border_dist)

        color1 = np.array([0.611765, 0.262745, 0.996078])
        color2 = np.array([0.298039, 0.760784, 0.913725])
        color3 = np.array([0.062745, 0.078431, 0.600000])
        color_mix = color1 * (1.0 - cl[:, :, None]) + color2 * cl[:, :, None]
        col = color3 * (1.0 - v0[:, :, None]) + color_mix * v0[:, :, None]
        col = (col + v1[:, :, None]) * v2[:, :, None] * v3[:, :, None]
        col = np.clip(col * 1.8, 0.0, 1.0)
        return EffectFactory._extract_alpha(col)

    @staticmethod
    def _triwave(x):
        return np.abs(EffectFactory._fract(0.5 * x / math.pi - 0.25) - 0.5) * 4.0 - 1.0

    @staticmethod
    def _arcane_fire_layer(size, time_value, bounds=None):
        w, h = size
        border_dist, phase = EffectFactory._rect_border_fields(size, bounds=bounds)
        c = np.cos(time_value * 1.35)
        s = np.sin(time_value * 1.35)
        qx = phase * 4.0 * c - border_dist * 12.0 * s
        qy = phase * 4.0 * s + border_dist * 12.0 * c
        qz = np.full_like(qx, time_value * 0.6)
        for d in range(2, 9):
            wave = EffectFactory._triwave(qx * d + qy * 0.75 + time_value * 2.0)
            qx = qx + EffectFactory._triwave(qy * d + qz + time_value) / d
            qy = qy + EffectFactory._triwave(qz * d + wave + time_value * 1.7) / d

        wobble = np.sin(phase * math.tau * 9.0 - time_value * 4.5 + qx * 2.0 + qy * 1.4)
        edge = border_dist
        flame = np.exp(-edge * 36.0) * (0.65 + 0.35 * wobble)
        flame += np.exp(-(edge * 58.0) ** 2) * 1.55
        flame += np.exp(-np.abs(edge - (0.028 + 0.012 * wobble)) * 42.0) * 0.5
        flame = np.clip(flame, 0.0, 1.7)

        orange = np.array([1.0, 0.38, 0.04])
        yellow = np.array([1.0, 0.86, 0.25])
        violet = np.array([0.38, 0.12, 0.72])
        hot = np.clip(flame, 0.0, 1.0)
        col = orange * (1.0 - hot[:, :, None]) + yellow * hot[:, :, None]
        col = col + violet * (np.maximum(0.0, 0.35 - edge)[:, :, None] * 0.45)
        col *= np.clip(flame[:, :, None] * 1.15, 0.0, 1.0)
        return EffectFactory._extract_alpha(np.clip(col, 0.0, 1.0))

    @staticmethod
    def _draw_petals(canvas, progress, bounds=None, count=38):
        w, h = canvas.size
        draw = ImageDraw.Draw(canvas, "RGBA")
        if bounds is None:
            bounds = (0, 0, w, h)
        raw_left, raw_top, raw_right, raw_bottom = bounds
        min_dim = max(1.0, float(min(raw_right - raw_left, raw_bottom - raw_top)))
        inset_px = min_dim * 0.025
        left = raw_left + inset_px
        right = raw_right - inset_px
        top = raw_top + inset_px
        bottom = raw_bottom - inset_px
        if right <= left:
            left, right = raw_left, raw_right
        if bottom <= top:
            top, bottom = raw_top, raw_bottom
        life = max(0.0, 1.0 - progress) ** 1.35

        for idx in range(count):
            rng = random.Random(12000 + idx * 131)
            anchors = (
                (left, top, -1.0, -1.0, 1.0, 0.0),
                ((left + right) * 0.5, top, 0.0, -1.0, 1.0, 0.0),
                (right, top, 1.0, -1.0, 0.0, 1.0),
                (right, (top + bottom) * 0.5, 1.0, 0.0, 0.0, 1.0),
                (right, bottom, 1.0, 1.0, -1.0, 0.0),
                ((left + right) * 0.5, bottom, 0.0, 1.0, -1.0, 0.0),
                (left, bottom, -1.0, 1.0, 0.0, -1.0),
                (left, (top + bottom) * 0.5, -1.0, 0.0, 0.0, -1.0),
            )
            if idx < len(anchors):
                base_x, base_y, normal_x, normal_y, tangent_x, tangent_y = anchors[idx]
                normal_len = math.sqrt(normal_x * normal_x + normal_y * normal_y) or 1.0
                normal_x /= normal_len
                normal_y /= normal_len
            else:
                side = rng.randrange(4)
                along = rng.random()
                if side == 0:
                    base_x = left + along * (right - left)
                    base_y = top
                    normal_x, normal_y = 0.0, -1.0
                    tangent_x, tangent_y = 1.0, 0.0
                elif side == 1:
                    base_x = right
                    base_y = top + along * (bottom - top)
                    normal_x, normal_y = 1.0, 0.0
                    tangent_x, tangent_y = 0.0, 1.0
                elif side == 2:
                    base_x = right - along * (right - left)
                    base_y = bottom
                    normal_x, normal_y = 0.0, 1.0
                    tangent_x, tangent_y = -1.0, 0.0
                else:
                    base_x = left
                    base_y = bottom - along * (bottom - top)
                    normal_x, normal_y = -1.0, 0.0
                    tangent_x, tangent_y = 0.0, -1.0

            start_angle = math.atan2(normal_y, normal_x)
            speed = 0.18 + rng.random() * 0.78
            normal_distance = max(w, h) * progress * speed * 0.42
            tangent_distance = math.sin(progress * math.tau * (0.55 + rng.random() * 0.9) + idx) * max(w, h) * 0.08 * progress
            x = base_x + normal_x * normal_distance + tangent_x * tangent_distance + rng.uniform(-5, 5) * progress
            y = base_y + normal_y * normal_distance + tangent_y * tangent_distance - h * 0.07 * progress + rng.uniform(-4, 4) * progress
            size = (2.0 + rng.random() * 4.5) * (0.5 + life)
            alpha = int((70 + rng.random() * 150) * life)
            if alpha <= 0:
                continue

            color = rng.choice(((255, 92, 166), (255, 152, 205), (255, 218, 238), (215, 80, 255)))
            rot = start_angle + progress * 5.0 + idx
            p1 = (x + math.cos(rot) * size * 1.7, y + math.sin(rot) * size * 1.7)
            p2 = (x + math.cos(rot + 1.7) * size, y + math.sin(rot + 1.7) * size)
            p3 = (x - math.cos(rot) * size * 1.2, y - math.sin(rot) * size * 1.2)
            p4 = (x + math.cos(rot - 1.7) * size, y + math.sin(rot - 1.7) * size)
            draw.polygon((p1, p2, p3, p4), fill=(*color, alpha))

        return canvas

    @staticmethod
    def _apply_petal_dissolve(canvas, frame_index, total_frames, bounds=None):
        progress = frame_index / max(1, total_frames - 1)
        result = canvas.copy()

        if progress > 0.35:
            amount = EffectFactory._smoothstep(0.35, 1.0, progress)
            alpha = np.array(result.split()[3]).astype(float)
            uv_x, uv_y = EffectFactory._shader_uv(result.size)
            noise = EffectFactory._snoise3(uv_x * 3.2, uv_y * 3.2, np.full_like(uv_x, progress * 2.2)) * 0.5 + 0.5
            keep = EffectFactory._smoothstep(amount - 0.16, amount + 0.06, noise)
            result.putalpha(Image.fromarray(np.clip(alpha * keep, 0, 255).astype(np.uint8), mode="L"))

        petals = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        petal_progress = EffectFactory._smoothstep(0.12, 1.0, progress)
        petals = EffectFactory._draw_petals(petals, petal_progress, bounds=bounds, count=42)
        return Image.alpha_composite(result, petals)

    @staticmethod
    def generate(input_data, mode, frames=18):
        # 1. 准备基础数据
        is_sequence = isinstance(input_data, list)
        if is_sequence:
            ref_img = input_data[0]
            w, h = ref_img.size
        else:
            ref_img = input_data
            w, h = ref_img.size

        # 预先生成侧边蒙版 (数组化以提高性能)
        side_mask = None
        side_mask_arr = None
        
        # 只有在需要特效时才生成蒙版
        if mode == "简单 Cut-in":
            side_mask = EffectFactory._create_side_fade_mask(w, h)
            side_mask_arr = np.array(side_mask).astype(float)

        results = []

        # 关键帧定义
        # Frame 0-3: 入场 (4帧)
        # Frame 4-14: 保持 (11帧)
        # Frame 15-17: 退场 (3帧)
        
        for i in range(frames):
            # --- 步骤 1: 创建绝对透明的画布 ---
            canvas = Image.new("RGBA", (w, h), (0, 0, 0, 0))
            
            # --- 步骤 2: 获取当前帧的角色图 ---
            if is_sequence:
                char_img = input_data[i % len(input_data)]
            else:
                char_img = input_data
            
            if char_img.mode != "RGBA":
                char_img = char_img.convert("RGBA")

            # --- 步骤 3: 计算位移 (核心动作) ---
            offset_x = 0
            offset_y = 0
            scale = 1.0
            alpha = 1.0
            
            if mode == "简单 Cut-in":
                if i < 4:
                    # [入场]: 从下往上冲
                    t = (i + 1) / 4.0 
                    ease = EffectFactory._ease_out_expo(t)
                    start_offset = h 
                    current_offset = start_offset * (1.0 - ease)
                    offset_y = int(current_offset)
                    
                elif i >= 15:
                    # [退场]: 从中往上冲
                    t = (i - 14) / 3.0
                    if t > 1.0: t = 1.0
                    ease = EffectFactory._ease_in_expo(t) 
                    target_offset = -h 
                    current_offset = target_offset * ease
                    offset_y = int(current_offset)
                else:
                    offset_y = 0

            # --- 步骤 4: 绘制 ---
            EffectFactory._paste_centered(
                canvas,
                char_img,
                offset_x=offset_x,
                offset_y=offset_y,
                scale=scale,
                alpha=alpha,
            )

            # --- 步骤 5: 应用侧边渐变蒙版 ---
            progress = i / max(1, frames - 1)
            effect_time = progress * 2.4
            effect_bounds = EffectFactory._alpha_bounds(canvas)
            if mode == "简单 Cut-in":
                canvas = EffectFactory._apply_side_fade(canvas, side_mask_arr)
            elif mode == "噪声光环":
                halo = EffectFactory._noise_halo_layer(canvas.size, effect_time, bounds=effect_bounds)
                canvas = Image.alpha_composite(halo, canvas)
                canvas = Image.alpha_composite(canvas, EffectFactory._multiply_alpha(halo, 0.55))
            elif mode == "秘法火光":
                fire = EffectFactory._arcane_fire_layer(canvas.size, effect_time, bounds=effect_bounds)
                canvas = Image.alpha_composite(fire, canvas)
                canvas = Image.alpha_composite(canvas, EffectFactory._multiply_alpha(fire, 0.5))
            elif mode == "花瓣消散":
                canvas = EffectFactory._apply_petal_dissolve(canvas, i, frames, bounds=effect_bounds)
            
            results.append(canvas)

        return results

class VideoProcessor:
    @staticmethod
    def process_video_to_frames(video_path, output_dir, target_frames=18, crop_box=None):
        """
        读取视频 -> 抽帧(跳过首帧) -> 裁剪 -> 强制转RGBA -> 保存
        (已移除 chroma_key_mode 等背景去除参数)
        """
        VideoFileClip = get_video_file_clip_class()

        if VideoFileClip is None:
            return False, "未安装 MoviePy 库"

        try:
            # 1. 加载视频
            clip = VideoFileClip(video_path)
            duration = clip.duration
            
            # 跳过前0.15秒，防止淡入黑屏
            start_time = 0.15 if duration > 0.3 else 0 
            end_time = duration - 0.1
            
            times = np.linspace(start_time, end_time, target_frames)
            
            processed_count = 0
            
            for i, t in enumerate(times):
                try:
                    frame = clip.get_frame(t)
                except OSError:
                    continue

                img = Image.fromarray(frame)
                
                # 裁剪
                if crop_box:
                    cx, cy, cw, ch = crop_box
                    img_w, img_h = img.size
                    cx = max(0, cx)
                    cy = max(0, cy)
                    cw = min(cw, img_w - cx)
                    ch = min(ch, img_h - cy)
                    if cw > 0 and ch > 0:
                        img = img.crop((cx, cy, cx + cw, cy + ch))
                
                # 强制转为 RGBA (保留Alpha通道能力，即使不扣像也保持格式统一)
                img = img.convert("RGBA")
                
                # --- 原背景去除逻辑已移除 ---
                
                save_name = f"frame_{i:04d}.png"
                img.save(os.path.join(output_dir, save_name))
                processed_count += 1
            
            clip.close()
            return True, f"成功转换 {processed_count} 帧"

        except Exception as e:
            return False, f"视频处理出错: {e}"


class VideoSettingsDialog(tk.Toplevel):
    def __init__(self, parent, video_path, callback):
        super().__init__(parent)
        self.title("🎬 视频预处理 - 拖动红框裁剪区域")
        self.video_path = video_path
        self.callback = callback
        self.result_data = None
        
        # 视频原始信息
        self.raw_w = 0
        self.raw_h = 0
        self.display_scale = 1.0 # 预览缩放比
        
        # 裁剪框坐标 (真实坐标)
        self.crop_x = 0
        self.crop_y = 0
        self.crop_w = 0
        self.crop_h = 0
        
        # 鼠标拖拽状态
        self.drag_start_x = 0
        self.drag_start_y = 0
        self.rect_start_x = 0
        self.rect_start_y = 0
        
        # 设置变量
        self.var_frames = tk.IntVar(value=18)
        self.var_crop_w = tk.IntVar(value=0) # 绑定输入框
        self.var_crop_h = tk.IntVar(value=0) # 绑定输入框
        
        self.create_ui()
        self.load_preview_and_init() # 加载视频并初始化尺寸
        self.center_window()

    def center_window(self):
        self.update_idletasks()
        w, h = 900, 650 # 稍微增加高度以容纳新按钮
        x = (self.winfo_screenwidth() // 2) - (w // 2)
        y = (self.winfo_screenheight() // 2) - (h // 2)
        self.geometry(f"{w}x{h}+{x}+{y}")

    def create_ui(self):
        # 左侧预览 (画布)
        f_left = ttk.LabelFrame(self, text=" 裁剪预览 (拖动红框) ", padding=10)
        f_left.pack(side="left", fill="both", expand=True, padx=10, pady=10)
        
        self.canvas = tk.Canvas(f_left, bg="#333", width=500, height=500, cursor="fleur")
        self.canvas.pack(fill="both", expand=True)
        
        self.canvas.bind("<Button-1>", self.on_mouse_down)
        self.canvas.bind("<B1-Motion>", self.on_mouse_drag)

        # 右侧设置
        f_right = ttk.Frame(self, padding=10)
        f_right.pack(side="right", fill="y", padx=10)

        # 1. 基础设置
        grp_basic = ttk.LabelFrame(f_right, text="抽帧设置", padding=10)
        grp_basic.pack(fill="x", pady=5)
        ttk.Label(grp_basic, text="总帧数:").pack(anchor="w")
        ttk.Entry(grp_basic, textvariable=self.var_frames).pack(fill="x")

        # 2. 裁剪设置 (数字控制)
        grp_crop = ttk.LabelFrame(f_right, text="裁剪尺寸 (px)", padding=10)
        grp_crop.pack(fill="x", pady=5)
        
        # 宽
        f_cw = ttk.Frame(grp_crop)
        f_cw.pack(fill="x", pady=2)
        ttk.Label(f_cw, text="宽:", width=4).pack(side="left")
        entry_w = ttk.Entry(f_cw, textvariable=self.var_crop_w)
        entry_w.pack(side="left", fill="x", expand=True)
        entry_w.bind("<Return>", self.on_entry_change) 
        
        # 高
        f_ch = ttk.Frame(grp_crop)
        f_ch.pack(fill="x", pady=2)
        ttk.Label(f_ch, text="高:", width=4).pack(side="left")
        entry_h = ttk.Entry(f_ch, textvariable=self.var_crop_h)
        entry_h.pack(side="left", fill="x", expand=True)
        entry_h.bind("<Return>", self.on_entry_change)

        # 操作按钮区
        f_btns = ttk.Frame(grp_crop)
        f_btns.pack(fill="x", pady=5)
        
        # 【修改点】增加“应用尺寸”按钮
        ttk.Button(f_btns, text="应用尺寸", command=self.on_entry_change, width=10).pack(side="left", fill="x", expand=True, padx=(0, 2))
        
        # 【修改点】改为“重置为原图”
        ttk.Button(f_btns, text="重置为原图", command=self.reset_to_original, width=10).pack(side="left", fill="x", expand=True, padx=(2, 0))

        # 底部按钮
        ttk.Button(f_right, text="✅ 开始转换", command=self.confirm, width=20).pack(side="bottom", pady=20)
        ttk.Button(f_right, text="❌ 取消", command=self.destroy).pack(side="bottom")

    def load_preview_and_init(self):
        VideoFileClip = get_video_file_clip_class()
        if VideoFileClip is None:
            messagebox.showerror(
                "错误",
                "处理视频需要安装或打包 moviepy 库！\n"
                f"{get_video_dependency_error()}\n"
                "请更新到已修复的视频依赖版本。",
            )
            self.destroy()
            return
        try:
            clip = VideoFileClip(self.video_path)
            frame = clip.get_frame(0) # 第0秒
            clip.close()
            
            pil_img = Image.fromarray(frame)
            self.raw_w, self.raw_h = pil_img.size
            
            # 【修改点】初始默认设置为 470 x 900
            default_w = 470
            default_h = 900
            
            self.crop_w = default_w if self.raw_w >= default_w else self.raw_w
            self.crop_h = default_h if self.raw_h >= default_h else self.raw_h
            
            # 居中放置裁剪框
            self.crop_x = (self.raw_w - self.crop_w) // 2
            self.crop_y = (self.raw_h - self.crop_h) // 2
            
            self.var_crop_w.set(self.crop_w)
            self.var_crop_h.set(self.crop_h)
            
            # 计算显示缩放
            max_view = 480
            scale_w = max_view / self.raw_w
            scale_h = max_view / self.raw_h
            self.display_scale = min(scale_w, scale_h, 1.0)
            
            display_w = int(self.raw_w * self.display_scale)
            display_h = int(self.raw_h * self.display_scale)
            
            # 生成预览图
            self.tk_img = ImageTk.PhotoImage(pil_img.resize((display_w, display_h)))
            
            cx = 250
            cy = 250
            self.img_offset_x = cx - display_w // 2
            self.img_offset_y = cy - display_h // 2
            
            self.canvas.create_image(self.img_offset_x, self.img_offset_y, image=self.tk_img, anchor="nw")
            
            self.rect_id = self.canvas.create_rectangle(0, 0, 1, 1, outline="red", width=3, tags="crop_rect")
            self.draw_rect()
            
        except Exception as e:
            print(f"Preview Error: {e}")

    def draw_rect(self):
        # 将真实坐标映射到画布坐标
        x1 = self.img_offset_x + (self.crop_x * self.display_scale)
        y1 = self.img_offset_y + (self.crop_y * self.display_scale)
        w = self.crop_w * self.display_scale
        h = self.crop_h * self.display_scale
        self.canvas.coords(self.rect_id, x1, y1, x1+w, y1+h)

    def on_mouse_down(self, event):
        self.drag_start_x = event.x
        self.drag_start_y = event.y
        self.rect_start_x = self.crop_x
        self.rect_start_y = self.crop_y

    def on_mouse_drag(self, event):
        dx = (event.x - self.drag_start_x) / self.display_scale
        dy = (event.y - self.drag_start_y) / self.display_scale
        
        new_x = self.rect_start_x + dx
        new_y = self.rect_start_y + dy
        
        max_x = self.raw_w - self.crop_w
        max_y = self.raw_h - self.crop_h
        
        self.crop_x = max(0, min(new_x, max_x))
        self.crop_y = max(0, min(new_y, max_y))
        
        self.draw_rect()

    def on_entry_change(self, event=None):
        try:
            w = int(self.var_crop_w.get())
            h = int(self.var_crop_h.get())
            
            # 限制输入不能超过原视频尺寸
            w = min(w, self.raw_w)
            h = min(h, self.raw_h)
            
            # 限制最小尺寸
            w = max(10, w)
            h = max(10, h)
            
            # 更新变量显示
            self.var_crop_w.set(w)
            self.var_crop_h.set(h)

            self.crop_w = w
            self.crop_h = h
            
            # 重置坐标防止越界
            if self.crop_x + self.crop_w > self.raw_w: self.crop_x = self.raw_w - self.crop_w
            if self.crop_y + self.crop_h > self.raw_h: self.crop_y = self.raw_h - self.crop_h
            self.draw_rect()
        except: pass

    def reset_to_original(self):
        # 【修改点】重置为原视频大小
        self.crop_x = 0
        self.crop_y = 0
        self.crop_w = self.raw_w
        self.crop_h = self.raw_h
        
        self.var_crop_w.set(self.crop_w)
        self.var_crop_h.set(self.crop_h)
        self.draw_rect()

    def confirm(self):
        # 收集数据
        self.result_data = {
            "frames": self.var_frames.get(),
            "crop_box": (int(self.crop_x), int(self.crop_y), int(self.crop_w), int(self.crop_h))
        }
        if self.callback:
            self.callback(self.result_data)
        self.destroy()
    

class FrameSequencePreview(tk.Toplevel):
    def __init__(self, parent, frame_paths):
        super().__init__(parent)
        self.title("预处理帧预览")
        self.frame_paths = frame_paths
        self.index = 0
        self.playing = len(frame_paths) > 1
        self.after_id = None
        self.tk_img = None

        self.label = ttk.Label(self)
        self.label.pack(fill="both", expand=True, padx=10, pady=10)

        bottom = ttk.Frame(self, padding=8)
        bottom.pack(fill="x")
        self.info = ttk.Label(bottom, text="")
        self.info.pack(side="left")

        ttk.Button(bottom, text="上一帧", command=self.prev_frame).pack(side="right", padx=3)
        ttk.Button(bottom, text="下一帧", command=self.next_frame).pack(side="right", padx=3)
        self.play_btn = ttk.Button(bottom, text="暂停" if self.playing else "播放", command=self.toggle_play)
        self.play_btn.pack(side="right", padx=3)

        self.protocol("WM_DELETE_WINDOW", self.close)
        self.geometry("560x640")
        self.show_frame()
        if self.playing:
            self.schedule_next()

    def show_frame(self):
        path = self.frame_paths[self.index]
        img = Image.open(path).convert("RGBA")
        img.thumbnail((520, 560), Image.Resampling.LANCZOS)
        self.tk_img = ImageTk.PhotoImage(img)
        self.label.config(image=self.tk_img)
        self.info.config(text=f"{self.index + 1}/{len(self.frame_paths)}  {os.path.basename(path)}")

    def schedule_next(self):
        if self.playing:
            self.after_id = self.after(80, self.advance)

    def advance(self):
        self.index = (self.index + 1) % len(self.frame_paths)
        self.show_frame()
        self.schedule_next()

    def toggle_play(self):
        self.playing = not self.playing
        self.play_btn.config(text="暂停" if self.playing else "播放")
        if self.playing:
            self.schedule_next()
        elif self.after_id:
            self.after_cancel(self.after_id)
            self.after_id = None

    def prev_frame(self):
        self.index = (self.index - 1) % len(self.frame_paths)
        self.show_frame()

    def next_frame(self):
        self.index = (self.index + 1) % len(self.frame_paths)
        self.show_frame()

    def close(self):
        if self.after_id:
            self.after_cancel(self.after_id)
        self.destroy()


# =========================================================================
# PART 4: UI 页面 - BUFF替换 (BK2 生成器) - [已修改]
# =========================================================================

# 1. 定义职业对照数据 (直接嵌入代码，方便调用)
BUFF_MAPPING_SRC = """
鬼剑士
01_ghost_M_buf_asura.bk2——阿修罗
01_ghost_M_buf_bsk.bk2——狂战士
01_ghost_M_buf_ghost.bk2——剑影
01_ghost_M_buf_soul.bk2——鬼泣
01_ghost_M_buf_wep.bk2——剑魂
02_ghost_F_buf_blade.bk2——刃影
02_ghost_F_buf_demon.bk2——剑魔
02_ghost_F_buf_darktemp.bk2——暗帝
02_ghost_F_buf_sword.bk2——剑宗
02_ghost_F_buf_vega.bk2——剑帝
格斗家
04_fighter_F_buf_grap.bk2——柔道家(女)
04_fighter_F_buf_nen.bk2——气功师(女)
04_fighter_F_buf_street.bk2——街霸(女)
04_fighter_F_buf_strik.bk2——散打(女)
03_figher_M_buf_grap.bk2——柔道家(男)
03_figher_M_buf_nen.bk2——气功师(男)
03_figher_M_buf_Street.bk2——街霸(男)
03_figher_M_buf_strik.bk2——散打(男)
魔法师
07_mage_M_buf_bloodm.bk2——血法师
07_mage_M_buf_dimension.bk2——次元行者
07_mage_M_buf_elbomber.bk2——元素爆破师
07_mage_M_buf_glancial.bk2——冰结师
07_mage_M_buf_swiftma.bk2——逐风者
08_mage_F_buf_battlemage.bk2——战斗法师
08_mage_F_buf_element.bk2——元素师
08_mage_F_buf_enchant.bk2——小魔女
08_mage_F_buf_summoner.bk2——召唤师
08_mage_F_buf_witch.bk2——魔道学者
神枪手
05_gunner_M_buf_assult.bk2——合金战士
05_gunner_M_buf_luncher.bk2——枪炮师(男)
05_gunner_M_buf_meca.bk2——机械师(男)
05_gunner_M_buf_ranger.bk2——漫游枪手(男)
05_gunner_M_buf_spit.bk2——弹药专家(男)
06_gunner_F_buf_launcher.bk2——枪炮师(女)
06_gunner_F_buf_meca.bk2——机械师(女)
06_gunner_F_buf_ranger.bk2——漫游枪手(女)
06_gunner_F_buf_spit.bk2——弹药专家(女)
06_gunner_F_buf_paramedic.bk2——协战师
圣职者
09_prist_M_buf_avenger.bk2——复仇者
09_prist_M_buf_battlecru.bk2——圣骑士(审判)
09_prist_M_buf_buffcru.bk2——圣骑士(奶爸)
09_prist_M_buf_exorcist.bk2——驱魔师
09_prist_M_buf_infight.bk2——蓝拳圣使(男)
10_priest_F_buf_sorcer.bk2——巫女
10_priest_F_buf_crusager.bk2——圣骑士(女)
10_priest_F_buf_inquis.bk2——异端审判者
10_priest_F_buf_mistress.bk2——诱魔者
10_priest_F_buf_infigh——蓝拳圣使(女)
暗夜
11_thief_buf_necro.bk2——暗夜使者
11_thief_buf_rogue.bk2——刺客
11_thief_buf_kuno.bk2——忍者
11_thief_buf_shadow.bk2——影舞者
魔枪士
14_demolancer_buf_darklancer.bk2——暗枪士
14_demolancer_buf_dralancer.bk2——狩猎者
14_demolancer_buf_duelist.bk2——决战者
14_demolancer_buf_vanguard.bk2——征战者
守护者
12_knight_buf_chaos.bk2——混沌魔灵
12_knight_buf_dragonkn.bk2——龙骑士
12_knight_buf_eleven.bk2——精灵骑士
12_knight_buf_paladin.bk2——帕拉丁
枪剑士
15_GunBla_buf_agent.bk2——特工
15_GunBla_buf_hitman.bk2——暗刃
15_GunBla_buf_specilist.bk2——源能专家
15_GunBla_buf_trouble.bk2——战线佣兵
弓箭手
16_archer_buf_hunter.bk2——猎人
16_archer_buf_vigil.bk2——妖护使
16_archer_buf_muse.bk2——缪斯
16_archer_buf_traveler.bk2——旅人
16_archer_buf_chimera.bk2——奇美拉
外传
13_ECT_darkknight_buf.bk2——黑暗武士
13_ECT_Creater_buf.bk2——缔造者
帝国骑士
17_imperial_F_buf_break——破浪者
"""

# =========================================================================
# 辅助类：手动裁剪窗口
# =========================================================================
# =========================================================================
# 辅助类：手动裁剪窗口 (修复版：左上角对齐 + 智能缩放)
# =========================================================================
# =========================================================================
# 辅助类：手动裁剪窗口 (修复版：支持宽高自定义 + 智能窗口 + 边界限制)
# =========================================================================
# =========================================================================
# 辅助类：手动裁剪窗口 (修改版：移除ESC/回车快捷键，保留输入框回车更新预览)
# =========================================================================
class ManualCropper(tk.Toplevel):
    def __init__(self, master, img_path, callback=None):
        super().__init__(master)
        # 【修改点】标题去掉了快捷键提示
        self.title("✂️ 图片裁剪 - 拖动红框 / 输入尺寸")
        self.callback = callback
        self.src_img = Image.open(img_path)
        
        # 1. 初始尺寸逻辑
        self.img_w, self.img_h = self.src_img.size
        
        # 默认裁剪尺寸 (470x668)，如果原图小，则取原图大小
        self.crop_w_real = 470 if self.img_w >= 470 else self.img_w
        self.crop_h_real = 668 if self.img_h >= 668 else self.img_h
        
        # 2. 智能计算窗口显示比例
        screen_w = self.winfo_screenwidth()
        screen_h = self.winfo_screenheight() - 150
        
        target_view_h = int(screen_h * 0.8)
        self.scale = target_view_h / self.img_h
        
        # 如果宽度超标，改用宽度适配
        if (self.img_w * self.scale) > (screen_w * 0.9):
            self.scale = (screen_w * 0.9) / self.img_w

        # 显示尺寸
        self.display_w = int(self.img_w * self.scale)
        self.display_h = int(self.img_h * self.scale)
        
        # 3. 窗口大小设置 (最小宽度 500)
        win_content_w = self.display_w + 20
        self.win_w = max(win_content_w, 500) 
        self.win_h = self.display_h + 100    
        
        self.geometry(f"{self.win_w}x{self.win_h}")
        
        self.tk_img = ImageTk.PhotoImage(self.src_img.resize((self.display_w, self.display_h)))

        # 4. 初始化红框位置 (居中)
        self.box_display_w = self.crop_w_real * self.scale
        self.box_display_h = self.crop_h_real * self.scale
        
        self.rect_x = (self.display_w - self.box_display_w) / 2
        self.rect_y = (self.display_h - self.box_display_h) / 2

        self.create_ui()
        self.center_window()

    def create_ui(self):
        # --- 顶部操作栏 ---
        top_bar = ttk.Frame(self, padding=10)
        top_bar.pack(fill="x", side="top")
        
        # 宽度控制
        ttk.Label(top_bar, text="宽:").pack(side="left")
        self.var_w = tk.IntVar(value=self.crop_w_real)
        e_w = ttk.Entry(top_bar, textvariable=self.var_w, width=6)
        e_w.pack(side="left", padx=(0, 5))
        # 这里的回车保留：只更新红框大小，不关闭窗口
        e_w.bind("<Return>", lambda e: self.update_rect_from_entry())
        
        # 高度控制
        ttk.Label(top_bar, text="高:").pack(side="left")
        self.var_h = tk.IntVar(value=self.crop_h_real)
        e_h = ttk.Entry(top_bar, textvariable=self.var_h, width=6)
        e_h.pack(side="left", padx=(0, 10))
        # 这里的回车保留：只更新红框大小，不关闭窗口
        e_h.bind("<Return>", lambda e: self.update_rect_from_entry())
        
        ttk.Button(top_bar, text="应用尺寸", command=self.update_rect_from_entry).pack(side="left")
        ttk.Button(top_bar, text="重置为全图", command=self.reset_full).pack(side="left", padx=5)
        
        ttk.Button(top_bar, text="✅ 确认裁剪", command=self.confirm).pack(side="right", padx=10, fill="y")

        # --- 画布区域 ---
        canvas_container = tk.Frame(self, bg="#333")
        canvas_container.pack(fill="both", expand=True)
        
        self.canvas = tk.Canvas(canvas_container, width=self.display_w, height=self.display_h, bg="#222", cursor="fleur")
        self.canvas.pack(pady=10) 
        
        self.canvas.create_image(0, 0, image=self.tk_img, anchor="nw")
        
        # 遮罩层
        self.mask_color = "black"
        self.mask_stipple = "gray50"
        self.mask_top = self.canvas.create_rectangle(0,0,0,0, fill=self.mask_color, stipple=self.mask_stipple, width=0)
        self.mask_btm = self.canvas.create_rectangle(0,0,0,0, fill=self.mask_color, stipple=self.mask_stipple, width=0)
        self.mask_lft = self.canvas.create_rectangle(0,0,0,0, fill=self.mask_color, stipple=self.mask_stipple, width=0)
        self.mask_rgt = self.canvas.create_rectangle(0,0,0,0, fill=self.mask_color, stipple=self.mask_stipple, width=0)

        # 红框
        self.rect_id = self.canvas.create_rectangle(0, 0, 1, 1, outline="#ff0000", width=2, tag="rect")
        
        self.draw_rect()

        # 事件
        self.canvas.bind("<Button-1>", self.on_click)
        self.canvas.bind("<B1-Motion>", self.on_drag)
        
        # 【修改点】移除了全局的 <Return> 和 <Escape> 绑定
        # self.bind("<Return>", lambda e: self.confirm())  <-- 已删除
        # self.bind("<Escape>", lambda e: self.destroy())  <-- 已删除

    def center_window(self):
        self.update_idletasks()
        x = (self.winfo_screenwidth() // 2) - (self.win_w // 2)
        y = (self.winfo_screenheight() // 2) - (self.win_h // 2)
        self.geometry(f"+{x}+{y}")

    def update_rect_from_entry(self):
        try:
            w = int(self.var_w.get())
            h = int(self.var_h.get())
            
            # 限制不能超过原图
            w = min(w, self.img_w)
            h = min(h, self.img_h)
            w = max(1, w)
            h = max(1, h)
            
            self.var_w.set(w)
            self.var_h.set(h)
            
            self.crop_w_real = w
            self.crop_h_real = h
            self.box_display_w = w * self.scale
            self.box_display_h = h * self.scale
            
            max_x = self.display_w - self.box_display_w
            max_y = self.display_h - self.box_display_h
            self.rect_x = min(max(0, self.rect_x), max_x)
            self.rect_y = min(max(0, self.rect_y), max_y)
            
            self.draw_rect()
        except: pass

    def reset_full(self):
        self.var_w.set(self.img_w)
        self.var_h.set(self.img_h)
        self.rect_x = 0
        self.rect_y = 0
        self.update_rect_from_entry()

    def on_click(self, event):
        self.move_rect_to_mouse(event.x, event.y)

    def on_drag(self, event):
        self.move_rect_to_mouse(event.x, event.y)

    def move_rect_to_mouse(self, mx, my):
        new_x = mx - (self.box_display_w / 2)
        new_y = my - (self.box_display_h / 2)
        
        max_x = self.display_w - self.box_display_w
        max_y = self.display_h - self.box_display_h
        
        self.rect_x = max(0, min(new_x, max_x))
        self.rect_y = max(0, min(new_y, max_y))
        
        self.draw_rect()

    def draw_rect(self):
        x1, y1 = self.rect_x, self.rect_y
        x2 = x1 + self.box_display_w
        y2 = y1 + self.box_display_h
        
        self.canvas.coords(self.rect_id, x1, y1, x2, y2)
        
        # Top
        self.canvas.coords(self.mask_top, 0, 0, self.display_w, y1)
        # Bottom
        self.canvas.coords(self.mask_btm, 0, y2, self.display_w, self.display_h)
        # Left
        self.canvas.coords(self.mask_lft, 0, y1, x1, y2)
        # Right
        self.canvas.coords(self.mask_rgt, x2, y1, self.display_w, y2)

    def confirm(self):
        real_x = int(self.rect_x / self.scale)
        real_y = int(self.rect_y / self.scale)
        real_w = int(self.crop_w_real)
        real_h = int(self.crop_h_real)
        
        if real_x + real_w > self.img_w: real_x = self.img_w - real_w
        if real_y + real_h > self.img_h: real_y = self.img_h - real_h
        
        box = (real_x, real_y, real_x + real_w, real_y + real_h)
        cropped = self.src_img.crop(box)
        
        if self.callback:
            self.callback(cropped)
        self.destroy()

def parse_buff_data():
    data = {}
    current_cat = None
    lines = BUFF_MAPPING_SRC.strip().split('\n')
    for line in lines:
        line = line.strip()
        if not line: continue
        if "——" in line:
            code, name = line.split("——", 1)
            code = code.strip()
            if code.lower().endswith(".bk2"):
                code = code[:-4]
            if current_cat:
                data[current_cat][name.strip()] = code
        else:
            current_cat = line
            data[current_cat] = {}
    return data

BUFF_DATA = parse_buff_data()

# =========================================================================
# PART 4: UI 页面 - BUFF替换 (带预览功能版)
# =========================================================================

# (请保留 BUFF_MAPPING_SRC 和 parse_buff_data 函数，不要删除)

class BuffPage(tk.Frame):
    def __init__(self, parent):
        super().__init__(parent)
        # 1. 从配置读取值
        self.input_path = tk.StringVar(value=Config.get("buff_input", ""))
        self.output_dir = tk.StringVar(value=Config.get("buff_output", ""))
        
        # 【修改点】默认路径改为当前文件夹下的 RADVideo\radvideo64.exe
        # os.getcwd() 获取当前运行目录
        default_rad = os.path.join(os.getcwd(), "RADVideo", "radvideo64.exe")
        self.rad_path = tk.StringVar(value=Config.get("buff_rad", default_rad))
        
        # --- 状态变量 ---
        # 【核心修改】新增影子变量，存储程序在后台生成的临时文件路径
        # input_path 显示原文件路径，actual_processed_path 存储裁剪/抽帧后的路径
        self.actual_processed_path = None 
        
        self.last_generated_file = None 
        self.temp_video_path = None
        
        self.selected_category = tk.StringVar(value=Config.get("buff_category", ""))
        self.selected_job_name = tk.StringVar(value=Config.get("buff_job", ""))
        self.target_filename_preview = tk.StringVar(value="等待选择...")
        self.effect_mode = tk.StringVar(value=Config.get("buff_effect", "简单 Cut-in"))

        self.create_widgets()
        
        # 2. 触发联动，确保职业列表正确回显
        if self.selected_category.get():
            self.on_category_change(None) # 填充职业列表
            # 重新设置职业（因为 on_category_change 会清空职业）
            saved_job = Config.get("buff_job", "")
            if saved_job in self.cb_job['values']:
                self.cb_job.set(saved_job)
                self.update_preview_label(None)
        
        # 绑定输入框变化事件：如果用户手动修改了路径，必须清空影子变量，防止逻辑错乱
        self.input_path.trace("w", self.on_input_changed)

    def create_widgets(self):
        tk.Label(self, text="BUFF替换", font=("微软雅黑", 16, "bold"), fg="#333").pack(pady=20)
        
        f_main = ttk.Frame(self, padding=20)
        f_main.pack(fill="both", expand=True)

        # 1. 设置
        f_set = ttk.LabelFrame(f_main, text=" 1. 工具设置 ", padding=10)
        f_set.pack(fill="x", pady=5)
        f_r = ttk.Frame(f_set)
        f_r.pack(fill="x")
        ttk.Label(f_r, text="RAD工具路径:", width=12).pack(side="left")
        ttk.Entry(f_r, textvariable=self.rad_path).pack(side="left", fill="x", expand=True)
        ttk.Button(f_r, text="浏览...", command=self.sel_rad).pack(side="left", padx=5)

        # 2. 职业与特效
        f_job = ttk.LabelFrame(f_main, text=" 2. 职业与特效 ", padding=10)
        f_job.pack(fill="x", pady=5)
        
        f_row1 = ttk.Frame(f_job)
        f_row1.pack(fill="x", pady=2)
        ttk.Label(f_row1, text="职业选择:", width=12).pack(side="left")
        self.cb_category = ttk.Combobox(f_row1, textvariable=self.selected_category, state="readonly", width=15)
        self.cb_category.pack(side="left", padx=2)
        self.cb_category['values'] = list(BUFF_DATA.keys())
        self.cb_category.bind("<<ComboboxSelected>>", self.on_category_change)
        
        self.cb_job = ttk.Combobox(f_row1, textvariable=self.selected_job_name, state="readonly", width=15)
        self.cb_job.pack(side="left", padx=2)
        self.cb_job.bind("<<ComboboxSelected>>", self.update_preview_label)
        
        ttk.Label(f_row1, textvariable=self.target_filename_preview, foreground="#e74c3c").pack(side="left", padx=10)

        f_row2 = ttk.Frame(f_job)
        f_row2.pack(fill="x", pady=5)
        ttk.Label(f_row2, text="动态特效:", width=12).pack(side="left")
        effect_list = EffectFactory.available_effects()
        self.cb_effect = ttk.Combobox(f_row2, textvariable=self.effect_mode, values=effect_list, state="readonly")
        self.cb_effect.pack(side="left", fill="x", expand=True)
        self.cb_effect.bind("<<ComboboxSelected>>", self.on_effect_change)

        # 3. 来源
        f_io = ttk.LabelFrame(f_main, text=" 3. 图片来源与保存 ", padding=10)
        f_io.pack(fill="x", pady=5)
        
        f_i = ttk.Frame(f_io)
        f_i.pack(fill="x", pady=5)
        ttk.Label(f_i, text="源文件:", width=12).pack(side="left")
        ttk.Entry(f_i, textvariable=self.input_path).pack(side="left", fill="x", expand=True)
        
        # 【修改点】 按钮改为 "选择源文件" 和 "选择序列文件夹"
        ttk.Button(f_i, text="📄 选择源文件 (图片/视频)", command=self.sel_source_file).pack(side="left", padx=2)
        ttk.Button(f_i, text="📂 选择序列文件夹", command=self.sel_img_dir).pack(side="left", padx=2)

        f_o = ttk.Frame(f_io)
        f_o.pack(fill="x", pady=5)
        ttk.Label(f_o, text="保存位置:", width=12).pack(side="left")
        ttk.Entry(f_o, textvariable=self.output_dir).pack(side="left", fill="x", expand=True)
        ttk.Button(f_o, text="选择...", command=self.sel_out_dir).pack(side="left", padx=5)

        # 4. 运行 & 预览
        f_run = ttk.Frame(f_main)
        f_run.pack(pady=15, fill="x")
        
        ttk.Button(f_run, text="🚀 生成动态 BK2 视频", command=self.start_build).pack(side="left", fill="x", expand=True, padx=2)
        ttk.Button(f_run, text="▶️ 播放/预览", command=self.preview_video, width=15).pack(side="right", padx=2)

        self.log_text = tk.Text(f_main, height=8, bg="#f0f0f0", font=("Consolas", 9), state="disabled")
        self.log_text.pack(fill="both", expand=True)

    # --- 逻辑处理 ---
    def on_input_changed(self, *args):
        # 只要输入框变了，就认为之前的临时文件无效了
        if self.actual_processed_path:
            # 可以选择这里是否立即删除旧文件，为了保险起见，只重置变量
            self.actual_processed_path = None
            # self.log("ℹ️ 检测到路径手动变更，将使用新路径作为源。")

    def on_effect_change(self, event):
        Config.set("buff_effect", self.effect_mode.get())

    def on_category_change(self, event):
        cat = self.selected_category.get()
        Config.set("buff_category", cat) # 保存大类
        if cat in BUFF_DATA:
            self.cb_job['values'] = list(BUFF_DATA[cat].keys())
            self.cb_job.set("")
            self.target_filename_preview.set("")
        else:
            self.cb_job['values'] = []

    def update_preview_label(self, event):
        cat = self.selected_category.get()
        name = self.selected_job_name.get()
        if cat in BUFF_DATA and name in BUFF_DATA[cat]:
            self.target_filename_preview.set(f"-> {BUFF_DATA[cat][name]}.bk2")
            Config.set("buff_job", name) # 保存具体职业

    def sel_rad(self):
        p = filedialog.askopenfilename(filetypes=[("Exe", "*.exe")])
        if p: 
            self.rad_path.set(p)
            Config.set("buff_rad", p)

    def sel_img_dir(self):
        p = filedialog.askdirectory()
        if p: 
            self.input_path.set(p)
            self.actual_processed_path = None # 文件夹模式不需要临时路径
            if not self.output_dir.get(): self.output_dir.set(p)
            self.log(f"📂 已选择文件夹模式(不适用特效): {os.path.basename(p)}")
            Config.set("buff_input", p)
            Config.set("buff_output", self.output_dir.get())

    # ---------------------------------------------------------
    # 【核心修改】整合后的选择文件逻辑
    # ---------------------------------------------------------
    def sel_source_file(self):
        # 扩展文件过滤器，加入视频格式
        file_types = [
            ("All Supported", "*.png;*.jpg;*.bmp;*.mp4;*.avi;*.webm;*.mov;*.gif"),
            ("Images", "*.png;*.jpg;*.bmp"),
            ("Videos", "*.mp4;*.avi;*.webm;*.mov;*.gif")
        ]
        p = filedialog.askopenfilename(filetypes=file_types)
        
        if not p: return

        # 【核心】UI 只显示原文件路径
        self.input_path.set(p)
        self.actual_processed_path = None # 重置
        
        # 保存选择的路径
        Config.set("buff_input", p)
        if not self.output_dir.get():
            out_d = os.path.dirname(p)
            self.output_dir.set(out_d)
            Config.set("buff_output", out_d)
        
        ext = os.path.splitext(p)[1].lower()
        if ext in ['.mp4', '.avi', '.webm', '.mov', '.gif', '.mkv']:
            if not HAS_MOVIEPY:
                messagebox.showerror(
                    "错误",
                    "处理视频需要安装或打包 moviepy 库！\n"
                    f"{get_video_dependency_error()}\n"
                    "请更新到已修复的视频依赖版本。",
                )
                return
            
            self.temp_video_path = p 
            VideoSettingsDialog(self.winfo_toplevel(), p, self.on_video_config_done)
            
        # --- 情况 B: 普通图片 ---
        else:
            ManualCropper(self.winfo_toplevel(), p, callback=self.on_crop_finished)

    # --- 视频设置完成后的回调 ---
    def on_video_config_done(self, settings):
        if not settings: return
        
        # 1. 准备临时文件夹
        temp_dir = os.path.join(os.getcwd(), "_temp_video_frames")
        if os.path.exists(temp_dir): shutil.rmtree(temp_dir)
        os.makedirs(temp_dir)
        
        self.log(f"🎬 正在后台处理视频...")
        self.update_idletasks()
        
        # 2. 执行转换
        success, msg = VideoProcessor.process_video_to_frames(
            self.temp_video_path, 
            temp_dir, 
            target_frames=settings['frames'],
            crop_box=settings['crop_box']
        )
        
        if success:
            # 【核心】只更新内部影子变量，不改变 UI 上的路径
            self.actual_processed_path = temp_dir
            self.log(f"✅ 视频预处理完成！(临时路径已记录)")
            self.log(f"ℹ️ 点击 [生成] 按钮即可开始制作。")
        else:
            messagebox.showerror("处理失败", msg)
            self.log(f"❌ 失败: {msg}")

    def on_crop_finished(self, pil_image):
        try:
            pil_image = pil_image.convert("RGBA")
            temp_name = "temp_cropped_buff_source.png"
            temp_path = os.path.join(os.getcwd(), temp_name)
            pil_image.save(temp_path)
            
            # 【核心】只更新内部影子变量
            self.actual_processed_path = temp_path
            self.log(f"✅ 图片裁剪完成！(临时路径已记录)")
            self.log(f"ℹ️ 点击 [生成] 按钮即可开始制作。")
        except Exception as e:
            messagebox.showerror("错误", f"保存失败: {e}")

    def sel_out_dir(self):
        p = filedialog.askdirectory()
        if p: 
            self.output_dir.set(p)
            Config.set("buff_output", p)

    def log(self, msg):
        self.log_text.config(state="normal")
        self.log_text.insert("end", str(msg) + "\n")
        self.log_text.see("end")
        self.log_text.config(state="disabled")

    # --- 预览功能 ---
    def preview_video(self):
        # 1. 确定目标文件
        target_file = self.last_generated_file
        
        # 如果没有记录，尝试根据当前选项推断
        if not target_file or not os.path.exists(target_file):
            out_dir = self.output_dir.get()
            cat = self.selected_category.get()
            job = self.selected_job_name.get()
            if out_dir and cat and job:
                if cat in BUFF_DATA and job in BUFF_DATA[cat]:
                    code = BUFF_DATA[cat][job]
                    target_file = os.path.join(out_dir, f"{code}.bk2")
        
        preview_kind, preview_target = resolve_preview_target(target_file, self.actual_processed_path)

        if preview_kind == "frames":
            self.log(f"▶️ 正在预览预处理帧: {len(preview_target)} 张")
            FrameSequencePreview(self.winfo_toplevel(), preview_target)
            return

        if preview_kind == "invalid_bink":
            messagebox.showwarning(
                "无法预览",
                f"找到目标文件，但它不是有效的 Bink/BK2 文件：\n{preview_target}\n\n"
                "请重新点击[生成动态 BK2 视频]，生成成功后再播放 BK2。"
            )
            return

        if preview_kind == "missing":
            messagebox.showwarning(
                "无法预览",
                f"找不到可播放的 .bk2，也没有可预览的预处理帧：\n{preview_target}\n\n"
                "导入 MP4 后请先完成预处理；要播放 BK2，请先点击[生成动态 BK2 视频]。"
            )
            return

        # 3. 寻找播放器
        rad_dir = os.path.dirname(self.rad_path.get())
        player_candidates = ["bink2play.exe", "binkplay.exe"] # 优先用 bink2play
        real_player = None
        for p_name in player_candidates:
            p_path = os.path.join(rad_dir, p_name)
            if os.path.exists(p_path):
                real_player = p_path
                break
        
        # 4. 执行播放
        try:
            target_file_abs = preview_target
            self.log(f"▶️ 正在播放: {os.path.basename(target_file_abs)}")
            
            if real_player:
                subprocess.Popen([real_player, target_file_abs, "/L"], shell=False)
            else:
                self.log("⚠️ 未找到专用播放器，尝试使用系统默认方式...")
                os.startfile(target_file_abs)
                
        except Exception as e:
            messagebox.showerror("启动失败", f"无法预览。\n错误信息: {e}")

    def start_build(self):
        rad = self.rad_path.get()
        
        # 【核心逻辑】确定真实的源路径
        # 如果有后台处理好的临时路径，优先用它；否则用输入框的路径
        real_src_path = self.actual_processed_path if self.actual_processed_path else self.input_path.get()
        
        out_dir = self.output_dir.get()
        cat = self.selected_category.get()
        job = self.selected_job_name.get()

        if not os.path.exists(rad): return messagebox.showerror("错误", "RAD工具路径无效！")
        if not real_src_path or not os.path.exists(real_src_path): return messagebox.showerror("错误", "源文件处理后的临时文件不存在！请重新处理。")
        if not cat or not job: return messagebox.showerror("错误", "请先选择职业！")
        if not out_dir: return messagebox.showerror("错误", "请设置保存位置！")

        file_code = BUFF_DATA[cat][job]
        final_bk2_path = os.path.join(out_dir, f"{file_code}.bk2")
        effect = self.effect_mode.get()
        
        self.last_generated_file = None
        
        # 传入 real_src_path
        threading.Thread(target=self.run_thread, args=(real_src_path, final_bk2_path, rad, effect)).start()

    def run_thread(self, src_path, dst_path, rad, effect_mode):
        self.log(f">>> 开始生成: {os.path.basename(dst_path)}")
        temp_dir = os.path.join(os.getcwd(), "_temp_buff_frames")
        
        try:
            target_folder = src_path
            
            input_data = None
            # 1. 读取源数据 
            # (此时 src_path 指向的是 actual_processed_path，即预处理好的 PNG 或 文件夹)
            if os.path.isfile(src_path):
                input_data = Image.open(src_path).convert("RGBA")
            elif os.path.isdir(src_path):
                pngs = glob.glob(os.path.join(src_path, "*.png"))
                try: pngs.sort(key=lambda x: int(''.join(filter(str.isdigit, os.path.basename(x))) or 0))
                except: pngs.sort()
                
                if not pngs:
                    self.log("❌ 错误: 文件夹内没有PNG图片")
                    return
                
                input_data = []
                for p in pngs:
                    input_data.append(Image.open(p).convert("RGBA"))
                self.log(f"📂 读取到序列帧: {len(input_data)} 张")
            
            # 2. 生成特效
            if input_data:
                if os.path.exists(temp_dir): shutil.rmtree(temp_dir)
                os.makedirs(temp_dir)
                
                self.log(f"✨ 正在渲染特效: {effect_mode} ...")
                
                target_frame_count = len(input_data) if isinstance(input_data, list) else 18
                frames = EffectFactory.generate(input_data, effect_mode, frames=target_frame_count)
                
                for i, frame in enumerate(frames):
                    frame.save(os.path.join(temp_dir, f"frame_{i:04d}.png"))
                
                target_folder = temp_dir
            
            # 3. 调用 BK2 生成器
            success = build_hidden_bk2(target_folder, dst_path, rad, status_callback=self.log)
            if success and is_bink_file(dst_path):
                self.last_generated_file = dst_path
                messagebox.showinfo("成功", f"生成完毕！\n您可以点击[预览]按钮查看效果。")
                self.log(">>> ✅ 任务完成")
            elif success:
                self.log(">>> ❌ 生成失败: 输出文件不是有效的 Bink/BK2")
                messagebox.showerror("生成失败", f"输出文件不是有效的 Bink/BK2：\n{dst_path}")
            else:
                self.log(">>> ❌ 任务失败")
                
        except Exception as e:
            self.log(f"❌ 异常，请先抽帧处理: {e}")
            import traceback
            traceback.print_exc()
        finally:
            # 1. 清理【特效生成过程】中的中间文件 (必须删，否则下次残留)
            if os.path.exists(temp_dir):
                try: shutil.rmtree(temp_dir)
                except: pass
            
            # 【核心修改】
            # 移除了清理 src_path (临时源文件) 的代码。
            # 这样 self.actual_processed_path 依然有效，
            # 下次点击生成时，依然会使用预处理好的图片/帧，而不会回滚去读 MP4。
