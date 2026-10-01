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
const leaked = EXCLUDED.filter(([name]) => css.includes(`[class$='${name}']`)).map(([name, why]) => `${name}（${why}）`)
check(leaked.length === 0, '补边框未命中任何会留下错线的元素', leaked.join('; '))

// ── 护栏 5：补边框声明浅/深两套都在 ─────────────────────────────────────────
const borderDecls = [...css.matchAll(/border:\s*1px solid (rgba\([^)]*\))/g)].map(m => m[1])
check(borderDecls.length >= 2, '补边框含 1px solid（浅色 + 深色各一套）', borderDecls.join(' / '))

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
