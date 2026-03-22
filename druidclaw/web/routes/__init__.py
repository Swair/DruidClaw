"""Route modules for the DruidClaw web server."""
from .auth import router as auth_router
from .sessions import router as sessions_router
from .cards import router as cards_router
from .im import router as im_router
from .stats import router as stats_router
from .tasks import router as tasks_router
from .ssh import router as ssh_router
from .skills import router as skills_router
from .config import router as config_router

__all__ = [
    "auth_router",
    "sessions_router",
    "cards_router",
    "im_router",
    "stats_router",
    "tasks_router",
    "ssh_router",
    "skills_router",
    "config_router",
]
