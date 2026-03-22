"""
Session REST API and WebSocket PTY bridge routes.
"""
import asyncio
import logging
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from druidclaw.web.state import _sessions, _sessions_lock
from druidclaw.web.bridge import get_session, create_session, remove_session
from druidclaw.core.session import ClaudeSession

logger = logging.getLogger(__name__)

router = APIRouter()


# ── Session helpers ───────────────────────────────────────────────

def all_sessions() -> list[dict]:
    with _sessions_lock:
        return [s.info() for s in _sessions.values()]


# ── REST API ──────────────────────────────────────────────────────

class NewSessionRequest(BaseModel):
    name: Optional[str] = None
    workdir: str = "."
    args: list[str] = []


class RenameRequest(BaseModel):
    new_name: str


@router.get("/api/sessions")
def api_list_sessions():
    with _sessions_lock:
        dead = [n for n, s in _sessions.items() if not s.is_alive()]
        for n in dead:
            del _sessions[n]
    return {"sessions": all_sessions()}


@router.post("/api/sessions")
def api_new_session(req: NewSessionRequest):
    # Prune dead sessions so their names are available for reuse
    with _sessions_lock:
        dead = [n for n, s in _sessions.items() if not s.is_alive()]
        for n in dead:
            del _sessions[n]

    name = req.name
    if not name:
        with _sessions_lock:
            i = 1
            while f"session{i}" in _sessions:
                i += 1
            name = f"session{i}"
    elif get_session(name) and get_session(name).is_alive():
        raise HTTPException(400, f"会话名 '{name}' 已被占用，请换一个名字")

    workdir_path = Path(req.workdir).expanduser().resolve()
    dir_created = not workdir_path.exists()
    try:
        s = create_session(name=name, workdir=req.workdir, claude_args=req.args)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {
        "ok": True,
        "name": name,
        "pid": s.pid,
        "workdir": str(workdir_path),
        "dir_created": dir_created,
    }


@router.delete("/api/sessions/{name}")
def api_kill_session(name: str, force: bool = False):
    s = get_session(name)
    if s is None:
        raise HTTPException(404, f"Session '{name}' not found")
    remove_session(name, force=force)
    return {"ok": True}


@router.patch("/api/sessions/{name}")
def api_rename_session(name: str, req: RenameRequest):
    new_name = req.new_name.strip()
    if not new_name:
        raise HTTPException(400, "名称不能为空")
    if new_name == name:
        return {"ok": True, "name": new_name}
    with _sessions_lock:
        if name not in _sessions:
            raise HTTPException(404, f"Session '{name}' not found")
        if new_name in _sessions:
            raise HTTPException(409, f"会话名 '{new_name}' 已存在")
        s = _sessions.pop(name)
        s.name = new_name
        _sessions[new_name] = s
    return {"ok": True, "name": new_name}


@router.get("/api/sessions/{name}")
def api_session_info(name: str):
    s = get_session(name)
    if s is None:
        raise HTTPException(404, f"Session '{name}' not found")
    return s.info()


# ── WebSocket PTY bridge ──────────────────────────────────────────

@router.websocket("/ws/{name}")
async def ws_attach(websocket: WebSocket, name: str):
    """
    Bidirectional WebSocket ↔ PTY bridge.

    Message protocol (JSON framed):
      Client → Server:
        {"type": "input",  "data": "<base64>"}   raw keystrokes
        {"type": "resize", "rows": N, "cols": N}  terminal resize
        {"type": "create", "workdir": ".", "args": []}  create+attach new session

      Server → Client:
        {"type": "output", "data": "<base64>"}   PTY output
        {"type": "exit"}                          session exited
        {"type": "error", "message": "..."}       error
        {"type": "connected", "name": "..."}      attach confirmed
    """
    await websocket.accept()

    s = get_session(name)
    if s is None:
        # Auto-create if not existing
        try:
            s = create_session(name=name, workdir=".")
        except Exception as e:
            await websocket.send_json({"type": "error", "message": str(e)})
            await websocket.close()
            return

    if not s.is_alive():
        await websocket.send_json({"type": "error", "message": f"Session '{name}' is not alive"})
        await websocket.close()
        return

    await websocket.send_json({"type": "connected", "name": name, "pid": s.pid})

    # Send buffered output first
    buf = s.get_buffer()
    if buf:
        import base64
        await websocket.send_json({"type": "output", "data": base64.b64encode(buf).decode()})

    loop = asyncio.get_event_loop()
    stop_event = asyncio.Event()

    # PTY → WebSocket
    import base64

    async def pty_output_task():
        """Forward PTY output to the WebSocket."""
        out_queue: asyncio.Queue = asyncio.Queue(maxsize=256)

        def on_output(data: bytes):
            try:
                loop.call_soon_threadsafe(out_queue.put_nowait, data)
            except Exception:
                pass

        s.add_output_callback(on_output)
        try:
            while not stop_event.is_set() and s.is_alive():
                try:
                    data = await asyncio.wait_for(out_queue.get(), timeout=0.5)
                    await websocket.send_json({
                        "type": "output",
                        "data": base64.b64encode(data).decode()
                    })
                except asyncio.TimeoutError:
                    continue
                except Exception:
                    break
        finally:
            s.remove_output_callback(on_output)
            if not s.is_alive():
                try:
                    await websocket.send_json({"type": "exit"})
                except Exception:
                    pass

    # WebSocket → PTY
    async def ws_input_task():
        try:
            while not stop_event.is_set():
                msg = await websocket.receive_json()
                mtype = msg.get("type", "")
                if mtype == "input":
                    data = base64.b64decode(msg["data"])
                    s.send_input(data)
                elif mtype == "resize":
                    rows = max(int(msg.get("rows", 24)), 1)
                    cols = max(int(msg.get("cols", 80)), 1)
                    s.resize(rows, cols)
                elif mtype == "ping":
                    await websocket.send_json({"type": "pong"})
        except WebSocketDisconnect:
            pass
        except Exception as e:
            logger.debug(f"ws_input_task error: {e}")
        finally:
            stop_event.set()

    try:
        await asyncio.gather(pty_output_task(), ws_input_task())
    except Exception:
        pass
    finally:
        stop_event.set()
