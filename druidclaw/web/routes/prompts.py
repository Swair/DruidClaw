"""Prompt template library API routes."""
import json
import uuid
import logging
import threading
from datetime import datetime
from typing import Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from druidclaw.web.state import RUN_DIR

router = APIRouter()
logger = logging.getLogger(__name__)

PROMPTS_FILE = RUN_DIR / "prompts.json"
_prompts: list[dict] = []
_lock = threading.Lock()


def _load():
    global _prompts
    if PROMPTS_FILE.exists():
        try:
            data = json.loads(PROMPTS_FILE.read_text())
            with _lock:
                _prompts[:] = data if isinstance(data, list) else []
        except Exception:
            pass


def _save():
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    with _lock:
        PROMPTS_FILE.write_text(json.dumps(_prompts, indent=2, ensure_ascii=False))


_load()


class PromptCreate(BaseModel):
    name: str
    prompt: str
    tags: list[str] = []


class PromptUpdate(BaseModel):
    name: Optional[str] = None
    prompt: Optional[str] = None
    tags: Optional[list[str]] = None


@router.get("/api/prompts")
def api_prompts_list():
    with _lock:
        return {"prompts": list(_prompts)}


@router.post("/api/prompts")
def api_prompts_create(req: PromptCreate):
    name   = req.name.strip()
    prompt = req.prompt.strip()
    if not name:   raise HTTPException(400, "name 不能为空")
    if not prompt: raise HTTPException(400, "prompt 不能为空")
    item = {
        "id": uuid.uuid4().hex[:8],
        "name": name,
        "prompt": prompt,
        "tags": req.tags,
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    with _lock:
        _prompts.append(item)
    _save()
    return item


@router.patch("/api/prompts/{pid}")
def api_prompts_update(pid: str, req: PromptUpdate):
    with _lock:
        item = next((p for p in _prompts if p["id"] == pid), None)
        if not item:
            raise HTTPException(404, "模板不存在")
        if req.name   is not None: item["name"]   = req.name.strip()
        if req.prompt is not None: item["prompt"]  = req.prompt.strip()
        if req.tags   is not None: item["tags"]   = req.tags
    _save()
    return item


@router.delete("/api/prompts/{pid}")
def api_prompts_delete(pid: str):
    with _lock:
        idx = next((i for i, p in enumerate(_prompts) if p["id"] == pid), None)
        if idx is None:
            raise HTTPException(404, "模板不存在")
        _prompts.pop(idx)
    _save()
    return {"ok": True}
