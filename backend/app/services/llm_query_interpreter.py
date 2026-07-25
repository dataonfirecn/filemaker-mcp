from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

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


class DeepSeekQueryInterpreter:
    def __init__(self, settings: Settings):
        self.settings = settings

    @property
    def enabled(self) -> bool:
        return (
            self.settings.natural_query_llm_enabled
            and self.settings.llm_provider.lower() == "deepseek"
            and bool(self.settings.llm_api_key)
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

        payload = {
            "model": self.settings.llm_model,
            "messages": [
                {"role": "system", "content": _system_prompt()},
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "today": now.date().isoformat(),
                            "timezone": self.settings.natural_query_timezone,
                            "supportedDomains": _supported_domains(layout_context or []),
                            "userPrompt": prompt,
                        },
                        ensure_ascii=False,
                    ),
                },
            ],
            "response_format": {"type": "json_object"},
            "thinking": {"type": "disabled"},
            "temperature": 0,
            "max_tokens": self.settings.llm_max_output_tokens,
            "stream": False,
        }
        try:
            async with httpx.AsyncClient(
                timeout=self.settings.llm_timeout_seconds,
                verify=self.settings.llm_ssl_verify,
            ) as client:
                response = await client.post(
                    f"{self.settings.llm_base_url.rstrip('/')}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self.settings.llm_api_key}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )
        except httpx.RequestError as exc:
            raise LlmQueryInterpreterError("Unable to connect to DeepSeek") from exc

        if not response.is_success:
            raise LlmQueryInterpreterError(f"DeepSeek API returned HTTP {response.status_code}")

        try:
            content = response.json()["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise LlmQueryInterpreterError("DeepSeek response did not include message content") from exc

        interpretation = _parse_interpretation(content)
        if not interpretation:
            return None
        return LlmQueryInterpretation(
            canonical_prompt=interpretation["canonicalPrompt"],
            provider="deepseek",
            model=self.settings.llm_model,
            confidence=interpretation.get("confidence", 0),
            warnings=interpretation.get("warnings", []),
        )


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
            "indexLayout": product.get("indexLayout", "@products"),
            "searchTerms": ["产品", "產品", "product", "sku", "车款", "客户", "类别"],
            "knownFields": product.get("fields", []),
            "keys": product.get("entity", {}).get("primaryKeys", []),
            "relationships": product.get("relationships", []),
        },
        "part": {
            "layout": "Parts",
            "indexLayout": part.get("indexLayout", "@零件"),
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
