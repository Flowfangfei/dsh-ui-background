/**
 * 自定义 UI 背景 —— 把一张图片和一组配色覆盖注入 Web GUI 的 index.html。
 *
 * 关键点：`webserver/index-inject` 在每一次 index 渲染时都会重新收集注入表，
 * 所以这里每次都从磁盘现读同目录的 background.css。改完 CSS 只要刷新浏览器
 * 页面就生效，不需要重启 DSH。
 *
 * 挂载方式见 ../README.md。
 */
import { readFileSync } from 'node:fs'

/** 样式表与本文件同目录；每次 index 渲染重新读取，便于即时调参。 */
const CSS_URL = new URL('./background.css', import.meta.url)

/** Cordis 插件名，出现在插件清单里。 */
export const name = 'custom-ui-background'

/**
 * 注册 index 注入监听，把样式表作为一个 `<style>` 行交给 index 渲染器。
 * @param ctx - Cordis 宿主上下文。
 */
export function apply(ctx) {
  ctx.on('webserver/index-inject', (table) => {
    let text
    try {
      text = readFileSync(CSS_URL, 'utf8')
    } catch (error) {
      // 读不到就静默跳过：宁可没有自定义背景，也不要让 index 渲染失败。
      ctx.logger?.warn?.(`custom-ui-background: 无法读取 ${CSS_URL.pathname}: ${String(error)}`)
      return
    }
    table.push({ kind: 'style', text })
  })
}
