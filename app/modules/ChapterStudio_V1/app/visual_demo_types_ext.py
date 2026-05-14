"""확장 시각 자료 Pydantic 스키마 — 타임라인·테이블·레이더·트리·비교 5종."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator


# ── 타임라인 스키마 ──


class TimelineEvent(BaseModel):
    """타임라인 이벤트 하나를 표현한다."""

    year: str
    event: str
    detail: str

    model_config = {"extra": "forbid"}


class TimelineSpec(BaseModel):
    """타임라인 시각 사양을 담는다."""

    spec_type: Literal["timeline"] = "timeline"
    events: list[TimelineEvent]

    model_config = {"extra": "forbid"}


# ── 테이블 스키마 ──


class TableSpec(BaseModel):
    """테이블 시각 사양을 담는다."""

    spec_type: Literal["table"] = "table"
    title: str
    headers: list[str]
    rows: list[list[str]]

    model_config = {"extra": "forbid"}

    @model_validator(mode="after")
    def _check_row_width(self) -> "TableSpec":
        """모든 행의 열 수가 헤더 열 수와 일치하는지 검증한다."""
        expected = len(self.headers)
        for i, row in enumerate(self.rows):
            if len(row) != expected:
                msg = f"rows[{i}] 열 수 {len(row)} ≠ headers 열 수 {expected}"
                raise ValueError(msg)
        return self


# ── 레이더 차트 스키마 ──


class RadarDataset(BaseModel):
    """레이더 차트 데이터셋 하나를 표현한다."""

    label: str
    # LLM이 소수점 값을 생성하는 경우를 허용하기 위해 float도 수용함
    values: list[int | float]
    # 유효한 hex 색상 코드만 허용한다 (#RGB ~ #RRGGBBAA).
    color: str = Field(pattern=r"^#[0-9A-Fa-f]{3,8}$")

    model_config = {"extra": "forbid"}


class RadarChartSpec(BaseModel):
    """레이더 차트 시각 사양을 담는다."""

    spec_type: Literal["radar_chart"] = "radar_chart"
    axes: list[str]
    datasets: list[RadarDataset]

    model_config = {"extra": "forbid"}

    @model_validator(mode="after")
    def _check_axes_match(self) -> "RadarChartSpec":
        """모든 데이터셋의 값 수가 축 수와 일치하는지 검증한다."""
        expected = len(self.axes)
        for ds in self.datasets:
            if len(ds.values) != expected:
                msg = f"dataset {ds.label!r} 값 수 {len(ds.values)} ≠ axes 수 {expected}"
                raise ValueError(msg)
        return self


# ── 트리 스키마 ──


class TreeNode(BaseModel):
    """트리 노드 하나(재귀 구조)를 표현한다."""

    label: str
    # 재귀 참조이므로 기본값을 빈 리스트로 설정한다.
    children: list[TreeNode] = Field(default_factory=list)

    model_config = {"extra": "forbid"}



class TreeSpec(BaseModel):
    """트리 시각 사양을 담는다."""

    spec_type: Literal["tree"] = "tree"
    root: TreeNode

    model_config = {"extra": "forbid"}

    @model_validator(mode="after")
    def _check_depth(self) -> "TreeSpec":
        """트리 깊이가 10을 초과하면 스택 오버플로를 방지하기 위해 거부한다."""

        def _measure(node: TreeNode, depth: int = 1) -> int:
            if not node.children:
                return depth
            return max(_measure(c, depth + 1) for c in node.children)

        if _measure(self.root) > 10:
            raise ValueError("트리 깊이가 10을 초과합니다")
        return self


# ── 좌우 비교 스키마 ──


class ComparisonSide(BaseModel):
    """비교 차트의 한쪽(좌 또는 우)을 표현한다."""

    title: str
    points: list[str]

    model_config = {"extra": "forbid"}


class ComparisonSpec(BaseModel):
    """좌우 비교 시각 사양을 담는다."""

    spec_type: Literal["comparison"] = "comparison"
    left: ComparisonSide
    right: ComparisonSide

    model_config = {"extra": "forbid"}
