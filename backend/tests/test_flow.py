import pytest

from edusci.domain.flow import (
    FlowStage,
    InvalidTransition,
    ResearchRoute,
    ResearchScores,
    determine_route,
    transition_stage,
)


@pytest.mark.parametrize(
    ("information", "researchability", "expected"),
    [
        (70, 70, ResearchRoute.A),
        (69, 90, ResearchRoute.B),
        (90, 69, ResearchRoute.C),
        (40, 30, ResearchRoute.D),
    ],
)
def test_four_quadrant_route_uses_inclusive_seventy_threshold(
    information: int, researchability: int, expected: ResearchRoute
) -> None:
    assert determine_route(ResearchScores(information, researchability)) is expected


def test_route_scores_reject_out_of_range_values() -> None:
    with pytest.raises(ValueError, match="0 到 100"):
        ResearchScores(information_sufficiency=101, researchability=50)


def test_flow_allows_declared_transition() -> None:
    assert transition_stage(FlowStage.IDEA, FlowStage.EVIDENCE) is FlowStage.EVIDENCE


def test_flow_rejects_skipping_human_gate() -> None:
    with pytest.raises(InvalidTransition, match="不允许"):
        transition_stage(FlowStage.EVIDENCE, FlowStage.ANALYSIS)

