"""Stats API routes: log entries, global token stats, trend, and per-session stats."""
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException

router = APIRouter()

logger = logging.getLogger(__name__)

_CLAUDE_SESSIONS_DIR = Path.home() / ".claude" / "sessions"
_CLAUDE_PROJECTS_DIR = Path.home() / ".claude" / "projects"

# _ring_handler is imported from state (set up at import time)
def _get_ring_handler():
    from druidclaw.web.state import _ring_handler
    return _ring_handler


@router.get("/api/log")
def api_log(after: int = 0):
    """Return recent server log entries since sequence `after`."""
    rh = _get_ring_handler()
    entries = rh.get_since(after)
    return {"entries": entries, "latest_seq": rh.latest_seq()}


@router.get("/api/stats/global")
def api_stats_global():
    """Aggregate token usage and cost across all Claude conversation files."""
    total = {"input": 0, "output": 0, "cache_read": 0, "cache_creation": 0}
    cost_total = 0.0
    file_count = 0
    turn_count = 0

    if not _CLAUDE_PROJECTS_DIR.exists():
        return {"total": total, "cost_usd": 0.0, "files": 0, "turns": 0}

    for proj_dir in _CLAUDE_PROJECTS_DIR.iterdir():
        if not proj_dir.is_dir():
            continue
        for conv_file in proj_dir.glob("*.jsonl"):
            file_count += 1
            try:
                for raw in conv_file.read_text(encoding="utf-8", errors="replace").split("\n"):
                    if not raw.strip():
                        continue
                    try:
                        d = json.loads(raw)
                        if d.get("type") == "assistant":
                            turn_count += 1
                            msg = d.get("message", {})
                            if isinstance(msg, dict):
                                u = msg.get("usage", {})
                                total["input"]         += u.get("input_tokens", 0)
                                total["output"]        += u.get("output_tokens", 0)
                                total["cache_read"]    += u.get("cache_read_input_tokens", 0)
                                total["cache_creation"]+= u.get("cache_creation_input_tokens", 0)
                        c = d.get("costUSD")
                        if c:
                            cost_total += float(c)
                    except Exception:
                        pass
            except Exception:
                pass

    return {
        "total":    total,
        "cost_usd": round(cost_total, 4),
        "files":    file_count,
        "turns":    turn_count,
    }


@router.get("/api/stats/trend")
def api_stats_trend(days: int = 14):
    """Return daily token counts for the last `days` days."""
    import time as _time
    cutoff = _time.time() - (days * 86400)

    # date_str → {input, output, turns}
    daily: dict[str, dict] = {}

    if not _CLAUDE_PROJECTS_DIR.exists():
        return {"days": [], "series": {}}

    for proj_dir in _CLAUDE_PROJECTS_DIR.iterdir():
        if not proj_dir.is_dir():
            continue
        for conv_file in proj_dir.glob("*.jsonl"):
            try:
                # Quick check: skip if file older than cutoff
                if conv_file.stat().st_mtime < cutoff:
                    continue
                for raw in conv_file.read_text(encoding="utf-8", errors="replace").split("\n"):
                    if not raw.strip():
                        continue
                    try:
                        d = json.loads(raw)
                        if d.get("type") != "assistant":
                            continue
                        ts = d.get("timestamp")
                        if not ts:
                            continue
                        # ts is ISO or epoch ms
                        try:
                            if isinstance(ts, (int, float)):
                                dt = datetime.utcfromtimestamp(ts / 1000 if ts > 1e10 else ts)
                            else:
                                dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
                            if dt.timestamp() < cutoff:
                                continue
                            day_key = dt.strftime("%Y-%m-%d")
                        except Exception:
                            continue
                        msg = d.get("message", {})
                        if not isinstance(msg, dict):
                            continue
                        u = msg.get("usage", {})
                        inp = u.get("input_tokens", 0)
                        out = u.get("output_tokens", 0)
                        if day_key not in daily:
                            daily[day_key] = {"input": 0, "output": 0, "turns": 0}
                        daily[day_key]["input"]  += inp
                        daily[day_key]["output"] += out
                        daily[day_key]["turns"]  += 1
                    except Exception:
                        pass
            except Exception:
                pass

    # Build sorted day list for the range
    import time as _time2
    day_list = []
    for i in range(days - 1, -1, -1):
        dt = datetime.utcnow() - __import__('datetime').timedelta(days=i)
        day_list.append(dt.strftime("%Y-%m-%d"))

    return {
        "days":   day_list,
        "input":  [daily.get(d, {}).get("input", 0)  for d in day_list],
        "output": [daily.get(d, {}).get("output", 0) for d in day_list],
        "turns":  [daily.get(d, {}).get("turns", 0)  for d in day_list],
    }


@router.get("/api/sessions/{name}/stats")
def api_session_stats(name: str):
    from druidclaw.web.bridge import get_session
    s = get_session(name)
    if s is None:
        raise HTTPException(404, f"Session '{name}' not found")

    now = datetime.now()
    stats: dict = {
        "name":             name,
        "pid":              s.pid,
        "workdir":          s.workdir,
        "alive":            s.is_alive(),
        "created_at":       s.created_at.isoformat(),
        "duration_seconds": (now - s.created_at).total_seconds(),
        "buffer_bytes":     len(s._buf),
        "log_path":         str(s.recorder.log_path) if s.recorder else None,
    }

    if not s.pid:
        return stats

    # Locate Claude's session metadata file by PID
    sess_file = _CLAUDE_SESSIONS_DIR / f"{s.pid}.json"
    if not sess_file.exists():
        return stats

    try:
        sess_data = json.loads(sess_file.read_text())
        session_id = sess_data.get("sessionId", "")
        cwd        = sess_data.get("cwd", s.workdir)
        stats["session_id"] = session_id

        # Locate the conversation JSONL
        cwd_hash  = cwd.replace("/", "-")   # /mnt/x → -mnt-x (leading - is correct)
        conv_file = _CLAUDE_PROJECTS_DIR / cwd_hash / f"{session_id}.jsonl"
        if not conv_file.exists():
            return stats

        # Parse token usage from conversation
        turns     = {"user": 0, "assistant": 0}
        tokens    = {"input": 0, "output": 0, "cache_read": 0, "cache_creation": 0}
        cost_usd  = 0.0
        tool_uses = 0

        for raw in conv_file.read_text("utf-8", errors="replace").split("\n"):
            if not raw.strip():
                continue
            try:
                d = json.loads(raw)
                t = d.get("type", "")
                if t == "user":
                    turns["user"] += 1
                    if d.get("toolUseResult") is not None:
                        tool_uses += 1
                elif t == "assistant":
                    turns["assistant"] += 1
                    msg = d.get("message", {})
                    if isinstance(msg, dict):
                        u = msg.get("usage", {})
                        tokens["input"]        += u.get("input_tokens", 0)
                        tokens["output"]       += u.get("output_tokens", 0)
                        tokens["cache_read"]   += u.get("cache_read_input_tokens", 0)
                        tokens["cache_creation"] += u.get("cache_creation_input_tokens", 0)
                c = d.get("costUSD")
                if c:
                    cost_usd += float(c)
            except Exception:
                pass

        stats["turns"]     = turns
        stats["tokens"]    = tokens
        stats["cost_usd"]  = round(cost_usd, 6)
        stats["tool_uses"] = tool_uses
        stats["conv_file"] = str(conv_file)

    except Exception as e:
        logger.debug(f"Session stats error for {name}: {e}")

    return stats


@router.get("/api/sessions/{name}/history")
def api_session_history(name: str, limit: int = 100):
    """Return user prompts (questions) for a session, newest first."""
    from druidclaw.web.bridge import get_session
    s = get_session(name)
    if s is None:
        raise HTTPException(404, f"Session '{name}' not found")
    if not s.pid:
        return {"prompts": []}

    sess_file = _CLAUDE_SESSIONS_DIR / f"{s.pid}.json"
    if not sess_file.exists():
        return {"prompts": []}

    try:
        sess_data = json.loads(sess_file.read_text())
        session_id = sess_data.get("sessionId", "")
        cwd        = sess_data.get("cwd", s.workdir)
        cwd_hash   = cwd.replace("/", "-")
        conv_file  = _CLAUDE_PROJECTS_DIR / cwd_hash / f"{session_id}.jsonl"
        if not conv_file.exists():
            return {"prompts": []}

        prompts = []
        for raw in conv_file.read_text("utf-8", errors="replace").split("\n"):
            if not raw.strip():
                continue
            try:
                d = json.loads(raw)
                if d.get("type") != "user":
                    continue
                if d.get("toolUseResult") is not None:
                    continue   # skip tool results
                msg = d.get("message", {})
                content = msg.get("content", []) if isinstance(msg, dict) else []
                text_parts = []
                for blk in (content if isinstance(content, list) else []):
                    if isinstance(blk, dict) and blk.get("type") == "text":
                        t = blk.get("text", "").strip()
                        if t:
                            text_parts.append(t)
                    elif isinstance(blk, str) and blk.strip():
                        text_parts.append(blk.strip())
                if not text_parts:
                    continue
                ts = d.get("timestamp", "")
                try:
                    if isinstance(ts, (int, float)):
                        ts_str = datetime.utcfromtimestamp(ts / 1000 if ts > 1e10 else ts).strftime("%H:%M:%S")
                    else:
                        ts_str = datetime.fromisoformat(str(ts).replace("Z", "+00:00")).strftime("%H:%M:%S")
                except Exception:
                    ts_str = ""
                prompts.append({"text": "\n".join(text_parts), "ts": ts_str})
            except Exception:
                pass

        # Newest first, capped at limit
        prompts.reverse()
        return {"prompts": prompts[:limit]}

    except Exception as e:
        logger.debug(f"Session history error for {name}: {e}")
        return {"prompts": []}
