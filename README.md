# dsh-ui-background

让 **DeepSeek Harness 桌面版**的界面表面透明、露出你自己的背景图，并用细边框区分面板。

不改 DSH 源码，不碰打包版，不安装任何包管理器依赖——只往 profile 补丁里插一个本地 Cordis 插件。

![合成占位图](background/placeholder.jpg)

> 上图是仓库自带的原创占位图，由 [`tools/make-placeholder.py`](tools/make-placeholder.py) 程序合成，可自由分发。
> 换成你自己的图只需要一条命令。

---

## 它解决什么

桌面版设置里的「外观」只有 `light` / `dark` / `system` 三项、字号 12–17px，**没有图片背景选项，也没有自定义 CSS 入口**。

真正挡住背景的也不是某一层不透明底色，而是一整族设计 token：消息气泡、输入框卡片、代码块、侧栏导航底色、浮层……各用各的。这个项目把这些表面改透明，再用边框把相邻面板重新区分开。

## 环境要求

| | |
|---|---|
| DSH | 桌面版（`DSH_PROFILE=desktop`），且 profile 机制可用 |
| Python | 3.9+，带 Pillow（生成样式表用） |
| Node.js | 18+（只用于跑自检，可选） |

## 安装

**1. 克隆**

```bash
git clone https://github.com/Flowfangfei/dsh-ui-background.git
cd dsh-ui-background
```

**2. 生成样式表**

仓库自带的占位图可以直接用；换成你自己的图只要覆盖 `background/source.jpg`（该路径已 `.gitignore`）。

```bash
python background/make-background.py --source background/placeholder.jpg
# 或者：把你的图放到 background/source.jpg，然后
python background/make-background.py
```

它会产出 `background/background.css` —— 这个文件是生成物，已 gitignore。

**3. 挂载插件**

把下面这段追加到 `$DSH_HOME/profiles/desktop/cordis.patch.yml`（Windows 下 `$DSH_HOME` 默认是 `%USERPROFILE%\.dsh`），并把路径换成你克隆后的真实位置：

```yaml
- insert:
    - id: custom-ui-background
      name: "C:/path/to/dsh-ui-background/background/plugin.mjs"
```

也可参考 [`examples/cordis.patch.example.yml`](examples/cordis.patch.example.yml)。

两个要点：

- `name` 写成路径时，`dsh-app-boot` 的 `anchorInsertedPluginNames` 会把它锚定成 `file://` URL；Windows 路径用正斜杠更稳妥。
- **扩展名必须是 `.mjs`**。该目录没有 `package.json`，`.js` 会被 Node 当成 CommonJS 解析，而插件用的是 ESM 语法。

**4. 生效**

1. 先**刷新页面**。profile 配置默认热重载，而插件每次渲染 `index.html` 都重新读取 CSS，所以改样式通常不需要重启。
2. 没生效就**重启桌面版**。增删 `cordis.patch.yml` 里那一行必须重启。

**卸载**：删掉上面那段 `- insert:`，重启。

---

## 工作原理

### 为什么需要插件

宿主侧的 `webserver/index-inject` 事件是可用扩展点：每次渲染 `index.html` 时，插件往注入表里 push 一行 `{ kind: 'style', text }`，渲染器把它作为 `<style>` 插进 `<head>`。DSH 自带的 `ui-theme` 就是用这个钩子注入启动样式的——所以这条路是官方机制，不是 hack。

**每次 index 渲染都会重新收集注入表**，所以 `plugin.mjs` 每次现读磁盘上的 `background.css`：调外观只需改 CSS 再刷新，不必重启。

### 为什么靠 token 而不是类名

扫过 179 个含 `src` 的包，只有 **7 处**字面量底色，其中多数还是 `var(令牌, 兜底值)` 的兜底。也就是说**整个 UI 的表面几乎全靠设计 token 驱动**——覆盖 token 就能覆盖全界面，不必去猜哈希类名。

反过来，补边框必须用类名，但只匹配**类名结尾**（`[class$='_bubble']`）。实测构建后的类名保留了原始局部名（`.HLIF-a_frame`、`._0VSdMW_bubble` 两种格式都如此），所以结尾匹配既能命中，又不受包哈希前缀变化影响。

### 样式表的四段结构

1. **背景图**铺在 `<html>` 上（`cover` + `fixed`），`<body>` 底色置 `transparent`——否则启动阶段写下的不透明底色会盖住它。
2. **35 个表面填充 token 变半透明**（`rgba(基色, --fill)`），黑色块随之透出背景图。
3. **6 个边框 token 加粗**，让相邻透明面板仍能区分。其中 `border-l4` 同时驱动 `--dsw-elevation-stroke-color`，所以那些 `border: 0` + 描边的浮层也一并覆盖。
4. **18 类本来没有边框的表面补一条**，用 `[class$='_名字']:not([aria-hidden='true'])` 结尾匹配。

选择器一律用 `html body` / `html body[data-ds-dark-theme]` 提高权重压过运行时注入的样式表，再加 `!important` 兜底。

---

## ⚠ 关于背景图（重要）

**这个仓库刻意不包含任何第三方画稿。**

原因有三，都与"图片地址"有关：

1. **版权**：第三方画作即便只是拿来当壁纸，公开分发也可能侵权。仓库里的 `placeholder.jpg` 是程序合成的原创图，可以安全分发。
2. **体积**：一张 2800×1608 的照片约 600 KB，内联成 base64 后膨胀到 850 KB。把它提交上来等于把仓库撑大近 1 MB，而且**每改一次参数就产生一个全新 blob**，历史会被迅速撑爆。
3. **生成物不该入库**：`background.css` 内嵌了图片的 base64。提交它等于把图片提交两遍。它是可随时重建的生成物，已 gitignore。

所以流程是：**图由使用者自备，代码只带生成器**。把图放到 `background/source.jpg`（已 gitignore）即可。

`background/preview*.jpg` 和 `background/variants*.jpg` 是本地生成的观感预览，同样不入库。

### 为什么图片是内联进 CSS 的

因为这是免安装、免路由的最简做法。代价是 base64 膨胀约 33%，且内联内容不参与浏览器缓存——**每次刷新页面都会重新传输**。走 localhost 是瞬时的，但如果你把背景图换成大图又介意这个开销，可以让插件通过本地 HTTP 路由提供图片、CSS 里只写 `url("/xxx.jpg")` 引用：省掉 33% 膨胀，且图片能进缓存只传一次。代价是插件要多注册一条路由，属于新增的失败面。当前实现没走这条路。

---

## 参数

```bash
python background/make-background.py --help
```

| 参数 | 默认 | 含义 |
|---|---|---|
| `--source` | `background/source.jpg` | 源图路径，可指向任意位置 |
| `--fill` | `0.10` | 表面填充 alpha。`0` = 完全透明；越大面板越实、文字越好读 |
| `--border` | `0.22` | 边框/描边 alpha。越大发丝线越亮，但**也会让折叠容器的残线变明显**，别调太高 |
| `--blur` | `0` | 高斯模糊半径（px）。`0` = 保留原清晰度。若照片自己的建筑硬边被误读成 UI 框线，调到 2~3 |
| `--gamma` | `0.70` | 暗部提升：`<1` 抬阴影。`1.0` = 完全不改色调 |
| `--saturate` | `1.0` | 饱和度倍数 |
| `--position` | `center center` | CSS `background-position`，如 `70% center` 把画面右移 |
| `--quality` | `95` | JPEG 质量 |
| `--max-side` | `0` | 图片最长边上限；`0` = 不缩放，保留原始分辨率 |

### `--gamma` 是暗色背景图的关键

面板接近全透明后，**你看到的就是图片本身**：图片的暗部有多暗，界面就有多暗。一张夜景图中位亮度可能只有 30，而深色面板色是 `(21,21,23)`——两者几乎相等，所以调 `--fill` 救不回来：面板加得再多，也只是把暗部换成同样暗的色块。

`--gamma` 才是那个旋钮。gamma 0.70 能把 25 百分位亮度从 20 抬到 43、中位从 30 抬到 57，暗墙才从"死黑"变成看得出的纹理。判断标准：

- 暗部像"一块黑" → `--gamma` 往 0.6 走
- 整张图像蒙了层灰、发白 → `--gamma` 往 0.85~1.0 走

### 清晰度与"框线感"是一枚硬币的两面

`--blur 0` 最清晰，但照片自己的高对比边缘会原样透出来——在几乎全透明的面板下，它们很容易被看成 UI 画错的线。想要清晰就用 `0`，想让它像背景纹理就用 `2~3`。

怎么判断一条线到底是照片的还是 UI 的？把图转灰度、算**列/行平均亮度的一阶差分**找最强边缘，再按 `background-size: cover` 的缩放与偏移投影到屏幕坐标对照即可。本项目开发时就靠这个方法确认过两处"疑似 UI 框线"其实是照片里的建筑交界。

---

## 面板边框：命中了什么，刻意避开了什么

加边框的前提是"这块是一个面板，而且它是可见的"。有两类元素不满足，已在生成器里排除。

**A 类：几何上全宽/全高，但不是面板**——边框会画成一条没有语义的长线。

| 类名 | 几何属性 | 问题 |
|---|---|---|
| `_composerSeat` | `absolute; left:0; right:<scrollbar>; bottom:0` | 全宽，边框横贯整个内容列 |
| `_schema` / `_payload` | `min-height:100%` | 全高，画出竖长线 |
| `_turnRail` | 本身即 `width:2px` 的竖轨 | 画成双线 |
| `_fade` | 渐隐遮罩 | 画出硬边 |

**B 类：会被"塌缩成 0 尺寸"隐藏，或应用自己声明了 `border: none`**。
元素收成 0 宽高时那 1px 边框**照样渲染**，于是关闭面板后残留一条线；而 `border: none` 是代码库在明确表达"这里不要边框"，不该被 `!important` 盖掉。

| 类名 | 实测证据 | 问题 |
|---|---|---|
| `_panel` | `settings-plugins` 的 `.llfbtq_panel` 带 `width:0` | 可折叠预览面板，关闭后残线 |
| `_table` | `trajectory` 的 `.EJg6FW_table` 带 `width:0` | 同上 |
| `_overviewPreview` | `trajectory` 带 `height:0` | 同上 |
| `_runHeader` | `workflow-run` 带 `width:0` | 同上 |
| `_badge` | `cordis` 的 `._7pkzhq_badge` 明确写了 `border: none` | `!important` 会盖掉应用的意图 |

另外所有补边框选择器都带 `:not([aria-hidden='true'])`：有些组件用"保持盒子但收成 0 尺寸 + 标 `aria-hidden`"来隐藏，这条能挡住那类残线。

### 刻意不碰的 token（改了会坏功能，不只是观感）

| 令牌族 | 原因 |
|---|---|
| `--dsw-alias-bg-mask-*` | 弹窗/抽屉遮罩，透明后模态框与背景分不清 |
| `--dsw-alias-button-primary-fill` / `-info-fill` / `-contrast-fill` | 强调按钮的实心填充，透明后主按钮消失 |
| `--dsw-alias-interactive-bg-*` | 悬停/激活反馈，本身是极淡叠加（.08/.14），不是黑块 |
| `--dsw-alias-bg-skeleton` | 加载骨架的动效底色 |
| `--dsw-alias-label-*`、`-link`、`-brand-*` | 前景/文字色 |
| `--dsw-alias-state-*` | 成功/错误/警告语义色 |
| `--dsw-alias-scrollbar-*` | 滚动条 |

另外补定义了 `--dsw-alias-fill-tertiary: transparent`：设计系统里没有这个 token，但 `FileCard` 引用了它，原本会走硬编码兜底 `rgba(0,0,0,0.08)`；定义它就绕开了兜底。

---

## 自检

```bash
python background/make-background.py --source background/placeholder.jpg   # 先产出 CSS
node verify/verify-plugin.mjs
node verify/verify-patch.mjs
```

`verify-plugin.mjs` 模拟 Cordis 宿主，共 23 项断言，分五组：

- **插件契约**：导出 `apply()` / 插件名、只注册 `webserver/index-inject`、注入行结构、CSS 缺失时优雅降级。
- **护栏 1**：全部表面 token 必须被覆盖（漏一个就有一块黑）。
- **护栏 2**：**不得**覆盖任何禁止的 token 族——上表逐条对应，含原因。这条防的是"改错一族令牌把功能弄坏"。
- **护栏 3~5**：边框 token 全部加粗、未定义令牌被补定义、补边框用结尾匹配且**未命中任何会留下错线的元素**。

期望的 token 清单是**从 `make-background.py` 解析出来的**，不是在 JS 里另抄一份——抄一份必然漂移，护栏就废了。

`verify-patch.mjs` 用桌面版自己的 `readProfilePatches` 校验你的 `cordis.patch.yml`：补丁能通过 schema、存在插件行、`name` 被正确锚定成 `file://`、目标文件存在且可 import。所有路径从 `$DSH_HOME` 推导，可加参数指定 profile：

```bash
node verify/verify-patch.mjs desktop
DSH_HOME=/path/to/.dsh node verify/verify-patch.mjs
```

---

## 已知限制

- **渲染结果无法在进程外验证**。桌面版界面要求启动令牌（直接请求会返回 401，令牌只存在于启动进程内存中），所以视觉效果只能由人眼确认；仓库里的自检覆盖的是插件契约与样式表内容，不覆盖渲染。
- **折叠残线无法完全穷尽**。加粗边框 token 会影响应用已有的每一条边框，其中难免有属于可折叠容器的，而编译后的类名里没有稳定的"已折叠"标记可供选择器判断。已按实测证据剔除已知的 5 个（B 类），并把 `--border` 压到 0.22。
- **补边框会强制 `border: 1px solid`**。若某元素没设 `box-sizing: border-box`，其尺寸会增 2px。实测影响可忽略。
- **18 类补边框里 11 类属轨迹视图**（`trajectory`）。该视图观感异常时单独删掉对应名字即可，不影响主聊天界面。
- **DSH 升级会让部分选择器失效**。类名若改名，表现是"少了一条边框"，不会坏布局。
- **`--position` 用的是 CSS `cover` 语义**：只有图片比窗口更"宽"时才会发生横向裁切，此时改横向值才有效果。

## License

[MIT](LICENSE)。仓库自带的 `placeholder.jpg` 由本仓库脚本合成，同样以 MIT 分发；使用者自备的背景图版权归各自作者。
