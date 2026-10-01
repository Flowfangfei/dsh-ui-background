#!/usr/bin/env python3
"""生成 background.css —— 让桌面版 DSH 的界面表面透明、露出背景图，并用细边框区分面板。

用法示例：
    python make-background.py                            # 推荐默认：面板留 12% 底色 + 边框
    python make-background.py --fill 0                   # 面板完全透明（亮区文字会更难读）
    python make-background.py --fill 0.18 --border 0.40  # 面板更实、边框更亮
    python make-background.py --source "D:/x/BG.jpg" --blur 0

改完刷新浏览器页面即可生效，DSH 不用重启（plugin.mjs 每次 index 渲染都重读本 CSS）。

⚠ 参数联动：面板一旦接近全透明，它就不再压暗背景图，所以 --gamma 应保持 1.0。
   之前用来压住亮度的 gamma 0.75 / saturate 会显得发灰。
"""
from __future__ import annotations

import argparse
import base64
import io
from pathlib import Path

from PIL import Image, ImageEnhance, ImageFilter

HERE = Path(__file__).resolve().parent
DEFAULT_SOURCE = HERE / "source.jpg"
CSS_OUT = HERE / "background.css"
PREVIEW = HERE / "preview.jpg"
PREVIEW_DARK = HERE / "preview-dark.jpg"


def display_path(path: Path) -> str:
    """把源图路径写成可公开的相对形式。

    生成的 CSS 会被分享、也可能被贴进 issue，所以绝不写入绝对路径或本机用户名：
    能相对仓库根表示就相对表示，否则只留文件名。
    """
    for base in (HERE.parent, HERE):
        try:
            return path.relative_to(base).as_posix()
        except ValueError:
            continue
    return path.name

# ── 主题基色 ────────────────────────────────────────────────────────────────
DARK_BASE = (21, 21, 23)
LIGHT_BASE = (255, 255, 255)

# ── 要变透明的表面填充 token（35 个）────────────────────────────────────────
# 严格排除：bg-mask-*（弹窗遮罩）、button-primary/info/contrast-fill（强调按钮）、
# interactive-bg-*（悬停反馈）、bg-skeleton（加载提示）、label-*/state-*/link/brand/scrollbar。
SURFACE_TOKENS = [
    # 画布与层级
    "--dsw-alias-bg-base",
    "--dsw-alias-bg-layer-1",
    "--dsw-alias-bg-layer-2",
    "--dsw-alias-bg-layer-3",
    "--dsw-alias-bg-overlay",
    "--dsw-alias-bg-module-platform",
    "--dsw-alias-bg-multi-select",
    "--dsw-alias-bg-document-preview",
    # 组件专用表面
    "--dsw-specific-sidebar-fill",
    "--dsw-specific-input-major",
    "--dsw-specific-bubble",
    "--dsw-specific-bubble-highlight",
    "--dsw-specific-selector",
    "--dsw-specific-tip",
    "--dsw-specific-menu",
    "--dsw-specific-login-input",
    "--dsw-specific-sidebar-nav-item-active",
    "--dsw-specific-sidebar-nav-item-active-accent",
    "--dsw-specific-sidebar-nav-item-hover",
    # markdown / 代码
    "--dsw-alias-markdown-code-block",
    "--dsw-alias-markdown-code-block-banner",
    "--dsw-alias-markdown-inline-code",
    "--dsw-alias-markdown-code-segment-selected",
    "--dsw-alias-markdown-code-segment-unselected",
    "--dsw-alias-markdown-citation",
    "--dsw-alias-markdown-tag",
    "--dsw-alias-markdown-placeholder",
    # 非强调按钮（强调按钮的 primary/info/contrast-fill 不在内）
    "--dsw-alias-button-elevated-fill",
    "--dsw-alias-button-floating-fill",
    "--dsw-alias-button-ghost-active-fill",
    "--dsw-alias-button-tool-bar-fill",
    "--dsw-alias-button-tool-bar-fill-invisible",
    "--dsw-alias-button-tool-bar-hover",
    # 浮层
    "--dsw-alias-toast-bg",
    "--dsw-alias-tooltip-bg",
]

# 设计系统里没有定义、但组件仍引用（于是走硬编码兜底）的 token。定义它们即可绕开兜底。
UNDEFINED_TOKENS = {
    "--dsw-alias-fill-tertiary": "transparent",
}

# ── 边框 token：以 --border 为基准叠加偏移 ──────────────────────────────────
# 实测被引用作边框的只有 l1 / l2 / l2-darkmode-thin / inverted；l3、l4 一并给出，
# 其中 l4 驱动 --dsw-elevation-stroke-color，连"border:0 + 描边"的浮层一起覆盖。
BORDER_OFFSETS = [
    ("--dsw-alias-border-l1", 0.00),
    ("--dsw-alias-border-l2-darkmode-thin", 0.00),
    ("--dsw-alias-border-l2", 0.06),
    ("--dsw-alias-border-l3", 0.10),
    ("--dsw-alias-border-l4", 0.16),
    ("--dsw-alias-border-inverted", -0.04),
]

# ── 本来没有边框、需要补一条的表面（按类名结尾匹配，避开包哈希前缀）────────
# 剔除标准有两类，都是"加了会留下错线"：
#
# A. 几何上横跨整个内容列/整高，但不是"面板"——边框会画成一条没有语义的长线：
#      composerSeat    : absolute; left:0; right:<scrollbar>; bottom:0  → 全宽
#      schema / payload: min-height:100%                               → 全高
#      turnRail        : 本身已是 width:2px 竖轨，会画成双线
#      fade            : 渐隐遮罩，会画出硬边
#
# B. 会被"塌缩成 0 尺寸"来隐藏、或应用自己声明了 border:none 的元素——
#    元素收成 0 宽高时那 1px 边框照样渲染，于是关闭后残留一条线。
#      panel         : settings-plugins 的 .llfbtq_panel 带 width:0（可折叠预览面板）
#      table         : trajectory 的 .EJg6FW_table 带 width:0
#      overviewPreview: trajectory 带 height:0
#      runHeader     : workflow-run 带 width:0
#      badge         : cordis 的 ._7pkzhq_badge 明确写了 border:none（不该被 !important 盖掉）
SELECTOR_BORDER_NAMES = [
    # 主聊天界面
    "bubble",
    "code",
    "image",
    "number",
    # 轨迹视图
    "turnLabel",
    "systemNeutral",
    "compacted",
    "promptDiff",
    "promptDiffLinemeta",
    "promptDiffLineremoved",
    "assistantVioletBright",
    "subtoolAmber",
    "overviewHeading",
    "assistantOutput",
    "panelImage",
    "toolCatalogDefinition",
    "controlThumb",
    "plot",
]


def clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    """把 alpha 夹到合法区间。"""
    return max(low, min(high, value))


def rgba(rgb: tuple[int, int, int], alpha: float) -> str:
    """渲染成 CSS 的 rgba() 字面量。"""
    red, green, blue = rgb
    return f"rgba({red}, {green}, {blue}, {alpha:.2f})"


def render_image(source: Path, blur: float, gamma: float, saturate: float, quality: int, max_side: int) -> tuple[bytes, Image.Image]:
    """按参数处理源图，返回 (JPEG 字节, 处理后的图)。

    gamma < 1 抬起暗部。面板接近全透明时不需要它（图片不再被压暗），保持 1.0。
    """
    image = Image.open(source).convert("RGB")
    if max_side and max(image.size) > max_side:
        image = image.copy()
        image.thumbnail((max_side, max_side), Image.LANCZOS)
    if blur > 0:
        image = image.filter(ImageFilter.GaussianBlur(blur))
    if saturate != 1.0:
        image = ImageEnhance.Color(image).enhance(saturate)
    if gamma != 1.0:
        lut = [min(255, int(round(255 * ((i / 255) ** gamma)))) for i in range(256)]
        image = image.point(lut * 3)
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=quality, optimize=True, progressive=True)
    return buffer.getvalue(), image


def scrim_preview(image: Image.Image, rgb: tuple[int, int, int], alpha: float) -> Image.Image:
    """把面板底色压到图上，近似最终观感（result = 面板色*a + 图*(1-a)）。"""
    solid = Image.new("RGB", image.size, rgb)
    return Image.blend(image, solid, alpha)


def declarations(tokens: dict[str, str], indent: str = "  ") -> str:
    """把 令牌→值 渲染成带 !important 的声明行。"""
    return "\n".join(f"{indent}{name}: {value} !important;" for name, value in tokens.items())


def surface_block(selector: str, base: tuple[int, int, int], fill: float) -> str:
    """生成一个主题的表面填充覆盖块。"""
    tokens = {name: rgba(base, fill) for name in SURFACE_TOKENS}
    tokens.update(UNDEFINED_TOKENS)
    return f"{selector} {{\n{declarations(tokens)}\n}}"


def border_block(selector: str, base: tuple[int, int, int], border: float) -> str:
    """生成一个主题的边框加粗块。"""
    tokens = {name: rgba(base, clamp(border + offset)) for name, offset in BORDER_OFFSETS}
    return f"{selector} {{\n{declarations(tokens)}\n}}"


def selector_border_block(selector: str, base: tuple[int, int, int], border: float) -> str:
    """给没有边框的表面补一条。按类名结尾匹配，不受包哈希前缀变化影响。

    末尾的 `:not([aria-hidden='true'])` 是一道保险：有些组件用"保持盒子但收成 0 尺寸
    并标 aria-hidden"来隐藏，那种元素上 1px 边框仍然会渲染，关闭后会残留一条线。
    """
    parts = ",\n".join(
        f"{selector} [class$='_{name}']:not([aria-hidden='true'])" for name in SELECTOR_BORDER_NAMES
    )
    return f"{parts} {{\n  border: 1px solid {rgba(base, clamp(border))} !important;\n}}"


def build_css(payload: bytes, fill: float, border: float, args) -> str:
    """拼出最终的 background.css。"""
    encoded = base64.b64encode(payload).decode("ascii")
    return f"""\
/* ==========================================================================
   自定义 UI 背景 —— 由 make-background.py 生成，请勿手改（重新生成会覆盖）。
   要调效果就改参数重新生成，例如：
       python make-background.py --fill 0.12 --border 0.32
   生成后刷新浏览器页面即可生效，DSH 不用重启。
   ==========================================================================

   当前参数：
     源图           {display_path(Path(args.source))}
     柔化半径       {args.blur} px
     暗部提升       gamma {args.gamma}
     饱和度         {args.saturate}
     图片定位       {args.position}
     JPEG 质量      {args.quality}
     表面填充 alpha {fill}      (0 = 完全透明，越大面板越实)
     边框 alpha     {border}    (越大发丝线越亮)

   四段结构：
   1. 背景图铺在 <html> 上；<body> 底色置透明。
   2. 把 {len(SURFACE_TOKENS)} 个表面填充 token 改成半透明，黑色块就会透出背景图。
      刻意不含 bg-mask-*（弹窗遮罩）、button-primary/info/contrast-fill（强调按钮）、
      interactive-bg-*（悬停反馈）、bg-skeleton（加载提示）、label-/state-/link/brand/scrollbar。
   3. 加粗边框 token，让相邻面板仍能区分。l4 同时驱动 --dsw-elevation-stroke-color，
      因此那些 border:0 + 描边的浮层也一并覆盖。
   4. 给 {len(SELECTOR_BORDER_NAMES)} 类本来没有边框的表面补一条，用 [class$='_名字']
      结尾匹配，不受包哈希前缀变化影响。

   选择器用 `html body` 提高权重以压过运行时注入的样式表，再加 !important 兜底。
   ========================================================================== */

/* ── 1. 背景图 ─────────────────────────────────────────────────────────── */
html {{
  background-color: #151517;
  background-image: url("data:image/jpeg;base64,{encoded}");
  background-position: {args.position};
  background-repeat: no-repeat;
  background-size: cover;
  background-attachment: fixed;
}}

/* html 上给了图，body 必须透明，否则启动阶段写下的不透明底色会盖住它。 */
html body {{
  background-color: transparent !important;
}}

/* ── 2/3. 浅色主题：表面透明 + 边框加粗 ────────────────────────────────── */
{surface_block("html body", LIGHT_BASE, fill)}

{border_block("html body", (0, 0, 0), border)}

/* ── 2/3. 深色主题：表面透明 + 边框加粗 ────────────────────────────────── */
{surface_block("html body[data-ds-dark-theme]", DARK_BASE, fill)}

{border_block("html body[data-ds-dark-theme]", (255, 255, 255), border)}

/* ── 4. 给本来没有边框的表面补边框 ─────────────────────────────────────── */
{selector_border_block("html body", (0, 0, 0), border)}

{selector_border_block("html body[data-ds-dark-theme]", (255, 255, 255), border)}
"""


def main() -> None:
    parser = argparse.ArgumentParser(description="生成 DSH 自定义界面背景的 background.css")
    parser.add_argument("--source", default=str(DEFAULT_SOURCE), help="源图路径，默认同目录的 source.jpg")
    parser.add_argument("--blur", type=float, default=0.0,
                        help="高斯模糊半径（px）。默认 0 = 不模糊，保留原清晰度；若照片自己的建筑硬边被误读成 UI 框线，调到 2~3")
    parser.add_argument("--fill", type=float, default=0.10, help="表面填充 alpha：0=完全透明，越大面板越实")
    parser.add_argument("--border", type=float, default=0.22, help="边框 alpha：越大发丝线越亮。调太高会让折叠容器的残线变明显")
    parser.add_argument("--gamma", type=float, default=0.70, help="暗部提升：<1 抬阴影。暗色背景图用它把暗部从'全黑'救回来；1.0 = 完全不改色调")
    parser.add_argument("--saturate", type=float, default=1.0, help="饱和度倍数，1.0 表示不变")
    parser.add_argument("--position", default="center center", help="CSS background-position，例如 '70%% center' 把画面右移")
    parser.add_argument("--quality", type=int, default=95, help="JPEG 质量 1-100。全分辨率下 95 与原图体积基本持平")
    parser.add_argument("--max-side", type=int, default=0, help="图片最长边上限（px）；0 = 不缩放，保留原始分辨率")
    args = parser.parse_args()

    source = Path(args.source).expanduser().resolve()
    if not source.exists():
        raise SystemExit(f"找不到源图：{source}")

    fill = clamp(args.fill)
    border = clamp(args.border)

    payload, image = render_image(source, args.blur, args.gamma, args.saturate, args.quality, args.max_side)
    CSS_OUT.write_text(build_css(payload, fill, border, args), encoding="utf-8")

    image.save(PREVIEW, format="JPEG", quality=88)
    scrim_preview(image, DARK_BASE, fill).save(PREVIEW_DARK, format="JPEG", quality=88)

    print(f"源图           {source}")
    print(f"处理后         {len(payload) / 1024:.0f} KB  ({image.width}x{image.height})")
    print(f"样式表         {CSS_OUT.name}  {CSS_OUT.stat().st_size / 1024:.0f} KB")
    print(f"预览(原图)     {PREVIEW.name}")
    print(f"预览(深色)     {PREVIEW_DARK.name}   <- 近似最终观感")
    print(f"表面透明       {len(SURFACE_TOKENS)} 个 token @ alpha {fill}")
    print(f"边框加粗       {len(BORDER_OFFSETS)} 个 token @ alpha {border}")
    print(f"补边框         {len(SELECTOR_BORDER_NAMES)} 类表面")


if __name__ == "__main__":
    main()
