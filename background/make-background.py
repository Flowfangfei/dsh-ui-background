#!/usr/bin/env python3
"""生成 background.css —— 让桌面版 DSH 的界面表面透明、露出背景图，并用细边框区分面板。

用法示例：
    python make-background.py                            # 默认：面板留 10% 底色 + 边框
    python make-background.py --fill 0                   # 面板完全透明（亮区文字会更难读）
    python make-background.py --fill 0.18 --border 0.40  # 面板更实、边框更亮
    python make-background.py --source "D:/x/BG.jpg" --blur 0

已挂载插件时，改完刷新页面即可重读 CSS；首次挂载或卸载须重启 DSH。

--gamma 默认 0.70，会提升暗部；图片已足够明亮时可用 1.0 保留原色调。
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

# ── 输入框座位：把翻到输入框下面的正文挡掉 ──────────────────────────────────
# 应用本来就有「输入遮掩」：座位自己那层 linear-gradient（ConversationRoot 的
# .composerSeat，从透明渐变到 --dsw-alias-bg-base）。底色不透明时它挡住正文；
# 本插件把底色改成 rgba(base, --fill) 之后，正文就从这层下面透出来了，和输入框
# 里的文字叠在一起。
#
# 修法：给座位加一个铺满它的 ::before，把「背景图 + 座位自己的渐隐带 + 被图片
# 盖住的祖先底色」按原样重画一遍。图片是不透明 JPEG，正文被它挡住；而座位对
# 背景依旧是全透明的——因为它画出来的就是背景本身，不是另加的一层色。
#
# 为什么是硬切而不是渐隐：表面接近全透明时，想让正文渐隐就得让遮罩带透明度，
# 那样背景图会跟着一起淡掉。硬切落在座位自己的上边界，也就是应用原本开始渐隐
# 的那条线，边界位置和从前一致。
SEAT_TARGET = (
    "[data-conversation-content][data-content-phase='active'] [data-composer-seat]"
)
# 与应用 .composerSeat 的渐隐带同宽（figma 1205:27463 的 36px）。
SEAT_FADE_PX = 36
# 座位要补回几层祖先底色：见 CANVAS_REGIONS 的 "center" 一行（Windows 标题栏布局
# 的那一层差异收在 --dsh-ui-canvas-center 的定义里）。

# ── 输入框上方的停靠卡片：去掉毛玻璃 ────────────────────────────────────────
# 停靠卡片（todo / queue / goal）画的是 --dsw-specific-menu，并带
# `backdrop-filter: var(--dsw-menu-backdrop-filter)`——主题里是
# `blur(40px) saturate(150%)`。于是卡片盖住的背景图被糊成一片，什么都看不清。
#
# 卡片在座位里，背后就是第 5 段那层不透明背景图，正文已经被挡住了，不必再靠模糊
# 去糊掉文字。所以只关掉模糊，卡片自身的底色照旧（与输入卡片一致）。
#
# 为什么设变量而不是直接写 `backdrop-filter: none`：
#   · 毛玻璃画在元素上还是伪元素上，各卡片不一样（TodoPanel 画在元素上，
#     QueueDock 画在 .panel::before 上），变量靠继承一次盖住两种写法；
#   · 变量盖不掉「自己又重新声明了这个变量」的浮层，直接写 !important 会。
# 作用域只到停靠槽位的锚点：从输入框里弹出的菜单/浮层不在这个子树里，它们背后是
# 正文，必须留着模糊才读得清。
DOCK_SLOT = "conversation.input.dock"

# ── 浮层：让它们也挡住下层的文字 ────────────────────────────────────────────
# 第 5 段那个道理放大到所有「压在别的内容之上、自己画半透明底色」的表面：下拉菜单、
# 弹层、设置页、吸顶表头、通知条……底色都被本插件改成了 rgba(base, fill)，下层
# 的正文就透上来跟它们自己的字叠在一起。逐个补一层不透明的
# `[它自己的底色][区域底色][背景图]`。
#
# 事实来源：安装版 bundle 0.1.5-alpha.1 的全量 CSS 扫描（52 条候选 + MenuSurface 族）。
# 底色有三种写法，各对应一条规则形状：
#   · MenuSurface 的 `.material` 子元素 —— 所有走 primitives MenuSurface 的菜单/弹层
#     的唯一底色层（≥15 个插件复用，模型选择、命令面板、页签菜单都在内）；
#   · `:before` 材料层 —— 面板/菜单/栏的局部约定（queue dock、cordis 面板、血缘菜单、
#     目标栏、agent team 面板）；
#   · 元素自身 `background` —— 其余大多数。
#
# 选择器一律用类名结尾匹配，不受包哈希前缀变化影响；漏命中只会「少挡一层」，
# 也就是回到今天的样子，不会坏布局。
#
# 区域决定补回几层祖先底色（`--dsh-ui-occluder-*`）：菜单/吸顶条在会话区 → center；
# 侧栏里的菜单 → sidebar；中栏面板 → panel；模态里的居中面板背后压着遮罩 → modal；
# 全屏浮层自己盖住一切，用最轻的 frame 自己就自洽。
#
# 侧栏那条用 `:has(> [data-slot='sidebar'])` 定位侧栏列（结构选择器，不猜哈希类名）。
SIDEBAR_SCOPE = ":has(> [data-slot='sidebar'])"
# `:before` 材料层那 5 处写法完全一样，用 :is() 合成一条。
BEFORE_MATERIAL = ":is([class$='_panel'], [class$='_menu'], [class$='_bar']):before"
OCCLUDED_SURFACES = [
    # (选择器, 它自己的底色令牌, 区域, 备注)
    # 选择器不含 `html body` 前缀（emit 时补）；同一族要分区域时，靠 SIDEBAR_SCOPE 区分，
    # 否则两条规则选择器一模一样，后一条会把前一条整个盖掉。

    # —— MenuSurface 材料层：一次覆盖所有共享菜单 ——
    ("[class$='_material']", "--dsw-menu-surface-fill", "center",
     "共享菜单/弹层的材料层（MenuSurface 全家：模型选择、命令面板、页签菜单…）"),
    (f"{SIDEBAR_SCOPE} [class$='_material']", "--dsw-menu-surface-fill", "sidebar",
     "同上，挂在侧栏里的那些"),

    # —— `:before` 材料层的那一族 ——
    (BEFORE_MATERIAL, "--dsw-specific-menu", "center",
     "把底色画在 :before 上的面板/菜单/栏（queue dock、cordis 面板、血缘菜单、目标栏…）"),
    (f"{SIDEBAR_SCOPE} {BEFORE_MATERIAL}", "--dsw-specific-menu", "sidebar",
     "同上，挂在侧栏里的那些"),

    # —— 底色画在元素自身上的浮层 ——
    ("[class$='_menu']", "--dsw-specific-menu", "center", "下拉菜单（后台任务列表、日程菜单…）"),
    (f"{SIDEBAR_SCOPE} [class$='_menu']", "--dsw-specific-menu", "sidebar", "同上，挂在侧栏里的那些"),
    ("[class$='_panel']", "--dsw-specific-menu", "panel",
     "浮层面板：统计详情、上下文用量、日期选择、文档预览缩放条…"),

    # —— 模态/全屏浮层 ——
    ("[class$='_overlay'] [class$='_panel']", "--dsw-alias-bg-layer-2", "modal",
     "模态里的居中面板（设置页）：背后压着遮罩，要一并还原"),
    ("[class$='_dialog']", "--dsw-alias-bg-layer-2", "modal", "通用模态卡片"),
    ("[class$='_overlay']", "--dsw-alias-bg-base", "center",
     "全屏浮层（登录、引导、设置页那层）：补成不透明的背景，浮层里的面板因此和四周同色"),

    # —— 会话正文里的吸顶元素（都压在滚动的内容之上）——
    ("[class$='_bannerWrap']", "--dsw-alias-bg-base", "center", "代码块/终端的吸顶 banner"),
    ("[class$='_compactionButton']", "--dsw-alias-bg-base", "center", "上下文压缩摘要的吸顶按钮"),
    ("[data-disclosure-row]", "--dsw-alias-bg-base", "center", "推理行展开后的吸顶头"),
    ("[class$='_earlierHistory']", "--dsw-alias-bg-layer-2", "center", "轨迹视图的「更早历史」吸顶按钮"),
    ("[class$='_table'] th", "--dsw-specific-sidebar-fill", "center", "轨迹表格的吸顶表头"),
    ("[class$='_copyButton']", "--dsw-alias-markdown-code-block", "center", "终端块的吸顶复制按钮"),
    ("[class$='_dockScrim']", "--dsw-alias-bg-base", "center", "停靠面板拖拽时盖住底下的那层"),

    # —— 提示 ——
    ("[class$='_toast']", "--dsw-alias-toast-bg", "center", "通知条"),
    ("[class$='_registry']", "--dsw-alias-bg-layer-2", "panel", "插件管理器的注册源选择浮层"),
]

# ── 画布底色：每个区域折成一层 ──────────────────────────────────────────────
# 「补回被不透明图片盖住的祖先底色」这件事，只要求总量对，不要求层数对：n 层
# rgba(base, fill) 顺序叠加后等效于一层 alpha = 1-(1-fill)^n。折成一层有三个好处：
#   · 规则不必按平台分叉（Windows 标题栏布局多一层 .centerCol，差异收进变量定义里）；
#   · 同一区域内的背景变成一处常量，任何浮层都能用同一条遮挡配方；
#   · 遮挡层从「若干层」降到「一层」，少一层就少一次取整。
# 层数是从安装版 bundle 里数出来的（0.1.5-alpha.1）：
#   frame    只剩 AppFrame .frame 那一层 —— 顶栏、右栏空白、挂在整个 frame 上的浮层
#   panel    .frame + AppFrame .centerCol —— 中栏里没有会话根的面板
#   sidebar  .frame + AppFrame .sidebarCol
#   center   .frame + (Windows 才有 .centerCol) + ConversationRoot .root —— 会话区
# ⚠ DSH 升级后若某个祖先多/少一层底色，这里要跟着改；visual-check.py 会逐像素告警。
CANVAS_REGIONS = [
    # (名字, 层数, 说明)
    ("frame", 1, "AppFrame .frame 一层"),
    ("panel", 1, "AppFrame .frame + .centerCol（中栏无会话根）"),
    ("sidebar", 2, "AppFrame .frame + .sidebarCol"),
    ("center", 2, "AppFrame .frame + ConversationRoot .root（会话区）"),
]
# Windows 标题栏布局多给 .centerCol 一层底色（见 AppFrame.module.css）。
CANVAS_REGION_OVERRIDES = {
    "windows-titlebar": {"panel": 2, "center": 3},
}


def stacked_alpha(fill: float, layers: int) -> float:
    """n 层 rgba(base, fill) 顺序叠加后的等效 alpha。"""
    return 1 - (1 - fill) ** layers


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


def dock_defrost_block() -> str:
    """停靠卡片去毛玻璃：只覆盖那一个变量，靠继承同时命中元素与伪元素两种写法。"""
    return f"""\
html body [data-slot='{DOCK_SLOT}'] {{
  --dsw-menu-backdrop-filter: none !important;
}}"""


def canvas_vars_block(selector: str, base: tuple[int, int, int], fill: float,
                      overrides: dict[str, int] | None = None) -> str:
    """一个主题的画布底色变量：每个区域折成一层。"""
    lines = [
        f"  --dsh-ui-canvas-{name}: {rgba(base, stacked_alpha(fill, (overrides or {}).get(name, layers)))};"
        for name, layers, _ in CANVAS_REGIONS
    ]
    return f"{selector} {{\n" + "\n".join(lines) + "\n}"


def with_hidden_guard(selector: str) -> str:
    """给浮层选择器加两道保险，见 occluded_surface_rules 的说明。

    选择器可能以 `:before` 结尾，保险要加在**元素**那一段上，不能落到伪元素后面
    （`X:before:not(...)` 是无效选择器）。
    """
    pseudo = ''
    if selector.endswith(':before'):
        selector, pseudo = selector[:-len(':before')], ':before'
    return (f"{selector}:not([aria-hidden='true']):not([aria-hidden='true'] *)"
            f":not([data-sidebar-right-panel]){pseudo}")


def occluded_surface_rules() -> str:
    """每个浮层一条规则：它自己的底色一层 + 区域底色与背景图（`--dsh-ui-occluder-*`）。

    用 `background` 简写而不是只加 `background-image`：简写会把应用那条 `background`
    整体换掉，底色、附着、尺寸一次说清，不必逐条和它的长写声明比权重。

    每条选择器都会加上两道保险：

      `:not([aria-hidden='true'])` / `:not([aria-hidden='true'] *)`
          自己或祖先声明了「这块藏着」就别给它铺背景。右侧栏面板收起时正是这么标的
          （`aria-hidden` + 子元素 translateX/visibility，**容器自己的盒子还在、
          而且保留着宽度**）。少了这道保险，那条规则会把容器整个刷成不透明的背景，
          把主对话区右侧挡掉一半——2026-10 就是这么坏过一次的。

      `:not([data-sidebar-right-panel])`
          同一个面板的属性版保险：它的隐藏全靠子元素，光看类名结尾跟它分不开。
    """
    blocks = []
    for selector, fill, region, note in OCCLUDED_SURFACES:
        blocks.append(f"""\
/* {note} */
html body {with_hidden_guard(selector)} {{
  background: linear-gradient(var({fill}), var({fill})), var(--dsh-ui-occluder-{region}) !important;
  backdrop-filter: none !important;
}}""")
    return "\n\n".join(blocks)


def occluder_vars_block() -> str:
    """遮挡配方：区域底色一层 + 背景图一层。浮层在自己的 background 里引用它。

    与主题无关（底色是 `--dsh-ui-canvas-*`，图片是 `--dsh-ui-bg-image`），所以只需要
    一份；浮层规则写成 `background: <它自己的底色>, var(--dsh-ui-occluder-<区域>)`。
    """
    lines = [
        "  /* 图片那一层：fixed 附着的定位区是视口，于是与 <html> 上那张逐像素对齐。 */",
        "  --dsh-ui-cover: var(--dsh-ui-bg-image) center center / cover no-repeat fixed;",
    ]
    for name, _, note in CANVAS_REGIONS:
        lines.append(
            f"  /* {note} */\n"
            f"  --dsh-ui-occluder-{name}: "
            f"linear-gradient(var(--dsh-ui-canvas-{name}), var(--dsh-ui-canvas-{name})) 0 0 / auto no-repeat scroll, "
            f"var(--dsh-ui-cover);"
        )
    lines.append(
        "  /* 模态：面板背后还压着一层遮罩，要一并还原，否则面板会比周围亮一块。 */\n"
        "  --dsh-ui-occluder-modal: "
        "linear-gradient(var(--dsw-alias-bg-mask-1), var(--dsw-alias-bg-mask-1)) 0 0 / auto no-repeat scroll, "
        "var(--dsh-ui-occluder-center);"
    )
    return "html body {\n" + "\n".join(lines) + "\n}"


def seat_occlusion_block(prefix: str, base: tuple[int, int, int], fill: float) -> str:
    """生成座位的遮挡层：座位自己的渐隐带 → 折成一层的区域底色 → 背景图。

    两层叠放的顺序就是它们自上而下的绘制顺序：
      1. 渐隐带的副本。应用那层被不透明的图片盖住了，不补回来座位一带会比原来亮；
      2. `--dsh-ui-occluder-center`（会话区底色一层 + 背景图）。图片不透明，正文
         就是被它挡住的。

    `prefix` 只区分浅/深主题：Windows 标题栏布局多出来的那一层已经收进
    `--dsh-ui-canvas-center` 的定义里了，这里不必再分叉。
    """
    fade = (f"linear-gradient(180deg, {rgba(base, 0)} 0px, {rgba(base, fill)} {SEAT_FADE_PX}px) "
            f"0 0 / auto no-repeat scroll")
    return f"""\
{prefix} {SEAT_TARGET}::before {{
  content: '';
  /* 绝对定位的伪元素不参与座位内的 flex 布局，只铺满座位。 */
  position: absolute;
  inset: 0;
  /* 座位在应用里是 position: sticky/absolute + z-index: 7，本身即成层叠上下文，
     所以负层级只会沉到座位底色之上、输入卡片之下，不会跑到滚动区后面去。 */
  z-index: -1;
  pointer-events: none;
  background: {fade}, var(--dsh-ui-occluder-center);
}}"""


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

   七段结构：
   1. 背景图铺在 <html> 上，同时抽成 --dsh-ui-bg-image 供第 5 段复用；
      <body> 底色置透明。
   2. 把 {len(SURFACE_TOKENS)} 个表面填充 token 改成半透明，黑色块就会透出背景图。
      刻意不含 bg-mask-*（弹窗遮罩）、button-primary/info/contrast-fill（强调按钮）、
      interactive-bg-*（悬停反馈）、bg-skeleton（加载提示）、label-/state-/link/brand/scrollbar。
   3. 加粗边框 token，让相邻面板仍能区分。l4 同时驱动 --dsw-elevation-stroke-color，
      因此那些 border:0 + 描边的浮层也一并覆盖。
   4. 给 {len(SELECTOR_BORDER_NAMES)} 类本来没有边框的表面补一条，用 [class$='_名字']
      结尾匹配，不受包哈希前缀变化影响。
   5. 输入框座位补一层遮挡：把翻到输入框下面的正文挡掉，而座位对背景依旧全透明。
   6. 输入框上方的停靠卡片去掉毛玻璃：它背后已经是第 5 段那层不透明背景图，
      再模糊一次只会让背景图看不清。

   选择器用 `html body` 提高权重以压过运行时注入的样式表，再加 !important 兜底。
   ========================================================================== */

/* ── 1. 背景图 ─────────────────────────────────────────────────────────── */
html {{
  /* 抽成自定义属性：第 5 段的座位要用同一张图。直接写两遍 base64 会让这个
     内联进每次 index.html 的样式表翻倍。 */
  --dsh-ui-bg-image: url("data:image/jpeg;base64,{encoded}");
  background-color: #151517;
  background-image: var(--dsh-ui-bg-image);
  background-position: {args.position};
  background-repeat: no-repeat;
  background-size: cover;
  background-attachment: fixed;
}}

/* html 上给了图，body 必须透明，否则启动阶段写下的不透明底色会盖住它。 */
html body {{
  background-color: transparent !important;
}}

{occluder_vars_block()}

/* ── 2/3. 浅色主题：表面透明 + 边框加粗 ────────────────────────────────── */
{surface_block("html body", LIGHT_BASE, fill)}

{border_block("html body", (0, 0, 0), border)}

/* 浅色主题的画布底色（每区域折成一层，层数见 CANVAS_REGIONS） */
{canvas_vars_block("html body", LIGHT_BASE, fill)}

/* ── 2/3. 深色主题：表面透明 + 边框加粗 ────────────────────────────────── */
{surface_block("html body[data-ds-dark-theme]", DARK_BASE, fill)}

{border_block("html body[data-ds-dark-theme]", (255, 255, 255), border)}

/* 深色主题的画布底色 */
{canvas_vars_block("html body[data-ds-dark-theme]", DARK_BASE, fill)}

/* ── 画布底色的平台覆盖 ─────────────────────────────────────────────────
   Windows 标题栏布局多给 .centerCol 一层底色。与上面两条主题规则同权重，
   所以必须放在它们后面，靠顺序取胜。 */
{canvas_vars_block("html[data-windows-titlebar] body", LIGHT_BASE, fill, CANVAS_REGION_OVERRIDES["windows-titlebar"])}

{canvas_vars_block("html[data-windows-titlebar] body[data-ds-dark-theme]", DARK_BASE, fill, CANVAS_REGION_OVERRIDES["windows-titlebar"])}

/* ── 4. 给本来没有边框的表面补边框 ─────────────────────────────────────── */
{selector_border_block("html body", (0, 0, 0), border)}

{selector_border_block("html body[data-ds-dark-theme]", (255, 255, 255), border)}

/* ── 5. 输入框座位：挡掉翻到输入框下面的正文 ─────────────────────────────
   座位那一层必须与背景逐像素一致，所以浅/深各来一份。Windows 标题栏布局多出来
   的那一层已经收进 --dsh-ui-canvas-center 的定义里，这里不再分叉。 */
{seat_occlusion_block("html body", LIGHT_BASE, fill)}

{seat_occlusion_block("html body[data-ds-dark-theme]", DARK_BASE, fill)}

/* ── 6. 输入框上方的停靠卡片：去掉毛玻璃 ─────────────────────────────────
   卡片画的是 --dsw-specific-menu，并带 backdrop-filter:
   var(--dsw-menu-backdrop-filter)（主题里是 blur(40px) saturate(150%)）。
   它背后已经是第 5 段那层不透明背景图，正文早被挡住，模糊只会让背景图看不清。
   只覆盖这一个变量，靠继承同时命中「画在元素上」与「画在伪元素上」两种写法；
   作用域只到停靠槽位的锚点，从输入框弹出的菜单/浮层不受影响。详见 DOCK_SLOT。 */
{dock_defrost_block()}

/* ── 7. 浮层：让它们也挡住下层的文字 ─────────────────────────────────────
   菜单、弹层、设置页、吸顶表头、通知条……凡是「压在别的内容之上、自己画半透明
   底色」的表面，都把底色补成不透明的一层背景图；对背景依旧透明，对下层文字不透明。
   这是第 5 段同一个道理，只是逐个表面来。清单与区域划分见 OCCLUDED_SURFACES。 */
{occluded_surface_rules()}
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
    # newline="\n" 是必须的：默认会按平台翻译成 CRLF，于是仓库里那份（.gitattributes
    # 声明了 LF）每次重新生成都显示成「整个文件都被改了」。
    CSS_OUT.write_text(build_css(payload, fill, border, args), encoding="utf-8", newline="\n")

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
    print(f"画布底色       {len(CANVAS_REGIONS)} 个区域各折成一层，"
          f"另有 {len(CANVAS_REGION_OVERRIDES['windows-titlebar'])} 项 Windows 标题栏覆盖")
    print(f"输入框遮挡     2 条规则（浅/深），用 --dsh-ui-occluder-center")
    print(f"停靠卡片去毛玻璃 1 条规则（--dsw-menu-backdrop-filter: none）")
    print(f"浮层挡文字     {len(OCCLUDED_SURFACES)} 条规则（"
          f"{len({s for s, *_ in OCCLUDED_SURFACES})} 个选择器，按区域补回底色）")


if __name__ == "__main__":
    main()
