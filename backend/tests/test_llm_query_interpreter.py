from app.services.llm_query_interpreter import _parse_interpretation, _system_prompt


def test_parse_interpretation_preserves_part_domain_and_timestamp_intent() -> None:
    result = _parse_interpretation(
        """
        {"canonicalPrompt":"今天新增的有哪些","domain":"part","confidence":0.9,"wantsTimestamp":true,"warnings":[]}
        """
    )

    assert result is not None
    assert "零件" in result["canonicalPrompt"]
    assert "具体时间戳" in result["canonicalPrompt"]
    assert result["confidence"] == 0.9


def test_parse_interpretation_rejects_oversized_prompt() -> None:
    result = _parse_interpretation(
        '{"canonicalPrompt":"' + ("x" * 241) + '","domain":"product","confidence":0.9}'
    )

    assert result is None


def test_system_prompt_requires_preserving_requested_fields() -> None:
    prompt = _system_prompt()

    assert "不要省略用户要求返回的信息或字段" in prompt
    assert "库存" in prompt
