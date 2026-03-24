"""History API: list session logs, generate and retrieve AI summaries."""
import json
import os
import re
import uuid
import logging
from datetime import datetime
from pathlib import Path

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter()
logger = logging.getLogger(__name__)

# Log files are stored here (same as core/session.py LOG_DIR default)
_LOG_DIR = Path(os.environ.get("DRUIDCLAW_LOG_DIR", Path.cwd() / "run" / "logs"))

# Summaries persist here
from druidclaw.web.state import RUN_DIR
_SUMMARIES_FILE = RUN_DIR / "summaries.json"

_ANSI_RE = re.compile(r'\x1b\[[0-9;]*[mGKHFJABCDsu]|\x1b\][^\x07]*\x07|\x1b[()][AB012]|\r')


def _strip_ansi(text: str) -> str:
    return _ANSI_RE.sub('', text)


def _load_summaries() -> list:
    if _SUMMARIES_FILE.exists():
        try:
            return json.loads(_SUMMARIES_FILE.read_text())
        except Exception:
            pass
    return []


def _save_summaries(summaries: list):
    _SUMMARIES_FILE.write_text(json.dumps(summaries, ensure_ascii=False, indent=2))


def _get_api_key() -> str:
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    if key:
        return key
    # Try ~/.claude/.credentials.json
    creds = Path.home() / ".claude" / ".credentials.json"
    if creds.exists():
        try:
            data = json.loads(creds.read_text())
            return data.get("apiKey", "") or data.get("api_key", "")
        except Exception:
            pass
    return ""


@router.get("/api/history/logs")
def api_history_logs():
    """List all .log files in the log directory."""
    if not _LOG_DIR.exists():
        return {"logs": []}

    summaries = _load_summaries()
    summarized = {s["log_file"] for s in summaries}

    logs = []
    for p in sorted(_LOG_DIR.glob("*.log"), key=lambda x: x.stat().st_mtime, reverse=True):
        stat = p.stat()
        logs.append({
            "name": p.name,
            "path": str(p),
            "size": stat.st_size,
            "mtime": stat.st_mtime,
            "mtime_str": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M"),
            "has_summary": p.name in summarized,
        })

    return {"logs": logs}


@router.get("/api/history/summaries")
def api_history_summaries():
    """List all saved summaries."""
    return {"summaries": _load_summaries()}


class GenerateRequest(BaseModel):
    log_file: str   # filename (basename only, for safety)
    model: str = "claude-haiku-4-5-20251001"


@router.post("/api/history/generate")
async def api_history_generate(req: GenerateRequest):
    """Generate an AI summary from a .log file using the Anthropic API."""
    # Safety: only allow basenames inside LOG_DIR
    log_path = _LOG_DIR / Path(req.log_file).name
    if not log_path.exists():
        raise HTTPException(404, f"Log file not found: {req.log_file}")

    api_key = _get_api_key()
    if not api_key:
        raise HTTPException(400, "ANTHROPIC_API_KEY not configured. Set it as an environment variable.")

    # Read and clean log
    raw = log_path.read_text(encoding="utf-8", errors="replace")
    clean = _strip_ansi(raw)
    # Truncate to ~60k chars to stay within token limits
    if len(clean) > 60000:
        clean = clean[:30000] + "\n\n[... truncated ...]\n\n" + clean[-30000:]

    prompt = f"""以下是一个 Claude Code 会话的终端日志。请用中文生成一份简洁的会话总结，包括：
1. 主要完成了什么任务
2. 关键操作和修改（文件、命令等）
3. 最终结果或状态

日志内容：
<log>
{clean}
</log>

请用 200-400 字总结，要求简洁清晰。"""

    try:
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": req.model,
                    "max_tokens": 1024,
                    "messages": [{"role": "user", "content": prompt}],
                },
            )
        if resp.status_code != 200:
            raise HTTPException(500, f"Anthropic API error {resp.status_code}: {resp.text[:300]}")

        data = resp.json()
        summary_text = data["content"][0]["text"]
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Failed to call Anthropic API: {e}")

    # Save summary
    summaries = _load_summaries()
    # Replace existing summary for same log file if any
    summaries = [s for s in summaries if s["log_file"] != log_path.name]
    entry = {
        "id": str(uuid.uuid4())[:8],
        "log_file": log_path.name,
        "summary": summary_text,
        "model": req.model,
        "created_at": datetime.now().isoformat(),
    }
    summaries.insert(0, entry)
    _save_summaries(summaries)

    return entry


@router.delete("/api/history/{sid}")
def api_history_delete(sid: str):
    """Delete a summary by id."""
    summaries = _load_summaries()
    new = [s for s in summaries if s["id"] != sid]
    if len(new) == len(summaries):
        raise HTTPException(404, f"Summary '{sid}' not found")
    _save_summaries(new)
    return {"ok": True}
