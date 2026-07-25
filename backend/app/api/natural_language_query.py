import asyncio
import logging
import re
import time
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.business_products import _product_row
from app.core.config import Settings
from app.models.natural_language_query import (
    NaturalLanguageDateRange,
    NaturalLanguageQueryPlan,
    NaturalLanguageQueryRequest,
    NaturalLanguageQueryResponse,
)
from app.models.rag_index import RagSearchHit
from app.services.audit_log import AuditLogStore, OperatorContext
from app.services.dependencies import (
    get_audit_log_store,
    get_filemaker_client,
    get_filemaker_odata_client,
    get_natural_query_analytics_worker,
    get_natural_query_conversation_store,
    get_operator_context,
    get_rag_index_store,
    get_settings,
)
from app.services.filemaker_client import FileMakerAPIError, FileMakerClient
from app.services.filemaker_odata_client import (
    FileMakerODataClient,
    FileMakerODataError,
    row_key_value,
)
from app.services.llm_query_interpreter import (
    DeepSeekQueryInterpreter,
    LlmQueryInterpretation,
    LlmQueryInterpreterError,
)
from app.services.metadata_semantics import (
    build_layout_semantic_profile,
    fallback_layout_semantic_profile,
    semantic_concept_field,
    semantic_concept_reason,
)
from app.services.natural_query_conversation_store import NaturalQueryConversationStore
from app.services.natural_query_analytics_worker import NaturalQueryAnalyticsWorker
from app.services.natural_language_query import (
    NaturalQueryError,
    build_product_natural_query_plan,
)
from app.services.product_api import PRODUCT_STOCK_FIELD
from app.services.rag_index import RagIndexStore, RagRecordChunk

router = APIRouter(prefix="/natural-query", tags=["natural-query"])
logger = logging.getLogger(__name__)

_CUSTOMER_INTERNAL_PRODUCT_TERMS = (
    "成本",
    "报价",
    "報價",
    "费用",
    "費用",
    "收费",
    "收費",
    "下单用",
    "下單用",
    "采购",
    "採購",
    "补发料",
    "補發料",
    "不要使用",
    "查库存用",
    "查庫存用",
    "错误",
    "錯誤",
    "cost",
    "quotation",
    "do not use",
    "for purchase",
)
_CUSTOMER_PRODUCT_NAME_FIELDS = ("產品名稱_中文", "product_name")
_RAG_LAYOUT_BY_QUERY_LAYOUT = {
    "Parts": "@零件",
}
_ODATA_EXACT_QUERY = {
    "product": ("產品", ("product_sku", "系統產品編號")),
    "part": ("零件", ("part_number",)),
}
_ODATA_LIVE_SELECT_FIELDS = {
    "product": (
        "product_sku",
        "系統產品編號",
        "product_name",
        "產品名稱_中文",
        "類別",
        "車款",
        "車子比例",
        "Client",
        PRODUCT_STOCK_FIELD,
        "MOQ",
        "status",
        "審核",
        "Retail_Price_USD",
        "updated_at",
    ),
    "part": (
        "part_number",
        "零件ID",
        "part_name",
        "part_name_對外",
        "客戶編號",
        "替代編號",
        "Notes",
        "customer_id",
        "專屬客戶",
        "status",
        "狀態",
        "零件性質",
        "零件品種",
        "part_name_en",
        "stock_on_hand_qty",
        "safety_stock_qty",
        "修改人",
        "修改日期",
    ),
}
_PRICE_QUERY_TERMS_CJK = (
    "价格",
    "價格",
    "单价",
    "單價",
    "售价",
    "售價",
    "成本价",
    "成本價",
    "成本",
    "金额",
    "金額",
    "货值",
    "貨值",
    "运费",
    "運費",
    "报价",
    "報價",
    "估价",
    "估價",
    "总价",
    "總價",
    "多少钱",
    "多少錢",
    "毛利",
    "利润",
    "利潤",
)
_PRICE_QUERY_TERMS_ENGLISH = (
    "price",
    "unit price",
    "unit_price",
    "unit cost",
    "cost",
    "amount",
    "quote",
    "quotation",
    "shipping cost",
    "shipping fee",
    "freight",
    "margin",
    "profit",
    "total price",
)


def _no_customer_scope() -> str:
    """Default dependency for the internal endpoint; callers cannot set this via HTTP."""
    return ""


@router.post("", response_model=NaturalLanguageQueryResponse)
async def run_natural_language_query(
    body: NaturalLanguageQueryRequest,
    filemaker: FileMakerClient = Depends(get_filemaker_client),
    odata_client: FileMakerODataClient = Depends(get_filemaker_odata_client),
    rag_store: RagIndexStore = Depends(get_rag_index_store),
    audit_log: AuditLogStore = Depends(get_audit_log_store),
    conversation_store: NaturalQueryConversationStore = Depends(get_natural_query_conversation_store),
    analytics_worker: NaturalQueryAnalyticsWorker = Depends(get_natural_query_analytics_worker),
    operator: OperatorContext = Depends(get_operator_context),
    settings: Settings = Depends(get_settings),
    enforced_product_client_id: str = Depends(_no_customer_scope),
    enforced_part_customer_id: str = Depends(_no_customer_scope),
) -> NaturalLanguageQueryResponse:
    started_at = time.perf_counter()
    prompt = body.prompt.strip()
    if (
        not (enforced_product_client_id or enforced_part_customer_id)
        and operator.permissions is not None
        and not operator.permissions.get("canViewPrice", False)
        and _wants_price_detail(prompt)
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "message": "当前账号没有查看价格的权限。",
                "permission": "canViewPrice",
            },
        )
    prompt_for_plan = prompt
    parsed_plan = None
    source = "filemaker"
    rag_hits: list[RagSearchHit] = []
    layout_fields: list[dict[str, object]] = []
    semantic_profile: dict[str, object] = {}
    llm_interpretation: LlmQueryInterpretation | None = None
    customer_scoped = bool(enforced_product_client_id or enforced_part_customer_id)
    result_limit = body.limit if customer_scoped else _effective_result_limit(settings, body.limit)
    try:
        internal_identifier = (
            _customer_exact_identifier(prompt)
            if not customer_scoped and _explicit_identifier_domain(prompt) is None
            else None
        )
        if internal_identifier:
            identifier_domain = await _resolve_internal_identifier_domain(
                filemaker,
                internal_identifier,
            )
            if identifier_domain in {"ambiguous", "not_found"}:
                plan = NaturalLanguageQueryPlan(
                    domain="unknown",
                    intent="clarify_identifier_domain",
                    layout="",
                    description=f"编号领域待确认：{internal_identifier}",
                )
                clarification = _identifier_domain_clarification(
                    prompt,
                    internal_identifier,
                    matched_both=identifier_domain == "ambiguous",
                )
                await _record_conversation_safe(
                    conversation_store,
                    operator=operator,
                    prompt=prompt,
                    interpreted_prompt=None,
                    llm_interpretation=None,
                    parsed_plan=plan,
                    semantic_profile={},
                    source="clarification",
                    answer=clarification["question"],
                    found_count=0,
                    returned_count=0,
                    rag_hit_count=0,
                    duration_ms=_duration_ms(started_at),
                    status="clarification",
                    analytics_worker=analytics_worker,
                )
                return NaturalLanguageQueryResponse(
                    answer=clarification["question"],
                    layout="",
                    rows=[],
                    foundCount=0,
                    returnedCount=0,
                    plan=plan,
                    source="clarification",
                    ragHits=[],
                    requiresClarification=True,
                    clarificationQuestion=clarification["question"],
                    clarificationOptions=clarification["options"],
                )
            prompt_for_plan = (
                f"零件 {prompt}"
                if identifier_domain == "part"
                else f"产品 {prompt}"
            )

        # External customer queries stay deterministic and are not sent to an
        # external LLM. Their inventory results must also come from live
        # FileMaker data rather than a potentially stale RAG record cache.
        llm_interpretation = None if customer_scoped else await _interpret_prompt_with_llm(
            prompt_for_plan,
            rag_store=rag_store,
            settings=settings,
        )
        if llm_interpretation:
            prompt_for_plan = llm_interpretation.canonical_prompt

        preliminary_plan = build_product_natural_query_plan(
            prompt_for_plan,
            layout_fields=[],
            settings=settings,
        )
        exact_customer_identifier = (
            _customer_exact_identifier(prompt_for_plan) if customer_scoped else None
        )
        if exact_customer_identifier:
            # Exact customer inventory checks use known stable item-number fields.
            # Do not let slow or stale layout metadata turn them into broad listings.
            layout_fields = []
            semantic_profile = fallback_layout_semantic_profile(
                layout=preliminary_plan.layout,
                fields=[],
            )
        else:
            layout_fields = await _layout_fields_for_query(
                preliminary_plan.layout,
                rag_store=rag_store,
                filemaker=filemaker,
                settings=settings,
            )
            semantic_profile = await _semantic_profile_for_query(
                preliminary_plan.layout,
                layout_fields,
                rag_store=rag_store,
                settings=settings,
            )
        parsed_plan = build_product_natural_query_plan(
            prompt_for_plan,
            layout_fields=layout_fields,
            settings=settings,
        )
        if customer_scoped:
            _force_exact_customer_identifier(parsed_plan, prompt_for_plan)
            _validate_customer_scope(
                parsed_plan,
                enforced_product_client_id,
                enforced_part_customer_id,
            )
        clarification = _clarification_for_plan(
            prompt=prompt,
            interpreted_prompt=prompt_for_plan,
            parsed_plan=parsed_plan,
        )
        if clarification and not _is_scoped_customer_listing(
            parsed_plan,
            enforced_product_client_id,
            enforced_part_customer_id,
        ):
            plan = _response_plan(parsed_plan)
            await _record_conversation_safe(
                conversation_store,
                operator=operator,
                prompt=prompt,
                interpreted_prompt=prompt_for_plan if prompt_for_plan != prompt else None,
                llm_interpretation=llm_interpretation,
                parsed_plan=parsed_plan,
                semantic_profile=semantic_profile,
                source="clarification",
                warnings=parsed_plan.warnings,
                answer=clarification["question"],
                found_count=0,
                returned_count=0,
                rag_hit_count=0,
                duration_ms=_duration_ms(started_at),
                status="clarification",
                analytics_worker=analytics_worker,
            )
            return NaturalLanguageQueryResponse(
                answer=clarification["question"],
                layout=parsed_plan.layout,
                rows=[],
                foundCount=0,
                returnedCount=0,
                plan=plan,
                source="clarification",
                ragHits=[],
                requiresClarification=True,
                clarificationQuestion=clarification["question"],
                clarificationOptions=clarification["options"],
            )
        if customer_scoped:
            _apply_customer_scope(
                parsed_plan,
                enforced_product_client_id,
                enforced_part_customer_id,
            )
        use_rag = settings.natural_query_use_rag and not customer_scoped
        use_rag_records = use_rag and settings.natural_query_use_cached_records
        cached_result = None
        if use_rag_records:
            cached_result = await rag_store.find_cached_records(
                layout=_rag_layout(parsed_plan.layout),
                query=parsed_plan.query,
                limit=result_limit,
                sort=parsed_plan.sort,
            )
        if cached_result and cached_result.found_count > 0:
            source = "rag-cache"
            rows = [
                _row_for_plan(
                    _chunk_to_record(chunk),
                    parsed_plan.domain,
                    semantic_profile=semantic_profile,
                )
                for chunk in cached_result.records
            ]
            found_count = cached_result.found_count
            returned_count = len(rows)
            rag_hits = [_chunk_to_hit(chunk) for chunk in cached_result.records]
        else:
            # OData product rows do not include the authenticated customer's
            # FileMaker find scope. External queries must therefore stay on the
            # scoped Data API path, including exact item-number lookups.
            result = None if customer_scoped else await _find_exact_records_via_odata(
                parsed_plan,
                client=odata_client,
                settings=settings,
                limit=result_limit,
                offset=body.offset,
            )
            if result is not None:
                source = "odata-live"
            else:
                result = await filemaker.find_records(
                    parsed_plan.layout,
                    query=parsed_plan.query,
                    limit=result_limit,
                    offset=body.offset,
                    sort=parsed_plan.sort or None,
                )
            rows = [
                _row_for_plan(record, parsed_plan.domain, semantic_profile=semantic_profile)
                for record in result["data"]
            ]
            found_count = int(result["foundCount"] or 0)
            returned_count = int(result["returnedCount"] or len(rows))
            if use_rag:
                hits = await rag_store.search(
                    prompt,
                    limit=settings.natural_query_rag_hit_limit,
                    layout=_rag_layout(parsed_plan.layout),
                )
                rag_hits = [_chunk_to_hit(chunk) for chunk in hits]

        coverage_warnings = _coverage_warnings_for_rows(
            parsed_plan.domain,
            parsed_plan.layout,
            layout_fields,
            rows,
            prompt=prompt,
            interpreted_prompt=prompt_for_plan,
            date_range=parsed_plan.date_range,
            semantic_profile=semantic_profile,
        )
        for warning in coverage_warnings:
            if warning not in parsed_plan.warnings:
                parsed_plan.warnings.append(warning)
    except NaturalQueryError as exc:
        await _record_conversation_safe(
            conversation_store,
            operator=operator,
            prompt=prompt,
            interpreted_prompt=prompt_for_plan if prompt_for_plan != prompt else None,
            llm_interpretation=llm_interpretation,
            parsed_plan=parsed_plan,
            semantic_profile=semantic_profile,
            source=source,
            found_count=0,
            returned_count=0,
            rag_hit_count=len(rag_hits),
            duration_ms=_duration_ms(started_at),
            status="error",
            error_message=str(exc),
            analytics_worker=analytics_worker,
        )
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"message": str(exc)},
        ) from exc
    except FileMakerAPIError as exc:
        error_message = str(exc)
        await _record_conversation_safe(
            conversation_store,
            operator=operator,
            prompt=prompt,
            interpreted_prompt=prompt_for_plan if prompt_for_plan != prompt else None,
            llm_interpretation=llm_interpretation,
            parsed_plan=parsed_plan,
            semantic_profile=semantic_profile,
            source=source,
            found_count=0,
            returned_count=0,
            rag_hit_count=len(rag_hits),
            duration_ms=_duration_ms(started_at),
            status="error",
            error_message=error_message,
            analytics_worker=analytics_worker,
        )
        if parsed_plan and parsed_plan.date_range:
            field_name = parsed_plan.date_range.get("field") or "创建日期"
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={
                    "message": (
                        f"FileMaker 日期查询字段“{field_name}”不可用。"
                        "请把 NATURAL_QUERY_PRODUCT_CREATED_FIELDS 配置成产品资料布局里的真实新增/创建日期字段。"
                    ),
                    "payload": exc.payload,
                },
            ) from exc
        raise HTTPException(
            status_code=exc.status_code or status.HTTP_502_BAD_GATEWAY,
            detail={"message": str(exc), "payload": exc.payload},
        ) from exc

    await audit_log.record(
        operator=operator,
        action_type="NATURAL_LANGUAGE_QUERY",
        status="success",
        target_layout=parsed_plan.layout,
        product_sku=(parsed_plan.keywords[0] if parsed_plan.keywords else None),
        request_payload={
            "prompt": prompt,
            "interpretedPrompt": prompt_for_plan if prompt_for_plan != prompt else None,
            "limit": result_limit,
            "requestedLimit": body.limit,
            "plan": {
                "query": parsed_plan.query,
                "sort": parsed_plan.sort,
                "filters": parsed_plan.filters,
                "keywords": parsed_plan.keywords,
                "dateRange": parsed_plan.date_range,
                "source": source,
                "llm": (
                    {
                        "provider": llm_interpretation.provider,
                        "model": llm_interpretation.model,
                        "confidence": llm_interpretation.confidence,
                    }
                    if llm_interpretation
                    else None
                ),
            },
        },
        response_payload={
            "foundCount": found_count,
            "returnedCount": returned_count,
            "ragHitCount": len(rag_hits),
        },
    )

    plan = _response_plan(parsed_plan)
    answer = _answer_text(
        found_count,
        returned_count,
        parsed_plan.description,
        "零件" if parsed_plan.domain == "part" else "产品",
        rows=rows,
        result_limit=result_limit,
    )
    await _record_conversation_safe(
        conversation_store,
        operator=operator,
        prompt=prompt,
        interpreted_prompt=prompt_for_plan if prompt_for_plan != prompt else None,
        llm_interpretation=llm_interpretation,
        parsed_plan=parsed_plan,
        semantic_profile=semantic_profile,
        source=source,
        warnings=parsed_plan.warnings,
        answer=answer,
        found_count=found_count,
        returned_count=returned_count,
        rag_hit_count=len(rag_hits),
        duration_ms=_duration_ms(started_at),
        status="success",
        analytics_worker=analytics_worker,
    )
    return NaturalLanguageQueryResponse(
        answer=answer,
        layout=parsed_plan.layout,
        rows=rows,
        foundCount=found_count,
        returnedCount=returned_count,
        plan=plan,
        source=source,
        ragHits=rag_hits,
    )


def _apply_customer_scope(
    parsed_plan,
    product_client_id: str,
    part_customer_id: str = "",
) -> None:
    """Force every FileMaker find branch into the account's exact domain scope."""
    _validate_customer_scope(parsed_plan, product_client_id, part_customer_id)
    parsed_plan.filters.pop("client", None)
    parsed_plan.filters.pop("audit", None)
    visible_description = [
        item for item in str(parsed_plan.description or "").split("；")
        if item and not item.startswith("客户包含")
    ]
    parsed_plan.description = "；".join([*visible_description, "您的可见范围"])

    if parsed_plan.domain == "part":
        scope_field = "customer_id"
        scope_value = part_customer_id.strip()
        parsed_plan.filters.pop("privilege", None)
        parsed_plan.filters["partCustomerId"] = scope_value
        sort_field = "part_number"
    else:
        scope_field = "id_client"
        scope_value = product_client_id.strip()
        parsed_plan.filters.pop("partCustomerId", None)
        parsed_plan.filters["productClientId"] = scope_value
        sort_field = "product_sku"

    scope_criteria = f"=={scope_value}"
    customer_scope_fields = {
        "Client",
        "ID_客戶",
        "customer_id",
        "id_client",
        "專屬客戶",
        "審核",
        "privilege",
        "omit",
        "產品名稱_中文",
        "客戶_Privilege::客戶公司簡稱",
        "Category_Product_1::title",
        "Category_Product_2::title",
        "Category_Product_3::title",
        "part_name",
        "English Name",
        "Notes",
        "零件_客戶::客戶代號",
        "零件_客戶::客戶公司簡稱",
    }
    if parsed_plan.query:
        scoped_query: list[dict[str, object]] = []
        for criteria in parsed_plan.query:
            safe_criteria = {
                field: value
                for field, value in criteria.items()
                if field not in customer_scope_fields
            }
            # A keyword OR-query can include customer relationship fields. Once
            # those fields are removed at the external boundary, keeping a
            # scope-only branch would match the customer's entire catalog and
            # turn any unknown phrase into a false positive.
            if not safe_criteria:
                continue
            scoped_query.append({**safe_criteria, scope_field: scope_criteria})
        if not scoped_query:
            raise NaturalQueryError(
                "Please search by product or part number, name, model, inventory, or date."
            )
        parsed_plan.query = scoped_query
    else:
        parsed_plan.query = [{scope_field: scope_criteria}]
    if not getattr(parsed_plan, "sort", None):
        parsed_plan.sort = [{"fieldName": sort_field, "sortOrder": "ascend"}]


def _force_exact_customer_identifier(parsed_plan, prompt: str) -> None:
    """Keep explicit customer item numbers exact even when layout metadata is stale."""
    identifier = _customer_exact_identifier(prompt)
    if not identifier or parsed_plan.domain not in {"product", "part"}:
        return

    field_name = "part_number" if parsed_plan.domain == "part" else "product_sku"
    parsed_plan.query = [{field_name: f"=={identifier}"}]
    parsed_plan.keywords = [identifier]
    parsed_plan.filters = {}
    parsed_plan.date_range = None
    parsed_plan.description = f"Exact item number: {identifier}"


def _customer_exact_identifier(prompt: str) -> str | None:
    match = re.search(
        r"(?<![A-Za-z0-9])"
        r"(?=[A-Za-z0-9_-]{4,40}(?![A-Za-z0-9_-]))"
        r"(?=[A-Za-z0-9_-]*[A-Za-z])"
        r"(?=[A-Za-z0-9_-]*[0-9])"
        r"[A-Za-z0-9]+(?:[-_][A-Za-z0-9]+)*"
        r"(?![A-Za-z0-9])",
        prompt,
    )
    return match.group(0).upper() if match else None


def _explicit_identifier_domain(prompt: str) -> str | None:
    """Return a domain only when the prompt names exactly one of them."""
    normalized = " ".join(prompt.casefold().split())
    names_part = (
        any(term in normalized for term in ("零件", "配件", "备件", "備件", "part_number"))
        or bool(re.search(r"\b(?:parts?|spares?)\b", normalized))
    )
    names_product = (
        any(term in normalized for term in ("产品", "產品", "product_sku"))
        or bool(re.search(r"\b(?:products?|sku)\b", normalized))
    )
    if names_part == names_product:
        return None
    return "part" if names_part else "product"


async def _resolve_internal_identifier_domain(
    filemaker: FileMakerClient,
    identifier: str,
) -> str:
    """Find an unlabeled identifier in both internal catalogs."""
    product_result, part_result = await asyncio.gather(
        filemaker.find_records(
            "@products",
            query={"product_sku": f"=={identifier}"},
            limit=1,
        ),
        filemaker.find_records(
            "Parts",
            query={"part_number": f"=={identifier}"},
            limit=1,
        ),
    )
    product_found = int(product_result.get("foundCount") or 0) > 0
    part_found = int(part_result.get("foundCount") or 0) > 0
    if product_found and part_found:
        return "ambiguous"
    if product_found:
        return "product"
    if part_found:
        return "part"
    return "not_found"


def _identifier_domain_clarification(
    prompt: str,
    identifier: str,
    *,
    matched_both: bool,
) -> dict[str, object]:
    lower = prompt.casefold()
    if _wants_price_detail(lower):
        options = [
            f"查询产品 {identifier} 的价格",
            f"查询零件 {identifier} 的价格",
        ]
    elif _wants_stock_detail(lower):
        options = [
            f"查询产品 {identifier} 的库存",
            f"查询零件 {identifier} 的库存",
        ]
    else:
        options = [
            f"查询产品 {identifier}",
            f"查询零件 {identifier}",
        ]
    question = (
        f"编号 {identifier} 在产品和零件资料中都存在。你要查询产品还是零件？"
        if matched_both
        else f"没有确认编号 {identifier} 属于哪个领域。它是产品还是零件？"
    )
    return {"question": question, "options": options}


def _validate_customer_scope(
    parsed_plan,
    product_client_id: str,
    part_customer_id: str = "",
) -> None:
    if parsed_plan.domain == "product" and not product_client_id.strip():
        raise NaturalQueryError("This customer account has no product data scope.")
    if parsed_plan.domain == "part" and not part_customer_id.strip():
        raise NaturalQueryError("This customer account has no part data scope.")
    if parsed_plan.domain not in {"product", "part"}:
        raise NaturalQueryError("This portal only supports product and part searches.")


def _is_scoped_customer_listing(
    parsed_plan,
    product_client_id: str,
    part_customer_id: str = "",
) -> bool:
    """A broad list is safe only after an authenticated customer scope is applied."""
    has_domain_scope = (
        bool(product_client_id.strip())
        if parsed_plan.domain == "product"
        else bool(part_customer_id.strip())
        if parsed_plan.domain == "part"
        else False
    )
    return bool(
        has_domain_scope
        and not parsed_plan.query
        and not parsed_plan.keywords
        and not parsed_plan.filters
        and not parsed_plan.date_range
    )


def _rag_layout(query_layout: str) -> str:
    return _RAG_LAYOUT_BY_QUERY_LAYOUT.get(query_layout, query_layout)


def _exact_odata_lookup(parsed_plan) -> tuple[str, tuple[str, ...], str] | None:
    mapping = _ODATA_EXACT_QUERY.get(str(parsed_plan.domain or ""))
    if not mapping:
        return None
    table, key_fields = mapping
    scope_fields = {"id_client", "ID_客戶", "customer_id", "privilege"}
    if any(
        scope_fields.intersection(criteria)
        for criteria in parsed_plan.query
        if isinstance(criteria, dict)
    ):
        return None
    values = {
        str(value)[2:].strip()
        for criteria in parsed_plan.query
        if isinstance(criteria, dict)
        for field, value in criteria.items()
        if field in key_fields and str(value).startswith("==") and str(value)[2:].strip()
    }
    if len(values) != 1:
        return None
    return table, key_fields, values.pop()


async def _find_exact_records_via_odata(
    parsed_plan,
    *,
    client: FileMakerODataClient,
    settings: Settings,
    limit: int,
    offset: int,
) -> dict[str, object] | None:
    lookup = _exact_odata_lookup(parsed_plan)
    if not lookup or not settings.filemaker_odata_configured:
        return None
    table, key_fields, value = lookup
    escaped = value.replace("'", "''")
    filter_expr = " or ".join(f"{field} eq '{escaped}'" for field in key_fields)
    try:
        result = await client.records(
            table,
            select=list(_ODATA_LIVE_SELECT_FIELDS.get(parsed_plan.domain, ())),
            filter_expr=filter_expr,
            top=limit,
            skip=max(0, offset - 1),
            count=True,
        )
    except FileMakerODataError as exc:
        logger.warning("Exact OData lookup failed; falling back to Data API: %s", exc)
        return None

    rows = result.get("rows") if isinstance(result, dict) else []
    if not isinstance(rows, list) or not rows:
        return None
    records = [_odata_row_to_filemaker_record(row, key_fields) for row in rows if isinstance(row, dict)]
    return {
        "data": records,
        "foundCount": int(result.get("foundCount") or len(records)),
        "returnedCount": len(records),
    }


def _odata_row_to_filemaker_record(row: dict[str, object], key_fields: tuple[str, ...]) -> dict[str, object]:
    field_data = {
        str(key): value
        for key, value in row.items()
        if not str(key).startswith("@") and key not in {"ROWID", "ROWMODID"}
    }
    return {
        "recordId": str(row_key_value(row, list(key_fields)) or ""),
        "modId": str(row.get("ROWMODID") or ""),
        "fieldData": field_data,
    }


async def _layout_fields_for_query(
    layout: str,
    *,
    rag_store: RagIndexStore,
    filemaker: FileMakerClient,
    settings: Settings,
) -> list[dict[str, object]]:
    profile = await rag_store.get_layout_profile(_rag_layout(layout))
    if profile:
        fields = [field for field in profile.get("fields", []) if isinstance(field, dict)]
        created_field = str(profile.get("createdField") or "")
        updated_field = str(profile.get("updatedField") or "")
        known_names = {str(field.get("name") or "") for field in fields}
        for field_name in (created_field, updated_field):
            if field_name and field_name not in known_names:
                fields.append({"name": field_name})
        if fields:
            return fields

    try:
        fields = await asyncio.wait_for(
            filemaker.get_layout_fields(layout),
            timeout=max(1.0, settings.rag_index_layout_fields_timeout_seconds),
        )
    except (asyncio.TimeoutError, FileMakerAPIError):
        return []
    return [field for field in fields if isinstance(field, dict)]


async def _semantic_profile_for_query(
    layout: str,
    layout_fields: list[dict[str, object]],
    *,
    rag_store: RagIndexStore,
    settings: Settings,
) -> dict[str, object]:
    profile_layout = _rag_layout(layout)
    profile = await rag_store.get_layout_profile(profile_layout)
    if profile:
        semantic_profile = profile.get("semanticProfile")
        if _has_semantic_concepts(semantic_profile):
            return semantic_profile

    fields = [dict(field) for field in layout_fields if isinstance(field, dict)]
    if not fields:
        return fallback_layout_semantic_profile(layout=layout, fields=[])

    semantic_profile = await build_layout_semantic_profile(
        layout=layout,
        fields=fields,
        settings=settings,
    )
    if profile:
        await rag_store.update_layout_semantic_profile(
            layout=profile_layout,
            semantic_profile=semantic_profile,
        )
    return semantic_profile


def _has_semantic_concepts(value: object) -> bool:
    return isinstance(value, dict) and isinstance(value.get("concepts"), dict)


async def _interpret_prompt_with_llm(
    prompt: str,
    *,
    rag_store: RagIndexStore,
    settings: Settings,
) -> LlmQueryInterpretation | None:
    interpreter = DeepSeekQueryInterpreter(settings)
    if not interpreter.enabled:
        return None

    try:
        return await interpreter.interpret(
            prompt,
            now=_now(settings),
            layout_context=await _layout_context_for_llm(rag_store),
        )
    except LlmQueryInterpreterError as exc:
        logger.warning("LLM natural query interpretation failed; falling back to local parser: %s", exc)
        return None


async def _layout_context_for_llm(rag_store: RagIndexStore) -> list[dict[str, object]]:
    context: list[dict[str, object]] = []
    layouts = (
        ("@products", "@products"),
        ("@零件", "Parts"),
    )
    for index_layout, query_layout in layouts:
        profile = await rag_store.get_layout_profile(index_layout)
        if not profile:
            continue
        fields = profile.get("fields", [])
        field_names = [
            str(field.get("name") or "")
            for field in fields
            if isinstance(field, dict) and field.get("name")
        ]
        semantic_profile = profile.get("semanticProfile")
        semantic_profile = semantic_profile if isinstance(semantic_profile, dict) else {}
        context.append({
            "layout": query_layout,
            "indexLayout": index_layout,
            "createdField": profile.get("createdField"),
            "updatedField": profile.get("updatedField"),
            "fields": field_names[:80],
            "entity": semantic_profile.get("entity", {}),
            "relationships": semantic_profile.get("relationships", []),
        })
    return context


def _now(settings: Settings) -> datetime:
    try:
        tz = ZoneInfo(settings.natural_query_timezone)
    except ZoneInfoNotFoundError:
        tz = ZoneInfo("UTC")
    return datetime.now(tz)


def _effective_result_limit(settings: Settings, requested_limit: int) -> int:
    configured_limit = max(1, settings.natural_query_max_display_rows)
    return min(max(1, requested_limit), configured_limit)


def _answer_text(
    found_count: int,
    returned_count: int,
    description: str,
    entity_label: str,
    *,
    rows: list[object] | None = None,
    result_limit: int = 10,
) -> str:
    if found_count == 0:
        return f"没有找到符合“{description}”的{entity_label}记录。"
    if found_count > result_limit:
        summary = _large_result_summary(rows or [], entity_label)
        return (
            f"符合“{description}”的{entity_label}记录共 {found_count} 条，"
            f"数据量较大，本次只显示前 {returned_count} 条。{summary}"
        )
    return f"找到 {found_count} 条符合“{description}”的{entity_label}记录，本次显示 {returned_count} 条。"


def _large_result_summary(rows: list[object], entity_label: str) -> str:
    labels = [_row_display_label(row) for row in rows[:3]]
    labels = [label for label in labels if label]
    if labels:
        return f"简要总结：前几条{entity_label}包括 {'、'.join(labels)}；如需完整明细，请缩小日期、型号、材料或客户范围。"
    return f"简要总结：已按当前排序返回前几条{entity_label}；如需完整明细，请缩小日期、型号、材料或客户范围。"


def _row_display_label(row: object) -> str:
    for attr in ("product_sku", "system_product_sku", "product_name_cn", "product_name", "model_name"):
        value = getattr(row, attr, "")
        if value not in (None, ""):
            return str(value)
    raw = getattr(row, "raw", {})
    if isinstance(raw, dict):
        for key in (
            "part_number",
            "part_name_en",
            "part_name",
            "English Name",
            "product_sku",
            "產品名稱_中文",
        ):
            value = raw.get(key)
            if value not in (None, ""):
                return str(value)
    return ""


def _response_plan(parsed_plan) -> NaturalLanguageQueryPlan:
    return NaturalLanguageQueryPlan(
        domain=parsed_plan.domain,
        intent=parsed_plan.intent,
        layout=parsed_plan.layout,
        description=parsed_plan.description,
        query=parsed_plan.query,
        sort=parsed_plan.sort,
        keywords=parsed_plan.keywords,
        filters=parsed_plan.filters,
        dateRange=(
            NaturalLanguageDateRange(**parsed_plan.date_range)
            if parsed_plan.date_range
            else None
        ),
        warnings=parsed_plan.warnings,
    )


def _clarification_for_plan(
    *,
    prompt: str,
    interpreted_prompt: str,
    parsed_plan,
) -> dict[str, list[str] | str] | None:
    broad_keyword_only = bool(parsed_plan.keywords) and all(
        _is_broad_keyword(keyword) for keyword in parsed_plan.keywords
    )
    if parsed_plan.filters or parsed_plan.date_range or parsed_plan.sort:
        return None
    if (parsed_plan.query or parsed_plan.keywords) and not broad_keyword_only:
        return None

    entity_label = "零件" if parsed_plan.domain == "part" else "产品"
    text = f"{prompt} {interpreted_prompt}".lower()
    wants_value = (
        _wants_price_detail(text)
        or _wants_stock_detail(text)
        or _wants_creator_detail(text)
        or _wants_timestamp_detail(text)
    )

    if "最近" in text or "最新" in text:
        return {
            "question": f"你说的“最近”是指近几天新增的{entity_label}，还是只想看最新几条？",
            "options": [
                f"近7天新增的{entity_label}",
                f"今天新增的{entity_label}有哪些",
                f"昨天新增的{entity_label}有哪些",
            ],
        }

    if wants_value:
        return {
            "question": f"你想查询哪一批{entity_label}的信息？请补充关键词、日期范围、客户或编号。",
            "options": (
                [
                    "昨天新增的零件，价格分别是多少",
                    "pvc的零件，库存还有多少",
                    "近7天新增的零件，都是谁创建的",
                ]
                if parsed_plan.domain == "part"
                else [
                    "查询 STRX-202 产品",
                    "昨天新增的产品有哪些",
                    "HPI 客户的产品有哪些",
                ]
            ),
        }

    return {
        "question": f"这个问题范围太宽。你想按什么条件查询{entity_label}？",
        "options": (
            [
                "pvc的零件有哪些",
                "今天新增的零件有哪些",
                "近7天新增的零件",
            ]
            if parsed_plan.domain == "part"
            else [
                "查询 STRX-202 产品",
                "昨天新增的产品有哪些",
                "HPI 客户的产品有哪些",
            ]
        ),
    }


def _is_broad_keyword(value: str) -> bool:
    normalized = value.strip().casefold()
    normalized = normalized.replace("的", "")
    return normalized in {
        "所有",
        "全部",
        "全部零件",
        "所有零件",
        "全部产品",
        "所有产品",
        "全部產品",
        "所有產品",
        "all",
        "allparts",
        "allproducts",
    }


def _duration_ms(started_at: float) -> int:
    return max(0, int((time.perf_counter() - started_at) * 1000))


async def _record_conversation_safe(
    store: NaturalQueryConversationStore,
    *,
    operator: OperatorContext,
    prompt: str,
    interpreted_prompt: str | None,
    llm_interpretation: LlmQueryInterpretation | None,
    parsed_plan,
    semantic_profile: dict[str, object] | None,
    source: str,
    found_count: int,
    returned_count: int,
    rag_hit_count: int,
    duration_ms: int,
    status: str,
    warnings: list[str] | None = None,
    answer: str | None = None,
    error_message: str | None = None,
    analytics_worker: NaturalQueryAnalyticsWorker | None = None,
) -> None:
    try:
        await store.record(
            operator=operator,
            prompt=prompt,
            interpreted_prompt=interpreted_prompt,
            llm=_llm_record(llm_interpretation),
            layout=parsed_plan.layout if parsed_plan else None,
            domain=parsed_plan.domain if parsed_plan else None,
            intent=parsed_plan.intent if parsed_plan else None,
            source=source,
            query=parsed_plan.query if parsed_plan else [],
            sort=parsed_plan.sort if parsed_plan else [],
            filters=parsed_plan.filters if parsed_plan else {},
            date_range=parsed_plan.date_range if parsed_plan else None,
            semantic_profile=semantic_profile,
            warnings=warnings or (parsed_plan.warnings if parsed_plan else []),
            answer=answer,
            found_count=found_count,
            returned_count=returned_count,
            rag_hit_count=rag_hit_count,
            duration_ms=duration_ms,
            status=status,
            error_message=error_message,
        )
        if analytics_worker:
            analytics_worker.notify()
    except Exception:
        logger.exception("Unable to record natural query conversation")


def _llm_record(llm_interpretation: LlmQueryInterpretation | None) -> dict[str, object]:
    if not llm_interpretation:
        return {}
    return {
        "provider": llm_interpretation.provider,
        "model": llm_interpretation.model,
        "confidence": llm_interpretation.confidence,
        "warnings": llm_interpretation.warnings,
    }


def _row_for_plan(
    record: dict[str, object],
    domain: str,
    *,
    semantic_profile: dict[str, object] | None = None,
):
    if domain != "part":
        return _product_row(record)
    return _product_row(_part_record_to_product_shape(record, semantic_profile=semantic_profile))


def _part_record_to_product_shape(
    record: dict[str, object],
    *,
    semantic_profile: dict[str, object] | None = None,
) -> dict[str, object]:
    fields = record.get("fieldData", {})
    if not isinstance(fields, dict):
        fields = {}
    mapped_fields = dict(fields)
    part_number = str(fields.get("part_number") or "")
    part_name = str(fields.get("part_name") or "")
    english_name = str(fields.get("part_name_en") or fields.get("English Name") or "")
    mapped_fields["product_sku"] = part_number
    mapped_fields["系統產品編號"] = part_number
    mapped_fields["product_name"] = english_name or part_name
    mapped_fields["產品名稱_中文"] = part_name or english_name
    mapped_fields[PRODUCT_STOCK_FIELD] = (
        fields.get("stock_on_hand_qty")
        if fields.get("stock_on_hand_qty") not in (None, "")
        else fields.get("current_stock")
    )
    mapped_fields["檔案 1 | 容器"] = fields.get("影像 | 容器") or fields.get("圖面 | 容器")
    created_by_field = semantic_concept_field(semantic_profile, "createdBy")
    if created_by_field:
        mapped_fields["Created By"] = fields.get(created_by_field)
        mapped_fields["创建人"] = fields.get(created_by_field)
    price_field = semantic_concept_field(semantic_profile, "price")
    if price_field:
        mapped_fields["Price"] = fields.get(price_field)
        mapped_fields["价格"] = fields.get(price_field)
    mapped_fields["Client"] = fields.get("專屬客戶") or fields.get("零件_客戶::客戶公司簡稱")
    return {
        **record,
        "fieldData": mapped_fields,
    }


def _coverage_warnings_for_rows(
    domain: str,
    layout: str,
    layout_fields: list[dict[str, object]],
    rows: list[object],
    *,
    prompt: str,
    interpreted_prompt: str,
    date_range: dict[str, str] | None,
    semantic_profile: dict[str, object] | None = None,
) -> list[str]:
    warnings: list[str] = []
    timestamp_warning = _timestamp_warning_for_layout(
        layout,
        layout_fields,
        prompt=prompt,
        interpreted_prompt=interpreted_prompt,
        date_range=date_range,
    )
    if timestamp_warning:
        warnings.append(timestamp_warning)
    stock_warning = _stock_warning_for_rows(
        domain,
        rows,
        prompt=prompt,
        interpreted_prompt=interpreted_prompt,
    )
    if stock_warning:
        warnings.append(stock_warning)
    price_warning = _price_warning_for_rows(
        domain,
        layout,
        rows,
        prompt=prompt,
        interpreted_prompt=interpreted_prompt,
        semantic_profile=semantic_profile,
    )
    if price_warning:
        warnings.append(price_warning)
    creator_warning = _creator_warning_for_rows(
        domain,
        layout,
        rows,
        prompt=prompt,
        interpreted_prompt=interpreted_prompt,
        semantic_profile=semantic_profile,
    )
    if creator_warning:
        warnings.append(creator_warning)
    return warnings


def _timestamp_warning_for_layout(
    layout: str,
    layout_fields: list[dict[str, object]],
    *,
    prompt: str,
    interpreted_prompt: str,
    date_range: dict[str, str] | None,
) -> str | None:
    if not date_range:
        return None
    if not (_wants_timestamp_detail(prompt) or _wants_timestamp_detail(interpreted_prompt)):
        return None
    if _layout_has_timestamp_field(layout_fields):
        return None

    created_field = date_range.get("field") or "创建日期"
    return (
        f"FileMaker 的 {layout} 布局目前只提供“{created_field}”日期字段，"
        "没有创建时间戳或更新时间字段；已回退显示创建日期。"
    )


def _layout_has_timestamp_field(layout_fields: list[dict[str, object]]) -> bool:
    return any(_is_timestamp_field(field) for field in layout_fields)


def _is_timestamp_field(field: dict[str, object]) -> bool:
    name = str(field.get("name") or "").lower()
    result = str(
        field.get("result")
        or field.get("type")
        or field.get("fieldType")
        or field.get("displayType")
        or ""
    ).lower()
    if "turnover time" in name:
        return False
    timestamp_terms = (
        "timestamp",
        "created_at",
        "updated_at",
        "creationtimestamp",
        "recordcreationtimestamp",
        "created time",
        "time created",
        "modified at",
        "updated at",
        "last modified",
        "创建时间",
        "創建時間",
        "新增时间",
        "新增時間",
        "修改时间",
        "修改時間",
        "更新时间",
        "更新時間",
    )
    return (
        "timestamp" in result
        or bool(field.get("timeOfDay"))
        or any(term in name for term in timestamp_terms)
    )


def _stock_warning_for_rows(
    domain: str,
    rows: list[object],
    *,
    prompt: str,
    interpreted_prompt: str,
) -> str | None:
    if domain != "part" or not rows:
        return None
    if not (_wants_stock_detail(prompt) or _wants_stock_detail(interpreted_prompt)):
        return None

    stock_values = [_row_stock_value(row) for row in rows]
    if all(_is_empty_value(value) for value in stock_values):
        return (
            "Parts 的当前库存字段是 stock_on_hand_qty；本次显示的记录该字段为空，"
            "已在结果中显示为“未填”。"
        )
    if any(_is_empty_value(value) for value in stock_values):
        return "部分 Parts 记录的 stock_on_hand_qty 为空，已在结果中显示为“未填”。"
    return None


def _price_warning_for_rows(
    domain: str,
    layout: str,
    rows: list[object],
    *,
    prompt: str,
    interpreted_prompt: str,
    semantic_profile: dict[str, object] | None = None,
) -> str | None:
    if domain != "part":
        return None
    if not (_wants_price_detail(prompt) or _wants_price_detail(interpreted_prompt)):
        return None

    price_field = semantic_concept_field(semantic_profile, "price")
    if not price_field:
        reason = semantic_concept_reason(semantic_profile, "price")
        reason_suffix = f"语义分析结果：{reason}" if reason else "metadata 中没有价格/单价/售价字段。"
        return (
            f"FileMaker 的 {layout} 布局 metadata 没有发现可表示“价格/单价”的字段；"
            f"无法返回这些零件的价格。{reason_suffix}"
        )

    if not rows:
        return None
    price_values = [_row_raw_value(row, price_field) or _row_raw_value(row, "Price") for row in rows]
    if all(_is_empty_value(value) for value in price_values):
        return f"{layout} 的价格字段是“{price_field}”；本次显示的记录该字段为空。"
    if any(_is_empty_value(value) for value in price_values):
        return f"部分 {layout} 记录的价格字段“{price_field}”为空。"
    return None


def _creator_warning_for_rows(
    domain: str,
    layout: str,
    rows: list[object],
    *,
    prompt: str,
    interpreted_prompt: str,
    semantic_profile: dict[str, object] | None = None,
) -> str | None:
    if domain != "part":
        return None
    if not (_wants_creator_detail(prompt) or _wants_creator_detail(interpreted_prompt)):
        return None

    creator_field = semantic_concept_field(semantic_profile, "createdBy")
    if not creator_field:
        reason = semantic_concept_reason(semantic_profile, "createdBy")
        reason_suffix = f"语义分析结果：{reason}" if reason else "metadata 中没有创建人/创建者/录入人字段。"
        return (
            f"FileMaker 的 {layout} 布局 metadata 没有发现可表示“创建人/创建者”的字段；"
            f"无法判断这些零件是谁创建的。{reason_suffix}"
        )

    if not rows:
        return None
    creator_values = [_row_raw_value(row, creator_field) or _row_raw_value(row, "Created By") for row in rows]
    if all(_is_empty_value(value) for value in creator_values):
        return f"{layout} 的创建人字段是“{creator_field}”；本次显示的记录该字段为空。"
    if any(_is_empty_value(value) for value in creator_values):
        return f"部分 {layout} 记录的创建人字段“{creator_field}”为空。"
    return None


def _wants_stock_detail(text: str) -> bool:
    lower = text.lower()
    return any(
        term in lower
        for term in (
            "库存",
            "庫存",
            "stock",
            "stock_on_hand_qty",
            "current_stock",
            "还有多少",
            "還有多少",
            "剩余",
            "剩餘",
        )
    )


def _wants_price_detail(text: str) -> bool:
    lower = text.lower()
    return (
        any(term in lower for term in _PRICE_QUERY_TERMS_CJK)
        or any(
            re.search(rf"(?<![a-z0-9]){re.escape(term)}(?![a-z0-9])", lower)
            for term in _PRICE_QUERY_TERMS_ENGLISH
        )
    )


def _wants_creator_detail(text: str) -> bool:
    lower = text.lower()
    return any(
        term in lower
        for term in (
            "谁创建",
            "誰創建",
            "谁建立",
            "誰建立",
            "谁录入",
            "誰錄入",
            "创建人",
            "創建人",
            "创建者",
            "創建者",
            "录入人",
            "錄入人",
            "建档人",
            "建檔人",
            "操作员",
            "操作員",
            "created by",
            "creator",
            "created_by",
        )
    )


def _wants_timestamp_detail(text: str) -> bool:
    lower = text.lower()
    return any(
        term in lower
        for term in (
            "时间戳",
            "時間戳",
            "timestamp",
            "具体时间",
            "具體時間",
            "创建时间",
            "創建時間",
            "新增时间",
            "新增時間",
            "更新时间",
            "更新時間",
            "修改时间",
            "修改時間",
            "几点",
            "幾點",
        )
    )


def _row_stock_value(row: object) -> object:
    return getattr(row, "stock", None)


def _row_raw_value(row: object, field: str) -> object:
    raw = getattr(row, "raw", None)
    if not isinstance(raw, dict):
        return None
    return raw.get(field)


def _is_empty_value(value: object) -> bool:
    return value is None or value == "" or value == []


def _chunk_to_record(chunk: RagRecordChunk) -> dict[str, object]:
    return {
        "recordId": chunk.record_id,
        "modId": chunk.mod_id,
        "fieldData": chunk.fields,
    }


def _chunk_to_hit(chunk: RagRecordChunk) -> RagSearchHit:
    return RagSearchHit(
        layout=chunk.layout,
        recordId=chunk.record_id,
        title=chunk.title,
        snippet=chunk.snippet,
        score=chunk.score,
        fields=chunk.fields,
        updatedAt=chunk.updated_at,
    )
