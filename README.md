# DruidClaw

DruidClaw 是一个基于 Claude Code 的多功能会话管理和 IM 机器人集成平台。

## 功能特性

- **Claude Code 会话管理**: 在浏览器中管理多个 Claude Code 会话
- **本地终端**: 基于 PTY 的本地 Shell 终端，支持会话保持
- **SSH 远程终端**: 通过 Paramiko 连接远程 SSH 服务器，支持会话保持
- **IM 机器人集成**: 支持飞书、钉钉、Telegram、QQ、企业微信机器人
- **会话持久化**: 页面刷新后自动恢复终端会话，后端进程保持 60 秒
- **多服务器管理**: 支持添加多个服务器连接
- **Skills 市场**: 扩展 Claude Code 功能

## 快速开始

### 安装

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 安装 Node.js (如未安装)
# Ubuntu/Debian
curl -fsSL https://deb.nodesource.com/setup_18.x | sudo -E bash -
sudo apt-get install -y nodejs

# macOS
brew install node

# 3. 安装 Claude Code
npx @anthropic-ai/claude-code

# 或使用安装脚本
./install.sh
```

### 启动服务

```bash
# 默认启动 (绑定 0.0.0.0:19123)
./start.sh

# 自定义配置
./start.sh --host 0.0.0.0 --port 19123 --passwd your_password
```

### 访问 Web 界面

打开浏览器访问 `http://localhost:19123`

## 目录结构

```
DruidClaw/
├── druidclaw/          # 主程序包
│   ├── core/          # 核心功能 (会话管理、守护进程)
│   ├── web/           # Web 界面 (FastAPI)
│   └── imbot/         # IM 机器人 (飞书、钉钉等)
├── doc/               # 文档
├── tests/             # 测试用例
├── docker/            # Docker 配置
├── requirements.txt   # Python 依赖
├── start.sh          # 启动脚本
└── install.sh        # 安装脚本
```

## 配置

### 环境变量

| 变量名 | 默认值 | 说明 |
|--------|--------|------|
| `DRUIDCLAW_TOKEN` | `dc` | Web 访问密码 |
| `DRUIDCLAW_RUN_DIR` | `~/.druidclaw/run` | 运行时数据目录 |
| `DRUIDCLAW_WEB_HOST` | `0.0.0.0` | 绑定地址 |
| `DRUIDCLAW_WEB_PORT` | `19123` | 监听端口 |

### Claude Code 配置

在 Web 界面点击 "ClaudeCode 安装" 按钮配置：
- Anthropic API Key
- API Base URL (可选，用于代理)
- 模型名称 (如 `claude-sonnet-4-5`)

## 终端会话

### 本地终端
- 基于 PTY 的本地 Shell
- 支持自定义 Shell (bash/zsh 等)
- 页面刷新后自动重连 (60 秒内)

### SSH 远程终端
- 支持密码/密钥认证
- 支持保存连接历史
- 页面刷新后自动重连 (60 秒内)

## API 端点

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/cards` | GET | 获取卡片列表 |
| `/api/sessions` | GET | 获取会话列表 |
| `/api/sessions` | POST | 创建新会话 |
| `/api/ssh/history` | GET | 获取 SSH 历史 |
| `/api/feishu/config` | GET/POST | 飞书配置 |
| `/api/install/config` | GET/POST | 安装配置 |

## 技术栈

- **后端**: Python 3, FastAPI, Paramiko
- **前端**: 原生 JavaScript, xterm.js
- **终端**: PTY (本地), SSH (远程)

## License

MIT

## 测试

运行所有测试：

```bash
source venv/bin/activate
pip install pytest httpx
pytest -v
```

详见 [doc/testing.md](doc/testing.md)

## 文档

- [使用文档](doc/usage.md) - 详细的使用指南
- [测试文档](doc/testing.md) - 测试运行和编写指南
