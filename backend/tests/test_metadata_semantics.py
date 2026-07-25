from app.services.metadata_semantics import (
    fallback_layout_semantic_profile,
    parse_layout_semantic_profile,
    semantic_concept_field,
)


def test_fallback_parts_semantics_marks_created_by_unavailable() -> None:
    profile = fallback_layout_semantic_profile(
        layout="Parts",
        fields=[
            {"name": "Date Created", "result": "date"},
            {"name": "part_number"},
            {"name": "stock_on_hand_qty"},
        ],
        sample_records=[
            {
                "Date Created": "07/06/2026",
                "part_number": "AL0812-016-PS",
                "stock_on_hand_qty": "12",
            }
        ],
    )

    assert profile["sampleRecordCount"] == 1
    assert set(profile["fields"]) == {"Date Created", "part_number", "stock_on_hand_qty"}
    assert profile["fields"]["stock_on_hand_qty"]["sampleValues"] == ["12"]
    assert semantic_concept_field(profile, "createdDate") == "Date Created"
    assert semantic_concept_field(profile, "stock") == "stock_on_hand_qty"
    assert semantic_concept_field(profile, "price") == ""
    assert semantic_concept_field(profile, "createdBy") == ""
    assert profile["concepts"]["price"]["available"] is False
    assert profile["concepts"]["createdBy"]["available"] is False


def test_parse_semantics_rejects_hallucinated_field_name() -> None:
    profile = parse_layout_semantic_profile(
        """
        {
          "concepts": {
            "createdBy": {
              "field": "Created By",
              "label": "创建人",
              "confidence": 0.9,
              "reason": "looks right"
            }
          }
        }
        """,
        layout="Parts",
        fields=[{"name": "Date Created"}, {"name": "part_number"}],
        sample_records=[{"Date Created": "07/06/2026", "part_number": "A-1"}],
    )

    assert profile is not None
    assert set(profile["fields"]) == {"Date Created", "part_number"}
    assert semantic_concept_field(profile, "createdBy") == ""


def test_parse_semantics_keeps_llm_field_analysis_for_existing_field() -> None:
    profile = parse_layout_semantic_profile(
        """
        {
          "fields": {
            "part_number": {
              "semanticLabel": "零件编号",
              "businessConcepts": ["partNumber"],
              "description": "唯一零件编号",
              "likelyContains": "零件料号",
              "confidence": 0.95
            }
          },
          "concepts": {
            "partNumber": {
              "field": "part_number",
              "label": "零件编号",
              "confidence": 0.95,
              "reason": "字段名和样本值匹配"
            }
          }
        }
        """,
        layout="Parts",
        fields=[{"name": "part_number", "result": "text"}],
        sample_records=[{"part_number": "AL0812-016-PS"}],
    )

    assert profile is not None
    assert profile["fields"]["part_number"]["semanticLabel"] == "零件编号"
    assert profile["fields"]["part_number"]["sampleValues"] == ["AL0812-016-PS"]
    assert semantic_concept_field(profile, "partNumber") == "part_number"
