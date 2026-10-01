#!/usr/bin/env python3
"""生成一张原创的抽象渐变占位图，供演示与本地测试使用。

这张图完全由本脚本程序合成，不含任何第三方素材，可以安全地随仓库分发。
它只是为了让人克隆后能立刻跑通 make-background.py，不代表推荐的实际背景风格。

用法：
    python tools/make-placeholder.py
    python tools/make-placeholder.py --width 2560 --height 1440 --out /tmp/x.jpg
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUT = ROOT / "background" / "placeholder.jpg"

# 深色调渐变停靠点 (位置 0..1, RGB)，便于演示深色主题下的透明面板
STOPS = [
    (0.00, (18, 22, 38)),
    (0.35, (36, 44, 78)),
    (0.62, (72, 62, 96)),
    (0.85, (128, 92, 84)),
    (1.00, (176, 138, 92)),
]

# 柔和高光团 (中心x, 中心y, 半径, RGB, 强度)，比例均相对画面尺寸
BLOBS = [
    (0.78, 0.30, 0.34, (222, 168, 96), 0.55),
    (0.22, 0.68, 0.30, (86, 128, 200), 0.42),
    (0.55, 0.92, 0.26, (196, 120, 140), 0.30),
]


def gradient(width: int, height: int) -> np.ndarray:
    """沿对角方向做多段线性渐变，返回 float32 的 HxWx3 数组。"""
    xs = np.linspace(0.0, 1.0, width, dtype=np.float32)
    ys = np.linspace(0.0, 1.0, height, dtype=np.float32)
    t = xs[None, :] * 0.55 + ys[:, None] * 0.45

    positions = np.array([s[0] for s in STOPS], dtype=np.float32)
    colors = np.array([s[1] for s in STOPS], dtype=np.float32)
    out = np.empty((height, width, 3), dtype=np.float32)
    for channel in range(3):
        out[..., channel] = np.interp(t, positions, colors[:, channel])
    return out


def add_blobs(base: np.ndarray) -> np.ndarray:
    """叠加几团柔和高光（screen 混合），让画面有层次而不是一条纯渐变。"""
    height, width = base.shape[:2]
    top = np.zeros_like(base)
    ys, xs = np.mgrid[0:height, 0:width].astype(np.float32)
    for cx, cy, radius, color, strength in BLOBS:
        r = radius * max(width, height)
        distance = np.hypot(xs - cx * width, ys - cy * height)
        falloff = np.clip(1.0 - distance / r, 0.0, 1.0) ** 2
        for channel in range(3):
            top[..., channel] = np.maximum(top[..., channel], falloff * color[channel] * strength)
    # screen: 255 - (255-a)(255-b)/255
    return 255.0 - (255.0 - base) * (255.0 - top) / 255.0


def vignette(image: np.ndarray, strength: float = 0.35) -> np.ndarray:
    """四角压暗，避免边缘过于平坦。"""
    height, width = image.shape[:2]
    ys, xs = np.mgrid[0:height, 0:width].astype(np.float32)
    cx, cy = width / 2.0, height / 2.0
    distance = np.hypot(xs - cx, ys - cy) / np.hypot(cx, cy)
    mask = (1.0 - strength * distance ** 2)[..., None]
    return image * mask


def main() -> None:
    parser = argparse.ArgumentParser(description="生成原创抽象渐变占位图")
    parser.add_argument("--width", type=int, default=1920)
    parser.add_argument("--height", type=int, default=1080)
    parser.add_argument("--quality", type=int, default=88)
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    args = parser.parse_args()

    image = vignette(add_blobs(gradient(args.width, args.height)))
    array = np.clip(image, 0, 255).astype(np.uint8)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(array, "RGB").save(out, format="JPEG", quality=args.quality, optimize=True, progressive=True)
    print(f"已生成 {out}  {args.width}x{args.height}  {out.stat().st_size / 1024:.0f} KB")


if __name__ == "__main__":
    main()
