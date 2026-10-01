/**
 * 用桌面版 DSH 自己的 profile 解析器校验 cordis.patch.yml，确认插件挂载正确：
 *   1. 补丁能通过 DSH 的 schema 解析（不是靠肉眼看"像是合法 YAML"）；
 *   2. 存在 id 为 custom-ui-background 的 insert 行；
 *   3. 该行的 name 被锚定成本地插件的 file:// URL；
 *   4. 目标文件真实存在、可被 import、且导出 apply()。
 *
 * 所有路径都从 $DSH_HOME 推导，不写死任何机器路径。
 *
 * 用法：
 *     node verify/verify-patch.mjs [profileName]     # 默认 desktop
 *     $env:DSH_HOME = "D:\other\.dsh"; node verify/verify-patch.mjs
 */
import { existsSync, readFileSync } from 'node:fs'
import { homedir } from 'node:os'
import { dirname, join } from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'

const ROOT = dirname(dirname(fileURLToPath(import.meta.url)))
const ROW_ID = 'custom-ui-background'

const HOME = process.env.DSH_HOME || join(homedir(), '.dsh')
const PROFILE = process.argv[2] || 'desktop'
const PROFILE_DIR = join(HOME, 'profiles', PROFILE)
const PATCH = join(PROFILE_DIR, 'cordis.patch.yml')
const MANIFEST = join(PROFILE_DIR, 'package.json')
const MODULES = join(HOME, 'profiles', 'node_modules')
const BOOT = join(MODULES, '@deepseek-ai', 'dsh-app-boot', 'lib', 'index.js')

const failures = []
const check = (ok, label, detail = '') => {
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${label}${detail ? ` — ${detail}` : ''}`)
  if (!ok) failures.push(label)
}

console.log(`DSH_HOME   ${HOME}`)
console.log(`profile    ${PROFILE}`)
console.log(`补丁文件   ${PATCH}\n`)

if (!existsSync(PATCH)) {
  console.error(`找不到 ${PATCH}\n请确认 DSH_HOME 与 profile 名，或先挂载插件（见 README 的安装一节）。`)
  process.exit(1)
}
if (!existsSync(BOOT)) {
  console.error(`找不到 DSH 的 profile 解析器：\n  ${BOOT}\n请确认 DSH_HOME（当前 ${HOME}）指向真正的 harness home。`)
  process.exit(1)
}

const { readProfilePatches } = await import(pathToFileURL(BOOT).href)

// startedBundles 取 profile 自己声明的，而不是写死
let startedBundles = []
try {
  startedBundles = JSON.parse(readFileSync(MANIFEST, 'utf8'))?.dsh?.profile?.bundles ?? []
} catch { /* 缺清单时留空，解析器会自行回退 */ }
check(startedBundles.length > 0, '读到 profile 的 bundle 清单', startedBundles.join(', ') || '（空）')

// installAnchor 依机器而异，按候选链尝试，并允许环境变量覆盖
const anchors = [
  process.env.DSH_INSTALL_ANCHOR,
  join(MODULES, '@deepseek-ai', 'dsh', 'package.json'),
  join(PROFILE_DIR, 'package.json'),
].filter(Boolean)
const installAnchor = anchors.find(existsSync) ?? join(PROFILE_DIR, 'package.json')

const context = {
  name: PROFILE,
  dir: PROFILE_DIR,
  patchPath: PATCH,
  installAnchor,
  cwd: ROOT,
  home: HOME,
  startedBundles,
  overlays: [],
  telemetryDisabledEnv: process.env.DSH_TELEMETRY_DISABLED,
}

let patches
try {
  patches = readProfilePatches('dsh', context)
  check(true, 'DSH 解析器接受 cordis.patch.yml', `${patches.length} 个补丁条目`)
} catch (error) {
  check(false, 'DSH 解析器接受 cordis.patch.yml', String(error))
  console.log('\n解析失败，后续检查跳过')
  process.exit(1)
}

const mine = patches.flatMap(patch => patch.insert ?? []).find(entry => entry.id === ROW_ID)
check(mine !== undefined, `补丁里存在 ${ROW_ID} 行`)
check(mine?.name?.startsWith('file:///'), 'name 被锚定为 file:// URL', String(mine?.name))

if (mine?.name) {
  const modulePath = fileURLToPath(mine.name)
  check(existsSync(modulePath), '插件文件真实存在', modulePath)
  try {
    const mod = await import(pathToFileURL(modulePath).href)
    check(typeof mod.apply === 'function', '插件可被 import 且导出 apply()')
  } catch (error) {
    check(false, '插件可被 import 且导出 apply()', String(error))
  }
}

console.log(failures.length === 0 ? '\n全部通过' : `\n失败 ${failures.length} 项: ${failures.join(', ')}`)
process.exit(failures.length === 0 ? 0 : 1)
