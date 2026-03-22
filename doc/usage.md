# DruidClaw 使用文档

DruidClaw 是一个基于 Claude Code 的多功能会话管理和 IM 机器人集成平台。

---

## 目录

1. [快速开始](#快速开始)
2. [Web 界面使用](#web-界面使用)
3. [Claude Code 会话管理](#claude-code-会话管理)
4. [终端使用](#终端使用)
5. [IM 机器人配置](#im-机器人配置)
6. [API 参考](#api-参考)
7. [常见问题](#常见问题)

---

## 快速开始

### 环境要求

- Python 3.10+
- Node.js 18+
- Claude Code

### 安装步骤

```bash
# 1. 克隆仓库
cd /path/to/DruidClaw

# 2. 创建虚拟环境并安装依赖
python -m venv venv
source venv/bin/activate  # Linux/macOS
pip install -r requirements.txt

# 3. 安装 Claude Code
npx @anthropic-ai/claude-code
# 或使用安装脚本
./install.sh

# 4. 启动服务
./start.sh
```

### 启动选项

```bash
# 默认启动 (绑定 0.0.0.0:19123)
./start.sh

# 自定义配置
./start.sh --host 0.0.0.0 --port 19123 --passwd your_password
```

访问地址：`http://localhost:19123`

---

## Web 界面使用

### 登录

1. 打开浏览器访问 `http://localhost:19123`
2. 输入密码（默认：`dc`，可通过 `DRUIDCLAW_TOKEN` 环境变量修改）

### 主界面功能

| 功能 | 说明 |
|------|------|
| 会话列表 | 查看和管理所有 Claude Code 会话 |
| 新建会话 | 创建新的 Claude Code 会话 |
| 本地终端 | 打开本地 PTY 终端 |
| SSH 终端 | 连接远程服务器 |
| IM 机器人 | 配置和管理 IM 机器人 |

---

## Claude Code 会话管理

### 创建会话

1. 点击「新建会话」按钮
2. 选择工作目录（可选）
3. 输入额外的 Claude 参数（可选）
4. 点击确认创建

### 会话操作

| 操作 | 说明 |
|------|------|
| 附加 | 连接到会话，与 Claude 交互 |
| 分离 | 保持会话运行，断开连接（Ctrl+Z） |
| 停止 | 终止会话 |
| 删除 | 删除会话记录 |

### 会话保持

- 会话在后台持续运行，即使断开连接
- 页面刷新后自动恢复连接（60 秒内）
- 输出自动缓冲（64KB 环形缓冲区）

---

## 终端使用

### 本地终端

本地终端基于 PTY（伪终端），支持完整的 Shell 功能：

1. 点击「本地终端」按钮
2. 选择 Shell 类型（bash/zsh 等）
3. 开始使用终端

**快捷键：**
- `Ctrl+Z` - 分离终端（保持会话）
- `Ctrl+C` - 中断当前命令
- `Ctrl+L` - 清屏

### SSH 远程终端

连接远程服务器：

1. 点击「SSH 终端」
2. 配置连接信息：
   - 主机地址
   - 端口（默认 22）
   - 用户名
   - 密码或私钥
3. 点击连接

**功能：**
- 支持密码/密钥认证
- 保存连接历史
- 会话保持（60 秒内自动恢复）

---

## IM 机器人配置

DruidClaw 支持多种 IM 平台的机器人集成，可将 Claude 的回复转发到 IM 群组。

### 支持的 IM 平台

| 平台 | 连接方式 | 配置项 |
|------|----------|--------|
| 飞书 (Feishu) | WebSocket 长连接 | app_id, app_secret |
| 钉钉 (DingTalk) | WebSocket | app_key, app_secret |
| Telegram | 长轮询 | bot_token |
| QQ | WebSocket | app_id, app_key |
| 企业微信 (WeWork) | Webhook | corp_id, agent_id, secret |

### 飞书机器人配置

#### 1. 获取凭证

1. 登录 [飞书开放平台](https://open.feishu.cn/)
2. 创建企业自建应用
3. 获取 `App ID` 和 `App Secret`

#### 2. 配置机器人

1. 在 Web 界面进入「IM 机器人」配置
2. 输入 `App ID` 和 `App Secret`
3. 保存配置

#### 3. 连接机器人

1. 点击「连接」按钮
2. 机器人自动创建会话并处理消息
3. 状态显示为「已连接」

#### 4. 功能说明

- 自动监听群消息
- Claude 回复自动转发
- 消息记录查看
- 断线自动重连

### Telegram 机器人配置

#### 1. 获取 Bot Token

1. 在 Telegram 中联系 [@BotFather](https://t.me/BotFather)
2. 发送 `/newbot` 创建机器人
3. 获取 Bot Token

#### 2. 配置并连接

1. 在 Web 界面输入 Bot Token
2. 点击连接
3. 将机器人添加到群组

### 企业微信机器人配置

#### 1. 获取凭证

1. 登录 [企业微信管理后台](https://work.weixin.qq.com/)
2. 创建自建应用
3. 获取 `Corp ID`、`Agent ID`、`Secret`

#### 2. 配置 Webhook

1. 在企业微信后台配置「接收消息服务器」
2. URL 格式：`http://your-server:19123/webhook/wecom/{card_id}`
3. 填写 Token 和 EncodingAESKey

---

## API 参考

### 认证

所有 API 请求需在 Header 中携带认证信息：
```
Authorization: Bearer <DRUIDCLAW_TOKEN>
```

### 会话 API

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/sessions` | GET | 获取会话列表 |
| `/api/sessions` | POST | 创建新会话 |
| `/api/sessions/{id}` | GET | 获取会话详情 |
| `/api/sessions/{id}` | DELETE | 删除会话 |
| `/api/sessions/{id}/attach` | POST | 附加会话 |

### SSH API

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/ssh/history` | GET | 获取 SSH 历史 |
| `/api/ssh/connect` | POST | 连接 SSH |
| `/api/ssh/disconnect` | POST | 断开 SSH |

### IM 机器人 API

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/feishu/config` | GET/POST | 飞书配置 |
| `/api/feishu/connect` | POST | 连接飞书 |
| `/api/feishu/disconnect` | POST | 断开飞书 |
| `/api/feishu/status` | GET | 飞书状态 |
| `/api/feishu/events` | GET | 飞书事件 |
| `/api/im/{card_id}/events` | GET | 通用 IM 事件 |
| `/api/im/{card_id}/status` | GET | 通用 IM 状态 |
| `/webhook/wecom/{card_id}` | GET/POST | 企业微信回调 |

### 配置 API

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/install/config` | GET/POST | 安装配置 |
| `/api/feishu/bridge` | GET/POST | 桥接配置 |

---

## 常见问题

### 1. Claude Code 无法启动

**检查点：**
- 确认已安装 Claude Code：`claude --version`
- 检查 PATH 环境变量
- 配置 Anthropic API Key

### 2. IM 机器人连接失败

**飞书：**
- 检查 App ID 和 App Secret 是否正确
- 确认应用已发布
- 检查网络连通性

**Telegram：**
- 检查 Bot Token 是否正确
- 确认机器人已启动（@BotFather 测试）

### 3. 终端显示异常

- 刷新页面重新连接
- 检查终端类型设置（TERM=xterm-256color）
- 清除浏览器缓存

### 4. SSH 连接超时

- 检查防火墙设置
- 确认 SSH 服务运行
- 检查主机地址和端口

---

## 环境变量配置

| 变量名 | 默认值 | 说明 |
|--------|--------|------|
| `DRUIDCLAW_TOKEN` | `dc` | Web 访问密码 |
| `DRUIDCLAW_RUN_DIR` | `~/.druidclaw/run` | 运行时数据目录 |
| `DRUIDCLAW_WEB_HOST` | `0.0.0.0` | 绑定地址 |
| `DRUIDCLAW_WEB_PORT` | `19123` | 监听端口 |
| `CLAUDE_BIN` | `claude` | Claude 可执行文件路径 |
| `DRUIDCLAW_LOG_DIR` | `./log` | 日志目录 |

---

## 日志查看

会话日志保存在 `log/` 目录下：

```
log/
├── app_<session_name>_<timestamp>.log   # 可读日志
└── app_<session_name>_<timestamp>.raw   # 原始数据
```

---

## 技术支持

- GitHub Issues: 提交问题和功能请求
- 文档更新：查看最新文档获取更多信息
