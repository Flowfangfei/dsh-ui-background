#!/usr/bin/env python3
"""视觉验证：composer 这一带的三件事。

  1. 翻到输入框下面的正文有没有消失；
  2. 输入框座位那一带的背景观感有没有被改动；
  3. 上方的停靠卡片还糊不糊背景（应用给它上了 backdrop-filter: blur(40px)）。

做法（无头 Edge/Chrome + 逐像素比对，不启动 DSH、不需要启动令牌）：

  1. 取一份**改前**的 background.css 当基准：优先用 git 里的基准提交
     （`baseline-pre-composer-occlusion`），取不到时由当前样式表切掉第 5～7 段合成 ——
     后者让它在**不入库生成样式表**的公开仓库里也能直接跑。
  2. 用 `verify/visual-fixture.html` 复刻安装版里 composer 那条 DOM 链，渲染若干
     张截图，每次只改一个变量：用哪份样式表、哪一块不画、滚到哪里。
  3. 逐像素比、并按矩形量「锐度」，跑十一条断言：

     有牙   改前：正文画 / 不画            必须差很多   —— 否则验证台看不见这个问题
     精确   改后：正文画 / 不画            必须落在抗锯齿容差内 —— 正文确实被挡住了
     精确   改后：滚动 0 / 滚动 900        必须落在抗锯齿容差内 —— 座位画的是背景，不跟正文滚
     容差   改后(全画) / 改前(正文不画)    必须落在重采样容差内 —— 背景观感没变
                                             （停靠卡片那一行除外，它由下面两条负责）
     有牙   改前：停靠卡片遮住的背景        必须明显发糊   —— 否则第二个问题无从验证
     比值   改后：停靠卡片遮住的背景        锐度必须回到裸背景的水平 —— 毛玻璃没了
     有牙   改前：浮层矩形里有没有透字      必须看得见透字
     精确   改后：浮层矩形里有没有透字      落在抗锯齿容差内 —— 三类浮层都挡住了下层文字

  遮挡与滚动比对使用 AA_TOLERANCE；背景观感用 RESAMPLE_PEAK / RESAMPLE_LOUD，
  毛玻璃用锐度比值。十一条断言的完整清单见 ../docs/testing.md。

为什么基准要「改前 CSS + 正文不画」：拿掉改动的那份样式表，那一带就恢复成
「背景本身」，这正是本次改动唯一的硬约束——不能顺手改掉背景观感。

用法：
    python verify/visual-check.py
    python verify/visual-check.py --prev HEAD~1
    python verify/visual-check.py --browser "C:/Program Files/Google/Chrome/Application/chrome.exe"
"""
from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageChops

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
TMP = HERE / ".tmp"
FIXTURE = HERE / "visual-fixture.html"
FIXTURE_CSS = HERE / "visual-fixture.css"
LIVE_CSS = ROOT / "background" / "background.css"

# 基准样式表必须是「改前」的：它带着 bug，也带着本次改动要保住的原始观感。
DEFAULT_PREV_REF = "baseline-pre-composer-occlusion"
# 「这是改后版本」的标记：座位遮挡层只在第 5 段之后才有。
SEAT_MARKER = "[data-composer-seat]::before"

# 右侧留出的滚动条宽度：座位不覆盖它，两边的原生滚动条渲染也可能有细微差别。
SCROLLBAR_GUARD = 20
# 量停靠卡片时从卡片矩形内缩这么多，避开圆角与那圈 0.5px 描边。
DOCK_INSET = 8

# 座位那一层用 background-attachment: fixed 重画背景图，Chromium 会对它单独重采样
# 一次，于是它和根元素自己画的那张相差最多 12/255（实测峰值 8，通道差 >4 的像素占
# 0.17%，放大 8 倍看是全黑）。这不是算术错误：层数或 alpha 错了会差 20 以上，所以
# 这个容差仍然能挡住「祖先底色补错层数」这类回归。
#
# 试过两条能逐像素相同的路，都被否掉：
#   · 视口大小的 fixed 元素 + mask 限制到这一带 —— 确实逐像素相同，但它的横向范围
#     是整个视口，会在座位那一带把侧栏底部也刷成「中栏的底色」，即侧栏多一层 0.10；
#   · 座位大小的盒子 + 手算 cover 几何 —— 更差（峰值 22），Chromium 按盒子的尺寸
#     重新光栅化背景，盒子一小，采样就和根元素对不上了。
RESAMPLE_PEAK = 12
RESAMPLE_LOUD = 0.001   # 通道差 > 8 的像素占比上限
LEAK_LOUD = 0.005       # 证明验证台看得见漏字的下限

# 停靠卡片的毛玻璃（backdrop-filter: blur(40px) saturate(150%)）会把卡片盖住的背景
# 压成一片糊。判据用「锐度比值」而不是绝对阈值：卡片那一块矩形里的平均横向亮度
# 梯度，除以同一块矩形上「卡片不画」时的裸背景锐度。
#   只加一层 0.10 底色时，锐度按 0.9 缩放 → 实测约 0.92；
#   还带着 blur(40px) 时，实测约 0.02。
# 0.6 与 0.3 之间留了很宽的余量，也不会被照片本身的内容差异干扰。
FROST_SHARP_MIN = 0.6   # 改后必须达到裸背景锐度的这个比例
FROST_SHARP_MAX = 0.3   # 改前必须低于这个比例，才证明验证台看得见毛玻璃

# 「逐像素相同」这类断言实际比的是**两次独立渲染**，所以只能要求落在噪声内：
# 文字抗锯齿会在 subpixel 与 grayscale 之间跳，背景越饱和越明显（实测占位图上峰值
# 到过 3）。要抓的问题都是 20 以上的差别（漏字 100+、给容器铺背景 37），所以
# 8 这个门限既压得住噪声，又不会把问题放过去。换背景图后若这项开始抖，先看是不是
# 抗锯齿：把比对面里的文字一块块藏掉（?hide=…），抖动就会消失。
AA_TOLERANCE = 8
# 「有牙」那几条的下限：改前的漏字必须至少差这么多，否则说明验证台看不见问题。
LEAK_PEAK = 15

BROWSERS = (
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
)

failures: list[str] = []


def check(ok: bool, label: str, detail: str = "") -> None:
    print(f"{'PASS' if ok else 'FAIL'}  {label}{' — ' + detail if detail else ''}")
    if not ok:
        failures.append(label)


def fixture_px(name: str) -> int:
    """读验证台样式表里的一个钉值，避免在两处各写一个数。"""
    match = re.search(rf"{name}:\s*(\d+)px", FIXTURE_CSS.read_text(encoding="utf-8"))
    if match is None:
        raise SystemExit(f"{FIXTURE_CSS} 里找不到 {name}")
    return int(match.group(1))


def strip_guards(css: str) -> str:
    """把第 7 段那两道保险去掉，做自检用。

    实测：去掉之后，右侧栏面板（容器自己不画底色、靠隐藏子元素收起）会被铺上一层
    不透明背景，把主对话区右侧整块盖掉 —— 那正是要防的回归。带上保险时这一块与
    「面板不画」逐像素相同。
    """
    return (css
            .replace(":not([aria-hidden='true']):not([aria-hidden='true'] *)", "")
            .replace(":not([data-sidebar-right-panel])", ""))


def floating_surfaces(width: int, height: int) -> list[tuple[str, tuple[int, int, int, int]]]:
    """验证台里三类浮层的矩形（左, 上, 右, 下），坐标都从钉值推出来。

    它们分别对应应用里的三种底色写法，第 7 段各有一条规则：
      · 吸顶条   —— 元素自身画底色
      · 菜单     —— 底色画在 .material 子元素上（MenuSurface 家族）
      · 模态面板 —— 全屏浮层 + 遮罩 + 居中面板
    """
    banner_top = fixture_px("--fixture-banner-top")   # 同时是会话内容区的顶（frame 的 padding-top）
    banner_h = fixture_px("--fixture-banner-height")
    menu_left = fixture_px("--fixture-menu-left")
    menu_top = fixture_px("--fixture-menu-top")
    menu_w = fixture_px("--fixture-menu-w")
    menu_h = fixture_px("--fixture-menu-h")
    modal_w = fixture_px("--fixture-modal-w")
    modal_h = fixture_px("--fixture-modal-h")
    modal_region_h = fixture_px("--fixture-modal-region-h")
    right = width - SCROLLBAR_GUARD
    # 模态面板在浮层里居中（.floatOverlay 是 flex 居中，浮层只盖上半屏）
    modal_left = (width - modal_w) // 2
    modal_top = (modal_region_h - modal_h) // 2
    return [
        ("吸顶条（元素自身底色）", (0, banner_top, right, banner_top + banner_h)),
        ("菜单（.material 子元素底色）", (menu_left, banner_top + menu_top,
                                          menu_left + menu_w, banner_top + menu_top + menu_h)),
        ("模态面板（浮层+遮罩+居中面板）", (modal_left, modal_top,
                                            modal_left + modal_w, modal_top + modal_h)),
    ]


def export_previous_css(ref: str) -> Path:
    """取一份「改前」的 background.css 当视觉基准。

    两条路，优先第一条：

      1. `git show <ref>:background/background.css` —— 本地部署版走这条
         （有 `baseline-pre-composer-occlusion` 那个基准标签）。
      2. 拿不到基准提交时，**从当前这份里把第 5～7 段切掉** —— 那几段全是本次加出来
         的遮挡层，切掉就是改前那一版。公开仓库不入库生成的样式表，也就没有基准提交
         （`background.css` 在 .gitignore 里），这条路让它照样能跑。
    """
    target = TMP / "prev-background.css"
    blob = subprocess.run(
        ["git", "show", f"{ref}:background/background.css"],
        cwd=ROOT, capture_output=True, check=False,
    )
    if blob.returncode == 0:
        target.write_bytes(blob.stdout)
        if SEAT_MARKER in target.read_text(encoding="utf-8"):
            raise SystemExit(
                f"{ref} 里的 background.css 已经含 {SEAT_MARKER}，它是改后版本，不能当基准。\n"
                f"请用 --prev 指向改动之前的提交（例如 {DEFAULT_PREV_REF}）。"
            )
        print(f"基准样式表    {ref}:background/background.css → {target.relative_to(ROOT)}")
        return target
    # 没有 git 基准：从当前这份切掉第 5～7 段合成一份
    live = LIVE_CSS.read_text(encoding="utf-8")
    marker = live.find("/* ── 5.")
    if marker < 0:
        raise SystemExit(
            f"取不到 {ref}:background/background.css，当前样式表里也找不到第 5 段，"
            f"没法合成基准。请先用 --prev 指定一份改前的 background.css 所在提交。"
        )
    target.write_text(live[:marker], encoding="utf-8", newline="\n")
    print(f"基准样式表    没有 {ref}:background/background.css → 由当前样式表切掉第 5～7 段合成"
          f"（{target.relative_to(ROOT)}）")
    return target


def pick_browser(explicit: str | None) -> str:
    if explicit:
        if not Path(explicit).exists():
            raise SystemExit(f"找不到浏览器：{explicit}")
        return explicit
    for candidate in BROWSERS:
        if Path(candidate).exists():
            return candidate
    raise SystemExit("没找到 Edge 或 Chrome，无法截图；用 --browser 指定可执行文件。")


def shoot(browser: str, css_rel: str, hide: str, scroll: int, out: Path,
          width: int, height: int, profile: Path) -> None:
    """渲染一张截图。"""
    from urllib.parse import quote

    url = f"{FIXTURE.as_uri()}?css={quote(css_rel)}&hide={quote(hide)}&scroll={scroll}"
    command = [
        browser,
        "--headless=new",
        "--disable-gpu",
        "--no-first-run",
        "--no-default-browser-check",
        "--allow-file-access-from-files",
        "--hide-crash-restore-bubble",
        "--force-device-scale-factor=1",
        "--run-all-compositor-stages-before-draw",
        "--virtual-time-budget=5000",
        f"--user-data-dir={profile}",
        f"--window-size={width},{height}",
        f"--screenshot={out}",
        url,
    ]
    result = subprocess.run(command, capture_output=True)
    if not out.exists():
        raise SystemExit(f"截图失败：{out}\n{result.stderr.decode('utf-8', 'replace')[-2000:]}")


def load(png: Path, width: int, height: int) -> Image.Image:
    image = Image.open(png).convert("RGB")
    if image.size != (width, height):
        raise SystemExit(
            f"{png.name} 尺寸是 {image.size}，与期望的 {(width, height)} 不符；"
            f"截图可能被系统缩放影响，检查 --force-device-scale-factor。"
        )
    return image


def band(page: Image.Image, width: int, height: int, top: int) -> Image.Image:
    """裁出输入框座位覆盖的那一带。"""
    return page.crop((0, top, width - SCROLLBAR_GUARD, height))


def difference(left: Image.Image, right: Image.Image,
               exclude: tuple[int, int, int, int] | None = None) -> tuple[int, float]:
    """返回 (最大通道差, 通道差 > 8 的像素占比)。

    `exclude` 是「不比」的矩形（相对传进来的图），只在第 4 条断言里用：那一条要
    证明「除了停靠卡片，别的都没变」，而卡片自己的渲染正是这次有意改掉的东西。
    """
    delta = np.abs(
        np.asarray(left).astype(int) - np.asarray(right).astype(int)
    ).max(axis=2)
    if exclude is not None:
        x0, y0, x1, y1 = exclude
        delta[y0:y1, x0:x1] = 0
    return int(delta.max()), float((delta > 8).mean())


def sharpness(image: Image.Image) -> float:
    """平均横向亮度梯度：一上模糊，这个值就塌下去。"""
    grey = np.asarray(image.convert("L")).astype(float)
    return float(np.abs(np.diff(grey, axis=1)).mean())


def main() -> None:
    parser = argparse.ArgumentParser(description="composer 遮挡与毛玻璃的视觉验证")
    parser.add_argument("--prev", default=DEFAULT_PREV_REF,
                        help="改前的 git 引用；取不到时自动由当前样式表切掉第 5～7 段合成")
    parser.add_argument("--browser", default=None, help="浏览器可执行文件，默认自动找 Edge/Chrome")
    parser.add_argument("--width", type=int, default=1000)
    parser.add_argument("--height", type=int, default=800)
    parser.add_argument("--keep-profile", action="store_true", help="保留浏览器临时配置目录")
    args = parser.parse_args()

    TMP.mkdir(exist_ok=True)
    browser = pick_browser(args.browser)
    seat_height = fixture_px("--fixture-seat-height")
    dock_height = fixture_px("--fixture-dock-height")
    seat_top = args.height - seat_height
    dock_box = (
        DOCK_INSET,
        seat_top + DOCK_INSET,
        args.width - SCROLLBAR_GUARD - DOCK_INSET,
        seat_top + dock_height - DOCK_INSET,
    )
    print(f"浏览器        {browser}")
    print(f"视口          {args.width}x{args.height}")
    print(f"座位          {seat_height}px → 比对 y ∈ [{seat_top}, {args.height})")
    print(f"停靠卡片      {dock_height}px → 量 x ∈ [{dock_box[0]}, {dock_box[2]}) "
          f"y ∈ [{dock_box[1]}, {dock_box[3]})（内缩 {DOCK_INSET}px 避开圆角与描边）")
    print()

    previous = export_previous_css(args.prev)
    print()

    # 验证台在 verify/ 下，所以 css 参数是相对 verify/ 的路径。
    current_rel = "../background/background.css"
    previous_rel = f".tmp/{previous.name}"
    profile = TMP / "browser-profile"

    # 去掉保险的变体，用来给「关掉的右侧栏面板」那条断言做自检（见 strip_guards）。
    noguard = TMP / "noguard.css"
    noguard.write_text(strip_guards(LIVE_CSS.read_text(encoding="utf-8")), encoding="utf-8")
    noguard_rel = f".tmp/{noguard.name}"

    scenarios = [
        ("before-ghost", previous_rel, "transcript", 900, "改前 CSS + 正文不画（基准画面）"),
        ("before-visible", previous_rel, "", 900, "改前 CSS + 全画（应当漏字 + 卡片发糊）"),
        ("after-ghost", current_rel, "transcript", 900, "改后 CSS + 正文不画（对照）"),
        ("after-visible-0", current_rel, "", 0, "改后 CSS + 全画（滚动到顶）"),
        ("after-visible-900", current_rel, "", 900, "改后 CSS + 全画（滚动 900）"),
        ("after-nodock", current_rel, "transcript,dock", 900, "改后 CSS + 停靠卡片不画（裸背景）"),
        ("after-docktext", current_rel, "transcript,docktext", 900, "改后 CSS + 卡片文字不画"),
        ("before-docktext", previous_rel, "transcript,docktext", 900, "改前 CSS + 卡片文字不画"),
        ("after-closedhidden", current_rel, "transcript,closedpanel", 900,
         "改后 CSS + 关掉的右侧栏面板也不画（与上一张比它那块矩形）"),
        ("noguard-visible", noguard_rel, "transcript", 900, "去掉保险的 CSS + 面板照画（自检）"),
        ("noguard-hidden", noguard_rel, "transcript,closedpanel", 900, "去掉保险的 CSS + 面板不画（自检）"),
    ]
    # 会动的那两块文字一律不画：它们压在同一张照片的饱和区域上时，字体抗锯齿会在两次
    # 渲染之间跳（同一组参数跑两遍，字形像素峰值就能差 132；换成占位图后，停靠卡片
    # 那行字也会跳），而矩形里其余像素是稳的。藏掉之后，比对面里只剩「表面遮住的
    # 背景」+ 正文，比较才有意义。换背景图后若某条断言开始抖，先往这里加一块。
    scenarios = [(name, css, f"{hide},surfacetext,docktext".strip(','), scroll, note)
                 for name, css, hide, scroll, note in scenarios]

    pages: dict[str, Image.Image] = {}
    for name, css_rel, hide, scroll, note in scenarios:
        out = TMP / f"{name}.png"
        if out.exists():
            out.unlink()
        shoot(browser, css_rel, hide, scroll, out, args.width, args.height, profile)
        pages[name] = load(out, args.width, args.height)
        print(f"已截图        {name:<18} {note}")

    for name, page in pages.items():
        band(page, args.width, args.height, seat_top).save(TMP / f"band-{name}.png")

    print()

    # 有牙：验证台必须先证明自己看得见改前的漏字，否则后面几条「相同」毫无意义。
    peak, loud = difference(
        band(pages["before-ghost"], args.width, args.height, seat_top),
        band(pages["before-visible"], args.width, args.height, seat_top),
    )
    check(loud > LEAK_LOUD, "验证台看得见改前的漏字（改前：正文不画 vs 全画）",
          f"最大通道差 {peak}，明显不同像素 {loud:.2%}")

    # 精确：正文画与不画，座位那一带必须一模一样——正文确实没露出来。
    peak, loud = difference(
        band(pages["after-ghost"], args.width, args.height, seat_top),
        band(pages["after-visible-900"], args.width, args.height, seat_top),
    )
    check(peak <= AA_TOLERANCE, "正文被完全挡住（改后：正文不画 vs 全画只在抗锯齿噪声内）",
          f"最大通道差 {peak}（上限 {AA_TOLERANCE}），明显不同像素 {loud:.2%}")

    # 精确：与滚动位置无关——座位画的是背景本身，不是跟着正文滚的一块。
    peak, loud = difference(
        band(pages["after-visible-0"], args.width, args.height, seat_top),
        band(pages["after-visible-900"], args.width, args.height, seat_top),
    )
    check(peak <= AA_TOLERANCE, "座位那一带不随滚动变化（改后：滚动 0 vs 900）",
          f"最大通道差 {peak}（上限 {AA_TOLERANCE}），明显不同像素 {loud:.2%}")

    # 容差：与改前的背景观感一致。停靠卡片那一行整行不比——它的渲染正是这次有意
    # 改掉的东西（去毛玻璃），由下面两条锐度断言单独负责。同一行以外的每一处，
    # 包括输入卡片、栈间距、座位两侧，都必须和改前一模一样。
    peak, loud = difference(
        band(pages["before-ghost"], args.width, args.height, seat_top),
        band(pages["after-visible-900"], args.width, args.height, seat_top),
        exclude=(0, 0, args.width, dock_height + 4),
    )
    check(peak <= RESAMPLE_PEAK and loud <= RESAMPLE_LOUD,
          "背景观感与改前一致（容差内，停靠卡片那一行除外）",
          f"最大通道差 {peak}（上限 {RESAMPLE_PEAK}），明显不同像素 {loud:.2%}（上限 {RESAMPLE_LOUD:.1%}）")

    # 停靠卡片的毛玻璃：同一块矩形上量锐度比值。
    bare = sharpness(pages["after-nodock"].crop(dock_box))
    frosted = sharpness(pages["before-docktext"].crop(dock_box))
    defrosted = sharpness(pages["after-docktext"].crop(dock_box))
    check(bare > 1.0, "停靠卡片那块矩形上有可测的细节（裸背景锐度）", f"锐度 {bare:.2f}")
    check(frosted / bare <= FROST_SHARP_MAX,
          "验证台看得见改前停靠卡片的毛玻璃",
          f"锐度 {frosted:.2f} / 裸背景 {bare:.2f} = {frosted / bare:.3f}（上限 {FROST_SHARP_MAX}）")
    check(defrosted / bare >= FROST_SHARP_MIN,
          "改后停靠卡片不再糊背景（毛玻璃已去掉）",
          f"锐度 {defrosted:.2f} / 裸背景 {bare:.2f} = {defrosted / bare:.3f}（下限 {FROST_SHARP_MIN}）")

    # 浮层：三类写法各一个代表，比对「正文画 / 不画」时浮层矩形里的像素。
    # 一样 → 下层文字被挡住了；不一样 → 字透上来了。这条是精确断言，不给容差。
    surfaces = floating_surfaces(args.width, args.height)
    teeth = [
        (name, difference(pages["before-visible"].crop(box), pages["before-ghost"].crop(box))[0])
        for name, box in surfaces
    ]
    leaks = [
        (name, difference(pages["after-visible-900"].crop(box), pages["after-ghost"].crop(box))[0])
        for name, box in surfaces
    ]
    check(all(peak >= LEAK_PEAK for _, peak in teeth),
          "验证台看得见改前浮层下面的透字（改前：正文画 vs 不画）",
          '；'.join(f"{name} 峰值 {peak}" for name, peak in teeth))
    check(all(peak <= AA_TOLERANCE for _, peak in leaks),
          "改后浮层挡住了下层文字（只在抗锯齿噪声内）",
          '；'.join(f"{name} 峰值 {peak}" for name, peak in leaks))

    # 反向断言：关掉的右侧栏面板**不能**变成不透明块。
    # 它是「容器自己不画底色、靠隐藏子元素收起、盒子还保留着宽度」的写法（安装版
    # 0.1.5 的右侧栏面板就是这样）。按类名结尾匹配的第 7 段一不小心就会给它铺一层
    # 背景，把主对话区右侧整块盖掉。判据：它照画与不画，两张图在它矩形里必须一模一样。
    closed = (args.width - fixture_px("--fixture-closed-panel-w"), fixture_px("--fixture-banner-top"),
              args.width - SCROLLBAR_GUARD, args.height)
    peak, _ = difference(pages["after-visible-900"].crop(closed),
                         pages["after-closedhidden"].crop(closed))
    check(peak <= AA_TOLERANCE, "关掉的右侧栏面板没有盖住主对话区（照画与不画只在噪声内）",
          f"矩形 {closed}，峰值 {peak}（上限 {AA_TOLERANCE}）")
    # 自检：把两道保险去掉，同一块矩形必须被盖住 —— 证明那两道保险是吃劲的，
    # 而不是这条断言恰好测不出问题。
    peak, _ = difference(pages["noguard-visible"].crop(closed),
                         pages["noguard-hidden"].crop(closed))
    check(peak >= LEAK_PEAK, "去掉保险后那塊确实会被盖住（证明保险吃劲）",
          f"峰值 {peak}（要 ≥{LEAK_PEAK}）")

    # 差分图放大 8 倍，方便人眼复核
    for name in ("before-visible", "after-visible-900"):
        amplified = ImageChops.difference(
            band(pages["before-ghost"], args.width, args.height, seat_top),
            band(pages[name], args.width, args.height, seat_top),
        ).point(lambda value: min(255, value * 8))
        amplified.save(TMP / f"diff-{name}.png")
    pages["after-nodock"].crop(dock_box).save(TMP / "dock-after-nodock.png")
    pages["before-docktext"].crop(dock_box).save(TMP / "dock-before-docktext.png")
    pages["after-docktext"].crop(dock_box).save(TMP / "dock-after-docktext.png")

    print()
    print(f"截图与差分图  {TMP}")
    print("  band-*.png                座位那一带（改前漏字 / 改后干净）")
    print("  dock-after-nodock.png     停靠卡片那块矩形上的裸背景（锐度基准）")
    print("  dock-before-docktext.png  改前：被毛玻璃糊过")
    print("  dock-after-docktext.png   改后：清晰")
    print("  diff-*.png                与基准的差分，放大 8 倍")

    if not args.keep_profile:
        shutil.rmtree(profile, ignore_errors=True)

    print()
    print("全部通过" if not failures else f"失败 {len(failures)} 项: {', '.join(failures)}")
    sys.exit(0 if not failures else 1)


if __name__ == "__main__":
    main()
