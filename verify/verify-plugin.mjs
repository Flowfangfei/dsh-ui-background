/**
 * 离线自检：模拟 Cordis 宿主，验证插件与生成出来的样式表。
 *
 * 不启动 DSH，也不访问网络。所有路径都相对本仓库解析，因此可以在任何机器上运行。
 * 运行前请先生成样式表：
 *     python background/make-background.py --source background/placeholder.jpg
 *
 * 用法：node verify/verify-plugin.mjs
 */
import { existsSync, readFileSync, renameSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'

const ROOT = dirname(dirname(fileURLToPath(import.meta.url)))
const PLUGIN = join(ROOT, 'background', 'plugin.mjs')
const GENERATOR = join(ROOT, 'background', 'make-background.py')
const CSS_PATH = join(ROOT, 'background', 'background.css')

const failures = []
const check = (ok, label, detail = '') => {
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${label}${detail ? ` — ${detail}` : ''}`)
  if (!ok) failures.push(label)
}

if (!existsSync(CSS_PATH)) {
  console.error(`找不到 ${CSS_PATH}\n请先生成样式表：\n  python background/make-background.py --source background/placeholder.jpg`)
  process.exit(1)
}

// ── 从生成器解析期望值，避免在 JS 里重复维护一份清单（重复必然漂移）──────────
const python = readFileSync(GENERATOR, 'utf8')

/** 抓取 `名字 = [ ... ]` 之间的内容。 */
function pyBlock(name) {
  const match = new RegExp(`${name}\\s*=\\s*\\[([\\s\\S]*?)\\n\\]`).exec(python)
  if (!match) throw new Error(`无法从生成器解析 ${name}`)
  return match[1]
}

const SURFACE_TOKENS = [...pyBlock('SURFACE_TOKENS').matchAll(/"(--dsw-[a-z0-9-]+)"/g)].map(m => m[1])
const SELECTOR_NAMES = [...pyBlock('SELECTOR_BORDER_NAMES').matchAll(/"([A-Za-z0-9]+)"/g)].map(m => m[1])
const BORDER_TOKENS = [...pyBlock('BORDER_OFFSETS').matchAll(/\("(--dsw-[a-z0-9-]+)"/g)].map(m => m[1])

check(SURFACE_TOKENS.length >= 30, '从生成器解析出表面 token 清单', `${SURFACE_TOKENS.length} 个`)
check(SELECTOR_NAMES.length >= 10, '从生成器解析出补边框类名清单', `${SELECTOR_NAMES.length} 个`)
check(BORDER_TOKENS.length === 6, '从生成器解析出边框 token 清单', `${BORDER_TOKENS.length} 个`)

// ── 插件契约 ────────────────────────────────────────────────────────────────
const mod = await import(pathToFileURL(PLUGIN).href)
check(typeof mod.apply === 'function', '插件导出 apply()')
check(mod.name === 'custom-ui-background', '插件名正确', String(mod.name))

let listener
const warnings = []
const ctx = {
  on(event, handler) {
    if (event !== 'webserver/index-inject') throw new Error(`注册了意外事件 ${event}`)
    listener = handler
  },
  logger: { warn: message => warnings.push(message) },
}
mod.apply(ctx)
check(typeof listener === 'function', '注册 webserver/index-inject 监听')

const table = []
listener(table)
check(table.length === 1, '推送了 1 行注入', `实际 ${table.length}`)

const row = table[0]
check(row?.kind === 'style', "行类型是 'style'", String(row?.kind))
check(typeof row?.text === 'string' && row.text.length > 0, '行携带样式文本')

const css = row?.text ?? ''
check(css.includes('data:image/jpeg;base64,') || css.includes('url('), '样式表引用了背景图')
check(!css.includes('</style'), '样式文本不含会提前闭合的 </style')
check(css.split('{').length === css.split('}').length, '花括号配对')
check(warnings.length === 0, '无读取告警', warnings.join('; '))

// ── 护栏 1：表面 token 必须全部被覆盖（漏一个就有一块黑）────────────────────
const missing = SURFACE_TOKENS.filter(token => !css.includes(`${token}:`))
check(missing.length === 0, `全部 ${SURFACE_TOKENS.length} 个表面 token 被覆盖`, missing.length ? `缺 ${missing.join(', ')}` : '')

// ── 护栏 2：绝不能碰的 token 族（改了会坏功能，不只是观感）──────────────────
const FORBIDDEN = [
  ['--dsw-alias-bg-mask', '弹窗遮罩：透明后模态框与背景分不清'],
  ['--dsw-alias-label-', '文字前景色'],
  ['--dsw-alias-state-', '成功/错误/警告语义色'],
  ['--dsw-alias-link', '链接色'],
  ['--dsw-alias-brand-', '品牌色'],
  ['--dsw-alias-scrollbar-', '滚动条'],
  ['--dsw-alias-button-primary-fill', '强调按钮填充：透明后主按钮消失'],
  ['--dsw-alias-button-info-fill', '信息按钮填充'],
  ['--dsw-alias-button-contrast-fill', '对比按钮填充'],
  ['--dsw-alias-interactive-bg-', '悬停/激活反馈'],
  ['--dsw-alias-bg-skeleton', '加载骨架提示'],
]
const violated = FORBIDDEN
  .filter(([prefix]) => new RegExp(`${prefix.replace(/-/g, '\\-')}[a-z0-9-]*:`).test(css))
  .map(([token, why]) => `${token}（${why}）`)
check(violated.length === 0, '没有覆盖任何禁止的 token 族', violated.join('; '))

// ── 护栏 3：边框 token 全部加粗，且未定义令牌被补定义 ───────────────────────
const missingBorder = BORDER_TOKENS.filter(token => !css.includes(`${token}:`))
check(missingBorder.length === 0, `全部 ${BORDER_TOKENS.length} 个边框 token 被加粗`, missingBorder.join(', '))
check(/--dsw-alias-fill-tertiary:\s*transparent/.test(css), '补定义了未定义的 --dsw-alias-fill-tertiary')

// ── 护栏 4：补边框只命中该命中的，且不含会留下错线的元素 ────────────────────
check(SELECTOR_NAMES.every(name => css.includes(`[class$='_${name}']`)), '补边框覆盖了全部目标类名')
check(css.includes(":not([aria-hidden='true'])"), '补边框带 aria-hidden 保险（折叠元素不画线）')

// A 类：几何上全宽/全高但不是面板，边框会画成一条没有语义的长线。
// B 类：会被"塌缩成 0 尺寸"隐藏，或应用自己声明了 border:none——
//       前者关闭面板后残留一条线，后者不该被 !important 盖掉。
// 只看补边框那两条规则的**选择器**：第 7 段的浮层清单也用 _panel / _card 这类结尾，
// 但它们不画边框，不该被这里误判。用 indexOf 定位（正则在大样式表上会回溯到卡死）。
function selectorsBefore(marker) {
  const parts = []
  let from = 0
  while (true) {
    const at = css.indexOf(marker, from)
    if (at < 0) break
    const open = css.lastIndexOf('{', at)
    const prev = css.lastIndexOf('}', open)
    parts.push(css.slice(prev + 1, open))
    from = at + marker.length
  }
  return parts.join('\n')
}
const borderSelectors = selectorsBefore('border: 1px solid rgba')
const EXCLUDED = [
  ['_composerSeat', 'A 全宽绝对定位容器，边框横贯内容列'],
  ['_schema', 'A min-height:100% 全高容器'],
  ['_payload', 'A min-height:100% 全高容器'],
  ['_turnRail', 'A 本身已是 2px 竖轨，会画成双线'],
  ['_fade', 'A 渐隐遮罩，会画出硬边'],
  ['_panel', 'B settings-plugins 的 .llfbtq_panel 带 width:0，关闭后残线'],
  ['_table', 'B trajectory 的 .EJg6FW_table 带 width:0'],
  ['_overviewPreview', 'B trajectory 带 height:0'],
  ['_runHeader', 'B workflow-run 带 width:0'],
  ['_badge', 'B cordis 的 ._7pkzhq_badge 明确写了 border:none'],
]
const leaked = EXCLUDED.filter(([name]) => borderSelectors.includes(`[class$='${name}']`)).map(([name, why]) => `${name}（${why}）`)
check(leaked.length === 0, '补边框未命中任何会留下错线的元素', leaked.join('; '))

// ── 护栏 5：补边框声明浅/深两套都在 ─────────────────────────────────────────
const borderDecls = [...css.matchAll(/border:\s*1px solid (rgba\([^)]*\))/g)].map(m => m[1])
check(borderDecls.length >= 2, '补边框含 1px solid（浅色 + 深色各一套）', borderDecls.join(' / '))

// ── 护栏 6：输入框座位的遮挡层 ──────────────────────────────────────────────
// 这一段的形状是「一个铺满座位的 ::before，自下而上画：背景图 → 补回的祖先底色
// ×N → 座位自己的渐隐带」。改成别的形状（比如直接覆盖座位自己的 background）就
// 会和应用的 .composerSeat 规则打架，所以逐条钉住。
const SEAT_TARGET = /SEAT_TARGET\s*=\s*\(\s*"([^"]+)"/.exec(python)?.[1]
const SEAT_FADE_PX = Number(/SEAT_FADE_PX\s*=\s*(\d+)/.exec(python)?.[1])
check(Boolean(SEAT_TARGET) && SEAT_FADE_PX > 0, '从生成器解析出座位遮挡层的参数', `fade ${SEAT_FADE_PX}px`)

/** 按选择器取出规则块（生成器写出的都是单层花括号，够用）。 */
function ruleBlock(selector) {
  const start = css.indexOf(`${selector} {`)
  return start < 0 ? '' : css.slice(start, css.indexOf('}', start) + 1)
}

/** 画布底色区域名 → 层数；从生成器解析，避免在 JS 里再抄一份。 */
const CANVAS_REGIONS = [.../CANVAS_REGIONS\s*=\s*\[([\s\S]*?)\n\]/.exec(python)[1]
  .matchAll(/\("([a-z]+)",\s*(\d+)/g)].map(m => [m[1], Number(m[2])])
check(CANVAS_REGIONS.length >= 4, '从生成器解析出画布底色区域', CANVAS_REGIONS.map(([n]) => n).join(' / '))

/** 从生成器解析浮层清单：(选择器, 底色令牌, 区域)。
    清单里有两处用了生成器常量（SIDEBAR_SCOPE / BEFORE_MATERIAL），先还原成字面量，
    否则它们会从断言里漏掉。 */
const SIDEBAR_SCOPE = /SIDEBAR_SCOPE\s*=\s*"([^"]+)"/.exec(python)?.[1]
const BEFORE_MATERIAL = /BEFORE_MATERIAL\s*=\s*"([^"]+)"/.exec(python)?.[1]
const surfaceTable = /OCCLUDED_SURFACES\s*=\s*\[([\s\S]*?)\n\]/.exec(python)[1]
  .replaceAll('f"{SIDEBAR_SCOPE} ', `"${SIDEBAR_SCOPE} `)
  .replaceAll('{BEFORE_MATERIAL}', BEFORE_MATERIAL)
const OCCLUDED_SURFACES = [...surfaceTable.matchAll(/\("([^"]*)",\s*"(--dsw-[a-z0-9-]+)",\s*"([a-z]+)"/g)]
  .map(m => ({ selector: m[1], fill: m[2], region: m[3] }))
check(OCCLUDED_SURFACES.length >= 18, '从生成器解析出浮层清单', `${OCCLUDED_SURFACES.length} 条`)

/** 声明的值里有几层：只数顶层逗号，rgb()/linear-gradient() 里的不算。 */
function layerCount(block, property) {
  const value = new RegExp(`${property}:\\s*([^;]+);`).exec(block)?.[1]
  if (value === undefined) return 0
  let depth = 0
  let layers = 1
  for (const char of value) {
    if (char === '(') depth += 1
    else if (char === ')') depth -= 1
    else if (char === ',' && depth === 0) layers += 1
  }
  return layers
}

// 座位那一层：浅/深各一条，只画「座位自己的渐隐带 + 会话区遮挡配方」。平台差异已经
// 收进 --dsh-ui-canvas-center 的定义里，所以这里不该再出现 data-windows-titlebar。
const SEAT_VARIANTS = [
  ['浅色', 'html body', 'rgba(255, 255, 255'],
  ['深色', 'html body[data-ds-dark-theme]', 'rgba(21, 21, 23'],
]
const escapeForRegExp = text => text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
const seatProblems = []
for (const [label, prefix, base] of SEAT_VARIANTS) {
  const block = ruleBlock(`${prefix} ${SEAT_TARGET}::before`)
  const expect = (ok, why) => { if (!ok) seatProblems.push(`${label}：${why}`) }
  expect(block !== '', '规则缺失')
  if (block === '') continue
  expect(/position:\s*absolute/.test(block), '不是绝对定位（会挤动座位里的 flex 布局）')
  expect(/inset:\s*0/.test(block), '没有铺满座位')
  expect(/z-index:\s*-1/.test(block), '不是负层级（会盖住输入卡片）')
  expect(/pointer-events:\s*none/.test(block), '会吃掉点击')
  expect(/background:\s*linear-gradient\(180deg/.test(block), '没有把座位自己的渐隐带画回来')
  const fade = escapeForRegExp(base)
  expect(new RegExp(`linear-gradient\\(180deg, ${fade}, 0\\.00\\) 0px, ${fade}, [\\d.]+\\) ${SEAT_FADE_PX}px\\)`).test(block),
    `渐隐带不是「${base}, 0) → ${base}, fill) ${SEAT_FADE_PX}px」`)
  expect(block.includes('var(--dsh-ui-occluder-center)'), '没有用会话区的遮挡配方')
  expect(/background:\s*linear-gradient\(180deg,/.test(block), '遮挡层的写法不是「渐隐带 + 会话区配方」')
}
check(seatProblems.length === 0, `座位遮挡层 ${SEAT_VARIANTS.length} 条规则形状正确`, seatProblems.join('; '))
check(!css.includes(`html[data-windows-titlebar] body ${SEAT_TARGET}`), '座位规则不再按平台分叉（差异收进画布变量）')

// ── 护栏 8：浮层清单 ────────────────────────────────────────────────────────
// 每条：自己的底色一层 + 指定区域的遮挡配方，并且关掉自己的毛玻璃。选择器只允许
// 类名结尾匹配 / 属性 / :is / :has —— 不许出现包哈希前缀（升级后必换）。
const REGION_NAMES = new Set([...CANVAS_REGIONS.map(([name]) => name), 'modal'])

/** 生成器给每条浮层选择器加的保险（与 make-background.py 的 with_hidden_guard 一致）。 */
function guardedSelector(selector) {
  const pseudo = selector.endsWith(':before') ? ':before' : ''
  const base = pseudo === '' ? selector : selector.slice(0, -pseudo.length)
  return `${base}:not([aria-hidden='true']):not([aria-hidden='true'] *):not([data-sidebar-right-panel])${pseudo}`
}

const surfaceProblems = []
for (const { selector, fill, region } of OCCLUDED_SURFACES) {
  const label = selector.replace(/\s+/g, ' ').slice(0, 48)
  const expect = (ok, why) => { if (!ok) surfaceProblems.push(`${label}：${why}`) }
  expect(REGION_NAMES.has(region), `区域 ${region} 不在画布区域表里`)
  expect(/\[class\$='_[A-Za-z]+'\]|\[data-[a-z-]+/.test(selector), '选择器没有用类名结尾匹配或 data 属性（会跟着哈希前缀一起失效）')
  expect(!/\.[A-Za-z0-9_-]{5,}_/.test(selector), '选择器里出现了哈希类名')
  const block = ruleBlock(`html body ${guardedSelector(selector)}`)
  expect(block !== '', '规则缺失')
  if (block === '') continue
  expect(block.includes(`linear-gradient(var(${fill}), var(${fill}))`), `没有把它自己的底色 ${fill} 画回来`)
  expect(block.includes(`var(--dsh-ui-occluder-${region})`), `没有用 ${region} 区的遮挡配方`)
  expect(/background:[^;]*!important/.test(block), 'background 没带 !important（压不过应用那条）')
  expect(/backdrop-filter:\s*none\s*!important/.test(block), '没有关掉自己的毛玻璃')
  // 两道「自己藏着就别铺」的保险。右侧栏面板收起时是「容器自己不画底色、盒子还留着
  // 宽度、靠隐藏子元素收起」，少了它们就会被刷成不透明块，挡住主对话区右侧。
  expect(block.includes(":not([aria-hidden='true'])"), '少了 aria-hidden 那道保险')
  expect(block.includes(":not([aria-hidden='true'] *)"), '少了「祖先藏着」那道保险')
  expect(block.includes(':not([data-sidebar-right-panel])'), '少了右侧栏面板那道保险')
}
check(surfaceProblems.length === 0, `浮层 ${OCCLUDED_SURFACES.length} 条规则形状正确`, surfaceProblems.join('; '))

// 每个用到的区域都得有对应的遮挡配方变量。
const missingRegions = [...new Set(OCCLUDED_SURFACES.map(s => s.region))]
  .filter(region => !css.includes(`--dsh-ui-occluder-${region}:`))
check(missingRegions.length === 0, '用到的区域都有遮挡配方变量', missingRegions.join(', '))

// 图片只内联一次：座位复用 <html> 上那一个自定义属性，写两遍 base64 会让样式表翻倍。
check((css.match(/--dsh-ui-bg-image:/g) ?? []).length === 1, '背景图只内联一次（--dsh-ui-bg-image）')
check(/background-image:\s*var\(--dsh-ui-bg-image\)/.test(ruleBlock('html')), '<html> 用的是同一个图片变量')

// 不能直接改座位自己的 background：应用那条 .composerSeat 渐隐规则要保持原样，
// 遮挡全靠新的 ::before，这样出问题只需删掉这一段。
const seatUses = [...css.matchAll(/\[data-composer-seat\]/g)]
check(seatUses.length > 0 && seatUses.every(m => css.startsWith('::before', m.index + m[0].length)),
  '只对座位加 ::before，没有覆盖座位自身的声明', `出现 ${seatUses.length} 次`)

// ── 护栏 7：停靠卡片去毛玻璃 ────────────────────────────────────────────────
// 应用给停靠卡片上了 `backdrop-filter: var(--dsw-menu-backdrop-filter)`
// （主题里是 blur(40px) saturate(150%)），卡片背后的背景图被糊成一片。修法是只覆盖
// 那一个变量：靠继承同时命中「画在元素上」和「画在伪元素上」两种写法，也盖不掉
// 自己重新声明了该变量的浮层。断言先剥掉注释，免得注释里的字样被当成声明。
const cssRules = css.replace(/\/\*[\s\S]*?\*\//g, '')
const DOCK_SLOT = /DOCK_SLOT\s*=\s*"([^"]+)"/.exec(python)?.[1]
check(DOCK_SLOT === 'conversation.input.dock',
  '去毛玻璃的作用域是停靠槽位', String(DOCK_SLOT))
check(/--dsw-menu-backdrop-filter:\s*none\s*!important/.test(ruleBlock(`html body [data-slot='${DOCK_SLOT}']`)),
  '停靠卡片把 --dsw-menu-backdrop-filter 覆盖成 none（带 !important）')
check((cssRules.match(/--dsw-menu-backdrop-filter:\s*none/g) ?? []).length === 1,
  '只覆盖一次（与主题无关，不需要浅/深各一份）')
check(!/(^|[;{\s])backdrop-filter\s*:(?!\s*none)/.test(cssRules),
  '不写 blur 型的 backdrop-filter 声明（要关就关成 none，绝不重新加模糊）')

// ── 优雅降级：样式表缺失时不得让 index 渲染失败 ─────────────────────────────
const hidden = `${CSS_PATH}.hidden`
renameSync(CSS_PATH, hidden)
try {
  const table2 = []
  listener(table2)
  check(table2.length === 0, 'CSS 缺失时不注入任何行（优雅降级）')
  check(warnings.length === 1, 'CSS 缺失时记录告警')
} finally {
  renameSync(hidden, CSS_PATH)
}

console.log(failures.length === 0 ? '\n全部通过' : `\n失败 ${failures.length} 项: ${failures.join(', ')}`)
process.exit(failures.length === 0 ? 0 : 1)
