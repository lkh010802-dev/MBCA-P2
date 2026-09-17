"""KOALA layered backend entrypoint.

`core` contains the upstream MVP backend. `extensions` contains only the local
overrides/additions.  Keeping both directories on the import path lets the
extension modules override matching core modules while every other import
continues to come from the untouched core.
"""

from pathlib import Path
import importlib.util
import os
import sys

from fastapi.middleware.cors import CORSMiddleware


BACKEND_DIR = Path(__file__).resolve().parent
CORE_DIR = BACKEND_DIR / "core"
EXTENSIONS_DIR = BACKEND_DIR / "extensions"
LLM_RUNTIME_DIR = CORE_DIR / "LLM" / "LLM_V1_4_FREEZE"

if not (CORE_DIR / "main.py").exists():
    raise RuntimeError("backend/core/main.py를 찾을 수 없습니다.")

# dotenv and relative data paths used by the upstream backend resolve from core.
os.chdir(CORE_DIR)

# Extensions take precedence; missing modules fall back to the upstream core.
sys.path.insert(0, str(CORE_DIR))
if (LLM_RUNTIME_DIR / "intent_parser.py").exists():
    sys.path.insert(0, str(LLM_RUNTIME_DIR))
sys.path.insert(0, str(EXTENSIONS_DIR))

# Pytest and development reloaders can import a core module before this
# entrypoint.  Clear only names that have an extension counterpart so the
# integrated app consistently uses the extension implementation instead of a
# stale core module from ``sys.modules``.
for extension_file in EXTENSIONS_DIR.glob("*.py"):
    module_name = extension_file.stem
    if module_name not in {"main", "extension_routes"}:
        sys.modules.pop(module_name, None)

# Always load the upstream application entrypoint from ``core`` explicitly.
# Extension modules still take precedence for ordinary imports through
# ``sys.path``, but a legacy ``extensions/main.py`` must never replace the
# current upstream app and pull in routes that no longer exist.
core_main_spec = importlib.util.spec_from_file_location(
    "koala_core_main",
    CORE_DIR / "main.py",
)
if core_main_spec is None or core_main_spec.loader is None:
    raise RuntimeError("backend/core/main.py를 불러올 수 없습니다.")
core_main = importlib.util.module_from_spec(core_main_spec)
core_main_spec.loader.exec_module(core_main)
app = core_main.app
from extension_routes import router as extension_router  # noqa: E402
from user_data_routes import ensure_user_data_tables  # noqa: E402


# Extension-owned schema is prepared before serving requests.  Running DDL
# lazily inside authenticated requests can deadlock with MySQL metadata locks.
ensure_user_data_tables()


def _cors_origins() -> list[str]:
    """Return explicit browser origins without changing the upstream app."""
    origins = {
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    }
    configured = os.getenv("KOALA_CORS_ORIGINS", "")
    frontend_url = os.getenv("FRONTEND_URL", "")
    for value in (*configured.split(","), frontend_url):
        origin = value.strip().rstrip("/")
        if origin and origin != "*":
            origins.add(origin)
    return sorted(origins)


app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins(),
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=[
        "Authorization",
        "Content-Type",
        "X-Koala-Trace-Id",
    ],
)

app.include_router(extension_router)

# The launcher owns the health/identity endpoint.  Replace the upstream root
# response without changing ``core/main.py`` so operators can verify that the
# extension layer, not the standalone core app, is running.
app.router.routes = [
    route for route in app.router.routes if getattr(route, "path", None) != "/"
]


@app.get("/")
def integrated_root():
    return {
        "message": "KOALA integrated backend is running",
        "version": "mvp2-integrated-extensions",
        "entrypoint": "run:app",
    }
