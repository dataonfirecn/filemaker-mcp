from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Any

import httpx

from app.core.config import Settings
from app.services.natural_query_conversation_store import (
    NaturalQueryConversationStore,
    NaturalQueryQuestionCandidate,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class QuestionAnalysis:
    canonical_question: str
    normalized_key: str
    domain: str
    intent: str
    is_meaningful: bool
    reason: str
    source: str
    model: str = ""


@dataclass(frozen=True)
class PendingAnalysisResult:
    analyzed: int
    meaningful: int
    ignored: int


async def analyze_pending_questions(
    *,
    store: NaturalQueryConversationStore,
    settings: Settings,
    limit: int | None = None,
) -> PendingAnalysisResult:
    candidates = await store.list_unanalyzed_question_candidates(
        limit=limit or settings.natural_query_analytics_pending_limit,
    )
    analyzed = 0
    meaningful = 0
    ignored = 0
    for candidate in candidates:
        analysis = await analyze_question(candidate, settings=settings)
        await store.upsert_question_analytics(
            conversation_id=candidate.id,
            prompt=candidate.prompt,
            canonical_question=analysis.canonical_question,
            normalized_key=analysis.normalized_key,
            domain=analysis.domain,
            intent=analysis.intent,
            is_meaningful=analysis.is_meaningful,
            reason=analysis.reason,
            source=analysis.source,
            model=analysis.model,
            created_at=candidate.created_at,
        )
        analyzed += 1
        if analysis.is_meaningful:
            meaningful += 1
        else:
            ignored += 1
    return PendingAnalysisResult(analyzed=analyzed, meaningful=meaningful, ignored=ignored)


async def analyze_question(candidate: NaturalQueryQuestionCandidate, *, settings: Settings) -> QuestionAnalysis:
    heuristic = heuristic_question_analysis(candidate)
    if not heuristic.is_meaningful:
        return heuristic
    if not _llm_enabled(settings):
        return heuristic

    payload = {
        "model": settings.llm_model,
        "messages": [
            {"role": "system", "content": _system_prompt()},
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "prompt": candidate.prompt,
                        "interpretedPrompt": candidate.interpreted_prompt,
                        "domain": candidate.domain,
                        "intent": candidate.intent,
                        "layout": candidate.layout,
                        "status": candidate.status,
                    },
                    ensure_ascii=False,
                ),
            },
        ],
        "response_format": {"type": "json_object"},
        "thinking": {"type": "disabled"},
        "temperature": 0,
        "max_tokens": 260,
        "stream": False,
    }
    try:
        async with httpx.AsyncClient(
            timeout=settings.llm_timeout_seconds,
            verify=settings.llm_ssl_verify,
        ) as client:
            response = await client.post(
                f"{settings.llm_base_url.rstrip('/')}/chat/completions",
                headers={
                    "Authorization": f"Bearer {settings.llm_api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
    except httpx.RequestError:
        logger.exception("Unable to connect to LLM for natural query analytics")
        return heuristic

    if not response.is_success:
        logger.warning("LLM natural query analytics returned HTTP %s", response.status_code)
        return heuristic

    try:
        content = response.json()["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError, ValueError):
        logger.warning("LLM natural query analytics response did not include message content")
        return heuristic

    parsed = _parse_llm_analysis(content, fallback=heuristic, settings=settings)
    return parsed or heuristic


def heuristic_question_analysis(candidate: NaturalQueryQuestionCandidate) -> QuestionAnalysis:
    text = _display_prompt(candidate)
    if _is_noise_question(text):
        return QuestionAnalysis(
            canonical_question=text.strip() or "无意义输入",
            normalized_key=_normalized_key(text) or "noise",
            domain=candidate.domain or "",
            intent=candidate.intent or "",
            is_meaningful=False,
            reason="无业务查询意图",
            source="heuristic",
        )

    canonical = _canonical_question(text)
    return QuestionAnalysis(
        canonical_question=canonical,
        normalized_key=_normalized_key(canonical),
        domain=candidate.domain or _infer_domain(text),
        intent=candidate.intent or _infer_intent(text),
        is_meaningful=True,
        reason="包含业务查询意图",
        source="heuristic",
    )


def _llm_enabled(settings: Settings) -> bool:
    return (
        settings.natural_query_analytics_llm_enabled
        and settings.natural_query_llm_enabled
        and settings.llm_provider.lower() == "deepseek"
        and bool(settings.llm_api_key)
    )


def _system_prompt() -> str:
    return (
        "你是 FileMaker 自然语言查询质量分析器，只输出 JSON。\n"
        "任务：判断用户问题是否是有效业务查询，并把同义问题归一到同一个 canonicalQuestion，"
        "用于统计高频问题。\n"
        "必须过滤无意义输入，例如：在吗、你好、测试、test、hello、随便试试、空泛寒暄。\n"
        "有效业务问题包括产品/零件/库存/价格/创建日期/客户/状态/BOM/RAG 等查询或管理诉求。\n"
        "不要发明数据库结果，只做问题分类。\n"
        "输出 JSON schema："
        "{\"isMeaningful\":true,\"canonicalQuestion\":\"中文短句\","
        "\"domain\":\"part|product|rag|bom|unknown\","
        "\"intent\":\"中文意图标签\",\"reason\":\"string\"}。"
    )


def _parse_llm_analysis(
    content: str,
    *,
    fallback: QuestionAnalysis,
    settings: Settings,
) -> QuestionAnalysis | None:
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

    is_meaningful = bool(data.get("isMeaningful"))
    canonical = str(data.get("canonicalQuestion") or fallback.canonical_question).strip()
    if not canonical:
        canonical = fallback.canonical_question
    normalized_key = _normalized_key(canonical) or fallback.normalized_key or "noise"
    if not is_meaningful:
        normalized_key = f"ignored:{normalized_key}"
    return QuestionAnalysis(
        canonical_question=canonical,
        normalized_key=normalized_key,
        domain=str(data.get("domain") or fallback.domain or ""),
        intent=str(data.get("intent") or fallback.intent or ""),
        is_meaningful=is_meaningful,
        reason=str(data.get("reason") or fallback.reason or ""),
        source="llm",
        model=settings.llm_model,
    )


def _display_prompt(candidate: NaturalQueryQuestionCandidate) -> str:
    return (candidate.interpreted_prompt or candidate.prompt or "").strip()


def _is_noise_question(text: str) -> bool:
    normalized = _normalized_key(text)
    if not normalized:
        return True
    noise = {
        "在吗",
        "在嘛",
        "你好",
        "您好",
        "hello",
        "hi",
        "hey",
        "test",
        "testing",
        "测试",
        "測試",
        "试试",
        "試試",
        "随便试试",
        "隨便試試",
        "ok",
        "1",
        "123",
    }
    if normalized in noise:
        return True
    if ("测试" in normalized or "測試" in normalized or "test" in normalized) and not _has_business_term(normalized):
        return True
    return len(normalized) <= 1 and not _has_business_term(normalized)


def _has_business_term(value: str) -> bool:
    return any(
        term in value
        for term in (
            "零件",
            "产品",
            "產品",
            "库存",
            "庫存",
            "价格",
            "價格",
            "新增",
            "创建",
            "創建",
            "客户",
            "客戶",
            "bom",
            "rag",
            "part",
            "product",
            "sku",
            "pvc",
        )
    )


def _canonical_question(text: str) -> str:
    cleaned = re.sub(r"\s+", " ", text.strip())
    cleaned = cleaned.strip(" ，。！？?;；")
    replacements = {
        "有那些": "有哪些",
        "哪一些": "哪些",
        "最近7天": "近7天",
        "近一周": "近7天",
        "過去": "过去",
        "創建": "创建",
        "產品": "产品",
        "庫存": "库存",
        "價格": "价格",
        "單價": "单价",
    }
    for source, target in replacements.items():
        cleaned = cleaned.replace(source, target)
    return cleaned[:120] or text.strip()[:120]


def _normalized_key(value: str) -> str:
    text = value.casefold()
    text = re.sub(r"[\s,，。.!！?？;；:：'\"“”‘’（）()【】\\[\\]{}<>《》、/_\\-]+", "", text)
    return text


def _infer_domain(text: str) -> str:
    lowered = text.casefold()
    if any(term in lowered for term in ("零件", "part", "pvc")):
        return "part"
    if any(term in lowered for term in ("产品", "產品", "product", "sku")):
        return "product"
    if "rag" in lowered:
        return "rag"
    if "bom" in lowered:
        return "bom"
    return "unknown"


def _infer_intent(text: str) -> str:
    lowered = text.casefold()
    if any(term in lowered for term in ("价格", "價格", "单价", "單價")):
        return "查询价格"
    if any(term in lowered for term in ("库存", "庫存", "stock")):
        return "查询库存"
    if any(term in lowered for term in ("新增", "创建", "創建")):
        return "查询新增记录"
    if "rag" in lowered:
        return "RAG 管理"
    return "查询资料"
