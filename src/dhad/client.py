"""Developer-facing Python SDK for local and remote Dhad execution."""

from __future__ import annotations

import asyncio
import json
from functools import lru_cache
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from . import Dhad, __version__
from .api.models import (
    CheckRequest,
    CheckResponse,
    DiacritizeRequest,
    DiacritizeResponse,
    DialectRequest,
    DialectResponse,
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
from .style import StyleProfile
from .templates import generate_document, list_templates
from .suppression import Suppression


class DhadClientError(RuntimeError):
    """Raised when a remote API call fails or returns an invalid response."""


@lru_cache(maxsize=8)
def _local_profile_engine(profile: str) -> Dhad:
    return Dhad(style_profile=StyleProfile(profile))


class DhadClient:
    """Unified SDK over either an in-process engine or a Dhad REST server.

    By default the SDK runs locally and returns validated Pydantic response
    models. Pass ``base_url`` to use a remote server without changing calling
    code. Every synchronous method has an ``a*`` asynchronous counterpart.
    """

    def __init__(
        self,
        *,
        base_url: str | None = None,
        engine: Dhad | None = None,
        timeout: float = 30.0,
    ) -> None:
        if base_url is not None and engine is not None:
            raise ValueError("base_url and engine are mutually exclusive")
        if timeout <= 0:
            raise ValueError("timeout must be positive")
        self.base_url = base_url.rstrip("/") if base_url else None
        self.engine = engine if base_url is None else None
        if self.engine is None and self.base_url is None:
            self.engine = Dhad()
        self.timeout = timeout

    @property
    def is_remote(self) -> bool:
        return self.base_url is not None

    def _post(self, endpoint: str, payload: dict[str, Any]) -> dict[str, Any]:
        if self.base_url is None:
            raise DhadClientError("Remote transport requested in local mode")
        request = Request(
            f"{self.base_url}{endpoint}",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:  # noqa: S310
                body = response.read().decode("utf-8")
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise DhadClientError(f"Dhad API returned HTTP {exc.code}: {detail}") from exc
        except URLError as exc:
            raise DhadClientError(f"Cannot reach Dhad API: {exc.reason}") from exc
        try:
            data = json.loads(body)
        except json.JSONDecodeError as exc:
            raise DhadClientError("Dhad API returned invalid JSON") from exc
        if not isinstance(data, dict):
            raise DhadClientError("Dhad API returned a non-object response")
        return data

    def _get(self, endpoint: str) -> dict[str, Any]:
        if self.base_url is None:
            raise DhadClientError("Remote transport requested in local mode")
        request = Request(
            f"{self.base_url}{endpoint}",
            headers={"Accept": "application/json"},
            method="GET",
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:  # noqa: S310
                body = response.read().decode("utf-8")
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise DhadClientError(f"Dhad API returned HTTP {exc.code}: {detail}") from exc
        except URLError as exc:
            raise DhadClientError(f"Cannot reach Dhad API: {exc.reason}") from exc
        try:
            data = json.loads(body)
        except json.JSONDecodeError as exc:
            raise DhadClientError("Dhad API returned invalid JSON") from exc
        if not isinstance(data, dict):
            raise DhadClientError("Dhad API returned a non-object response")
        return data

    def check(
        self,
        text: str,
        *,
        profiles: list[str] | None = None,
        disabled_rules: list[str] | None = None,
        disabled_categories: list[str] | None = None,
        custom_words: list[str] | None = None,
        diacritics_mode: str | None = None,
    ) -> CheckResponse:
        request = CheckRequest(
            text=text,
            profiles=profiles or ["default"],
            disabled_rules=disabled_rules or [],
            disabled_categories=disabled_categories or [],
            custom_words=custom_words or [],
            diacritics_mode=diacritics_mode,
        )
        if self.is_remote:
            return CheckResponse.model_validate(self._post("/api/v1/check", request.model_dump()))
        assert self.engine is not None
        matches = self.engine.check(
            request.text,
            profiles=request.profiles,
            suppression=Suppression(
                rule_ids=frozenset(request.disabled_rules),
                words=frozenset(request.custom_words),
            ),
            diacritics_mode=request.diacritics_mode,
        )
        disabled = {item.lower() for item in request.disabled_categories}
        if disabled:
            matches = [item for item in matches if item.category.lower() not in disabled]
        return check_response(__version__, matches)

    async def acheck(self, text: str, **kwargs: Any) -> CheckResponse:
        return await asyncio.to_thread(self.check, text, **kwargs)

    def parse(
        self,
        text: str,
        *,
        dialect_to_msa: bool = False,
        neural_refine: bool = True,
    ) -> ParseResponse:
        request = ParseRequest(
            text=text,
            dialect_to_msa=dialect_to_msa,
            neural_refine=neural_refine,
        )
        if self.is_remote:
            return ParseResponse.model_validate(self._post("/api/v1/parse", request.model_dump()))
        assert self.engine is not None
        result = self.engine.parse(
            request.text,
            dialect_to_msa=request.dialect_to_msa,
            neural_refine=request.neural_refine,
        )
        return parse_response(__version__, result)

    async def aparse(self, text: str, **kwargs: Any) -> ParseResponse:
        return await asyncio.to_thread(self.parse, text, **kwargs)

    def diacritize(
        self,
        text: str,
        *,
        mode: str = "full",
        neural_refine: bool = True,
    ) -> DiacritizeResponse:
        request = DiacritizeRequest(text=text, mode=mode, neural_refine=neural_refine)
        if self.is_remote:
            return DiacritizeResponse.model_validate(
                self._post("/api/v1/diacritize", request.model_dump())
            )
        assert self.engine is not None
        result = self.engine.diacritize(
            request.text,
            mode=request.mode,
            neural_refine=request.neural_refine,
        )
        return diacritize_response(__version__, result)

    async def adiacritize(self, text: str, **kwargs: Any) -> DiacritizeResponse:
        return await asyncio.to_thread(self.diacritize, text, **kwargs)

    def style(self, text: str, *, profile: str = "general") -> StyleResponse:
        request = StyleRequest(text=text, profile=profile)
        if self.is_remote:
            return StyleResponse.model_validate(self._post("/api/v1/style", request.model_dump()))
        engine = (
            self.engine if request.profile == "general" else _local_profile_engine(request.profile)
        )
        assert engine is not None
        return style_response(__version__, engine.style_report(request.text))

    async def astyle(self, text: str, **kwargs: Any) -> StyleResponse:
        return await asyncio.to_thread(self.style, text, **kwargs)

    def dialect(self, text: str) -> DialectResponse:
        request = DialectRequest(text=text)
        if self.is_remote:
            return DialectResponse.model_validate(
                self._post("/api/v1/dialect", request.model_dump())
            )
        assert self.engine is not None
        return dialect_response(__version__, self.engine.dialect_report(request.text))

    async def adialect(self, text: str) -> DialectResponse:
        return await asyncio.to_thread(self.dialect, text)

    def intelligence(
        self,
        text: str,
        *,
        profile: str = "general",
        custom_words: list[str] | None = None,
        disabled_rules: list[str] | None = None,
    ) -> IntelligenceResponse:
        request = IntelligenceRequest(
            text=text,
            profile=profile,
            custom_words=custom_words or [],
            disabled_rules=disabled_rules or [],
        )
        if self.is_remote:
            return IntelligenceResponse.model_validate(
                self._post("/api/v1/intelligence", request.model_dump())
            )
        assert self.engine is not None
        report = self.engine.intelligence_report(
            request.text,
            style_profile=request.profile,
            suppression=Suppression(
                rule_ids=frozenset(request.disabled_rules),
                words=frozenset(request.custom_words),
            ),
        )
        return intelligence_response(__version__, report)

    async def aintelligence(self, text: str, **kwargs: Any) -> IntelligenceResponse:
        return await asyncio.to_thread(self.intelligence, text, **kwargs)
    def rewrite(
        self,
        text: str,
        *,
        mode: str = "formal",
        alternatives: int = 3,
    ) -> RewriteResponse:
        request = RewriteRequest(text=text, mode=mode, alternatives=alternatives)
        if self.is_remote:
            return RewriteResponse.model_validate(
                self._post("/api/v1/rewrite", request.model_dump())
            )
        assert self.engine is not None
        return rewrite_response(
            __version__,
            self.engine.rewrite(
                request.text,
                mode=request.mode,
                alternatives=request.alternatives,
            ),
        )

    async def arewrite(self, text: str, **kwargs: Any) -> RewriteResponse:
        return await asyncio.to_thread(self.rewrite, text, **kwargs)

    def analytics(self, text: str, *, profile: str = "general") -> AnalyticsResponse:
        request = AnalyticsRequest(text=text, profile=profile)
        if self.is_remote:
            return AnalyticsResponse.model_validate(
                self._post("/api/v1/analytics", request.model_dump())
            )
        assert self.engine is not None
        return analytics_response(
            __version__,
            self.engine.analytics_report(request.text, style_profile=request.profile),
        )

    async def aanalytics(self, text: str, **kwargs: Any) -> AnalyticsResponse:
        return await asyncio.to_thread(self.analytics, text, **kwargs)

    def templates(self) -> TemplateListResponse:
        if self.is_remote:
            return TemplateListResponse.model_validate(self._get("/api/v1/templates"))
        return template_list_response(__version__, list_templates())

    def generate_template(
        self,
        template_id: str,
        values: dict[str, str],
        *,
        tone: str = "formal",
    ) -> TemplateGenerateResponse:
        request = TemplateGenerateRequest(
            template_id=template_id,
            values=values,
            tone=tone,
        )
        if self.is_remote:
            return TemplateGenerateResponse.model_validate(
                self._post("/api/v1/templates/generate", request.model_dump())
            )
        document = generate_document(
            request.template_id,
            request.values,
            tone=request.tone,
        )
        return template_generate_response(__version__, document)

    async def agenerate_template(
        self, template_id: str, values: dict[str, str], **kwargs: Any
    ) -> TemplateGenerateResponse:
        return await asyncio.to_thread(
            self.generate_template, template_id, values, **kwargs
        )

