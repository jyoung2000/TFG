"""FastAPI app factory decoupled from runtime bootstrap side effects."""

from __future__ import annotations

import base64
import hmac
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any, cast

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.responses import Response as StarletteResponse

from _routes._errors import HTTPError
from _routes.film import router as film_router
from _routes.film_director import router as film_director_router
from _routes.knowledge import router as knowledge_router
from _routes.jobs import router as jobs_router
from _routes.vision import router as vision_router
from _routes.reproduce import router as reproduce_router
from _routes.prompts import router as prompts_router
from _routes.shot_library import router as shot_library_router
from _routes.timeline import router as timeline_router
from _routes.video_analysis import router as video_analysis_router
from _routes.video_reproduce import router as video_reproduce_router
from _routes.scene import router as scene_router
from _routes.training import router as training_router
from _routes.wangp import router as wangp_router
from _routes.film_generation import router as film_generation_router
from _routes.generation import router as generation_router
from _routes.health import router as health_router
from _routes.ic_lora import router as ic_lora_router
from _routes.image_gen import router as image_gen_router
from _routes.image_analysis import router as image_analysis_router
from _routes.model_library import router as model_library_router
from _routes.models import router as models_router
from _routes.suggest_gap_prompt import router as suggest_gap_prompt_router
from _routes.retake import router as retake_router
from _routes.runtime_policy import router as runtime_policy_router
from _routes.settings import router as settings_router
from logging_policy import install_secret_redaction, log_http_error, log_unhandled_exception, redact_secrets
from state import init_state_service

if TYPE_CHECKING:
    from app_handler import AppHandler

DEFAULT_ALLOWED_ORIGINS: list[str] = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]


def _is_media_path(path: str) -> bool:
    """True for the read-only media endpoints that <img>/<video> load.

    These are the only paths where a query token is accepted, because a media
    element cannot send an Authorization header. Each is a GET that serves one
    file the backend resolved itself — never a path the caller supplied.
    """
    if path == "/api/film/output":
        return True
    # EventSource cannot send headers either; the job feed is read-only.
    if path == "/api/jobs/events":
        return True
    if path.startswith("/api/shot-library/") and path.endswith("/preview"):
        return True
    # Frame thumbnails from video analysis — img tags can't send Bearer.
    if path.startswith("/api/video-analysis/") and path.endswith("/frame"):
        return True
    if path.startswith("/api/image-analysis/") and path.endswith("/media"):
        return True
    if path.startswith("/api/reproduce/") and path.endswith("/media"):
        return True
    if path.startswith("/api/video-reproduce/") and path.endswith("/media"):
        return True
    if path.startswith("/api/training/") and path.endswith("/media"):
        return True
    return path.startswith("/api/film/projects/") and path.endswith("/media")


def create_app(
    *,
    handler: "AppHandler",
    allowed_origins: list[str] | None = None,
    title: str = "LTX-2 Video Generation Server",
    auth_token: str = "",
) -> FastAPI:
    """Create a configured FastAPI app bound to the provided handler."""
    init_state_service(handler)
    install_secret_redaction()

    app = FastAPI(title=title)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins or DEFAULT_ALLOWED_ORIGINS,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def _auth_middleware(  # pyright: ignore[reportUnusedFunction]
        request: Request,
        call_next: Callable[[Request], Awaitable[StarletteResponse]],
    ) -> StarletteResponse:
        if not auth_token:
            return await call_next(request)
        if request.method == "OPTIONS":
            return await call_next(request)
        def _token_matches(candidate: str) -> bool:
            return hmac.compare_digest(candidate, auth_token)

        # WebSocket: check query param
        if request.headers.get("upgrade", "").lower() == "websocket":
            if _token_matches(request.query_params.get("token", "")):
                return await call_next(request)
            return JSONResponse(status_code=401, content={"error": "Unauthorized"})
        # Read-only media GETs are loaded via <img>/<video> tags, which cannot
        # send an Authorization header — accept the query token there only.
        if request.method == "GET" and _is_media_path(request.url.path):
            if _token_matches(request.query_params.get("token", "")):
                return await call_next(request)
        # HTTP: Bearer or Basic auth
        auth_header = request.headers.get("authorization", "")
        if auth_header.startswith("Bearer ") and _token_matches(auth_header[7:]):
            return await call_next(request)
        if auth_header.startswith("Basic "):
            try:
                decoded = base64.b64decode(auth_header[6:]).decode()
                _, _, password = decoded.partition(":")
                if _token_matches(password):
                    return await call_next(request)
            except Exception:
                pass
        return JSONResponse(status_code=401, content={"error": "Unauthorized"})

    async def _route_http_error_handler(request: Request, exc: Exception) -> JSONResponse:
        if isinstance(exc, HTTPError):
            log_http_error(request, exc)
            return JSONResponse(status_code=exc.status_code, content={"error": redact_secrets(str(exc.detail))})
        return JSONResponse(status_code=500, content={"error": redact_secrets(str(exc))})

    async def _validation_error_handler(request: Request, exc: Exception) -> JSONResponse:
        return JSONResponse(status_code=422, content={"error": redact_secrets(str(exc))})

    async def _route_generic_error_handler(request: Request, exc: Exception) -> JSONResponse:
        log_unhandled_exception(request, exc)
        return JSONResponse(status_code=500, content={"error": redact_secrets(str(exc))})

    app.add_exception_handler(RequestValidationError, _validation_error_handler)
    app.add_exception_handler(HTTPError, _route_http_error_handler)
    app.add_exception_handler(Exception, _route_generic_error_handler)

    _include_all_routers(app)
    _install_mcp(app)

    return app


def _include_all_routers(app: FastAPI) -> None:
    for router in (
        health_router, generation_router, models_router, model_library_router, settings_router, image_gen_router,
        image_analysis_router, suggest_gap_prompt_router, retake_router, ic_lora_router, runtime_policy_router,
        film_router, film_generation_router, film_director_router, video_analysis_router, video_reproduce_router,
        scene_router, training_router, wangp_router, knowledge_router, jobs_router, vision_router, reproduce_router,
        prompts_router, shot_library_router, timeline_router,
    ):
        app.include_router(router)


def create_app_routes_only(title: str = "LTX-2 Video Generation Server") -> FastAPI:
    """Only the route table (no handler, no state): what the MCP stdio server
    reads to generate its tools without starting anything heavy."""
    app = FastAPI(title=title)
    _include_all_routers(app)
    return app


def _install_mcp(app: FastAPI) -> None:
    """`POST /mcp`: the MCP Streamable-HTTP endpoint (docs/AGENTS_GUIDE.md).
    Tool calls run in-process through the app's own routes, under the same
    auth token the middleware already checked for this request."""
    from agent.asgi_forward import make_asgi_forwarder
    from agent.mcp_core import McpDispatcher, ToolSpec, build_tools

    # Generated on the first MCP request, not at app creation: walking the
    # OpenAPI schema costs ~1 s and every test builds its own app.
    cache: dict[str, list[ToolSpec]] = {}

    def tools() -> list[ToolSpec]:
        if "tools" not in cache:
            cache["tools"] = build_tools(app)
        return cache["tools"]

    @app.post("/mcp", include_in_schema=False)
    async def route_mcp(request: Request) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        try:
            message = await request.json()
        except ValueError:
            return JSONResponse(status_code=400, content={"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}})
        auth = request.headers.get("authorization", "")
        dispatcher = McpDispatcher(tools=tools(), forward=make_asgi_forwarder(app, {"authorization": auth} if auth else {}))
        if isinstance(message, list):
            batch = cast(list[object], message)
            handled = [await dispatcher.handle(cast(dict[str, Any], m)) for m in batch if isinstance(m, dict)]
            responses = [r for r in handled if r is not None]
            return JSONResponse(content=responses, status_code=200)
        if not isinstance(message, dict):
            return JSONResponse(status_code=400, content={"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "Invalid request"}})
        response = await dispatcher.handle(cast(dict[str, Any], message))
        if response is None:
            return JSONResponse(content=None, status_code=202)
        return JSONResponse(content=response)

    @app.get("/mcp", include_in_schema=False)
    async def route_mcp_get() -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        return JSONResponse(status_code=405, content={"error": "MCP over HTTP is POST-only here (no server-initiated stream)"})
