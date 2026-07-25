"""生产环境安全配置校验测试。

覆盖 ``Settings.validate_production_security()``：仅在生产环境（``app_env``
为 production/prod）时聚合校验关键密钥，非生产环境保持向后兼容。
"""

import json

import pytest

from app.core.config import Settings
from app.services.customer_chat_auth import hash_customer_password

# 带有 validation_alias 的字段（如 llm_api_key）无法通过构造参数字段名赋值，
# 需借助环境变量；其余字段直接用构造参数。
_ENV_KEY = "LLM_API_KEY"


def _strong_settings(
    monkeypatch: pytest.MonkeyPatch | None = None,
    **overrides: object,
) -> Settings:
    """返回一组生产环境可用、各项安全配置齐全的 Settings。

    用 ``_env_file=None`` 禁止加载本地 ``.env``，保证测试不受 .env 文件干扰。
    若需要设置带 alias 的 ``llm_api_key``，请配合 monkeypatch 传入环境变量。
    """
    base: dict[str, object] = {
        "app_env": "production",
        "webviewer_context_secret": "a-very-strong-random-secret-0123456789abcdef",
        "webviewer_allow_mock_context": False,
        "mes_callback_api_key": "mes-key",
        "mes_hmac_secret": "hmac-secret",
        "natural_query_llm_enabled": False,
    }
    if monkeypatch is not None:
        monkeypatch.setenv(_ENV_KEY, "sk-test")
    base.update(overrides)
    return Settings(_env_file=None, **base)


def _expect_validation_error(settings: Settings) -> None:
    """断言 validate_production_security 抛出 RuntimeError（避免 raises 上下文歧义）。"""
    try:
        settings.validate_production_security()
    except RuntimeError:
        return
    raise AssertionError("validate_production_security 应抛出 RuntimeError 但未抛出")


def test_is_production_recognizes_production_and_prod() -> None:
    assert Settings(_env_file=None, app_env="production").is_production is True
    assert Settings(_env_file=None, app_env="prod").is_production is True
    # 大小写与首尾空格应被容忍
    assert Settings(_env_file=None, app_env="  Production ").is_production is True


def test_is_production_false_for_local_and_other_values() -> None:
    assert Settings(_env_file=None, app_env="local").is_production is False
    assert Settings(_env_file=None, app_env="staging").is_production is False
    assert Settings(_env_file=None).is_production is False  # 默认值 local


def test_non_production_skips_validation_with_weak_defaults() -> None:
    """非生产环境即使沿用全部默认弱配置，也不应抛错（向后兼容）。"""
    settings = Settings(_env_file=None)  # 全默认值，secret 为占位符、mock 开启
    # 不应抛出任何异常
    settings.validate_production_security()


def test_production_with_strong_config_passes(monkeypatch: pytest.MonkeyPatch) -> None:
    _strong_settings(monkeypatch).validate_production_security()  # 不抛异常即通过


def test_production_default_weak_secret_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = _strong_settings(monkeypatch, webviewer_context_secret="dev-webviewer-secret-change-me")
    _expect_validation_error(settings)


def test_production_placeholder_secret_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = _strong_settings(monkeypatch, webviewer_context_secret="change-me")
    _expect_validation_error(settings)


def test_production_empty_secret_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = _strong_settings(monkeypatch, webviewer_context_secret="")
    _expect_validation_error(settings)


def test_production_mock_context_enabled_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    raised = False
    try:
        _strong_settings(monkeypatch, webviewer_allow_mock_context=True).validate_production_security()
    except RuntimeError:
        raised = True
    assert raised, "webviewer_allow_mock_context=True 在生产环境必须抛错"


def test_production_remote_access_with_hashed_account_passes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    accounts = json.dumps(
        [
            {
                "username": "starrc-team",
                "displayName": "StarRC Team",
                "passwordHash": hash_customer_password("test-password", iterations=100_000),
            }
        ]
    )
    settings = _strong_settings(
        monkeypatch,
        webviewer_remote_access_enabled=True,
        webviewer_remote_accounts_json=accounts,
    )
    settings.validate_production_security()


def test_production_missing_mes_credentials_raise(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = _strong_settings(monkeypatch, mes_callback_api_key="", mes_hmac_secret="")
    raised = False
    try:
        settings.validate_production_security()
    except RuntimeError as exc:
        raised = True
        message = str(exc)
        assert "MES_CALLBACK_API_KEY" in message
        assert "MES_HMAC_SECRET" in message
    assert raised


def test_production_llm_enabled_without_api_key_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    # 显式清空 LLM_API_KEY，模拟启用 LLM 但未配置 key
    monkeypatch.setenv(_ENV_KEY, "")
    settings = _strong_settings(monkeypatch=None, natural_query_llm_enabled=True)
    raised = False
    try:
        settings.validate_production_security()
    except RuntimeError as exc:
        raised = True
        assert "LLM_API_KEY" in str(exc)
    assert raised


def test_production_llm_enabled_with_api_key_passes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(_ENV_KEY, "sk-real-key")
    settings = _strong_settings(monkeypatch=None, natural_query_llm_enabled=True)
    settings.validate_production_security()  # 不抛异常即通过


def test_production_aggregates_all_problems_at_once(monkeypatch: pytest.MonkeyPatch) -> None:
    """多个问题应一次性收集，避免逐个修复后反复重启。"""
    monkeypatch.setenv(_ENV_KEY, "")
    settings = _strong_settings(
        monkeypatch=None,
        webviewer_context_secret="change-me",
        webviewer_allow_mock_context=True,
        mes_callback_api_key="",
        mes_hmac_secret="",
        natural_query_llm_enabled=True,
    )
    raised = False
    try:
        settings.validate_production_security()
    except RuntimeError as exc:
        raised = True
        message = str(exc)
        assert "WEBVIEWER_CONTEXT_SECRET" in message
        assert "WEBVIEWER_ALLOW_MOCK_CONTEXT" in message
        assert "MES_CALLBACK_API_KEY" in message
        assert "MES_HMAC_SECRET" in message
        assert "LLM_API_KEY" in message
    assert raised, "应聚合抛出包含全部问题的 RuntimeError"
