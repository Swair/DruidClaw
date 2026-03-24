# DruidClaw 界面元素文档

## 概述

DruidClaw 是一个基于 Web 的 Claude Code 远程管理界面，采用深色科技主题设计。

## 目录结构

```
druidclaw/web/static/
├── index.html      # 主界面
├── login.html      # 登录页面
├── style.css       # 样式定义
├── main.js         # 主逻辑
├── connections.js  # 服务器连接管理
├── ssh_terminal.js # SSH 终端
├── claude_session.js # Claude 会话
└── local_terminal.js # 本地终端
```

---

## 1. 登录页面 (login.html)

| 元素 | 类型 | ID/Class | 说明 |
|------|------|----------|------|
| 登录框 | div | `.box` | 深色卡片容器 |
| 标题 | h2 | - | "🐻 DruidClaw" |
| 说明文字 | p | - | "请输入访问令牌" |
| 密码输入 | input | `name="token"` | 访问令牌输入框 |
| 登录按钮 | button | `type="submit"` | 提交登录表单 |
| 错误提示 | - | `{error}` | 动态插入的错误消息 |

---

## 2. 主界面布局 (index.html)

### 2.1 整体结构

```
┌─────────────────────────────────────────────────────┐
│                      Header                         │
├─────────────────────────────────────────────────────┤
│                    Server Bar                       │
├───────────┬─────────────────────────┬───────────────┤
│  Sidebar  │     Terminal Area       │ Skills Sidebar│
│  (Cards)  │     (Main Content)      │ (Right Panel) │
└───────────┴─────────────────────────┴───────────────┘
```

### 2.2 Header 头部区域

| 元素 | 类型 | ID | 说明 |
|------|------|-----|------|
| Logo | img | - | `/static/logo.png` |
| 标题 | h1 | - | "DruidClaw" |
| 分隔线 | div | `.sep` | 垂直分隔线 |
| 副标题 | span | - | "Claude Code OS Shell" |
| CC 终端标签 | button | `#tab-cc` | 切换到 Claude Code 终端 |
| IM 频道标签 | button | `#tab-feishu` | 切换到 IM 消息频道 |
| 历史标签 | button | `#tab-history` | 查看会话历史总结 |
| 飞书状态点 | span | `#feishu-dot` | 飞书消息提示点 |
| 飞书标签 | span | `#feishu-label` | "飞书" 文字 |
| Skills 市场按钮 | button | `.inst-btn` | 打开 Skills 市场 |
| MCP 市场按钮 | button | `.inst-btn` | 打开 MCP 市场 |
| Prompt 模板按钮 | button | `.inst-btn` | 打开 Prompt 模板管理 |
| 安装配置按钮 | button | `.inst-btn` | Claude Code 安装/配置 |
| 主题切换按钮 | button | `#theme-btn` | 切换明暗主题 |
| 语言切换按钮 | button | `#lang-btn` | 切换中/英文 |
| 状态面板按钮 | button | `#log-btn` | 打开日志/统计面板 |
| 状态徽章 | span | `#log-badge` | 未读消息数 |
| 服务器设置按钮 | button | `.tbtn` | 当前服务器配置 |
| 退出按钮 | button | `.tbtn` | 退出登录 |

### 2.3 Server Bar 服务器连接栏

| 元素 | 类型 | ID | 说明 |
|------|------|-----|------|
| 服务器标签 | button | `.srv-tab` | 显示已连接的服务器 |
| 状态点 | span | `.dot` | 绿色=正常，红色=错误，黄色=等待 |
| 关闭按钮 | span | `.x` | 断开连接 |
| 添加服务器 | div | `.srv-add` | 打开添加服务器对话框 |

### 2.4 Sidebar 侧边栏（卡片列表）

| 元素 | 类型 | ID | 说明 |
|------|------|-----|------|
| 卡片头部 | div | `.cards-hdr` | 卡片区域标题 |
| 卡片标题 | span | `.cards-hdr-title` | "卡片" |
| 新建卡片按钮 | button | `.cards-add-btn` | 打开新建卡片对话框 |
| 卡片列表 | div | `#cards-list` | 动态插入的卡片项 |
| 空状态提示 | div | `.cards-empty` | "暂无卡片" |
| 调整宽度手柄 | div | `#sidebar-resize` | 拖动调整侧边栏宽度 |

### 2.5 Terminal Area 终端区域

| 元素 | 类型 | ID | 说明 |
|------|------|-----|------|
| 折叠侧栏按钮 | button | `.toggle-sidebar` | "☰" 折叠/展开侧栏 |
| 终端名称 | span | `#t-name` | 显示当前终端名称 |
| 进程 ID | span | `#t-pid` | 显示进程 ID |
| 终端徽章 | span | `#t-badge` | 状态徽章 |
| 清屏按钮 | button | `#t-clear` | 清空终端屏幕 |
| 终止按钮 | button | `#t-kill` | 终止当前会话 |
| 定时任务按钮 | button | `.tbtn` | 打开定时任务管理 |
| Skills 面板按钮 | button | `.toggle-skills` | "🧙‍♂️" 打开 Skills |
| Prompt 模板按钮 | button | `.toggle-skills` | "📝" 打开 Prompt |
| 终端容器 | div | `#term-wrap` | xterm.js 终端容器 |
| 空状态 | div | `#term-empty` | "选择或新建会话"提示 |
| 飞书视图 | div | `#feishu-view` | 飞书消息日志 |
| 飞书页面 | div | `#feishu-page` | 飞书配置页面 |
| 历史页面 | div | `#history-page` | 会话历史总结页面 |

### 2.6 Right Sidebar 右侧边栏（Skills/Prompts/History）

| 元素 | 类型 | ID | 说明 |
|------|------|-----|------|
| Skills 标签 | button | `#sk-tab-skills` | Skills 面板 |
| Prompt 标签 | button | `#sk-tab-prompts` | Prompt 模板面板 |
| 历史标签 | button | `#sk-tab-history` | 用户提问历史面板 |
| Skills 头部 | div | `.skills-hdr` | Skills 区域标题 |
| Skills 列表 | div | `#skills-list` | Skills 列表 |
| Prompt 搜索框 | input | `#prompt-search` | 搜索 Prompt 模板 |
| Prompt 列表 | div | `#prompt-list` | Prompt 模板列表 |
| 历史列表 | div | `#history-list` | 用户提问历史列表 |

---

## 3. 对话框/模态框

### 3.1 Skills 市场 (mkt-overlay)

| 元素 | 类型 | ID | 说明 |
|------|------|-----|------|
| 市场标签页 | div | `#mkt-src-tabs` | 市场源切换 |
| URL 输入框 | input | `#mkt-url` | marketplace.json URL |
| 加载按钮 | button | `.mkt-btn` | 加载 URL |
| 搜索框 | input | `#mkt-search` | 搜索插件 |
| 插件网格 | div | `#mkt-grid` | 插件卡片网格 |
| 安装日志 | div | `#mkt-log` | 安装进度日志 |
| 状态栏 | span | `#mkt-status` | 状态消息 |

### 3.2 MCP 市场 (mcp-overlay)

| 元素 | 类型 | ID | 说明 |
|------|------|-----|------|
| 已安装列表 | div | `#mcp-installed-list` | 已安装的 MCP 服务 |
| 名称输入 | input | `#mcp-add-name` | 自定义添加名称 |
| 命令输入 | input | `#mcp-add-command` | 命令 (如 npx) |
| 参数输入 | input | `#mcp-add-args` | 参数 (空格分隔) |
| 环境变量 | input | `#mcp-add-env` | JSON 格式环境变量 |
| 预设网格 | div | `#mcp-preset-grid` | 常用 MCP 服务预设 |

### 3.3 Prompt 模板管理 (prompt-mgmt-overlay)

| 元素 | 类型 | ID | 说明 |
|------|------|-----|------|
| 搜索框 | input | `#pm-search` | 搜索模板 |
| 模板列表 | div | `#pm-list` | 模板列表 |
| 名称输入 | input | `#pe-name` | 模板名称 |
| 提示词框 | textarea | `#pe-prompt` | Prompt 内容 |
| 清空按钮 | button | `.mkt-btn` | 清空表单 |
| 保存按钮 | button | `.mkt-btn primary` | 保存模板 |

### 3.4 安装/配置 (install-overlay)

| 元素 | 类型 | ID | 说明 |
|------|------|-----|------|
| 状态网格 | div | `#inst-status-grid` | 环境检测状态 |
| 检测环境按钮 | button | `#inst-check-btn` | 检测环境 |
| 安装 Node 按钮 | button | `#inst-node-btn` | 安装 Node.js |
| 安装 Claude 按钮 | button | `#inst-claude-btn` | 安装 Claude Code |
| 更新 Claude 按钮 | button | `#inst-update-btn` | 更新 Claude Code |
| 进度日志 | div | `#inst-log` | 操作日志 |
| API Key 输入 | input | `#inst-apikey` | Anthropic API Key |
| Base URL 输入 | input | `#inst-base-url` | API Base URL |
| 模型输入 | input | `#inst-model` | 模型名称 |
| 可执行路径 | input | `#inst-bin` | Claude 可执行文件路径 |

### 3.5 状态面板 (status-panel-overlay)

| 元素 | 类型 | ID | 说明 |
|------|------|-----|------|
| 日志标签 | div | `.sp-tab` | 日志面板 |
| 统计标签 | div | `.sp-tab` | Token 统计面板 |
| 趋势标签 | div | `.sp-tab` | 趋势图面板 |
| 日志数量 | span | `#sp-log-count` | 日志条目数 |
| 清空按钮 | button | `.mbtn` | 清空日志 |
| 自动滚动 | input | `#sp-log-auto` | 自动滚动复选框 |
| 日志条目 | div | `#sp-log-entries` | 日志列表 |
| 统计网格 | div | `#sp-stats-grid` | Token 统计网格 |
| 天数选择 | select | `#sp-trend-days` | 趋势图天数 (7/14/30) |
| 图表画布 | canvas | `#sp-chart` | Chart.js 趋势图 |

### 3.6 新建卡片 (new-card-modal)

| 元素 | 类型 | ID | 说明 |
|------|------|-----|------|
| Claude 类型按钮 | div | `#nc-t-claude` | Claude 会话类型 |
| 会话名称 | input | `#nc-name` | 会话名称 (auto) |
| 工作目录 | input | `#nc-workdir` | 工作目录 |
| 参数输入 | input | `#nc-args` | Claude 参数 |
| 自动启动 | input | `#nc-autostart` | 创建后启动复选框 |

### 3.7 定时任务 (tasks-modal)

| 元素 | 类型 | ID | 说明 |
|------|------|-----|------|
| 任务列表 | div | `#task-list` | 任务列表 |
| 新建任务按钮 | button | `.mbtn ok` | 打开任务表单 |
| 任务表单 | div | `#task-form` | 添加/编辑表单 |
| 任务 ID | input | `#tf-id` | 任务 ID (隐藏) |
| 任务名称 | input | `#tf-name` | 任务名称 |
| 目标 Session | input | `#tf-session` | 目标会话 |
| 提词内容 | textarea | `#tf-prompt` | 发送内容 |
| 间隔触发 | input | `type="radio"` | 间隔触发单选 |
| Cron 触发 | input | `type="radio"` | Cron 表达式单选 |
| 间隔输入 | input | `#tf-interval` | 分钟数 |
| Cron 输入 | input | `#tf-cron` | Cron 表达式 |

### 3.8 新建 IM 配置 (new-im-modal)

| 元素 | 类型 | ID | 说明 |
|------|------|-----|------|
| 飞书类型按钮 | div | `#im-t-feishu` | 飞书类型 |
| Telegram 按钮 | div | `#im-t-telegram` | Telegram 类型 |
| 钉钉按钮 | div | `#im-t-dingtalk` | 钉钉类型 |
| QQ 按钮 | div | `#im-t-qq` | QQ 类型 |
| 企业微信按钮 | div | `#im-t-wework` | 企业微信类型 |
| 名称输入 | input | 各平台对应 ID | 机器人名称 |
| App ID/Key | input | 各平台对应 ID | 应用凭证 |
| Secret | input | `type="password"` | 应用密钥 |
| 延迟输入 | input | `type="number"` | 回复延迟 (秒) |

### 3.9 添加/编辑服务器 (srv-modal)

| 元素 | 类型 | ID | 说明 |
|------|------|-----|------|
| HTTP 类型按钮 | div | `#ct-http` | Claude Code 连接 |
| 本地终端按钮 | div | `#ct-local` | 本地终端连接 |
| SSH 类型按钮 | div | `#ct-ssh` | SSH 远程连接 |
| Shell 输入 | input | `#local-shell` | 本地 Shell 路径 |
| 显示名称 | input | `#m-label` / `#ssh-label` | 连接名称 |
| 主机输入 | input | `#m-host` / `#ssh-host` | IP 地址 |
| 端口输入 | input | `#m-port` / `#ssh-port` | 端口号 |
| SSH 用户 | input | `#ssh-user` | SSH 用户名 |
| SSH 密码 | input | `#ssh-pass` | SSH 密码 |
| SSH 密钥 | textarea | `#ssh-key` | SSH 私钥 |
| 历史列表 | div | `#ssh-hist-list` | SSH 历史连接 |

### 3.10 服务器配置 (cfg-modal)

| 元素 | 类型 | ID | 说明 |
|------|------|-----|------|
| 基础配置标签 | div | `#cfg-tab-basic` | 基础配置 |
| 文件配置标签 | div | `#cfg-tab-files` | 文件目录配置 |
| 主机输入 | input | `#c-host` | 监听主机 |
| 端口输入 | input | `#c-port` | 监听端口 |
| 保存按钮 | button | `.mbtn` | 仅保存配置 |
| 重启按钮 | button | `.mbtn ok` | 保存并重启 |

---

## 4. CSS 样式类

### 4.1 颜色变量

```css
--bg:         #0a0e1a   /* 背景色 */
--bg2:        #0f1629   /* 次要背景 */
--bg3:        #151f36   /* 第三背景 */
--border:     #1e3a5f   /* 边框色 */
--text:       #e8f1ff   /* 文字色 */
--muted:      #6b7c99   /* 弱化文字 */
--blue:       #00d4ff   /* 主色调 */
--green:      #00ff88   /* 成功色 */
--yellow:     #ffaa00   /* 警告色 */
--red:        #ff4757   /* 错误色 */
```

### 4.2 主要组件样式

| 样式类 | 说明 |
|--------|------|
| `.header` | 顶部导航栏 |
| `.server-bar` | 服务器标签栏 |
| `.srv-tab` | 服务器标签 |
| `.srv-tab.active` | 激活的标签 |
| `.dot-ok` | 绿色状态点 |
| `.dot-err` | 红色错误点 |
| `.dot-wait` | 黄色等待点 |
| `.dot-busy` | 绿色忙碌点 |
| `.sidebar` | 左侧卡片栏 |
| `.sidebar-resize` | 调整宽度手柄 |
| `.cards-hdr` | 卡片区域头部 |
| `.cards-list` | 卡片列表容器 |
| `.term-area` | 终端区域 |
| `.term-toolbar` | 终端工具栏 |
| `.skills-sidebar` | 右侧边栏 |
| `.sk-tabs` | 右侧标签页 |
| `.right-pane` | 右方面板 |
| `.overlay` | 模态框遮罩 |
| `.modal` | 模态框容器 |
| `.mbtn` | 模态框按钮 |
| `.mbtn.ok` | 确认按钮 (绿色) |
| `.inst-btn` | 工具按钮 |
| `.tbtn` | 工具栏按钮 |
| `.theme-btn` | 主题切换 |
| `.lang-btn` | 语言切换 |
| `.log-btn` | 日志按钮 |
| `.log-badge` | 日志徽章 |

---

## 5. JavaScript 主要函数

### 5.1 导航与标签

| 函数 | 说明 |
|------|------|
| `switchTab(tab)` | 切换主标签页 (cc/feishu/history) |
| `switchRightTab(tab)` | 切换右侧标签 (skills/prompts/history) |
| `activeSrv()` | 获取当前激活的服务器 |

### 5.2 服务器管理

| 函数 | 说明 |
|------|------|
| `openAddServer()` | 打开添加服务器对话框 |
| `closeSrvModal(ev)` | 关闭服务器对话框 |
| `selectConnType(type)` | 选择连接类型 (http/local/ssh) |
| `renderServerBar()` | 渲染服务器标签栏 |

### 5.3 会话管理

| 函数 | 说明 |
|------|------|
| `refreshSessions()` | 刷新会话列表 |
| `renderSessionList()` | 渲染会话列表 |
| `connectSession(srv, name)` | 连接到会话 |
| `killSession(ev, name)` | 终止会话 |
| `startRename(item, oldName)` | 开始重命名 |
| `commitRename(oldName, newName)` | 提交重命名 |

### 5.4 终端操作

| 函数 | 说明 |
|------|------|
| `clearTerm()` | 清空终端 |
| `killActive()` | 终止当前终端进程 |
| `toggleSidebar()` | 折叠/展开侧栏 |

### 5.5 模态框操作

| 函数 | 说明 |
|------|------|
| `openNewCardModal()` | 打开新建卡片 |
| `closeNewCardModal(ev)` | 关闭新建卡片 |
| `openTasksModal()` | 打开定时任务 |
| `closeTasksModal(ev)` | 关闭定时任务 |
| `openInstallModal()` | 打开安装配置 |
| `closeInstallModal(ev)` | 关闭安装配置 |
| `openStatusPanel()` | 打开状态面板 |
| `closeStatusPanel(ev)` | 关闭状态面板 |
| `openSrvSettings()` | 打开服务器设置 |

### 5.6 市场与技能

| 函数 | 说明 |
|------|------|
| `openMarketplace()` | 打开 Skills 市场 |
| `closeMkt(ev)` | 关闭市场 |
| `mktFilter()` | 市场搜索过滤 |
| `mktLoadUrl()` | 加载 URL |
| `openMcpModal()` | 打开 MCP 市场 |
| `closeMcpModal(ev)` | 关闭 MCP 市场 |
| `openPromptMgmt()` | 打开 Prompt 管理 |
| `closePromptMgmt(ev)` | 关闭 Prompt 管理 |

### 5.7 工具函数

| 函数 | 说明 |
|------|------|
| `toast(msg, isError)` | 显示提示消息 |
| `toggleTheme()` | 切换明暗主题 |
| `toggleLang()` | 切换语言 |
| `t(key)` | 国际化翻译函数 |

---

## 6. 页面状态指示

### 6.1 会话状态

| 状态 | 样式类 | 说明 |
|------|--------|------|
| 连接中 | `dot-wait` | 黄色闪烁 |
| 正常 | `dot-ok` | 绿色常亮 |
| 错误 | `dot-err` | 红色常亮 |
| 忙碌 | `dot-busy` | 绿色闪烁 |

### 6.2 服务器状态

| 状态 | 说明 |
|------|------|
| ok | 连接正常 |
| err | 连接失败 |
| wait | 等待响应 |

---

## 7. 响应式布局

- 侧边栏宽度：`240px` (可调整范围 150px - 500px)
- 头部高度：`40px`
- 服务器栏高度：`36px`
- 最小窗口：由浏览器决定，内容使用 flex 布局自适应

---

## 8. 主题支持

### 8.1 暗色主题 (默认)

背景色深，文字亮色，蓝色高亮带有发光效果。

### 8.2 亮色主题

通过 `:root.light` 类切换，背景色浅，文字深色，无发光效果。
