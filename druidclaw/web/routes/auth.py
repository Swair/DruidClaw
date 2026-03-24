"""Authentication routes: login page and auth middleware."""
import os
from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse, Response

router = APIRouter()

_DRUIDCLAW_TOKEN: str = os.environ.get("DRUIDCLAW_TOKEN", "dc").strip()

_PUBLIC = {"/login", "/logout", "/favicon.ico", "/api/auth/check"}
_STATIC_PREFIX = "/static"

_LOGIN_HTML = """<!DOCTYPE html>
<html><head><meta charset="UTF-8"><title>DruidClaw</title><style>
*{{box-sizing:border-box}}
body{{display:flex;align-items:center;justify-content:center;height:100vh;
     margin:0;background:#1a1a2e;font-family:system-ui,sans-serif}}
.box{{background:#16213e;padding:40px;border-radius:14px;width:320px;
      box-shadow:0 8px 32px rgba(0,0,0,.4)}}
h2{{color:#e2e8f0;margin:0 0 8px;font-size:1.3rem}}
p{{color:#94a3b8;margin:0 0 24px;font-size:.85rem}}
input{{width:100%;padding:10px 14px;background:#0f3460;border:1px solid #334155;
       border-radius:8px;color:#e2e8f0;font-size:15px;outline:none}}
input:focus{{border-color:#7c6fd7}}
button{{width:100%;padding:10px;margin-top:14px;background:#7c6fd7;border:none;
        border-radius:8px;color:#fff;font-size:15px;cursor:pointer;font-weight:600}}
button:hover{{background:#6c5fc7}}
.err{{color:#f87171;margin-top:12px;font-size:13px;text-align:center}}
</style></head><body>
<div class="box">
  <h2>🔐 DruidClaw</h2>
  <p>请输入访问密码</p>
  <form method="post" action="/login">
    <input type="hidden" name="next" value="{next}">
    <input type="password" name="password" placeholder="密码" autofocus autocomplete="current-password">
    <button type="submit">登录</button>
    {error}
  </form>
</div>
</body></html>"""


async def _auth_middleware(request: Request, call_next):
    # 如果没有设置令牌，则不需要认证
    if not _DRUIDCLAW_TOKEN:
        return await call_next(request)

    # 检查是否是公开路径
    if request.url.path in _PUBLIC or request.url.path.startswith(_STATIC_PREFIX):
        return await call_next(request)

    # 获取用户的 token（从 cookie、header 或 query 参数）
    token = (
        request.cookies.get("cc_token", "")
        or request.headers.get("authorization", "").removeprefix("Bearer ").strip()
        or request.query_params.get("token", "")
    )

    # token 有效，允许访问
    if token == _DRUIDCLAW_TOKEN:
        return await call_next(request)

    # 对于 API、WebSocket 和 Webhook 请求，返回 401
    if any(request.url.path.startswith(p) for p in ("/api", "/ws", "/webhook")):
        return Response(status_code=401, content="Unauthorized")

    # 对于其他请求，重定向到登录页面
    return RedirectResponse(url=f"/login?next={request.url.path}", status_code=303)


@router.get("/login", response_class=HTMLResponse)
def login_page(next: str = "/", error: str = ""):
    err = '<p class="err">密码错误，请重试</p>' if error else ""
    return HTMLResponse(_LOGIN_HTML.format(next=next, error=err))


@router.post("/api/auth/check")
async def auth_check(request: Request):
    """Check if the current request is authenticated."""
    if not _DRUIDCLAW_TOKEN:
        return {"ok": True, "auth_enabled": False}

    token = (
        request.cookies.get("cc_token", "")
        or request.headers.get("authorization", "").removeprefix("Bearer ").strip()
        or request.query_params.get("token", "")
    )

    if token == _DRUIDCLAW_TOKEN:
        return {"ok": True, "auth_enabled": True}

    return Response(status_code=401, content="Unauthorized")


@router.post("/login")
async def do_login(next: str = Form("/"), password: str = Form("")):
    if not _DRUIDCLAW_TOKEN or password == _DRUIDCLAW_TOKEN:
        resp = RedirectResponse(url=next or "/", status_code=303)
        resp.set_cookie("cc_token", password, max_age=86400 * 30,
                        httponly=True, samesite="strict")
        return resp
    return RedirectResponse(url=f"/login?next={next}&error=1", status_code=303)


@router.get("/logout")
@router.post("/logout")
async def do_logout():
    resp = RedirectResponse(url="/login", status_code=303)
    resp.delete_cookie("cc_token")
    return resp
