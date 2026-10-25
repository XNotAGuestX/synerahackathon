# 前端设计与布局评审报告（Wayfinder）

> 日期：2026-10-25 · 依据：`ui-ux-design` 规范（语义 token、状态优先、响应式外壳、WCAG 2.2 AA、克制动效）· 范围：`frontend/src`
> 约束：第 1–7 节是评审时的原始结论，所有建议默认**保持现有行为**（路由、API 调用、请求体、提交时机、对话流程不变），涉及行为变化的条目标注 ⚠️。
> **修复状态见第 8 节**（2026-10-25 已实施，`e2e/layout_check.py` 92/92 项通过）。

## 1. 方法与覆盖范围

- **代码审阅**：`src/app/App.tsx`、`src/styles.css`（2987 行）、`GuidePanel.tsx`、`PlaceDiscovery.tsx`、`PlanCanvas.tsx`、`WalkPad.tsx`、`DebugPanel.tsx`、`EditorPanel.tsx`。
- **浏览器实测**：Playwright 驱动本地 Chromium，连接运行中的 API 和 Agent，默认楼栋为 `Fertigung Ost 27`（2 层）。脚本和截图都在仓库外：`D:\tmp\uxshots\`（`shoot.py`、`states.py`、`extra.py`）。
- **第 1 轮：布局**。dark/light × 320/390/768/1024/1440，初始状态。
- **第 2 轮：状态**。共测了以下状态：

| 状态 | 方式 | 宽度 | axe |
|---|---|---|---|
| 起点抽屉：打开、过滤为空、Escape、焦点返回、焦点陷阱 | 真实 | 1440 | 0 |
| A→B 路线：分类 → 类型 → Route here → 选起点 → 出路线 | 真实 | 1440 / 390 | 1440: 0；**390: 1（target-size, serious）** |
| 已有路线时切换 Step-free，触发重新算路 | 真实 | 1440 / 390 | — |
| 对话：发送中、Agent 回复（耗时 14.3s）、长输入 | 真实 | 1440 | 0 |
| 澄清（clarify）、不可达（unreachable）、待确认动作（pending） | DEV 预览 fixture | 1440 | — |
| 编辑器：打开、选中物件、Escape 退出 | 真实 | 1440 / 390 | 0 / 0 |
| 加载中 | CDP 注入 2.5s 网络延迟 | 1440 | — |
| 加载失败 + Reconnect | 拦截 `/sessions*`，返回 503 | 1440 / 390 | 0 |
| 长楼栋名和长房间名 | 拦截响应，给名称追加长后缀 | 1440 / 320 | — |
| 语音模式和 Transcript 模式的 UI | 假麦克风设备 | 1440 | 0 |
| 键盘 Tab 顺序与焦点环 | 真实 | 1440 | — |
| 3D 堆叠展开、Escape，reduced-motion | 真实 | 1440 | — |

**未覆盖**：
- 真实的语音识别和 TTS 播放（headless 下无法验证听感）。
- 多楼层路线：测试楼栋里没找到能稳定触发跨层路线的入口，`chat-floor-links` 一直为空。
- 导入平面图的完整流程。
- 中英切换：项目只有 `en.ts`，没有这项。
- 真实触屏设备。

## 2. 实测数据

**第 1 轮：首屏空间**

| 视口 | 顶栏高 | 搜索/分类区高 | 地图顶部 y | 地图是否在首屏 | 对话输入框是否在首屏 |
|---|---|---|---|---|---|
| 320×720 | 93 | 211 | **730** | ❌ 完全不在 | ❌（y≈2450） |
| 390×844 | 93 | 211 | 626 | ⚠️ 只露出 ~218px | ❌（y≈2450） |
| 768×1024 | 64 | 201 | 435 | ✅ | ❌ |
| 1024×768 | 64 | 255 | **599** | ⚠️ 只露出 ~170px | ❌ |
| 1440×900 | 64 | 199 | 409 | ✅（约一半） | **❌（composer 顶部 y=1000）** |

选择类型后分类区会再增高一行"类型"和一行"结果"。1440 宽下地图顶部会被推到 y≈600（截图 `s-route-1440`）。

**第 2 轮：关键测量**

| 项目 | 结果 |
|---|---|
| 页面滚动 400px 后顶栏底边 | **−336px**：sticky 失效，顶栏随页面滚走 |
| 页面滚动 600px 后 next-bar 顶部（390 宽） | **1913px**，视口高 844：sticky 失效，底栏不吸底 |
| 页面滚动 900px 后聊天栏顶部 | −637px：聊天栏随页面滚走，sticky 失效 |
| 从页面顶部 Tab 到对话输入框 | **81 次**，其中 47 次落在地图房间多边形上 |
| 同时存在的 live region | **7 个**：zoom %、map-caption、stack-info、voice-pill、chat-feed、sr-only、walk-status |
| Agent 回复中的 Markdown | `**Toilet 0.22**` 原样显示，没有渲染 |
| 加载中的状态 | 显示 "API disconnected"，h1 是 "Floor 1"，地图显示 "No plan fixture for this floor." |
| 移动端打开编辑器 | 编辑面板在 y=1957，`scrollY=0`。焦点进入面板的搜索框，但视口不动，用户看不到变化 |
| 320 宽 + 长名称 | **整页向左偏移**：品牌 "W" 和 "LIVE PLAN" 左侧被切掉；楼栋选择、搜索框、Step-free 越过右边缘 |
| API 状态胶囊颜色 | connected 和 disconnected 都是 `rgb(71,111,0)`，只有文字不同 |
| Reconnect 按钮 | 浏览器原生样式：`#f0f0f0` 底、outset 边框、高 24px，深色主题下也一样 |

**做得好的地方**（已实测通过，改动时请保持）：
- 起点抽屉：打开时焦点进入搜索框；Tab 被困在抽屉内；Escape 关闭后焦点回到触发按钮；空结果有提示文案。
- 编辑器：打开时焦点进入搜索框；Escape 退出后焦点回到 "Edit map"；表单和校验提示同时用颜色、图标和文字表达；删除使用内联确认。
- 所有可聚焦元素都有可见焦点环（Tab 序列中 0 个缺失）。
- 加载失败后点 Reconnect 能恢复；失败时 Send 被禁用；分类区有"加载后出现"的空状态。
- 无起点时点 "Route here"，会同时打开起点抽屉并在对话里说明原因。

---

## 3. 总体结论

视觉基础扎实：token 分层清楚，双主题完整，焦点和对话框处理到位。问题集中在三处：

1. **空间分配**：页面声明"地图优先"，实际上地图在中小视口被挤出首屏；**连 1440×900 下对话输入框都在首屏之外**。
2. **一个全局 CSS 缺陷让所有 sticky 失效**：顶栏、聊天栏、next-bar 本应常驻，现在全部随页面滚走。这一条修复后，上面很多空间问题会同时缓解。
3. **状态表达不准确**：加载中显示"已断开"，没问路时显示"没有无障碍路线"，Markdown 原样输出，Agent 推断出的起点与位置 chip 不同步。

页面的单一任务是：**"告诉我我在哪、要去哪 → 在地图上看到路线 → 跟着走"**。下面按这个主线排优先级。

---

## 4. 问题清单与建议

### P0：直接影响主任务

#### P0-1 `overflow-x: hidden` 让所有 sticky 失效（根因级）
- **证据**：`html { overflow-x: hidden }`（`styles.css:168`）和 `body { overflow-x: hidden }`（`:172`）同时设置。这样 `body` 自身成为滚动容器，但它不受高度约束，实际滚动的是视口。结果是 `.topbar`（`:302`）、`.guide-region`（`:2840`）、`.next-bar`（`:2625`）这几处 `position: sticky` 都以 body 为参照，永远不会吸附。见上节实测：滚动后顶栏和聊天栏离开视口，next-bar 不吸底。
- **影响**：
  - 桌面端：用户滚动看 3D 堆叠时，聊天栏和楼栋切换都消失了。
  - 移动端：用户必须滚回页尾才能看到"下一步"。
  - 另外，组件溢出被掩盖（见 P0-5）。
- **建议**：删除两处 `overflow-x: hidden`；真实存在的溢出源头在各组件内用 `min-width: 0` / `overflow-wrap` 修掉。如果必须兜底，只对 `.app-shell` 用 `overflow-x: clip`（`clip` 不会创建滚动容器，不破坏 sticky）。
- **验收**：在 1440 和 390 宽下滚动 900px，顶栏 `top == 0`，next-bar 底边等于视口高，聊天栏 `top >= 顶栏高`。

#### P0-2 地图与对话输入框在首屏之外
- **证据**：
  - 见第 2 节表格。`PlaceDiscovery` 是 `.workspace` 之外的全宽区块（`App.tsx:501`），高 199–255px，选中类型后还会继续增高。
  - 地图上方还有图例：390 宽下是 2 列网格，约 130px。
  - 聊天栏高度是 `calc(100svh - 72px)`（`:2840`），起点却在 y=263，所以 1440×900 下 composer 落在 y=1000。
- **建议**：
  1. 搜索框并入 `.map-toolbar`，和楼层切换同一行。分类浏览默认**折叠**为 "Browse" disclosure；类型和结果行在展开后出现，结果可以用浮层列表（popover），不推开地图。
  2. 图例改为地图下方 caption 行里的 "Legend" 开关，≤600px 容器默认收起。
  3. 布局改为 `app-shell` 网格：`grid-template-rows: auto 1fr auto`，高度 `100svh`。工作区内部滚动（规范 layout.md："App shell: overflow hidden on body; scroll inside panes"）。地图和聊天栏各自填满 `1fr`，替换掉 `calc(100svh - 300px)` 这类估算值（`:861`）。
- **验收**：在 320/390/1024/1440 宽下，`.plan-wrap` 顶部 ≤ 视口高 × 0.45。桌面端 composer 完整位于首屏内。

#### P0-3 移动端主交互和编辑器埋在页面底部
- **证据**：
  - ≤800px 时 DOM 顺序为：地图 → 缩放 → 显示模式 → 3D 堆叠（默认展开，约 450px）→ 导入 → Revision → 聊天/编辑器。
  - 390 宽下聊天输入框在 y≈2450。
  - 点 "Edit map" 后，编辑面板出现在 y=1957，视口不动（实测 `scrollY=0`）。用户只看到按钮变成 "Done"，**看不到编辑器已经打开**；而焦点已经进入屏幕外的搜索框。
  - 点对话里的 "View route ↗" 会调用 `scrollIntoView` 滚回地图，但聊天和地图之间仍有 1500px 以上的距离。
- **建议**：
  - A（改动小）：≤800px 时 3D 堆叠默认收起（⚠️ `stackOpen` 初始值改为按宽度决定）；导入和 Revision 移到聊天之后；打开编辑器时 `scrollIntoView` 编辑面板。
  - B（推荐）：≤650px 采用 "Map | Guide" 两段切换（复用 `.segmented` 配方），放在 next-bar 上方；编辑器作为底部抽屉（bottom sheet）覆盖在地图上。符合 layout.md 的移动外壳。
- **验收**：390 宽下首屏有对话输入框或进入对话的入口；打开编辑器后，编辑面板标题在视口内。

#### P0-4 WalkPad 浮层遮挡控件
- **证据**：
  - `.walk-pad { position: fixed }`（`:1212`），首次定位 `y = innerHeight - height - 88`（`WalkPad.tsx:302`）。
  - 1024 宽时盖住 "Edit map"、楼层按钮和图例（`dark-1024`）；390 宽时盖住图例（`s-route-390`）；1440 宽时盖住地图左侧；页面滚到 3D 区时又浮在 3D 上（`s-chat-reply`）。
  - 390 宽路线状态下，axe 报告 `target-size`（serious）：Zoom in、Fit route、Fit floor 被遮挡，最小可点空间只有 77×0.4px。初始状态未复现，判断为浮层遮挡。
- **建议**：
  1. 改为 `position: absolute`，相对 `.plan-wrap` 定位，拖拽范围限制在地图内（拖拽逻辑不变，只换坐标系）。
  2. 窄容器下默认折叠。
  3. 它是**模拟行走工具**，建议放到 "Simulate walk" 开关后面。⚠️ 默认隐藏是行为变化，需要确认演示脚本。
- **验收**：任意宽度和状态下，WalkPad 不与 `.map-toolbar`、`.map-legend`、`.map-controls` 相交；路线状态下 axe `target-size` 为 0。

#### P0-5 窄屏与长名称导致整页偏移和裁切
- **证据**：
  - 320 宽下楼栋选择只剩箭头，Step-free 开关被切掉一半（`light-320`）。
  - 加上长名称后**整页向左偏移**：品牌 "W"、"LIVE PLAN"、分类卡片的左侧被切掉（`s-long-320`）。
  - 原因有两个：`.discover-bar` 不换行，且 `.step-free-toggle` 设了 `flex: 0 0 auto`；顶栏元素有最小宽度。overflow-hidden 的容器在聚焦或 `scrollIntoView` 时被滚动，于是整页错位，而 `scrollWidth == clientWidth` 测不出来。
  - 位置 chip 被截断，但没有 `title`，完整名称没有其他方式查看。
- **建议**：
  1. 先完成 P0-1（去掉 overflow 兜底），让溢出能暴露出来。
  2. ≤400px 时 `.discover-bar` 设 `flex-wrap: wrap`，或把 Step-free 缩成带 `aria-label` 的图标开关。
  3. ≤650px 时顶栏拆成两行：第 1 行品牌 + 设置菜单；第 2 行楼栋选择（`flex: 1`）+ 位置 chip。
  4. 截断的 chip 和选择器加上 `title`，或在选中后的 caption 中显示全名。
- **验收**：320 宽 + 长名称下，所有元素 `left >= 0` 且 `right <= innerWidth`。

#### P0-6 加载与失败态显示虚假状态
- **证据**（`x-loading`、`s-error-1440`）：
  - **加载中**：
    - API 状态胶囊显示 "API disconnected"，实际是正在连接。
    - h1 是 "Floor 1"：这是 `catalog.floors` fixture 的回退值，并不是当前楼栋的楼层。
    - 地图显示 "No plan fixture for this floor."：开发用语，而且是错误陈述。
    - 聊天仍显示欢迎语邀请输入，但 Send 被禁用，也没有解释原因。
  - **失败**：
    - 提示条把 `00001_internal` 这个错误码放在最醒目的位置，"API request failed (503)" 次之。
    - Reconnect 是**无样式的原生按钮**（浅灰底、outset 边框、24px 高），深色主题下非常突兀。
    - next-bar 仍显示 "No step-free route ->"。
  - API 状态胶囊在 connected 和 disconnected 时颜色完全一样，都是 primary 绿，只有文字不同。
- **建议**：
  - 区分三态：`connecting`（中性色 + 脉冲点，文案 "Connecting…"）、`connected`（不显示或仅显示小圆点）、`disconnected`（danger 色 + Reconnect）。
  - 加载中，地图区显示骨架或 "Loading building…"，h1 用占位，不使用 fixture 名称。
  - `.plan-empty` 文案改为面向用户的说法，例如 "This floor has no plan yet."。
  - 失败提示条：先写人话（`message`），错误码、trace 和 request 收到 "Details" disclosure 里；Reconnect 用 `.small-action` 配方。
  - 对话欢迎区在 `!ready` 时显示 "Connecting to the building…"，不要邀请用户输入。
  - next-bar 在 `!ready` 时只显示状态，不显示操作按钮。

### P1：状态、文案与一致性

#### P1-1 next-bar 状态文案不准确
- **证据**：
  - 无路线时按钮显示 `${copy.noRoute} ->`，即 "No step-free route ->"（`App.tsx:514`）。用户还没问路，就被告知"没有无障碍路线"。
  - 不可达时，标题和按钮**重复**显示 "No step-free route | Play | No step-free route ->"，而且 Play 仍然渲染。
  - 有路线时："Guide me"、"Play"、"34.2 m ->"、"×" 四个按钮同权重，主操作 "Guide me" 不突出。
- **建议**：

| 状态 | 标题 | 操作 |
|---|---|---|
| 未连接 / 加载 | Connecting… | 无 |
| 无路线 | Ask for a route | 无（或"Set your location"） |
| 有路线 | 当前步骤 | **Guide me**（实心主按钮）· Play · `34.2 m →` · × |
| 引导中 | 实时指令 | **Stop guidance** · × |
| 不可达 | No step-free route | **Allow stairs**（复用 `toggleStepFree`）· × |

  箭头 `->` 改为 `→` 或 SVG。

#### P1-2 Agent 回复的 Markdown 原样显示
- **证据**：真实回复为 "The nearest restroom is `**Toilet 0.22**` on the ground floor…"，星号原样出现（`x-reply-card`）。`.chat-text` 只是 `white-space: pre-wrap` 的纯文本。
- **建议**（二选一）：
  - 前端做最小安全渲染，只支持 `**bold**`、换行和有序列表，不引入 HTML。
  - 后端在 prompt 或输出层约定纯文本。⚠️ 属于后端行为变化。

#### P1-3 同一信息重复出现，状态不同步
- **路线步骤重复**：Agent 回复正文已经包含 "Route: 1. … 4. …"，下面的路线卡片又有一个 "Directions" 折叠。同一份步骤在一条消息里出现两次，回复卡片高 289px。建议当 `reply.routes` 存在时，前端把步骤只放在路线卡片里。正文如何去重需要和 Agent 输出格式一起约定。
- **重算路线产生重复消息**：切换 Step-free 后会新增一条与上一条文字完全相同的消息（"Additive zone H-A3 is 34.2 m away…"），区别只在 "Stairs allowed" 和 "Step-free"。建议新消息文案写明变化，例如 "Step-free route: 34.2 m."，或者原地更新当前路线卡片（⚠️ 消息流行为变化）。
- **起点不同步**：Agent 根据会话推断出起点（next-bar 显示 "Start in Warehouse zone H-C2"），但位置 chip 仍是 "Set your location"，map-caption 仍是 "Start / entrance"。同一事实在三个位置给出两种说法。建议 chip 和 caption 读取 `route.start_space_id ?? hereId`。

#### P1-4 待确认动作与不可达缺少层级和恢复路径
- **待确认**：
  - "Close Office lift" 会改动地图，但 Confirm 和 Cancel 视觉权重相同，都是描边按钮（`s-fx-pending`）。
  - 建议 Confirm 用实心按钮，并根据动作语义着色（关闭或删除用 danger）；Cancel 用次级样式。
  - 规范要求"不可逆动作先确认"，这一点已经做到，缺的是层级。
- **不可达**：
  - 卡片只写 "No route available"，没有下一步建议。
  - 建议提供 "Allow stairs"、"Choose another start" 两个按钮。
  - 消息本身可以带 `role="alert"`，或通过全局播报器以 assertive 播报一次。

#### P1-5 路线卡片的 CTA 抢走主操作
- **证据**：对话中的 "View route ↗" 是整宽橙色实心按钮（`--color-destination`，`:2951`），是全屏最醒目的元素（`s-route-1440`）。但在桌面端，地图本来就在旁边，这个按钮只起滚动作用。
- **建议**：
  - 桌面端（地图可见时）改为次级的文本或描边按钮；移动端（地图不可见时）保留为主按钮。
  - "Guide me" 应该是全局唯一的主 CTA，并且出现在 next-bar。
  - 橙色只用于地图上的终点（B），不用作按钮色。

#### P1-6 聊天头部挤压
- **证据**：1440 宽下 "Your building guide" 折成三行，原因是 `.input-mode` 分段控件和标题在同一 flex 行里。
- **建议**：分两行：avatar + 标题 + 副标题一行；Text/Transcript/Voice 一行，或并入 composer。

#### P1-7 顶栏信息过载
- **证据**：顶栏有 6 组元素。768 宽下品牌和 "CURRENT BUILDING" 文字相撞（`dark-768`）。
- **建议**：
  - 主题切换收进"⋯ 设置"菜单。
  - API 状态胶囊按 P0-6 三态处理，连接正常时不占空间。
  - ≤1100px 隐藏楼栋眉标。
  - `index.html` 的 `<meta name="theme-color" content="#f6f7f3">` 固定为浅色，而默认主题是深色。建议按主题同步更新，或用 `media` 属性提供两套值。

#### P1-8 控件标签与状态不一致
- `floor-rail-toggle`：3D 展开时 `aria-pressed=true`，标签却显示 "Flat plan"（`App.tsx:502`）。改为固定标签 "3D stack" + `aria-pressed`，或改成分段控件 "Plan | 3D"。
- 楼层命名有三套：楼层轨道 `0/1`、3D 视图 `L0/L1`、标题 "Ground floor"。统一为 `L0` 风格。
- 显示模式 "Rooms / Rooms + items / Rooms + numbers" 与内部值 `labels / items / rooms` 错位，选项含义也不直观。改为两个独立开关："Show items"、"Show numbers"。
- 地图控件 "Floor" 和 "Route" 单独看语义不明，改为 "Fit floor" 和 "Fit route"。

#### P1-9 空状态与输入
- 1440 宽下空聊天栏约 580px 只有一段居中文字。建议放 2–3 个**示例问题按钮**，点击只填充 composer、不自动发送；内容不得虚构。欢迎区改为顶部对齐。
- 输入超长文本时 textarea 固定 66px，不会增高，而且显示 resize 拖拽角（`s-chat-long-input`）。建议自动增高（2→6 行），去掉 resize。
- 浅色主题下 disabled 的 Send 是淡绿底白字，可感知度低。disabled 状态统一用 `--color-surface-raised` 底 + `--color-text-tertiary` 字 + 边框，不要只靠降低透明度。

#### P1-10 主色语义过载
- lime `--color-primary` 同时承担路线、选中楼层、激活切换、高亮资产、Send、typing、编辑模式和 3D office 色调。
- 建议新增 `--color-route`，路线、图例和 3D 路线都改用它。起点（紫）和终点（橙）已有独立 token，这个做法是正确的。

### P1：可访问性

- **地标结构**：`<main className="app-shell">` 把 header 和 footer 也包在里面（`App.tsx:497`）。改为 `div.app-shell` > `header` + `main#main-content` + `footer`，并加 skip link。
- **Tab 负担**：从页首到对话输入框需要 **81 次 Tab**，其中 47 次落在地图房间多边形上；顶栏三个主题按钮还排在搜索框前面。建议：
  - 地图 SVG 改为**单一 Tab 停靠点 + 方向键漫游**（roving tabindex），Enter 选中。
  - 提供 skip links："Skip to map"、"Skip to guide"。
  - 主题切换移出顶栏后，Tab 序列也会随之缩短。
- **live region 过多**：实测同时存在 7 个，包括 zoom 百分比、map-caption（自身含按钮）、stack-info、walk-status。建议：
  - 聊天只保留 `role="log"`，typing 状态放在 log 内部。
  - map-caption、stack-info、walk-status 去掉 live 属性，改由全局 `.sr-only` 播报器（`App.tsx:513`）按需播报。
  - 缩放百分比不播报。
- **3D 展开视图**：它是全屏遮罩式视图，但不是对话框。没有 `role="dialog"`，焦点停在原按钮上，Tab 可以跑到遮罩后面。Escape 可以关闭，这一点做对了。建议补上 `role="dialog"`、`aria-modal`、焦点移入和焦点陷阱。
- **触控目标**：`.location-chip` 36px、`.chat-floor-links` 和 `.chat-choices` 按钮 38px、Reconnect 24px。在 `(pointer: coarse)` 下统一提升到 44px。
- **CSS 生成的可见文字**：Send 和 Mic 的文字来自 `::after { content }`，同时 `font-size: 0`（`:2955–2958`）。可见文字不在 DOM 中，有 WCAG 2.5.3 风险。改为在 JSX 里写真实文字。

### P1：Token 与 CSS 架构

- **追加式覆盖**：
  - 同一选择器重复定义：`.workspace`（`:792`、`:2908`）、`.guide-region`（`:1784`、`:2840`、`:2939`）、`.space.picked`（`:907`、`:2786`）、`.map-route-target`（`:2886`、`:2912`）。
  - `@media (max-width: 800px)` 出现 3 次。
  - 建议合并到各自组件段，并按 feature 拆分文件：tokens、shell、discovery、map、chat、editor。
- **脱离 token 的段落**（`:2839–2987`）：间距用了 10/12/14/18/9/7/5/6px，圆角用了 14/13/10/9/7px，字号用了 10/12/13/17/18/21/22/24px，还有 `font-weight: 800`。全部映射到 `--space-*`、`--radius-*`、`--font-size-*`。
- **硬编码颜色**：`#fff`（`:1192`）、`#17110d`（`:2951`）、`rgb(0 0 0 / 25%)`（`:2887`），以及未定义 token 的回退 `var(--color-caution, #d19a24)`（`:935`）。新增 `--color-on-start`、`--color-on-destination`、`--color-scrim`、`--color-mock-marker`。
- **死样式**（TSX 中无引用）：`.guide-panel`、`.guide-orbit`、`.guide-content`、`.listen-button`、`.transcript-next`、`.guide-thinking`、`.thinking-dots`、`.spinner`、`.ask-block`、`.ask-field`、`.route-floors`、`.assumption-list`、`.icon-button`、`.route-status-dot`。
- **外部字体**：`@import` Google Fonts（`:1`）。断网演示会回退字体并引起布局跳动；在德国还有 DSGVO 风险。建议本地自托管。

### P2：打磨

- 外壳、地图和 3D 共三层网格纹理，只保留地图内的那一层。
- 3D chunk 约 734KB 且默认加载，移动端改为按需加载（与 P0-3 A 合并）。
- 导入平面图和 Revision 收进 "Building tools" 菜单，或并入编辑模式。
- DEV 用的 "Toggle debug view" 和楼层按钮并列，移到独立的开发工具条。
- 编辑模式的区分度：在地图列顶部加一条模式横幅 "Editing · Esc to finish"，地图边框换成编辑色。
- 品牌和助手头像都用 "W"，助手改用对话图标。

---

## 5. 推荐布局模型

**桌面 ≥1100px**（`app-shell` 高 100svh，各面板内部滚动）
```
┌ Topbar: 品牌 · 楼栋选择 · 位置 chip · [⋯ 设置] ───────────────────────┐
├───────────────────────────────────────────────┬──────────────────────┤
│ [🔍 搜索 ][Browse ▾][♿]  L0 L1 [Plan|3D] [Edit] │ Guide 头（2 行）     │
│ ┌─────────────────────────────────────────┐   │ 对话流（内部滚动）   │
│ │                地图（1fr）               │   │                      │
│ │   WalkPad 限定在地图内，可折叠           │   │                      │
│ └─────────────────────────────────────────┘   │ Composer（常驻）     │
│ caption · 缩放 · 显示模式 · 图例▾              │                      │
├───────────────────────────────────────────────┴──────────────────────┤
│ Next step：当前指令             [Guide me] [Play] [12 m →] [×]        │
└──────────────────────────────────────────────────────────────────────┘
```
3D 堆叠作为 Plan/3D 切换的另一视图，占用同一块地图区域，不再追加在地图下方。

**移动 ≤650px**
```
┌ 品牌 ············ [⋯] ┐
│ [楼栋 ▾] [⌖ 位置]     │
├───────────────────────┤
│ [🔍 搜索 ] [♿]        │
│ L0 L1  [Plan|3D]      │
│ ┌───────────────────┐ │
│ │  地图 / 对话       │ │  ← 由下方切换决定
│ └───────────────────┘ │
├───────────────────────┤
│ [ Map | Guide ]        │
│ Next：当前指令  [→]    │  sticky
└───────────────────────┘
```
编辑器在移动端以 bottom sheet 形式覆盖在地图上。

## 6. 建议实施顺序

| 步骤 | 内容 | 风险 | 预估 |
|---|---|---|---|
| 1 | **P0-1** 删除 `overflow-x: hidden`，修复暴露出来的溢出 | 低，收益最大 | 1h |
| 2 | P0-4 WalkPad 改为相对地图定位 | 低 | 0.5h |
| 3 | P0-6 连接三态、加载占位、错误条和 Reconnect 样式 | 低 | 1h |
| 4 | P1-1 next-bar 状态表；P1-4 确认和不可达的按钮层级 | 低 | 1h |
| 5 | P1-2 Markdown 最小渲染；P1-3 起点同步 | 低 | 1h |
| 6 | P1-6 / P1-8 聊天头分两行，标签与状态对齐 | 低 | 0.5h |
| 7 | P0-2 app-shell 网格 + 搜索并入工具栏 + 分类和图例折叠 | 中 | 3h |
| 8 | P0-3 移动端 Map/Guide 切换 + 编辑器 bottom sheet | 中 | 3h |
| 9 | 地标、skip link、地图 roving tabindex、live region 收敛、3D 对话框语义 | 中 | 2h |
| 10 | CSS 去重、拆文件、聊天段 token 化、删死样式、字体自托管 | 低（目标是截图零差异） | 2–3h |

第 10 步单独成一个 PR，以截图零差异为验收标准。

## 7. 验证计划

把本次的脚本迁入 `frontend/e2e/`（目前它们在仓库外的 `D:\tmp\uxshots\`），作为回归检查。至少包含以下断言：

- 五个宽度 × 两种主题截图；`scrollWidth == clientWidth`，**且所有可交互元素满足 `left >= 0`、`right <= innerWidth`**（测试时不要有 overflow 兜底）。
- 滚动 900px 后，顶栏、聊天栏和 next-bar 的位置符合 P0-1 的验收标准。
- `.plan-wrap` 顶部 < 0.45 × 视口高；桌面端 composer 在首屏内。
- WalkPad 与工具栏不相交；路线状态下 axe 0 违规。
- 从页首 Tab 到 composer 不超过 25 次。
- 加载中不出现 "disconnected" 和 "fixture" 字样。
- 状态覆盖：初始、加载、失败与 Reconnect、起点抽屉、A→B 路线、Step-free 重算、clarify、unreachable、pending、编辑器（桌面和移动）、长名称（320 宽）。

## 附：截图索引（`D:\tmp\uxshots\`）

| 文件 | 内容 |
|---|---|
| `{dark,light}-{320,390,768,1024,1440}.png`、`*-full.png` | 第 1 轮布局 |
| `s-drawer-1440.png`、`s-drawer-empty.png` | 起点抽屉 |
| `s-discover-*.png`、`s-startpick-*.png`、`s-route-*.png`、`s-stepfree-*.png` | A→B 路线流程 |
| `s-chat-sending.png`、`s-chat-reply.png`、`x-reply-card.png`、`s-chat-long-input.png` | 对话 |
| `s-fx-clarify.png`、`s-fx-unreachable.png`、`s-fx-pending.png` | 澄清、不可达、待确认 |
| `s-editor-1440.png`、`s-editor-item.png`、`s-editor-390-full.png`、`x-mobile-editor.png` | 编辑器 |
| `x-loading.png`、`s-error-{1440,390}.png` | 加载、失败 |
| `s-long-{1440,320}.png` | 长名称 |
| `s-voice-1440.png`、`s-transcript-1440.png` | 语音、转写 |
| `s-stack-expanded.png`、`x-scroll-900.png` | 3D 展开、滚动后 sticky 失效 |

---

## 8. 修复记录（2026-10-25）

### 8.1 验证结果

- `npm run build` 通过，`tsc -b` 无错误。
- `test:effects`、`test:walk`、`test:live`、`test:voice`、`test:perimeter`、`test:editor` 全部通过。
- 新增 `e2e/layout_check.py`（`npm run test:layout`），覆盖第 7 节列出的断言，结果 **92/92 通过**。范围：五个宽度 × 两种主题，加路线、键盘、加载、失败与 Reconnect、手机编辑器、320 宽长名称；需要开发服务器和 API 在运行。
- 另有一个补充脚本 `D:\tmp\uxshots\states2.py`（在仓库外），跑了以下状态，结果都符合预期：不可达 / 待确认 fixture、真实 Agent 回复、Step-free 重算、方向键漫游、3D 对话框、语音 / 转写、手机端 "Show on map"。
- `e2e/smoke.py` 在修改**之前就已失败**：它等待 `networkidle`，但引导 feed 是长轮询，这个状态永远不会到来；它的一些文案断言也早已过时。这次没有修它，回归检查以 `layout_check.py` 为准。

| 指标 | 修复前 | 修复后 |
|---|---|---|
| 地图顶部 y（320 / 390 / 1024 / 1440） | 730 / 626 / 599 / 409 | 309 / 309 / 204 / 204 |
| 1440×900 对话输入框底边 | 1000 以上（在首屏外） | 836（在首屏内） |
| 1024×768 对话输入框底边 | 在首屏外 | 704 |
| 页面级滚动 | 整页滚动，sticky 全部失效 | 页面本身不滚动，各面板内部滚动 |
| 从页首 Tab 到输入框 | 81 次（地图多边形占 47 次） | 33 次（地图占 1 次）；经 "Skip to guide" 只需 9 次 |
| 同时存在的 live region | 7 个 | 3–4 个（全局播报、对话 log、行走状态；语音模式下多一个 voice-pill） |
| 移动端打开编辑器后面板位置 | y=1957，视口外 | 以底部面板形式出现在视口内（y≈416） |
| 320 宽 + 长名称 | 整页向左偏移 | 没有元素越出视口 |
| axe（各宽度 + 路线态 + 语音） | 390 宽路线态有 1 个 serious | 0 |

### 8.2 逐项状态

| 条目 | 状态 | 实施方式 |
|---|---|---|
| P0-1 sticky 失效 | ✅ | 删除 `html` / `body` / `.app-shell` 上的 `overflow-x: hidden`。外壳改为一屏高的 grid（`100dvh`），页面不再整体滚动；顶栏和 next-bar 固定在各自的网格行，地图列和对话各自内部滚动。 |
| P0-2 首屏地图与输入框 | ✅ | 搜索框并入地图列，成为一行；分类浏览改为 "Browse" 浮层，不再推开地图。图例改为工具行里的开关，面板默认收起。地图用 `contain: size` 填满剩余空间，最小 300px。 |
| P0-3 移动端主交互 | ✅ | ≤800px 时底部出现 "Map / Guide" 切换，Guide 按钮带未读数。编辑器在手机上以底部面板（bottom sheet）形式覆盖地图下半部。"Show on map" 切回地图视图。⚠️ ≤1100px 时 3D 堆叠默认收起。 |
| P0-4 WalkPad 遮挡 | ✅ | 不再通过 portal 挂到 `body`，改为渲染在地图内部，坐标相对地图计算，`ResizeObserver` 让它始终留在地图边界内。⚠️ 默认折叠成一个 "Show" 按钮；位置记忆的存储键升级为 `wayfinder-walk-pad-v2`。 |
| P0-5 窄屏和长名称溢出 | ✅ | 去掉 overflow 兜底；顶栏在 ≤650px 时允许换行；Step-free 在 ≤480px 时只显示开关（可访问名称保留）；位置 chip 和楼栋选择加 `title` 显示全名。 |
| P0-6 加载 / 失败的虚假状态 | ✅ | 连接分为 connecting / connected / offline / local 四态，正常连接时不显示状态胶囊。加载中显示 "Loading building…"，离线时显示 "Plan unavailable"，不再出现 fixture 楼层名。错误条先写消息，再给样式化的 Reconnect（已连接时给 Dismiss），错误码和 trace 收进 Details。 |
| P1-1 next-bar 状态 | ✅ | 按状态表输出。有路线时 Guide me 是唯一的实心主按钮；不可达时提供 Allow stairs（仅当开启了 Step-free）和 Choose another start；无路线时只提供 Set your location；未连接时不显示任何操作。 |
| P1-2 Markdown | ✅ 前端 | 新增 `RichText`，只支持 `**bold**` 和 `` `code` ``，不解析 HTML。后端输出格式没有改。 |
| P1-3 重复与不同步 | ✅ | 回复正文已有编号步骤时，路线卡片不再显示 Directions 折叠（按文本识别，属于启发式）。Step-free 重算的消息前加 "Step-free route:" / "Stairs allowed:"。起点统一为"选择的地点，否则取路线起点"，chip、caption 和 Route here 都使用它。⚠️ Route here 现在会沿用 Agent 推断出的起点。 |
| P1-4 确认与不可达 | ✅ | Confirm 是实心按钮，关闭 / 删除类动作用 danger 色，Cancel 是次级按钮。不可达卡片带恢复按钮。⚠️ 切换 Step-free 时，不可达路线也会重新计算（原来只重算可达路线）。 |
| P1-5 路线卡片 CTA | ✅ | "Show on map" 在桌面是描边按钮，在 ≤800px 是主按钮；橙色只留给地图上的终点。 |
| P1-6 聊天头部 | ✅ | 改为两行：标题一行，输入方式一行；头像换成对话图标。 |
| P1-7 顶栏 | ✅ | 主题切换收进 "⋯ Settings"（`SettingsMenu`，支持 Escape 和点击外部关闭）。`theme-color` 跟随实际主题。≤1100px 隐藏楼栋眉标。 |
| P1-8 标签与状态 | ✅ | 固定标签 "3D stack" + `aria-pressed`；楼层统一为 `L0` / `L1`；显示模式改为 "Items"、"Room numbers" 两个独立开关；地图控件改为 "Fit route" / "Fit floor"。 |
| P1-9 空状态与输入 | ✅ | 欢迎区按当前楼栋**实际存在的房间类型**给出示例问题，点击只填充输入框、不发送。输入框随内容自动增高（66→160px）。disabled 状态统一为"去填充 + 边框"。 |
| P1-10 主色过载 | ✅ | 新增 `--color-route`，路线、图例、3D 路线、引导环都改用它。 |
| A11y：地标 / skip link | ✅ | 外层改为 `div.app-shell`，内部是 `header` + `main#main-content` + `footer`；新增 "Skip to map"、"Skip to guide"。 |
| A11y：Tab 负担 | ✅ | 房间多边形只保留一个 Tab 停靠点（roving tabindex），方向键 / Home / End 在房间之间移动，并阻止事件冒泡，避免 WalkPad 同时响应；编辑器可拖动物件时，方向键仍交给编辑器。 |
| A11y：live region | ✅ | 移除 map-caption、stack-info、缩放百分比上的 live 属性；聊天只保留 `role="log"`；WalkPad 只保留一个隐藏的状态播报。 |
| A11y：3D 展开 | ✅ | 展开时加 `role="dialog"`、`aria-modal`、焦点陷阱，Escape 关闭。 |
| A11y：触控目标 / CSS 文字 | ✅ | 在 `(pointer: coarse)` 下统一 44px；Send、Dictate 改为 JSX 中的真实文字，可见文字包含在可访问名称里。 |
| Token 与 CSS 架构 | ✅ | `styles.css`（2987 行）拆成 `styles/` 下 10 个文件：tokens、base、shell、discovery、map、stack、import、guide、editor、index。重复定义和追加覆盖都已合并；聊天和抽屉部分全部改用 token；硬编码颜色改为 `--color-on-start`、`--color-on-destination`、`--color-scrim`、`--map-mock-marker`、`--shadow-pin`；删除死样式和未使用的 `FloorStack.tsx`。 |
| 外部字体 | ✅ | 改用 `@fontsource/*` 本地打包，不再向 Google 发请求。 |
| P2 网格 / Debug / 编辑横幅 / 头像 | ✅ | 只有地图保留网格；Debug 按钮改为虚线描边、显示文字 "Debug"（可访问名称不变）；编辑模式在地图上方显示 "Editing the map · Esc to finish" 横幅。 |

### 8.3 与原建议的偏差

- **Tab 验收标准**：原定"≤25 次"。实际自然顺序是 33 次，其中包括 2 个 skip link、顶栏 4 个、工具栏 4 个、搜索 3 个、地图工具 6 个、3D 控件 5 个。真正的改进来自 roving tabindex 和 skip link（9 次即可到达输入框），所以测试改为"自然顺序 ≤35，经 skip link ≤12"。
- **"Simulate walk" 开关**：没有新增这个开关，改为让 WalkPad 默认折叠，效果相同：不遮挡地图、只占 1 个 Tab 停靠点。
- **Plan | 3D 互斥视图**：没有采用。3D 仍然在地图下方、地图列的滚动区内显示，保留了原来"平面和 3D 同时可见"的行为。
- **"Building tools" 菜单**：没有新建菜单。导入和 Revision 放在地图列滚动区的末尾，不占首屏。
- **步骤去重**：只在前端完成，通过识别编号列表实现。Agent 输出格式需要后端另行约定。

### 8.4 并行改动说明

修复期间，另一个会话在同一工作区新增了 "Campus walkway" 功能：`features/campus/CampusWalkway.tsx`、`gateway.ts` 中的 campus 接口，以及 `shell.css` 里的 `.campus-*` 样式。它在顶栏增加了一个按钮，因此 ≤650px 时顶栏第二行要放 3 个元素，在 320 宽下会折成两行；这已计入上表的测量结果，并且仍满足"地图顶部 ≤ 视口 45%"。这部分代码保留原样，没有改动。

### 8.5 未覆盖

- 真实的语音识别和 TTS 听感。
- 真实触屏设备。
- 导入平面图的完整流程。
- 多楼层路线：测试楼栋中没有稳定的触发入口。
