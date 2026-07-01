from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class ResearchRoute(StrEnum):
    A = "A"
    B = "B"
    C = "C"
    D = "D"


@dataclass(frozen=True, slots=True)
class ResearchScores:
    information_sufficiency: int
    researchability: int

    def __post_init__(self) -> None:
        for value in (self.information_sufficiency, self.researchability):
            if not 0 <= value <= 100:
                raise ValueError("评分必须在 0 到 100 之间")


def determine_route(scores: ResearchScores, threshold: int = 70) -> ResearchRoute:
    information_high = scores.information_sufficiency >= threshold
    researchability_high = scores.researchability >= threshold
    if information_high and researchability_high:
        return ResearchRoute.A
    if not information_high and researchability_high:
        return ResearchRoute.B
    if information_high and not researchability_high:
        return ResearchRoute.C
    return ResearchRoute.D


class FlowStage(StrEnum):
    IDEA = "S0_IDEA"
    EVIDENCE = "S1_EVIDENCE"
    GATE = "S2_GATE"
    DESIGN = "S3_DESIGN"
    WAITING_FOR_DATA = "WAITING_FOR_DATA"
    ANALYSIS = "S4_ANALYSIS"
    REPORT = "S5_REPORT"
    REVIEW = "S6_REVIEW"
    COMPLETED = "COMPLETED"
    BLOCKED = "BLOCKED"
    FAILED = "FAILED"


class InvalidTransition(ValueError):
    pass


_ALLOWED: dict[FlowStage, set[FlowStage]] = {
    FlowStage.IDEA: {FlowStage.EVIDENCE, FlowStage.FAILED},
    FlowStage.EVIDENCE: {FlowStage.GATE, FlowStage.FAILED},
    FlowStage.GATE: {FlowStage.DESIGN, FlowStage.FAILED},
    FlowStage.DESIGN: {
        FlowStage.WAITING_FOR_DATA,
        FlowStage.ANALYSIS,
        FlowStage.REPORT,
        FlowStage.FAILED,
    },
    FlowStage.WAITING_FOR_DATA: {FlowStage.ANALYSIS, FlowStage.FAILED},
    FlowStage.ANALYSIS: {FlowStage.REPORT, FlowStage.FAILED},
    FlowStage.REPORT: {FlowStage.REVIEW, FlowStage.FAILED},
    FlowStage.REVIEW: {
        FlowStage.REPORT,
        FlowStage.COMPLETED,
        FlowStage.BLOCKED,
        FlowStage.FAILED,
    },
    FlowStage.COMPLETED: set(),
    FlowStage.BLOCKED: {FlowStage.REPORT},
    FlowStage.FAILED: set(),
}


def transition_stage(current: FlowStage, target: FlowStage) -> FlowStage:
    if target not in _ALLOWED[current]:
        raise InvalidTransition(f"不允许从 {current.value} 跳转到 {target.value}")
    return target

