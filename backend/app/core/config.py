from functools import lru_cache
from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "StarRC FileMaker Service"
    app_env: str = "local"
    api_prefix: str = "/api"
    cors_origins: str = (
        "http://localhost:8080,http://localhost:5173,http://127.0.0.1:5173,"
        "http://localhost:3000"
    )

    database_path: str = "backend/data/app.db"
    audit_database_url: str = "postgresql://starrc:starrc@localhost:5432/starrc_audit"

    filemaker_host: str = ""
    filemaker_database: str = ""
    filemaker_username: str = ""
    filemaker_password: str = ""
    filemaker_api_version: str = "v2"
    filemaker_token_inactivity_timeout_seconds: int = Field(
        default=15 * 60,
        validation_alias=AliasChoices(
            "FILEMAKER_TOKEN_INACTIVITY_TIMEOUT_SECONDS",
            "FILEMAKER_TOKEN_TTL_SECONDS",
        ),
    )
    filemaker_material_options_cache_ttl_seconds: int = Field(
        default=24 * 60 * 60,
        ge=0,
        le=7 * 24 * 60 * 60,
    )
    filemaker_part_options_cache_refresh_interval_seconds: int = Field(
        default=24 * 60 * 60,
        ge=0,
        le=7 * 24 * 60 * 60,
    )
    filemaker_part_options_cache_retry_seconds: int = Field(
        default=5 * 60,
        ge=10,
        le=60 * 60,
    )
    filemaker_timeout_seconds: float = 30.0
    filemaker_ssl_verify: bool = False
    filemaker_read_only: bool = True
    # Dedicated, allow-listed write path for the internal-order merge page.
    # This remains independent from FILEMAKER_READ_ONLY so generic create/update/
    # delete/script endpoints can stay locked while this one workflow is enabled.
    filemaker_web_merge_enabled: bool = False
    filemaker_web_merge_order_layout: str = "@出貨單"
    filemaker_web_merge_order_create_layout: str = "訂單 資料_業務_EDIT"
    filemaker_web_merge_item_layout: str = "出貨單資料_List_業務"
    filemaker_web_merge_order_id_field: str = "id"
    filemaker_web_merge_internal_order_no_field: str = "internal_id"
    filemaker_web_merge_customer_id_field: str = "customer_id"
    filemaker_web_merge_log_field: str = "log"
    filemaker_web_merge_order_date_field: str = "日期"
    filemaker_web_merge_date_format: str = "%m/%d/%Y"
    filemaker_web_merge_order_type_field: str = "訂單型態"
    filemaker_web_merge_order_type_value: str = "零件包"
    filemaker_web_merge_order_category_field: str = "訂單分類"
    filemaker_web_merge_order_category_value: str = "合併單"
    filemaker_web_merge_item_order_id_field: str = "ID_出貨單"
    filemaker_web_merge_item_product_field: str = "產品編號"
    filemaker_web_merge_item_quantity_field: str = "數量"
    filemaker_web_merge_product_layout: str = "@products"
    filemaker_web_merge_product_sku_field: str = "product_sku"
    filemaker_web_merge_product_name_field: str = "product_name"
    filemaker_web_merge_max_orders: int = 200
    filemaker_web_merge_max_items: int = 2000
    # Dedicated, allow-listed Data API write path for creating an order BOM
    # calculation. Generic FileMaker write endpoints remain governed by
    # FILEMAKER_READ_ONLY and can stay disabled.
    filemaker_bom_write_enabled: bool = False
    filemaker_bom_order_read_layout: str = "訂單 發料單"
    filemaker_bom_order_write_layout: str = "web_BOM计算"
    filemaker_bom_order_item_layout: str = "出貨單資料_List_業務"
    filemaker_bom_order_rich_item_layout: str = "@出貨單資料"
    filemaker_bom_header_layout: str = "訂單 計算單_精簡"
    filemaker_bom_detail_layout: str = "@BOM计算单资料"
    filemaker_bom_nonrepeat_layout: str = "@BOM計算單資料Non"
    filemaker_bom_product_layout: str = "@product_bom"
    filemaker_bom_part_layout: str = "零件 資料_業務"
    filemaker_bom_max_detail_records: int = 1000
    # Dedicated, allow-listed Data API write path for the new-part WebViewer.
    # Generic FileMaker writes stay disabled by FILEMAKER_READ_ONLY.
    filemaker_part_create_enabled: bool = False
    filemaker_part_read_layout: str = "新增零件资料"
    filemaker_part_write_layout: str = "@零件"
    filemaker_part_number_field: str = "part_number"
    filemaker_part_photo_field: str = "影像 | 容器"
    filemaker_part_max_photo_bytes: int = 8 * 1024 * 1024
    # Dedicated PartAssets path. Keep disabled until the FileMaker table/layout
    # has been installed; legacy container reads and writes remain available.
    filemaker_part_assets_enabled: bool = False
    filemaker_part_asset_layout: str = "PartAssets"
    filemaker_odata_enabled: bool = True
    filemaker_odata_version: str = "v4"
    filemaker_odata_auth_mode: str = "basic"
    filemaker_odata_fmid_token: str = ""
    filemaker_odata_max_top: int = 10
    semantic_mapping_path: str = "backend/config/semantic_mapping.json"

    natural_query_timezone: str = "Asia/Shanghai"
    natural_query_filemaker_date_format: str = "%Y/%m/%d"
    natural_query_filemaker_timestamp_format: str = "%Y/%m/%d %H:%M:%S"
    natural_query_product_created_fields: str = (
        "创建日期,創建日期,建立日期,新增日期,创建时间,創建時間,建立時間,"
        "创建时间戳,創建時間戳,createdAt,created_at,CreationTimestamp,"
        "RecordCreatedAt,RecordCreationTimestamp"
    )
    natural_query_use_rag: bool = True
    natural_query_use_cached_records: bool = False
    natural_query_rag_hit_limit: int = 10
    natural_query_max_display_rows: int = 10
    natural_query_llm_enabled: bool = False
    natural_query_analytics_llm_enabled: bool = True
    natural_query_analytics_pending_limit: int = 100
    natural_query_analytics_worker_enabled: bool = False
    natural_query_analytics_poll_interval_seconds: float = 60.0
    llm_provider: str = "deepseek"
    llm_model: str = "deepseek-v4-flash"
    llm_base_url: str = "https://api.deepseek.com"
    llm_api_key: str = Field(
        default="",
        validation_alias=AliasChoices("LLM_API_KEY", "DEEPSEEK_API_KEY"),
    )
    llm_timeout_seconds: float = 12.0
    llm_max_output_tokens: int = 320
    llm_ssl_verify: bool = True

    rag_index_enabled: bool = True
    rag_database_path: str = "backend/data/rag_index.db"
    rag_index_refresh_on_startup: bool = False
    rag_index_startup_delay_seconds: float = 20.0
    rag_index_refresh_interval_seconds: int = 6 * 60 * 60
    rag_index_refresh_schedule_time: str = "00:00"
    rag_index_refresh_schedule_timezone: str = "Asia/Shanghai"
    rag_index_layout_prefix: str = "@"
    rag_index_layout_include: str = "@products,@零件"
    rag_index_layout_exclude: str = ""
    rag_index_max_layouts: int = 0
    rag_index_read_layout_fields: bool = True
    rag_index_layout_fields_timeout_seconds: float = 8.0
    rag_index_page_size: int = 500
    rag_index_max_records_per_layout: int = 5000
    rag_index_max_fields_per_record: int = 40
    rag_index_value_max_length: int = 160
    rag_index_semantic_profile_enabled: bool = True
    rag_index_semantic_profile_layouts: str = "@products,@零件"
    rag_index_semantic_sample_records: int = 200
    rag_index_semantic_llm_timeout_seconds: float = 30.0
    rag_index_semantic_llm_max_output_tokens: int = 3600

    webviewer_context_secret: str = "dev-webviewer-secret-change-me"
    webviewer_session_ttl_seconds: int = 8 * 60 * 60
    webviewer_allow_mock_context: bool = True
    webviewer_remote_access_enabled: bool = False
    webviewer_remote_accounts_json: str = "[]"
    webviewer_remote_login_max_attempts: int = 5
    webviewer_remote_login_window_seconds: int = 15 * 60
    webviewer_privilege_set_policy_path: str = (
        "backend/config/webviewer_privilege_sets.json"
    )

    customer_chat_enabled: bool = False
    customer_chat_token_secret: str = ""
    customer_chat_session_ttl_seconds: int = 2 * 60 * 60
    customer_chat_accounts_json: str = "[]"
    customer_chat_login_max_attempts: int = 5
    customer_chat_login_window_seconds: int = 15 * 60
    customer_portal_public_url: str = "https://mayakofm.dataonfire.cn/customer-chat"
    customer_smtp_host: str = ""
    customer_smtp_port: int = 587
    customer_smtp_username: str = ""
    customer_smtp_password: str = ""
    customer_smtp_from_email: str = ""
    customer_smtp_from_name: str = "MayakoFM Customer Portal"
    customer_smtp_starttls: bool = True
    customer_smtp_ssl: bool = False
    customer_smtp_timeout_seconds: float = 15.0

    mes_callback_api_key: str = ""
    mes_hmac_secret: str = ""
    mes_filemaker_layout: str = ""
    mes_filemaker_script_name: str = "MES_UpdateWorkOrder"
    callback_max_attempts: int = 8
    callback_poll_interval_seconds: float = 5.0

    cos_enabled: bool = False
    cos_secret_id: str = ""
    cos_secret_key: str = ""
    cos_bucket: str = "starrc-1252872963"
    cos_region: str = "ap-guangzhou"
    cos_upload_base_url: str = (
        "https://starrc-1252872963.cos.ap-guangzhou.myqcloud.com"
    )
    cos_public_base_url: str = "https://oss.dataonfire.cn"
    cos_presign_ttl_seconds: int = 10 * 60
    cos_max_upload_bytes: int = 10 * 1024 * 1024
    cos_max_attachments_per_receipt: int = 8
    cos_allowed_content_types: str = (
        "image/jpeg,image/png,image/webp,image/heic,image/heif"
    )

    qr_base_url: str = "http://localhost:8080/q"

    @property
    def cors_origin_list(self) -> list[str]:
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]

    @property
    def filemaker_configured(self) -> bool:
        return all(
            [
                self.filemaker_host,
                self.filemaker_database,
                self.filemaker_username,
                self.filemaker_password,
            ]
        )

    @property
    def customer_smtp_configured(self) -> bool:
        return bool(
            self.customer_smtp_host.strip()
            and self.customer_smtp_from_email.strip()
            and (
                (self.customer_smtp_username.strip() and self.customer_smtp_password)
                or (not self.customer_smtp_username.strip() and not self.customer_smtp_password)
            )
        )

    @property
    def filemaker_odata_configured(self) -> bool:
        if not self.filemaker_odata_enabled:
            return False
        if not self.filemaker_host or not self.filemaker_database:
            return False
        auth_mode = self.filemaker_odata_auth_mode.strip().lower()
        if auth_mode == "fmid":
            return bool(self.filemaker_odata_fmid_token)
        return bool(self.filemaker_username and self.filemaker_password)

    @property
    def cos_configured(self) -> bool:
        return bool(
            self.cos_enabled
            and self.cos_secret_id.strip()
            and self.cos_secret_key
            and self.cos_bucket.strip()
            and self.cos_region.strip()
        )

    @property
    def cos_allowed_content_type_set(self) -> set[str]:
        return {
            item.strip().lower()
            for item in self.cos_allowed_content_types.split(",")
            if item.strip()
        }

    # 历史上已知的不安全占位符/默认密钥，生产环境绝不允许沿用。
    _INSECURE_SECRET_PLACEHOLDERS = frozenset(
        {
            "",
            "change-me",
            "dev-webviewer-secret-change-me",
            "changeme",
            "secret",
        }
    )

    @property
    def is_production(self) -> bool:
        return self.app_env.strip().lower() in ("production", "prod")

    def validate_production_security(self) -> None:
        """生产环境下聚合校验关键安全配置。

        仅当 ``app_env`` 标记为生产环境时执行；非生产环境直接返回，保持本地
        开发与测试的向后兼容。所有问题一次性收集后抛出，避免逐个修复重启。
        """
        if not self.is_production:
            return

        problems: list[str] = []
        if self.webviewer_context_secret.strip().lower() in self._INSECURE_SECRET_PLACEHOLDERS:
            problems.append(
                "WEBVIEWER_CONTEXT_SECRET 未配置或仍为占位符；生产环境必须设置一个 "
                "足够强度的随机密钥。"
            )
        if self.webviewer_allow_mock_context:
            problems.append(
                "WEBVIEWER_ALLOW_MOCK_CONTEXT=true 在生产环境会允许未认证签发会话 "
                "token，必须关闭（设为 false）。"
            )
        if self.webviewer_remote_access_enabled:
            from app.services.webviewer_remote_auth import (
                validate_webviewer_remote_configuration,
            )

            problems.extend(validate_webviewer_remote_configuration(self))
        if not self.mes_callback_api_key.strip():
            problems.append("MES_CALLBACK_API_KEY 未配置；生产环境的 MES 回调必须鉴权。")
        if not self.mes_hmac_secret.strip():
            problems.append("MES_HMAC_SECRET 未配置；生产环境的 MES 回调必须校验签名。")
        if self.natural_query_llm_enabled and not self.llm_api_key.strip():
            problems.append(
                "NATURAL_QUERY_LLM_ENABLED=true 但 LLM_API_KEY 未配置；"
                "生产环境启用 LLM 必须同时提供 API key。"
            )
        if self.cos_enabled and not self.cos_configured:
            problems.append(
                "COS_ENABLED=true，但 COS_SECRET_ID、COS_SECRET_KEY、COS_BUCKET "
                "或 COS_REGION 未完整配置。"
            )
        if self.filemaker_part_assets_enabled and not self.cos_configured:
            problems.append(
                "FILEMAKER_PART_ASSETS_ENABLED=true，但零件资产所需的 COS 配置不完整。"
            )
        if (
            self.filemaker_part_assets_enabled
            and not self.filemaker_part_asset_layout.strip()
        ):
            problems.append(
                "FILEMAKER_PART_ASSETS_ENABLED=true，但 "
                "FILEMAKER_PART_ASSET_LAYOUT 为空。"
            )
        if not 60 <= self.cos_presign_ttl_seconds <= 60 * 60:
            problems.append(
                "COS_PRESIGN_TTL_SECONDS 必须在 60 到 3600 秒之间。"
            )
        if self.cos_max_upload_bytes <= 0:
            problems.append("COS_MAX_UPLOAD_BYTES 必须大于 0。")
        if self.cos_max_attachments_per_receipt <= 0:
            problems.append("COS_MAX_ATTACHMENTS_PER_RECEIPT 必须大于 0。")

        if self.customer_chat_enabled:
            # Local import avoids a module cycle: the auth service also consumes Settings.
            from app.services.customer_chat_auth import validate_customer_chat_configuration

            problems.extend(validate_customer_chat_configuration(self))

        if problems:
            raise RuntimeError(
                "生产环境安全配置校验失败，请修正以下问题后重启：\n  - "
                + "\n  - ".join(problems)
            )


@lru_cache
def get_settings() -> Settings:
    return Settings()
