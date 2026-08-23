from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import httpx

from app.core.config import Settings

logger = logging.getLogger(__name__)


class LlmQueryInterpreterError(RuntimeError):
    pass


@dataclass(frozen=True)
class LlmQueryInterpretation:
    canonical_prompt: str
    provider: str
    model: str
    confidence: float = 0
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class LlmChatResult:
    content: str
    provider: str
    model: str
    fallback_from: str = ""


def openai_compatible_llm_configured(settings: Settings) -> bool:
    return bool(
        settings.llm_provider.strip()
        and settings.llm_model.strip()
        and settings.llm_base_url.strip()
        and settings.llm_api_key.strip()
    )


def llm_json_response_format(settings: Settings) -> dict[str, str]:
    if settings.llm_provider.strip().lower() == "lm_studio":
        # LM Studio 0.4.x accepts "json_schema" or "text", but rejects the
        # legacy OpenAI/DeepSeek "json_object" value. The system prompts still
        # require JSON and the response parsers validate it before use.
        return {"type": "text"}
    return {"type": "json_object"}


async def request_llm_chat_content(
    settings: Settings,
    *,
    system_prompt: str,
    user_content: str,
    max_tokens: int,
    timeout_seconds: float | None = None,
) -> str:
    """Return chat content, automatically falling back from LM Studio to DeepSeek."""
    result = await request_llm_chat_result(
        settings,
        system_prompt=system_prompt,
        user_content=user_content,
        max_tokens=max_tokens,
        timeout_seconds=timeout_seconds,
    )
    return result.content


async def request_llm_chat_result(
    settings: Settings,
    *,
    system_prompt: str,
    user_content: str,
    max_tokens: int,
    timeout_seconds: float | None = None,
) -> LlmChatResult:
    """Return content and provider metadata, with an automatic DeepSeek fallback."""
    try:
        content = await _request_llm_chat_content_once(
            settings,
            system_prompt=system_prompt,
            user_content=user_content,
            max_tokens=max_tokens,
            timeout_seconds=timeout_seconds,
        )
    except LlmQueryInterpreterError as primary_error:
        fallback = _deepseek_fallback_settings(settings)
        if fallback is None:
            raise
        logger.warning(
            "Primary LLM provider %s failed; retrying with DeepSeek: %s",
            settings.llm_provider,
            primary_error,
        )
        try:
            content = await _request_llm_chat_content_once(
                fallback,
                system_prompt=system_prompt,
                user_content=user_content,
                max_tokens=min(max_tokens, fallback.llm_max_output_tokens),
                timeout_seconds=fallback.llm_timeout_seconds,
            )
        except LlmQueryInterpreterError as fallback_error:
            raise LlmQueryInterpreterError(
                f"Primary LLM provider {settings.llm_provider} and DeepSeek fallback both failed"
            ) from fallback_error
        return LlmChatResult(
            content=content,
            provider=fallback.llm_provider,
            model=fallback.llm_model,
            fallback_from=settings.llm_provider,
        )
    return LlmChatResult(
        content=content,
        provider=settings.llm_provider,
        model=settings.llm_model,
    )


async def _request_llm_chat_content_once(
    settings: Settings,
    *,
    system_prompt: str,
    user_content: str,
    max_tokens: int,
    timeout_seconds: float | None = None,
) -> str:
    """Make one provider request with LM Studio reasoning disabled natively."""
    provider = settings.llm_provider.strip().lower()
    headers = {"Content-Type": "application/json"}
    if settings.llm_api_key:
        headers["Authorization"] = f"Bearer {settings.llm_api_key}"
    if provider == "lm_studio":
        endpoint = _lm_studio_native_chat_url(settings.llm_base_url)
        payload = {
            "model": settings.llm_model,
            "system_prompt": system_prompt,
            "input": user_content,
            "reasoning": "off",
            "temperature": 0,
            "max_output_tokens": max_tokens,
            "stream": False,
        }
    else:
        endpoint = f"{settings.llm_base_url.rstrip('/')}/chat/completions"
        payload = {
            "model": settings.llm_model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
            "response_format": llm_json_response_format(settings),
            "temperature": 0,
            "max_tokens": max_tokens,
            "stream": False,
        }
    try:
        async with httpx.AsyncClient(
            timeout=timeout_seconds or settings.llm_timeout_seconds,
            verify=settings.llm_ssl_verify,
        ) as client:
            response = await client.post(endpoint, headers=headers, json=payload)
    except httpx.RequestError as exc:
        raise LlmQueryInterpreterError(
            f"Unable to connect to LLM provider {settings.llm_provider}"
        ) from exc
    if not response.is_success:
        raise LlmQueryInterpreterError(
            f"LLM provider {settings.llm_provider} returned HTTP {response.status_code}"
        )
    try:
        data = response.json()
        if provider == "lm_studio":
            content = "\n".join(
                str(item.get("content") or "")
                for item in data["output"]
                if isinstance(item, dict) and item.get("type") == "message"
            )
        else:
            content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        raise LlmQueryInterpreterError(
            "LLM response did not include message content"
        ) from exc
    if not isinstance(content, str) or not content.strip():
        raise LlmQueryInterpreterError(
            "LLM response did not include non-empty message content"
        )
    return content


def _deepseek_fallback_settings(settings: Settings) -> Settings | None:
    if settings.llm_provider.strip().lower() != "lm_studio":
        return None
    if not (
        settings.deepseek_model.strip()
        and settings.deepseek_base_url.strip()
        and settings.deepseek_api_key.strip()
    ):
        return None
    return settings.model_copy(
        update={
            "llm_provider": "deepseek",
            "llm_model": settings.deepseek_model,
            "llm_base_url": settings.deepseek_base_url,
            "llm_api_key": settings.deepseek_api_key,
            "llm_timeout_seconds": settings.deepseek_timeout_seconds,
            "llm_max_output_tokens": settings.deepseek_max_output_tokens,
            "llm_ssl_verify": settings.deepseek_ssl_verify,
        }
    )


def _lm_studio_native_chat_url(base_url: str) -> str:
    parsed = urlsplit(base_url)
    path = parsed.path.rstrip("/")
    if path.endswith("/v1"):
        path = path[:-3]
    return urlunsplit(
        (parsed.scheme, parsed.netloc, f"{path}/api/v1/chat", "", "")
    )


class OpenAICompatibleQueryInterpreter:
    def __init__(self, settings: Settings):
        self.settings = settings

    @property
    def enabled(self) -> bool:
        return (
            self.settings.natural_query_llm_enabled
            and openai_compatible_llm_configured(self.settings)
        )

    async def interpret(
        self,
        prompt: str,
        *,
        now: datetime,
        layout_context: list[dict[str, Any]] | None = None,
    ) -> LlmQueryInterpretation | None:
        if not self.enabled:
            return None

        result = await request_llm_chat_result(
            self.settings,
            system_prompt=_system_prompt(),
            user_content=json.dumps(
                {
                    "today": now.date().isoformat(),
                    "timezone": self.settings.natural_query_timezone,
                    "supportedDomains": _supported_domains(layout_context or []),
                    "userPrompt": prompt,
                },
                ensure_ascii=False,
            ),
            max_tokens=self.settings.llm_max_output_tokens,
        )

        interpretation = _parse_interpretation(result.content)
        if not interpretation:
            return None
        return LlmQueryInterpretation(
            canonical_prompt=interpretation["canonicalPrompt"],
            provider=result.provider,
            model=result.model,
            confidence=interpretation.get("confidence", 0),
            warnings=(
                interpretation.get("warnings", [])
                + (
                    [f"{result.fallback_from} 不可用，已自动切换到 DeepSeek。"]
                    if result.fallback_from
                    else []
                )
            ),
        )


# Backwards-compatible import for older integrations.
DeepSeekQueryInterpreter = OpenAICompatibleQueryInterpreter


def _system_prompt() -> str:
    return (
        "你是 FileMaker 自然语言查询归一化器，只输出 JSON，不要回答用户。\n"
        "目标：把用户原始问题改写成当前规则查询器能稳定解析的中文短句。\n"
        "只能使用两个业务域：product=产品资料，part=零件资料。\n"
        "支持的时间表达：今天、昨天、前天、近 N 天、近一周、本周、上周、本月、上月。\n"
        "如果用户要求时间戳/具体时间，但字段上下文只有日期字段，也必须保留“具体时间戳”语义，"
        "让下游可以解释 fallback。\n"
        "不要省略用户要求返回的信息或字段，例如库存、价格、客户、状态、时间戳、创建人、谁创建的；"
        "即使这些信息不参与筛选，也要保留在 canonicalPrompt 里，让下游展示或如实说明缺失。\n"
        "只能保留用户原问题明确要求的信息和字段；严禁根据 knownFields 自行补充编号、状态、重量、"
        "创建人、创建时间、时间戳或其他用户没有提出的字段。\n"
        "例如用户问“最近最新创建的零件有哪些”，canonicalPrompt 只能表达“查询最近创建的零件”，"
        "不得添加零件编号、状态、替代编号、重量、创建人或创建时间。\n"
        "禁止发明 FileMaker layout、字段名、SQL、脚本或写操作。\n"
        "输出 JSON schema："
        "{\"canonicalPrompt\":\"string <= 240 chars\","
        "\"domain\":\"product|part|unknown\","
        "\"confidence\":0.0,"
        "\"wantsTimestamp\":false,"
        "\"warnings\":[\"string\"]}。"
    )


def _supported_domains(layout_context: list[dict[str, Any]]) -> dict[str, Any]:
    context_by_layout = {
        str(item.get("layout") or ""): item
        for item in layout_context
        if isinstance(item, dict)
    }
    product = context_by_layout.get("@products", {})
    part = context_by_layout.get("Parts", {})
    return {
        "product": {
            "layout": "@products",
            "indexLayout": product.get("indexLayout", "@products_RAG"),
            "searchTerms": ["产品", "產品", "product", "sku", "车款", "客户", "类别"],
            "knownFields": product.get("fields", []),
            "keys": product.get("entity", {}).get("primaryKeys", []),
            "relationships": product.get("relationships", []),
        },
        "part": {
            "layout": "Parts",
            "indexLayout": part.get("indexLayout", "@零件_RAG"),
            "searchTerms": ["零件", "配件", "备件", "spare parts", "part", "parts", "part_number", "part_name"],
            "knownFields": part.get("fields", []),
            "keys": part.get("entity", {}).get("primaryKeys", []),
            "relationships": part.get("relationships", []),
        },
    }


def _parse_interpretation(content: str) -> dict[str, Any] | None:
    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", content, flags=re.DOTALL)
        if not match:
            return None
        try:
            data = json.loads(match.group(0))
        except json.JSONDecodeError:
            return None

    if not isinstance(data, dict):
        return None

    canonical = str(data.get("canonicalPrompt") or "").strip()
    domain = str(data.get("domain") or "").strip().lower()
    wants_timestamp = bool(data.get("wantsTimestamp"))
    if not canonical or len(canonical) > 240:
        return None
    if domain == "part" and all(term not in canonical.lower() for term in ("零件", "配件", "备件", "備件", "part", "spare")):
        canonical = f"{canonical} 零件"
    if domain == "product" and all(term not in canonical.lower() for term in ("产品", "產品", "product", "sku")):
        canonical = f"{canonical} 产品"
    if wants_timestamp and not any(term in canonical for term in ("时间戳", "時間戳", "具体时间", "具體時間")):
        canonical = f"{canonical}，具体时间戳"

    warnings = data.get("warnings") if isinstance(data.get("warnings"), list) else []
    confidence = data.get("confidence", 0)
    try:
        confidence_value = float(confidence)
    except (TypeError, ValueError):
        confidence_value = 0

    return {
        "canonicalPrompt": canonical,
        "domain": domain,
        "confidence": max(0.0, min(1.0, confidence_value)),
        "warnings": [str(item) for item in warnings if item],
    }
