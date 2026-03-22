"""Skills, install, and marketplace API routes."""
import os
import re
import json
import threading
import logging
import asyncio as _asyncio
import queue as _queue
import shutil as _shutil
import subprocess as _subprocess
import urllib.request as _urllib_req
import urllib.error as _urllib_err
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse as _StreamingResponse
from pydantic import BaseModel

from druidclaw.web.state import RUN_DIR

router = APIRouter()

logger = logging.getLogger(__name__)

_SKILLS_DIR     = Path.home() / ".claude" / "skills"
_PLUGINS_DIR    = Path.home() / ".claude" / "plugins"
_INSTALLED_JSON = _PLUGINS_DIR / "installed_plugins.json"

# Regex to remove ANSI escape codes from terminal output
_ANSI_ESCAPE = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')

def _clean_output(text: str) -> str:
    """Remove ANSI escape codes and strip whitespace."""
    return _ANSI_ESCAPE.sub('', text).strip()


def _parse_skill_md(skill_dir: Path, source: str = "") -> dict | None:
    """Parse SKILL.md in a directory and return skill dict, or None on failure."""
    import re as _re2
    skill_md = skill_dir / "SKILL.md"
    if not skill_md.exists():
        return None
    try:
        content = skill_md.read_text(encoding="utf-8", errors="replace")
        m = _re2.match(r'^---\s*\n(.*?)\n---', content, _re2.DOTALL)
        name, desc = skill_dir.name, ""
        if m:
            fm = m.group(1)
            nm = _re2.search(r'^name:\s*(.+)$', fm, _re2.MULTILINE)
            dm = _re2.search(r'^description:\s*(.+)$', fm, _re2.MULTILINE)
            if nm: name = nm.group(1).strip()
            if dm: desc = dm.group(1).strip()
        return {"name": name, "dir": skill_dir.name, "description": desc,
                "source": source, "path": str(skill_dir)}
    except Exception:
        return None


def _read_skills() -> list[dict]:
    """
    Read all available skills from:
    1. ~/.claude/skills/*/SKILL.md            (local / user-installed)
    2. ~/.claude/plugins/cache/.../skills/*/  (plugin-installed via claude plugins)
    Deduplicates by skill name; local skills take priority.
    """
    seen: dict[str, dict] = {}   # name → skill

    # 1. Local skills (~/.claude/skills/)
    if _SKILLS_DIR.exists():
        for d in sorted(_SKILLS_DIR.iterdir()):
            if not d.is_dir():
                continue
            sk = _parse_skill_md(d, source="local")
            if sk:
                seen[sk["name"]] = sk

    # 2. Plugin-installed skills from installed_plugins.json
    if _INSTALLED_JSON.exists():
        try:
            installed = json.loads(_INSTALLED_JSON.read_text())
            plugins = installed.get("plugins", {})
            for plugin_key, instances in plugins.items():
                for inst in (instances if isinstance(instances, list) else [instances]):
                    install_path = inst.get("installPath", "")
                    if not install_path:
                        continue
                    skills_root = Path(install_path) / "skills"
                    if not skills_root.exists():
                        continue
                    # plugin_key looks like "document-skills@anthropic-agent-skills"
                    plugin_name = plugin_key.split("@")[0]
                    for skill_dir in sorted(skills_root.iterdir()):
                        if not skill_dir.is_dir():
                            continue
                        sk = _parse_skill_md(skill_dir, source=plugin_name)
                        if sk and sk["name"] not in seen:
                            seen[sk["name"]] = sk
        except Exception:
            pass

    return sorted(seen.values(), key=lambda s: s["name"])


def _run_cmd(cmd: list[str], env=None) -> tuple[int, str]:
    """Run a shell command and return (returncode, output)."""
    env2 = os.environ.copy()
    if env:
        env2.update(env)
    # Add nvm paths
    home = Path.home()
    nvm_bin = home / ".nvm/versions/node"
    if nvm_bin.exists():
        node_dirs = sorted(nvm_bin.iterdir(), reverse=True)
        if node_dirs:
            env2["PATH"] = str(node_dirs[0] / "bin") + ":" + env2.get("PATH", "")
    try:
        r = _subprocess.run(cmd, capture_output=True, text=True, timeout=120, env=env2)
        return r.returncode, (r.stdout + r.stderr).strip()
    except Exception as e:
        return 1, str(e)


def _get_install_status() -> dict:
    """Check what is installed and return status dict."""
    status = {}

    # Node.js
    rc, out = _run_cmd(["node", "--version"])
    status["node"] = {"ok": rc == 0, "version": out if rc == 0 else None}

    # npm
    rc, out = _run_cmd(["npm", "--version"])
    status["npm"] = {"ok": rc == 0, "version": out if rc == 0 else None}

    # Claude Code
    rc, out = _run_cmd(["claude", "--version"])
    status["claude"] = {"ok": rc == 0, "version": out if rc == 0 else None,
                        "path": _shutil.which("claude")}

    # Auth: check if ~/.claude/.credentials.json or settings has auth info
    creds_file = Path.home() / ".claude" / ".credentials.json"
    settings_file = Path.home() / ".claude" / "settings.json"
    auth_ok = False
    auth_info = ""
    if creds_file.exists():
        try:
            creds = json.loads(creds_file.read_text())
            if creds:
                auth_ok = True
                auth_info = "OAuth credentials found"
        except Exception:
            pass
    if not auth_ok:
        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        if api_key:
            auth_ok = True
            auth_info = f"API key in env (len={len(api_key)})"
    status["auth"] = {"ok": auth_ok, "info": auth_info}

    # nvm
    nvm_dir = Path.home() / ".nvm"
    status["nvm"] = {"ok": nvm_dir.exists(), "path": str(nvm_dir) if nvm_dir.exists() else None}

    return status


_MARKETPLACE_DEFAULTS = [
    {
        "name": "anthropic-agent-skills",
        "url": "https://raw.githubusercontent.com/anthropics/skills/main/.claude-plugin/marketplace.json",
        "label": "Anthropic Skills",
    },
    {
        "name": "claude-plugins-official",
        "url": "https://raw.githubusercontent.com/anthropics/claude-plugins-official/main/.claude-plugin/marketplace.json",
        "label": "Claude Plugins Official",
    },
]

_MARKETPLACE_CACHE: dict[str, dict] = {}   # url → parsed data
_MARKETPLACE_CACHE_TS: dict[str, float] = {}  # url → fetch timestamp
_MARKETPLACE_CACHE_TTL = 300  # 5 minutes


def _fetch_marketplace(url: str) -> dict:
    """Fetch and parse a marketplace.json from a URL."""
    import time as _t
    now = _t.time()
    if url in _MARKETPLACE_CACHE and (now - _MARKETPLACE_CACHE_TS.get(url, 0)) < _MARKETPLACE_CACHE_TTL:
        return _MARKETPLACE_CACHE[url]

    req = _urllib_req.Request(url, headers={
        "User-Agent": "CCManager/1.0",
        "Accept": "application/json",
    })
    try:
        with _urllib_req.urlopen(req, timeout=10) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
        data = json.loads(raw)
    except _urllib_err.URLError as e:
        raise ValueError(f"无法访问 {url}: {e}")
    except json.JSONDecodeError as e:
        raise ValueError(f"JSON 解析失败: {e}")

    _MARKETPLACE_CACHE[url] = data
    _MARKETPLACE_CACHE_TS[url] = now
    return data


def _get_installed_plugins() -> set[str]:
    """Return set of installed plugin names via `claude plugins list`."""
    rc, out = _run_cmd(["claude", "plugins", "list"])
    if rc != 0:
        return set()
    # Parse output: lines like "❯ plugin-name@marketplace"
    import re as _re2
    names = set()
    for line in out.splitlines():
        m = _re2.search(r'[\u276f❯►>]\s+([a-zA-Z0-9_\-]+)', line)
        if m:
            names.add(m.group(1).strip())
    return names


@router.get("/api/install/status")
def api_install_status():
    return _get_install_status()


@router.post("/api/install/run")
async def api_install_run(request: Request):
    """
    Stream installation progress via SSE.
    Body: {"action": "install_claude" | "install_node" | "update_claude"}
    """
    try:
        body = await request.json()
    except Exception:
        body = {}
    action = body.get("action", "install_claude")

    async def sse_gen():
        q: _queue.Queue = _queue.Queue()

        def send(msg: str, level: str = "info"):
            q.put({"msg": msg, "level": level})

        def run_in_thread():
            try:
                home = Path.home()
                nvm_sh = home / ".nvm/nvm.sh"
                env = os.environ.copy()

                # Build PATH with nvm node
                nvm_bin = home / ".nvm/versions/node"
                if nvm_bin.exists():
                    node_dirs = sorted(nvm_bin.iterdir(), reverse=True)
                    if node_dirs:
                        env["PATH"] = str(node_dirs[0] / "bin") + ":" + env.get("PATH", "")

                if action == "install_node":
                    send("检查 nvm...")
                    if not nvm_sh.exists():
                        send("安装 nvm...")
                        rc, out = _run_cmd(["bash", "-c",
                            "curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.39.7/install.sh | bash"])
                        send(_clean_output(out), "info" if rc == 0 else "error")
                        if rc != 0:
                            send("nvm 安装失败", "error"); q.put(None); return
                    send("安装 Node.js LTS...")
                    rc, out = _run_cmd(["bash", "-c",
                        f"source {nvm_sh} && nvm install --lts && nvm use --lts"])
                    send(_clean_output(out[:2000]), "info" if rc == 0 else "error")

                elif action in ("install_claude", "update_claude"):
                    label = "更新" if action == "update_claude" else "安装"
                    send(f"{label} Claude Code...")
                    rc, out = _run_cmd(["npm", "install", "-g", "@anthropic-ai/claude-code"], env=env)
                    send(_clean_output(out[:3000]), "info" if rc == 0 else "error")
                    if rc == 0:
                        rc2, ver = _run_cmd(["claude", "--version"])
                        send(f"✅ {label}成功: {ver}", "success")
                    else:
                        send(f"❌ {label}失败", "error")

                elif action == "check":
                    send("检查环境...")
                    for cmd_name in ["node --version", "npm --version", "claude --version"]:
                        parts = cmd_name.split()
                        rc, out = _run_cmd(parts, env=env)
                        icon = "✅" if rc == 0 else "❌"
                        send(f"{icon} {parts[0]}: {_clean_output(out) or '未找到'}")

            except Exception as e:
                q.put({"msg": f"错误: {e}", "level": "error"})
            finally:
                q.put(None)  # sentinel

        thread = threading.Thread(target=run_in_thread, daemon=True)
        thread.start()

        while True:
            try:
                item = await _asyncio.get_event_loop().run_in_executor(
                    None, lambda: q.get(timeout=90))
                if item is None:
                    yield "data: {\"done\": true}\n\n"
                    break
                yield f"data: {json.dumps(item)}\n\n"
            except Exception:
                break

    return _StreamingResponse(sse_gen(), media_type="text/event-stream",
                              headers={"Cache-Control": "no-cache",
                                       "X-Accel-Buffering": "no"})


class InstallConfigRequest(BaseModel):
    api_key: str = ""
    model: str = ""
    claude_bin: str = ""


@router.post("/api/install/config")
def api_install_config(req: InstallConfigRequest):
    """Save Claude Code configuration."""
    _RUN_DIR = RUN_DIR
    changed = []
    # API key → env file or settings
    if req.api_key.strip():
        # Write to ~/.claude/env (Claude Code reads this)
        env_file = Path.home() / ".claude" / "env"
        env_file.parent.mkdir(exist_ok=True)
        lines = env_file.read_text().splitlines() if env_file.exists() else []
        lines = [l for l in lines if not l.startswith("ANTHROPIC_API_KEY=")]
        lines.append(f"ANTHROPIC_API_KEY={req.api_key.strip()}")
        env_file.write_text("\n".join(lines) + "\n")
        # Also set in current process env
        os.environ["ANTHROPIC_API_KEY"] = req.api_key.strip()
        changed.append("api_key")

    # Model
    if req.model.strip():
        settings_file = Path.home() / ".claude" / "settings.json"
        settings_file.parent.mkdir(exist_ok=True)
        settings = {}
        if settings_file.exists():
            try: settings = json.loads(settings_file.read_text())
            except Exception: pass
        settings["model"] = req.model.strip()
        settings_file.write_text(json.dumps(settings, indent=2))
        changed.append("model")

    # Claude binary override
    if req.claude_bin.strip():
        os.environ["CLAUDE_BIN"] = req.claude_bin.strip()
        # Persist to RUN_DIR/config.json as well
        cfg_file = _RUN_DIR / "claude_config.json"
        cfg = {}
        if cfg_file.exists():
            try: cfg = json.loads(cfg_file.read_text())
            except Exception: pass
        cfg["claude_bin"] = req.claude_bin.strip()
        _RUN_DIR.mkdir(exist_ok=True)
        cfg_file.write_text(json.dumps(cfg, indent=2))
        changed.append("claude_bin")

    return {"ok": True, "changed": changed}


@router.get("/api/marketplace/list")
def api_marketplace_list():
    """Return default marketplace sources."""
    return {"marketplaces": _MARKETPLACE_DEFAULTS}


@router.get("/api/marketplace/fetch")
def api_marketplace_fetch(url: str):
    """Fetch and parse a marketplace URL."""
    try:
        data = _fetch_marketplace(url)
        installed = _get_installed_plugins()
        plugins = data.get("plugins", [])
        # Enrich with installed status
        for p in plugins:
            p["installed"] = p.get("name", "") in installed
        return {
            "ok": True,
            "name":        data.get("name", ""),
            "description": data.get("metadata", {}).get("description", ""),
            "plugins":     plugins,
            "installed":   list(installed),
        }
    except Exception as e:
        return {"ok": False, "error": str(e), "plugins": []}


@router.post("/api/marketplace/install")
async def api_marketplace_install(request: Request):
    """Install a plugin, streaming output via SSE."""
    try:
        body = await request.json()
    except Exception:
        body = {}
    plugin   = body.get("plugin", "")
    mkt_name = body.get("marketplace", "")

    async def sse_gen():
        q: _queue.Queue = _queue.Queue()

        def run():
            try:
                if not plugin:
                    q.put({"msg": "缺少 plugin 名称", "level": "error"})
                    q.put(None); return

                install_target = f"{plugin}@{mkt_name}" if mkt_name else plugin
                q.put({"msg": f"安装 {install_target}...", "level": "info"})
                rc, out = _run_cmd(["claude", "plugins", "install", install_target])
                for line in out.splitlines():
                    if line.strip():
                        q.put({"msg": line, "level": "info" if rc == 0 else "error"})
                if rc == 0:
                    q.put({"msg": f"✅ {plugin} 安装成功", "level": "success"})
                else:
                    q.put({"msg": f"❌ 安装失败 (exit {rc})", "level": "error"})
            except Exception as e:
                q.put({"msg": str(e), "level": "error"})
            finally:
                q.put(None)

        threading.Thread(target=run, daemon=True).start()
        while True:
            try:
                item = await _asyncio.get_event_loop().run_in_executor(
                    None, lambda: q.get(timeout=60))
                if item is None:
                    yield "data: {\"done\": true}\n\n"; break
                yield f"data: {json.dumps(item, ensure_ascii=False)}\n\n"
            except Exception:
                break

    return _StreamingResponse(sse_gen(), media_type="text/event-stream",
                              headers={"Cache-Control": "no-cache",
                                       "X-Accel-Buffering": "no"})


@router.post("/api/marketplace/uninstall")
async def api_marketplace_uninstall(request: Request):
    """Uninstall a plugin, streaming output via SSE."""
    try:
        body = await request.json()
    except Exception:
        body = {}
    plugin = body.get("plugin", "")

    async def sse_gen():
        q: _queue.Queue = _queue.Queue()

        def run():
            try:
                if not plugin:
                    q.put({"msg": "缺少 plugin 名称", "level": "error"})
                    q.put(None); return
                q.put({"msg": f"卸载 {plugin}...", "level": "info"})
                rc, out = _run_cmd(["claude", "plugins", "uninstall", plugin, "--yes"])
                for line in out.splitlines():
                    if line.strip():
                        q.put({"msg": line, "level": "info" if rc == 0 else "error"})
                if rc == 0:
                    q.put({"msg": f"✅ {plugin} 已卸载", "level": "success"})
                else:
                    q.put({"msg": f"❌ 卸载失败", "level": "error"})
            except Exception as e:
                q.put({"msg": str(e), "level": "error"})
            finally:
                q.put(None)

        threading.Thread(target=run, daemon=True).start()
        while True:
            try:
                item = await _asyncio.get_event_loop().run_in_executor(
                    None, lambda: q.get(timeout=60))
                if item is None:
                    yield "data: {\"done\": true}\n\n"; break
                yield f"data: {json.dumps(item, ensure_ascii=False)}\n\n"
            except Exception:
                break

    return _StreamingResponse(sse_gen(), media_type="text/event-stream",
                              headers={"Cache-Control": "no-cache",
                                       "X-Accel-Buffering": "no"})


@router.get("/api/skills")
def api_skills():
    return {"skills": _read_skills()}


# ── MCP server management ────────────────────────────────────────

_CLAUDE_JSON = Path.home() / ".claude.json"

_MCP_PRESETS = [
    {"key": "filesystem",          "label": "Filesystem",          "desc": "读写本地文件",             "command": "npx", "args": ["-y", "@modelcontextprotocol/server-filesystem", str(Path.home())]},
    {"key": "memory",              "label": "Memory",              "desc": "跨会话持久记忆",           "command": "npx", "args": ["-y", "@modelcontextprotocol/server-memory"]},
    {"key": "fetch",               "label": "Fetch",               "desc": "HTTP 请求 / 网页抓取",     "command": "npx", "args": ["-y", "@modelcontextprotocol/server-fetch"]},
    {"key": "sequential-thinking", "label": "Sequential Thinking", "desc": "分步推理工具",             "command": "npx", "args": ["-y", "@modelcontextprotocol/server-sequential-thinking"]},
    {"key": "puppeteer",           "label": "Puppeteer",           "desc": "无头浏览器 / 截图",        "command": "npx", "args": ["-y", "@modelcontextprotocol/server-puppeteer"]},
    {"key": "github",              "label": "GitHub",              "desc": "GitHub API 集成（需 Token）", "command": "npx", "args": ["-y", "@modelcontextprotocol/server-github"], "env": {"GITHUB_PERSONAL_ACCESS_TOKEN": ""}},
    {"key": "brave-search",        "label": "Brave Search",        "desc": "网页搜索（需 API Key）",   "command": "npx", "args": ["-y", "@modelcontextprotocol/server-brave-search"], "env": {"BRAVE_API_KEY": ""}},
    {"key": "postgres",            "label": "PostgreSQL",          "desc": "PostgreSQL 数据库",        "command": "npx", "args": ["-y", "@modelcontextprotocol/server-postgres", "postgresql://localhost/mydb"]},
    {"key": "sqlite",              "label": "SQLite",              "desc": "SQLite 数据库",            "command": "npx", "args": ["-y", "@modelcontextprotocol/server-sqlite", "--db-path", str(Path.home() / "data.db")]},
    {"key": "git",                 "label": "Git",                 "desc": "Git 仓库操作",             "command": "uvx", "args": ["mcp-server-git", "--repository", "."]},
]


def _read_mcp_config() -> dict:
    """Read ~/.claude.json, return full dict."""
    if not _CLAUDE_JSON.exists():
        return {}
    try:
        return json.loads(_CLAUDE_JSON.read_text())
    except Exception:
        return {}


def _write_mcp_config(data: dict):
    _CLAUDE_JSON.write_text(json.dumps(data, indent=2, ensure_ascii=False))


@router.get("/api/mcp")
def api_mcp_list():
    data = _read_mcp_config()
    servers = data.get("mcpServers", {})
    installed_keys = set(servers.keys())
    presets = [{**p, "installed": p["key"] in installed_keys} for p in _MCP_PRESETS]
    return {"servers": servers, "presets": presets}


@router.post("/api/mcp")
async def api_mcp_add(request: Request):
    body = await request.json()
    name = body.get("name", "").strip()
    if not name:
        from fastapi import HTTPException
        raise HTTPException(400, "name 不能为空")
    command = body.get("command", "").strip()
    if not command:
        from fastapi import HTTPException
        raise HTTPException(400, "command 不能为空")
    args = body.get("args", [])
    env  = body.get("env", {})
    data = _read_mcp_config()
    servers = data.setdefault("mcpServers", {})
    entry: dict = {"command": command, "args": args}
    if env:
        entry["env"] = env
    servers[name] = entry
    _write_mcp_config(data)
    return {"ok": True, "name": name}


@router.delete("/api/mcp/{name}")
def api_mcp_remove(name: str):
    data = _read_mcp_config()
    servers = data.get("mcpServers", {})
    servers.pop(name, None)
    data["mcpServers"] = servers
    _write_mcp_config(data)
    return {"ok": True}
