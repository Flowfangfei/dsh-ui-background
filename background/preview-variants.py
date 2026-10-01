#!/usr/bin/env python3
"""生成不透明度对比图 —— 把同一张背景在不同 --canvas 档位下的近似观感拼成一张图。

用法：
    python preview-variants.py                      # 默认对比 0.50 / 0.58 / 0.65 / 0.72
    python preview-variants.py --blur 8 --canvas 0.55 0.65 0.75
    python preview-variants.py --theme light        # 看浅色主题下的观感

输出 variants.jpg。选好档位后再用 make-background.py 正式生成 background.css。
"""
from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter

HERE = Path(__file__).resolve().parent
DEFAULT_SOURCE = HERE / "source.jpg"
OUT = HERE / "variants.jpg"

DARK_BASE = (21, 21, 23)
LIGHT_BASE = (255, 255, 255)

ROW_WIDTH = 1120
LABEL_HEIGHT = 46
GAP = 10


def render_rows(source: Path, alphas: list[float], blur: float, saturate: float, gamma: float, base: tuple[int, int, int]) -> list[tuple[float, Image.Image]]:
    """按每个不透明度渲染一行近似观感图。"""
    image = Image.open(source).convert("RGB")
    image.thumbnail((ROW_WIDTH, ROW_WIDTH), Image.LANCZOS)
    if blur > 0:
        image = image.filter(ImageFilter.GaussianBlur(blur))
    if saturate != 1.0:
        image = ImageEnhance.Color(image).enhance(saturate)
    if gamma != 1.0:
        lut = [min(255, int(round(255 * ((i / 255) ** gamma)))) for i in range(256)]
        image = image.point(lut * 3)
    rows = []
    for alpha in alphas:
        solid = Image.new("RGB", image.size, base)
        rows.append((alpha, Image.blend(image, solid, alpha)))
    return rows


def build_sheet(rows: list[tuple[float, Image.Image]], theme: str) -> Image.Image:
    """把各行拼成一张带标签的对比图。"""
    width = rows[0][1].width
    row_height = rows[0][1].height
    height = len(rows) * (row_height + LABEL_HEIGHT) + GAP * (len(rows) - 1)
    sheet = Image.new("RGB", (width, height), (16, 16, 18))
    draw = ImageDraw.Draw(sheet)
    font = None
    for candidate in ("C:/Windows/Fonts/msyh.ttc", "C:/Windows/Fonts/segoeui.ttf", "C:/Windows/Fonts/arial.ttf"):
        if Path(candidate).exists():
            from PIL import ImageFont
            font = ImageFont.truetype(candidate, 24)
            break
    from PIL import ImageFont
    if font is None:
        font = ImageFont.load_default()

    y = 0
    for alpha, image in rows:
        draw.rectangle([0, y, width, y + LABEL_HEIGHT], fill=(28, 28, 32))
        label = f"--fill {alpha:.2f}   主题={theme}   （数值越大，面板越实、背景越淡）"
        draw.text((14, y + 10), label, fill=(235, 235, 240), font=font)
        y += LABEL_HEIGHT
        sheet.paste(image, (0, y))
        y += row_height + GAP
    return sheet


def main() -> None:
    parser = argparse.ArgumentParser(description="生成不同 --fill 档位的观感对比图")
    parser.add_argument("--source", default=str(DEFAULT_SOURCE), help="源图路径")
    parser.add_argument("--blur", type=float, default=0.0, help="高斯模糊半径（px）")
    parser.add_argument("--gamma", type=float, default=1.0, help="暗部提升：<1 抬阴影。要和 make-background.py 用同一个值")
    parser.add_argument("--saturate", type=float, default=1.0, help="饱和度倍数")
    parser.add_argument("--theme", choices=["dark", "light"], default="dark", help="按哪个主题合成")
    parser.add_argument("--fill", type=float, nargs="+", default=[0.00, 0.12, 0.24, 0.36], help="要对比的表面填充 alpha 档位")
    parser.add_argument("--canvas", type=float, nargs="+", dest="fill", help="--fill 的旧名，等价")
    args = parser.parse_args()

    source = Path(args.source).expanduser().resolve()
    if not source.exists():
        raise SystemExit(f"找不到源图：{source}")

    base = DARK_BASE if args.theme == "dark" else LIGHT_BASE
    rows = render_rows(source, sorted(args.fill), args.blur, args.saturate, args.gamma, base)
    sheet = build_sheet(rows, args.theme)
    sheet.save(OUT, format="JPEG", quality=88)
    print(f"对比图 {OUT}  ({sheet.width}x{sheet.height})")
    print("fill 档位   " + ", ".join(f"{a:.2f}" for a, _ in rows))


if __name__ == "__main__":
    main()
