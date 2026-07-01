import pandas as pd

from edusci.analysis.engine_v2 import analyze_questionnaire
from edusci.analysis.provenance import classify_dataset_origin


def test_filename_marks_simulated_dataset_and_never_real_source() -> None:
    assert classify_dataset_origin("ai心理健康问卷_模拟答案_120份.csv") == "synthetic_demo"
    assert classify_dataset_origin("survey.csv") == "unknown"
    assert classify_dataset_origin("survey.csv", "real_collected") == "real_collected"


def test_questionnaire_analysis_builds_scales_reliability_and_inferential_correlation() -> None:
    frame = pd.DataFrame(
        {
            "Q3_AI焦虑1": [1, 2, 2, 3, 4, 4, 5, 5],
            "Q4_AI焦虑2": [1, 2, 3, 3, 4, 5, 4, 5],
            "Q5_自我效能1": [5, 5, 4, 4, 3, 3, 2, 1],
            "Q6_自我效能2": [5, 4, 4, 3, 3, 2, 2, 1],
        }
    )
    questionnaire = {
        "variable_item_map": {
            "AI焦虑得分": ["Q3", "Q4"],
            "技术自我效能": ["Q5", "Q6"],
        }
    }

    result = analyze_questionnaire(frame, questionnaire)

    assert set(result["derived_scales"]) == {"AI焦虑得分", "技术自我效能"}
    assert result["reliability"]["AI焦虑得分"]["cronbach_alpha"] > 0.7
    finding = result["correlation_tests"][0]
    assert finding["n"] == 8
    assert finding["p_value"] is not None
    assert len(finding["confidence_interval_95"]) == 2
