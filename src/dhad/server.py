"""Asynchronous REST service for Dhad.

The server exposes two stable surfaces:

* ``/v2/*`` — backward-compatible LanguageTool v2 endpoints.
* ``/api/v1/*`` and short aliases — strict JSON/Pydantic endpoints for all
  first-class Dhad analyses.

CPU-bound linguistic work is dispatched to FastAPI's thread pool so the event
loop remains responsive under concurrent clients.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from functools import lru_cache
import os
from pathlib import Path
from typing import Annotated, AsyncIterator, Iterable

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from . import Dhad, Suppression, __version__
from .templates import generate_document, list_templates
from .api.models import (
    CheckRequest,
    CheckResponse,
    DiacritizeRequest,
    DiacritizeResponse,
    DialectRequest,
    DialectResponse,
    HealthResponse,
    IntelligenceRequest,
    IntelligenceResponse,
    RewriteRequest,
    RewriteResponse,
    AnalyticsRequest,
    AnalyticsResponse,
    TemplateGenerateRequest,
    TemplateGenerateResponse,
    TemplateListResponse,
    ParseRequest,
    ParseResponse,
    StyleRequest,
    StyleResponse,
)
from .api.serializers import (
    check_response,
    diacritize_response,
    dialect_response,
    intelligence_response,
    rewrite_response,
    analytics_response,
    template_generate_response,
    template_list_response,
    parse_response,
    style_response,
)
from .match import CATEGORIES, Match
from .privacy import configure_zero_text_logging
from .security import (
    ProductionSecurityMiddleware,
    SecuritySettings,
    enforce_text_limit,
)
from .style import StyleProfile
from .sync import RedisSyncBackend, SyncSettings, create_sync_router

WEB_DIR = Path(__file__).parent / "web"
WEB_ASSETS_DIR = WEB_DIR / "assets"
_DEFAULT_CORS_ORIGINS = (
    "http://127.0.0.1:8010",
    "http://localhost:8010",
    "http://[::1]:8010",
)
_EXTENSION_ORIGIN_RE = r"^(chrome-extension|moz-extension)://[A-Za-z0-9_-]+$"


def _configured_cors_origins(explicit: Iterable[str] | None = None) -> list[str]:
    """Resolve explicit or environment-provided browser origins.

    The default is intentionally local-only. Deployments that expose Dhad on a
    different origin must opt in through ``DHAD_CORS_ORIGINS`` or the app
    factory argument; wildcard origins are rejected to avoid silently sending
    user text to arbitrary web pages.
    """

    if explicit is not None:
        values = [item.strip().rstrip("/") for item in explicit if item.strip()]
    else:
        configured = os.environ.get("DHAD_CORS_ORIGINS", "")
        values = [item.strip().rstrip("/") for item in configured.split(",") if item.strip()]
        if not values:
            values = list(_DEFAULT_CORS_ORIGINS)
    if "*" in values:
        raise ValueError("DHAD_CORS_ORIGINS must enumerate trusted origins; '*' is forbidden")
    return list(dict.fromkeys(values))


def _lt_match(text: str, match: Match) -> dict:
    """Convert one Dhad match to the LanguageTool JSON shape."""

    context_start = max(0, match.offset - 20)
    context_end = min(len(text), match.end + 20)
    issue_type = {
        "spelling": "misspelling",
        "grammar": "grammar",
        "punctuation": "typographical",
        "style": "style",
    }.get(match.category, "uncategorized")
    return {
        "message": match.message,
        "shortMessage": match.message,
        "offset": match.offset,
        "length": match.length,
        "replacements": [{"value": replacement} for replacement in match.replacements],
        "context": {
            "text": text[context_start:context_end],
            "offset": match.offset - context_start,
            "length": match.length,
        },
        "sentence": "",
        "rule": {
            "id": match.rule_id,
            "description": match.explanation or match.message,
            "issueType": issue_type,
            "category": {"id": match.category.upper(), "name": CATEGORIES[match.category]},
        },
        "ignoreForIncompleteSentence": False,
        "contextForSureMatch": 0,
        "severity": match.severity,
        "autofix": match.autofix,
        "confidence": match.confidence,
        "priority": match.priority,
        "tags": list(match.tags),
        "references": list(match.references),
        "profiles": list(match.profiles),
    }


@lru_cache(maxsize=8)
def _profile_checker(profile: str) -> Dhad:
    """Reuse immutable linguistic resources across style profiles."""

    return Dhad(style_profile=StyleProfile(profile))


def create_app(
    engine: Dhad | None = None,
    *,
    serve_web: bool = True,
    cors_origins: Iterable[str] | None = None,
    security_settings: SecuritySettings | None = None,
    serve_sync: bool = True,
    sync_backend=None,
    sync_settings: SyncSettings | None = None,
    analysis_concurrency: int | None = None,
) -> FastAPI:
    """Create an independently testable FastAPI application.

    ``serve_web=False`` builds an API-only process for locked-down or reverse-
    proxied deployments. CORS defaults to loopback origins plus browser-
    extension origins; remote web origins require explicit configuration.
    """

    checker = engine or Dhad()
    settings = security_settings or SecuritySettings.from_env()
    if analysis_concurrency is None:
        raw_concurrency = os.environ.get("DHAD_MAX_CONCURRENT_ANALYSES", "8")
        try:
            analysis_concurrency = int(raw_concurrency)
        except ValueError as exc:
            raise ValueError("DHAD_MAX_CONCURRENT_ANALYSES must be an integer") from exc
    if analysis_concurrency < 1 or analysis_concurrency > 256:
        raise ValueError("analysis_concurrency must be between 1 and 256")
    analysis_slots = asyncio.Semaphore(analysis_concurrency)

    async def run_analysis(function, /, *args, **kwargs):
        async with analysis_slots:
            return await run_in_threadpool(function, *args, **kwargs)
    resolved_cors_origins = tuple(_configured_cors_origins(cors_origins))
    configure_zero_text_logging(checker.privacy)
    sync_router = None
    if serve_sync:
        if sync_backend is None and (redis_url := os.environ.get("DHAD_REDIS_URL")):
            sync_backend = RedisSyncBackend(redis_url)
        sync_router = create_sync_router(
            backend=sync_backend,
            settings=sync_settings or SyncSettings.from_env(),
            api_keys=settings.api_keys,
            allowed_origins=resolved_cors_origins,
            allowed_origin_regex=_EXTENSION_ORIGIN_RE,
        )

    @asynccontextmanager
    async def lifespan(_application: FastAPI) -> AsyncIterator[None]:
        yield
        if sync_router is not None:
            await sync_router.hub.close()  # type: ignore[attr-defined]

    application = FastAPI(
        title="Dhad — ضاد",
        description=(
            "Enterprise-grade Arabic spelling, grammar, morphology, syntax, "
            "style, dialect, semantics, and diacritization API."
        ),
        version=__version__,
        openapi_url="/openapi.json",
        docs_url="/docs",
        redoc_url="/redoc",
        lifespan=lifespan,
    )
    application.state.security_settings = settings
    application.state.zero_text_logging = True
    application.state.analysis_concurrency = analysis_concurrency
    application.add_middleware(
        ProductionSecurityMiddleware,
        settings=settings,
    )
    application.add_middleware(
        CORSMiddleware,
        allow_origins=resolved_cors_origins,
        allow_origin_regex=_EXTENSION_ORIGIN_RE,
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type", "Authorization", "X-API-Key", "Accept"],
        max_age=600,
    )

    @application.exception_handler(RequestValidationError)
    async def validation_error_handler(_request: Request, exc: RequestValidationError):
        errors = [
            {
                "type": item.get("type", "validation_error"),
                "loc": list(item.get("loc", ())),
                "msg": item.get("msg", "Invalid request"),
            }
            for item in exc.errors()
        ]
        too_long = any(
            item["type"] == "string_too_long" and "text" in item["loc"] for item in errors
        )
        status = 413 if too_long else 422
        return JSONResponse(
            status_code=status,
            content={
                "detail": errors,
                "error": {
                    "code": "text_too_large" if too_long else "validation_error",
                    "message": (
                        f"Text exceeds {settings.max_text_characters} characters"
                        if too_long
                        else "Request validation failed"
                    ),
                },
            },
            headers={"Cache-Control": "no-store"},
        )

    @application.middleware("http")
    async def security_headers(request, call_next):
        response: Response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
        response.headers.setdefault("Cross-Origin-Resource-Policy", "same-origin")
        if request.url.scheme == "https":
            response.headers.setdefault(
                "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
            )
        if request.url.path.startswith(("/api/", "/v2/")) or request.url.path in {
            "/check",
            "/parse",
            "/diacritize",
            "/style",
            "/dialect",
            "/intelligence",
            "/rewrite",
            "/analytics",
        }:
            response.headers.setdefault("Cache-Control", "no-store")
        response.headers.setdefault(
            "Permissions-Policy",
            "camera=(), microphone=(), geolocation=(), payment=(), usb=()",
        )
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self' https://cdn.jsdelivr.net; "
            "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
            "img-src 'self' data: https://fastapi.tiangolo.com; "
            "connect-src 'self' http://127.0.0.1:* "
            "http://localhost:*; worker-src 'self'; manifest-src 'self'; "
            "object-src 'none'; base-uri 'self'; frame-ancestors 'none'",
        )
        return response

    if serve_web:
        application.mount("/static", StaticFiles(directory=WEB_ASSETS_DIR), name="static")

    @application.post("/v2/check")
    async def languagetool_check(
        text: Annotated[str, Form()] = "",
        language: Annotated[str, Form()] = "ar",
        disabledCategories: Annotated[str, Form()] = "",  # noqa: N803
        disabledRules: Annotated[str, Form()] = "",  # noqa: N803
        profiles: Annotated[str, Form()] = "default",
    ) -> dict:
        del language
        try:
            enforce_text_limit(text, settings)
        except ValueError as exc:
            raise HTTPException(status_code=413, detail=str(exc)) from exc
        ignored_rules = frozenset(item.strip() for item in disabledRules.split(",") if item.strip())
        active_profiles = [item.strip() for item in profiles.split(",") if item.strip()] or [
            "default"
        ]
        matches = await run_analysis(
            checker.check,
            text,
            suppression=Suppression(rule_ids=ignored_rules),
            profiles=active_profiles,
        )
        if disabledCategories:
            disabled = {
                category.strip().lower()
                for category in disabledCategories.split(",")
                if category.strip()
            }
            matches = [item for item in matches if item.category.lower() not in disabled]
        return {
            "software": {
                "name": "Dhad",
                "version": __version__,
                "buildDate": "",
                "apiVersion": 1,
                "premium": False,
                "status": "",
            },
            "warnings": {"incompleteResults": False},
            "language": {
                "name": "Arabic",
                "code": "ar",
                "detectedLanguage": {"name": "Arabic", "code": "ar", "confidence": 1.0},
            },
            "matches": [_lt_match(text, item) for item in matches],
        }

    @application.get("/v2/languages")
    async def languages() -> list[dict]:
        return [{"name": "Arabic", "code": "ar", "longCode": "ar"}]

    def validate_text(text: str) -> None:
        try:
            enforce_text_limit(text, settings)
        except ValueError as exc:
            raise HTTPException(status_code=413, detail=str(exc)) from exc

    def validate_overrides(values: Iterable[str], *, label: str, max_length: int) -> frozenset[str]:
        cleaned: set[str] = set()
        for value in values:
            item = value.strip()
            if not item or len(item) > max_length:
                raise HTTPException(
                    status_code=422,
                    detail=f"{label} entries must be non-empty and at most {max_length} characters",
                )
            cleaned.add(item)
        return frozenset(cleaned)

    async def check_json(request: CheckRequest) -> CheckResponse:
        validate_text(request.text)
        suppression = Suppression(
            rule_ids=validate_overrides(
                request.disabled_rules, label="disabled_rules", max_length=160
            ),
            words=validate_overrides(request.custom_words, label="custom_words", max_length=128),
        )
        matches = await run_analysis(
            checker.check,
            request.text,
            suppression=suppression,
            profiles=request.profiles,
            diacritics_mode=request.diacritics_mode,
        )
        disabled = {category.lower() for category in request.disabled_categories}
        if disabled:
            matches = [item for item in matches if item.category.lower() not in disabled]
        return check_response(__version__, matches)

    application.add_api_route(
        "/check", check_json, methods=["POST"], response_model=CheckResponse, tags=["Analysis"]
    )
    application.add_api_route(
        "/api/v1/check",
        check_json,
        methods=["POST"],
        response_model=CheckResponse,
        tags=["Analysis"],
    )

    async def parse_json(request: ParseRequest) -> ParseResponse:
        validate_text(request.text)
        parsed = await run_analysis(
            checker.parse,
            request.text,
            dialect_to_msa=request.dialect_to_msa,
            neural_refine=request.neural_refine,
        )
        return parse_response(__version__, parsed)

    application.add_api_route(
        "/parse", parse_json, methods=["POST"], response_model=ParseResponse, tags=["Analysis"]
    )
    application.add_api_route(
        "/api/v1/parse",
        parse_json,
        methods=["POST"],
        response_model=ParseResponse,
        tags=["Analysis"],
    )

    async def diacritize_json(request: DiacritizeRequest) -> DiacritizeResponse:
        validate_text(request.text)
        result = await run_analysis(
            checker.diacritize,
            request.text,
            mode=request.mode,
            neural_refine=request.neural_refine,
        )
        return diacritize_response(__version__, result)

    application.add_api_route(
        "/diacritize",
        diacritize_json,
        methods=["POST"],
        response_model=DiacritizeResponse,
        tags=["Generation"],
    )
    application.add_api_route(
        "/api/v1/diacritize",
        diacritize_json,
        methods=["POST"],
        response_model=DiacritizeResponse,
        tags=["Generation"],
    )

    async def style_json(request: StyleRequest) -> StyleResponse:
        validate_text(request.text)
        style_checker = (
            checker if request.profile == "general" else _profile_checker(request.profile)
        )
        report = await run_analysis(style_checker.style_report, request.text)
        return style_response(__version__, report)

    application.add_api_route(
        "/style", style_json, methods=["POST"], response_model=StyleResponse, tags=["Analysis"]
    )
    application.add_api_route(
        "/api/v1/style",
        style_json,
        methods=["POST"],
        response_model=StyleResponse,
        tags=["Analysis"],
    )

    async def dialect_json(request: DialectRequest) -> DialectResponse:
        validate_text(request.text)
        report = await run_analysis(checker.dialect_report, request.text)
        return dialect_response(__version__, report)

    application.add_api_route(
        "/dialect",
        dialect_json,
        methods=["POST"],
        response_model=DialectResponse,
        tags=["Analysis"],
    )
    application.add_api_route(
        "/api/v1/dialect",
        dialect_json,
        methods=["POST"],
        response_model=DialectResponse,
        tags=["Analysis"],
    )

    async def intelligence_json(request: IntelligenceRequest) -> IntelligenceResponse:
        validate_text(request.text)
        suppression = Suppression(
            rule_ids=validate_overrides(
                request.disabled_rules, label="disabled_rules", max_length=160
            ),
            words=validate_overrides(request.custom_words, label="custom_words", max_length=128),
        )
        report = await run_analysis(
            checker.intelligence_report,
            request.text,
            style_profile=request.profile,
            suppression=suppression,
        )
        return intelligence_response(__version__, report)

    application.add_api_route(
        "/intelligence",
        intelligence_json,
        methods=["POST"],
        response_model=IntelligenceResponse,
        tags=["Writing Intelligence"],
    )
    application.add_api_route(
        "/api/v1/intelligence",
        intelligence_json,
        methods=["POST"],
        response_model=IntelligenceResponse,
        tags=["Writing Intelligence"],
    )

    async def rewrite_json(request: RewriteRequest) -> RewriteResponse:
        validate_text(request.text)
        report = await run_analysis(
            checker.rewrite,
            request.text,
            mode=request.mode,
            alternatives=request.alternatives,
        )
        return rewrite_response(__version__, report)

    application.add_api_route(
        "/rewrite",
        rewrite_json,
        methods=["POST"],
        response_model=RewriteResponse,
        tags=["Writing Intelligence"],
    )
    application.add_api_route(
        "/api/v1/rewrite",
        rewrite_json,
        methods=["POST"],
        response_model=RewriteResponse,
        tags=["Writing Intelligence"],
    )

    async def analytics_json(request: AnalyticsRequest) -> AnalyticsResponse:
        validate_text(request.text)
        report = await run_analysis(
            checker.analytics_report,
            request.text,
            style_profile=request.profile,
        )
        return analytics_response(__version__, report)

    application.add_api_route(
        "/analytics",
        analytics_json,
        methods=["POST"],
        response_model=AnalyticsResponse,
        tags=["Writing Intelligence"],
    )
    application.add_api_route(
        "/api/v1/analytics",
        analytics_json,
        methods=["POST"],
        response_model=AnalyticsResponse,
        tags=["Writing Intelligence"],
    )

    @application.get(
        "/api/v1/templates",
        response_model=TemplateListResponse,
        tags=["Writing Intelligence"],
    )
    async def templates_json() -> TemplateListResponse:
        return template_list_response(__version__, list_templates())

    @application.post(
        "/api/v1/templates/generate",
        response_model=TemplateGenerateResponse,
        tags=["Writing Intelligence"],
    )
    async def template_generate_json(
        request: TemplateGenerateRequest,
    ) -> TemplateGenerateResponse:
        try:
            document = await run_analysis(
                generate_document,
                request.template_id,
                request.values,
                tone=request.tone,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return template_generate_response(__version__, document)

    @application.get("/api/health", response_model=HealthResponse, tags=["Operations"])
    async def health() -> HealthResponse:
        return HealthResponse(
            status="ok",
            version=__version__,
            rules=checker.rule_count,
            lexicon_lemmas=len(checker.morphology.lexicon.lexemes),
            lexicon_forms=len(checker.morphology.lexicon.known_forms),
            syntax_engine="deterministic-v1+hybrid-fallback",
            candidate_irab=True,
            categories=CATEGORIES,
        )

    if serve_web:

        @application.get("/", include_in_schema=False)
        async def editor() -> FileResponse:
            return FileResponse(WEB_DIR / "index.html", media_type="text/html")

        @application.get("/manifest.webmanifest", include_in_schema=False)
        async def web_manifest() -> FileResponse:
            return FileResponse(
                WEB_DIR / "manifest.webmanifest",
                media_type="application/manifest+json",
            )

        @application.get("/service-worker.js", include_in_schema=False)
        async def service_worker() -> FileResponse:
            response = FileResponse(
                WEB_DIR / "service-worker.js",
                media_type="application/javascript",
            )
            response.headers["Cache-Control"] = "no-cache"
            response.headers["Service-Worker-Allowed"] = "/"
            return response

    if sync_router is not None:
        application.include_router(sync_router)

    return application


app = create_app()
