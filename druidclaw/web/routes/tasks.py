"""Scheduled tasks REST API routes."""
import os
import json
import threading
import logging
import uuid as _uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from druidclaw.web.state import (
    RUN_DIR,
    TASKS_FILE,
    _sched_tasks,
    _sched_lock,
)

router = APIRouter()

logger = logging.getLogger(__name__)


def _load_sched_tasks():
    global _sched_tasks
    if TASKS_FILE.exists():
        try:
            data = json.loads(TASKS_FILE.read_text())
            with _sched_lock:
                _sched_tasks[:] = data if isinstance(data, list) else []
        except Exception:
            pass


def _save_sched_tasks():
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    with _sched_lock:
        TASKS_FILE.write_text(json.dumps(_sched_tasks, indent=2, ensure_ascii=False))


def _cron_matches(expr: str, dt) -> bool:
    """Check if a 5-field cron expression matches the given datetime."""
    parts = expr.strip().split()
    if len(parts) != 5:
        return False

    def _match(field: str, val: int) -> bool:
        if field == '*':
            return True
        for part in field.split(','):
            if '/' in part:
                rng, step = part.split('/', 1)
                start = 0 if rng == '*' else int(rng.split('-')[0])
                end   = 59 if rng == '*' else (int(rng.split('-')[1]) if '-' in rng else start)
                if start <= val <= end and (val - start) % int(step) == 0:
                    return True
            elif '-' in part:
                a, b = part.split('-', 1)
                if int(a) <= val <= int(b):
                    return True
            elif int(part) == val:
                return True
        return False

    minute, hour, day, month, weekday = parts
    # Python weekday(): 0=Mon; cron weekday: 0=Sun → remap
    py_wd = dt.weekday()  # Mon=0..Sun=6
    cron_wd = (py_wd + 1) % 7   # Sun=0..Sat=6
    return (
        _match(minute,  dt.minute) and
        _match(hour,    dt.hour)   and
        _match(day,     dt.day)    and
        _match(month,   dt.month)  and
        _match(weekday, cron_wd)
    )


def _fire_sched_task(task: dict):
    """Send the task prompt to the target Claude session."""
    from druidclaw.web.bridge import get_session
    sess_name = task.get("session_name", "")
    prompt    = task.get("prompt", "").strip()
    if not prompt:
        return
    s = get_session(sess_name)
    if not s or not s.is_alive():
        logger.warning(f"[SchedTask {task['id']}] session '{sess_name}' not alive, skip")
        return
    s.send_input((prompt + "\n").encode("utf-8"))
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    logger.info(f"[SchedTask {task['id']}] → '{sess_name}': {prompt[:60]!r}")
    with _sched_lock:
        for t in _sched_tasks:
            if t["id"] == task["id"]:
                t["last_run"]  = now_str
                t["run_count"] = t.get("run_count", 0) + 1
                break
    _save_sched_tasks()


def _scheduler_loop():
    """Background daemon: fires scheduled tasks on time."""
    import time
    while True:
        # sleep until next full minute
        now = datetime.now()
        time.sleep(60 - now.second + 0.5)
        now = datetime.now()
        with _sched_lock:
            tasks = list(_sched_tasks)
        for task in tasks:
            if not task.get("enabled"):
                continue
            try:
                stype = task.get("schedule_type", "interval")
                due   = False
                if stype == "interval":
                    interval = max(1, int(task.get("interval_minutes", 60)))
                    last_run = task.get("last_run")
                    if last_run:
                        last_dt = datetime.strptime(last_run, "%Y-%m-%d %H:%M:%S")
                        due = (now - last_dt).total_seconds() >= interval * 60
                    else:
                        due = True  # never run yet
                elif stype == "cron":
                    due = _cron_matches(task.get("cron_expr", "* * * * *"), now)
                if due:
                    threading.Thread(target=_fire_sched_task, args=(task,),
                                     daemon=True).start()
            except Exception as e:
                logger.warning(f"[SchedTask {task['id']}] error: {e}")


def start_scheduler():
    """Start the background scheduler thread. Called from app lifespan."""
    _load_sched_tasks()
    threading.Thread(target=_scheduler_loop, daemon=True, name="task-scheduler").start()


# ---- Scheduled tasks REST API ----

class TaskCreateRequest(BaseModel):
    name:             str   = ""
    session_name:     str   = ""
    prompt:           str   = ""
    schedule_type:    str   = "interval"   # "interval" | "cron"
    interval_minutes: int   = 60
    cron_expr:        str   = "0 * * * *"  # hourly default
    enabled:          bool  = True


class TaskUpdateRequest(BaseModel):
    name:             Optional[str]  = None
    session_name:     Optional[str]  = None
    prompt:           Optional[str]  = None
    schedule_type:    Optional[str]  = None
    interval_minutes: Optional[int]  = None
    cron_expr:        Optional[str]  = None
    enabled:          Optional[bool] = None


@router.get("/api/tasks")
def api_tasks_list():
    with _sched_lock:
        return {"tasks": list(_sched_tasks)}


@router.post("/api/tasks")
def api_tasks_create(req: TaskCreateRequest):
    if not req.session_name.strip():
        raise HTTPException(400, "session_name 不能为空")
    if not req.prompt.strip():
        raise HTTPException(400, "prompt 不能为空")
    task = {
        "id":               _uuid.uuid4().hex[:8],
        "name":             req.name.strip() or f"任务{len(_sched_tasks)+1}",
        "session_name":     req.session_name.strip(),
        "prompt":           req.prompt,
        "schedule_type":    req.schedule_type,
        "interval_minutes": max(1, req.interval_minutes),
        "cron_expr":        req.cron_expr,
        "enabled":          req.enabled,
        "last_run":         None,
        "run_count":        0,
        "created_at":       datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    with _sched_lock:
        _sched_tasks.append(task)
    _save_sched_tasks()
    return task


@router.post("/api/tasks/{task_id}/run")
def api_tasks_run_now(task_id: str):
    """Immediately fire a task once regardless of schedule."""
    with _sched_lock:
        task = next((t for t in _sched_tasks if t["id"] == task_id), None)
    if task is None:
        raise HTTPException(404, "Task not found")
    threading.Thread(target=_fire_sched_task, args=(task,), daemon=True).start()
    return {"ok": True}


@router.delete("/api/tasks/{task_id}")
def api_tasks_delete(task_id: str):
    with _sched_lock:
        idx = next((i for i, t in enumerate(_sched_tasks) if t["id"] == task_id), None)
        if idx is None:
            raise HTTPException(404, "Task not found")
        _sched_tasks.pop(idx)
    _save_sched_tasks()
    return {"ok": True}


@router.patch("/api/tasks/{task_id}")
def api_tasks_update(task_id: str, req: TaskUpdateRequest):
    with _sched_lock:
        task = next((t for t in _sched_tasks if t["id"] == task_id), None)
        if task is None:
            raise HTTPException(404, "Task not found")
        if req.name             is not None: task["name"]             = req.name.strip()
        if req.session_name     is not None: task["session_name"]     = req.session_name.strip()
        if req.prompt           is not None: task["prompt"]           = req.prompt
        if req.schedule_type    is not None: task["schedule_type"]    = req.schedule_type
        if req.interval_minutes is not None: task["interval_minutes"] = max(1, req.interval_minutes)
        if req.cron_expr        is not None: task["cron_expr"]        = req.cron_expr
        if req.enabled          is not None: task["enabled"]          = req.enabled
    _save_sched_tasks()
    with _sched_lock:
        return next(t for t in _sched_tasks if t["id"] == task_id)


class FeishuStartRequest(BaseModel):
    app_id: str = ""
    app_secret: str = ""
    reply_delay: float = 2.0


@router.post("/api/feishu/start")
def api_feishu_start(req: FeishuStartRequest):
    """
    One-shot: save config + start bot.
    Claude session is auto-created on connect and auto-destroyed on disconnect.
    """
    from druidclaw.web.state import (
        _load_feishu_config, _save_feishu_config,
        _bridge_cfg, _bridge_cfg_lock,
    )
    from druidclaw.web.bridge import _start_feishu_bot, _save_bridge_config
    # 1. Resolve credentials
    app_id = req.app_id.strip()
    app_secret = req.app_secret.strip()
    if not app_id or not app_secret:
        cfg = _load_feishu_config()
        app_id = app_id or cfg.get("app_id", "")
        app_secret = app_secret or cfg.get("app_secret", "")
    if not app_id or not app_secret:
        raise HTTPException(400, "请先填写 App ID 和 App Secret")

    _save_feishu_config(app_id, app_secret)

    delay = max(0.5, min(60.0, req.reply_delay))
    with _bridge_cfg_lock:
        _bridge_cfg["reply_delay"] = delay
    _save_bridge_config()

    # Auto session name: generate from app_id prefix
    auto_sess = "fbs_" + app_id[-6:].replace("_", "")

    # Start legacy bot
    bot = _start_feishu_bot(app_id, app_secret,
                            auto_session_name=auto_sess, card_id="__legacy__")
    bot._reply_delay = delay

    return {"ok": True, "auto_session": auto_sess}


@router.post("/api/feishu/stop")
def api_feishu_stop():
    """Stop legacy bot (auto-destroys the bound Claude session via disconnect callback)."""
    from druidclaw.web.bridge import _stop_feishu_bot
    _stop_feishu_bot(card_id="__legacy__")
    return {"ok": True}
