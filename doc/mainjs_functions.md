# DruidClaw main.js 函数注释

## 用户交互触发函数

这些函数由用户的鼠标点击、键盘输入等交互行为触发：

### 连接管理
| 函数 | 触发时机 |
|------|----------|
| `selectConnType(type)` | 用户点击连接类型选项卡 (HTTP/本地/SSH) |
| `openAddServer()` | 用户点击"+"按钮打开添加服务器对话框 |
| `commitServer()` | 用户点击"连接"按钮提交连接 |
| `loadSshHistory()` | 用户切换到 SSH 选项卡时加载历史 |
| `fillSshForm(h)` | 用户点击 SSH 历史记录项填充表单 |
| `deleteSshHistory(idx)` | 用户点击删除 SSH 历史记录 |
| `addServer(host, port, label)` | 用户添加新的 HTTP 服务器 |
| `switchServer(id)` | 用户点击服务器标签切换 |
| `removeServer(id)` | 用户点击"✕"按钮删除服务器 |

### 本地终端
| 函数 | 触发时机 |
|------|----------|
| `connectLocalShell()` | 用户从模态框创建本地终端 |
| `addLocalSessionToCurrentServer()` | 用户点击"新建本地终端"快捷按钮 |
| `openLocalTerminal(srv, name, ...)` | 用户打开本地终端 |

### SSH 终端
| 函数 | 触发时机 |
|------|----------|
| `connectSSH()` | 用户从模态框创建 SSH 连接 |
| `openSshTerminal(srv, name, ...)` | 用户打开 SSH 终端 |

### Claude Code 会话
| 函数 | 触发时机 |
|------|----------|
| `createSession()` | 用户点击"新建会话"按钮 |
| `killActive()` | 用户点击"终止"按钮 |
| `connectSession(srv, name)` | 用户点击会话连接 |
| `killSessionByName(srvId, name)` | 用户删除会话 |

### 服务器设置
| 函数 | 触发时机 |
|------|----------|
| `openSrvSettings()` | 用户点击"服务器设置"按钮 |
| `saveConfigOnly()` | 用户点击"保存配置"按钮 |
| `saveAndRestart()` | 用户点击"保存并重启"按钮 |

### 会话管理
| 函数 | 触发时机 |
|------|----------|
| `refreshSessions()` | 用户点击"刷新"按钮 |
| `killSession(ev, name)` | 用户点击会话的"终止"按钮 |
| `startRename(item, oldName)` | 用户点击"重命名"按钮 |
| `commitRename(oldName, newName)` | 用户提交重命名 |

### 终端操作
| 函数 | 触发时机 |
|------|----------|
| `clearTerm()` | 用户点击"清屏"按钮 |
| `toggleSidebar()` | 用户点击侧边栏切换按钮 |

### 飞书/IM 机器人
| 函数 | 触发时机 |
|------|----------|
| `openFeishuModal()` | 用户点击"飞书配置"按钮 |
| `feishuSaveAndConnect()` | 用户点击"保存并连接"飞书 |
| `feishuDisconnect()` | 用户点击"断开"飞书连接 |
| `bridgeSave()` | 用户保存桥接配置 |

### 卡片管理
| 函数 | 触发时机 |
|------|----------|
| `loadCards()` | 页面加载时获取卡片列表 |
| `renderCards()` | 渲染卡片列表 |
| `cardStart(card)` | 用户点击卡片的"启动"按钮 |
| `cardStop(card)` | 用户点击卡片的"停止"按钮 |
| `cardDelete(card)` | 用户点击卡片的"删除"按钮 |
| `cardRestart(card)` | 用户点击卡片的"重启"按钮 |
| `openCardConfig(card)` | 用户点击卡片的"配置"按钮 |
| `submitNewImCard()` | 用户提交新建 IM 卡片 |

### 技能市场
| 函数 | 触发时机 |
|------|----------|
| `openSkillsMarket()` | 用户点击"技能市场"按钮 |
| `installSkill(skillId)` | 用户点击"安装"技能 |
| `uninstallSkill(skillId)` | 用户点击"卸载"技能 |

### Prompt 模板
| 函数 | 触发时机 |
|------|----------|
| `openPromptModal()` | 用户点击"Prompt 模板"按钮 |
| `applyPrompt(promptText)` | 用户点击应用 Prompt |
| `sendPrompt(promptText)` | 用户发送 Prompt 到会话 |

### MCP 市场
| 函数 | 触发时机 |
|------|----------|
| `openMcpMarket()` | 用户点击"MCP 市场"按钮 |
| `installMcpServer(mcpId)` | 用户点击"安装"MCP 服务器 |
| `uninstallMcpServer(mcpId)` | 用户点击"卸载"MCP 服务器 |

### 历史记录
| 函数 | 触发时机 |
|------|----------|
| `openHistoryPage()` | 用户点击"历史记录"按钮 |
| `loadHistory()` | 加载历史记录 |
| `deleteHistoryItem(id)` | 用户删除历史记录项 |

### 主题切换
| 函数 | 触发时机 |
|------|----------|
| `toggleTheme()` | 用户点击主题切换按钮 |

---

## 内部调用函数（非用户直接触发）

这些函数由其他函数内部调用，或作为回调/定时器触发：

### 工具函数
- `srvById(id)` - 根据 ID 查找服务器
- `activeSrv()` - 获取当前活跃的服务器
- `srvBase(srv)` - 获取服务器的基础 URL
- `wsUrl(srv, name)` - 获取 WebSocket URL
- `esc(s)` - HTML 转义

### 渲染函数
- `renderServerBar()` - 渲染服务器列表
- `renderSessionList()` - 渲染会话列表
- `renderCards()` - 渲染卡片列表
- `buildCardEl(card)` - 构建卡片元素
- `buildSessionCardEl(srv, name, sess)` - 构建会话卡片

### 状态管理
- `saveSessionsToStorage()` - 保存会话到 sessionStorage
- `restoreSessionsFromStorage()` - 从 sessionStorage 恢复会话

### 定时器/轮询
- `_startFeishuPoll()` - 启动飞书事件轮询
- `_stopFeishuPoll()` - 停止飞书事件轮询
- `_feishuPollTick()` - 飞书轮询 tick
- `_startCardPoll()` - 启动卡片轮询
- `_cardPollTick()` - 卡片轮询 tick

### 终端辅助
- `_getTerminalConstructors()` - 获取终端构造函数
- `_xtermTheme()` - 获取 xterm 主题
- `safeFit(srv, name)` - 安全地调整终端大小
- `restoreTerminal()` - 恢复终端显示

---

## 文件结构

```
druidclaw/web/static/
├── main.js           # 主前端逻辑 (4549 行)
├── style.css         # 样式
└── index.html        # 主页面
```
