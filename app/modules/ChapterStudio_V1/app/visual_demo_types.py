"""시각 비교 데모 데이터의 Pydantic 스키마."""
from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, Field, model_validator

from app.modules.ChapterStudio_V1.app.visual_demo_types_ext import (
    ComparisonSpec,
    RadarChartSpec,
    TableSpec,
    TimelineSpec,
    TreeSpec,
)


# ── 흐름도(Flowchart) 스키마 ──


class FlowchartNode(BaseModel):
    """흐름도 노드 하나를 표현한다."""

    id: str
    label: str
    # LLM이 비정상적으로 큰 좌표를 생성하면 SVG 렌더링이 깨지므로 범위를 제한한다.
    x: int = Field(ge=0, le=2000)
    y: int = Field(ge=0, le=2000)

    model_config = {"extra": "forbid"}


class FlowchartEdge(BaseModel):
    """흐름도 엣지 하나를 표현한다.

    JSON 직렬화 시 "from_id" 대신 Python 예약어가 아닌 "from" 키를 그대로 사용한다.
    """

    from_id: str = Field(alias="from")
    to: str

    # "from_id"로도, alias "from"으로도 모델을 생성할 수 있게 허용한다.
    # 정의되지 않은 추가 필드를 거부하여 Union 판별 모호성을 방지한다.
    model_config = {"populate_by_name": True, "extra": "forbid"}


class FlowchartSpec(BaseModel):
    """흐름도 전체 사양(노드 목록 + 엣지 목록)을 담는다."""

    # 판별자 필드 — discriminated union에서 이 타입을 식별한다.
    spec_type: Literal["flowchart"] = "flowchart"
    nodes: list[FlowchartNode]
    edges: list[FlowchartEdge]

    # Union 판별 시 BarChartSpec 전용 필드(title·data 등)를 거부하여 모호성을 제거한다.
    model_config = {"extra": "forbid"}


# ── 막대 차트(Bar Chart) 스키마 ──


class BarChartItem(BaseModel):
    """막대 차트의 항목 하나를 표현한다."""

    label: str
    # LLM이 75.5처럼 소수점 값을 생성하는 경우를 허용하기 위해 float도 수용함
    value: int | float
    # 유효한 hex 색상 코드만 허용한다 (#RGB ~ #RRGGBBAA).
    color: str = Field(pattern=r"^#[0-9A-Fa-f]{3,8}$")

    model_config = {"extra": "forbid"}


class BarChartSpec(BaseModel):
    """막대 차트 전체 사양을 담는다."""

    # 판별자 필드 — discriminated union에서 이 타입을 식별한다.
    spec_type: Literal["bar_chart"] = "bar_chart"
    title: str
    x_label: str
    y_label: str
    data: list[BarChartItem]

    # 정의되지 않은 추가 필드를 거부하여 Union 판별 모호성을 방지한다.
    model_config = {"extra": "forbid"}


# ── 개념 맵(Concept Map) 스키마 ──


class ConceptMapNode(BaseModel):
    """개념 맵 노드 하나를 표현한다."""

    id: str
    label: str
    size: int

    model_config = {"extra": "forbid"}


class ConceptMapEdge(BaseModel):
    """개념 맵 엣지 하나를 표현한다.

    JSON 직렬화 시 "from_id" 대신 "from" 키를 사용한다.
    """

    from_id: str = Field(alias="from")
    to: str

    # "from_id"로도, alias "from"으로도 모델을 생성할 수 있게 허용한다.
    # 정의되지 않은 추가 필드를 거부하여 Union 판별 모호성을 방지한다.
    model_config = {"populate_by_name": True, "extra": "forbid"}


class ConceptMapSpec(BaseModel):
    """개념 맵 전체 사양(노드 목록 + 엣지 목록)을 담는다."""

    # 판별자 필드 — discriminated union에서 이 타입을 식별한다.
    spec_type: Literal["concept_map"] = "concept_map"
    nodes: list[ConceptMapNode]
    edges: list[ConceptMapEdge]

    # 정의되지 않은 추가 필드를 거부하여 Union 판별 모호성을 방지한다.
    model_config = {"extra": "forbid"}


# ── Mermaid 다이어그램 스키마 ──


class MermaidSpec(BaseModel):
    """Mermaid 다이어그램 사양을 담는다. LLM이 텍스트로 생성한 다이어그램 코드."""

    # 판별자 필드 — discriminated union에서 이 타입을 식별한다.
    spec_type: Literal["mermaid"] = "mermaid"
    diagram_type: str  # 예: "flowchart", "sequenceDiagram", "classDiagram", "erDiagram"
    code: str  # Mermaid DSL 코드 문자열

    # 정의되지 않은 추가 필드를 거부하여 Union 판별 모호성을 방지한다.
    model_config = {"extra": "forbid"}


# ── 슬라이드 및 응답 스키마 ──

# 9종 시각 사양을 spec_type 필드로 판별하는 Annotated 타입 별칭.
VisualSpecUnion = Annotated[
    FlowchartSpec
    | BarChartSpec
    | ConceptMapSpec
    | MermaidSpec
    | TimelineSpec
    | TableSpec
    | RadarChartSpec
    | TreeSpec
    | ComparisonSpec,
    Field(discriminator="spec_type"),
]


class VisualSlide(BaseModel):
    """시각 슬라이드 하나를 담는다."""

    slide_idx: int
    title: str
    visual_type: str
    visual_spec: VisualSpecUnion
    voice_script: str

    # 엄격한 검증을 위해 정의되지 않은 추가 필드를 거부한다.
    model_config = {"extra": "forbid"}

    @model_validator(mode="after")
    def _check_type_match(self) -> "VisualSlide":
        """visual_type과 visual_spec.spec_type의 일치를 보장한다."""
        if self.visual_type != self.visual_spec.spec_type:
            msg = f"visual_type={self.visual_type!r} ≠ spec_type={self.visual_spec.spec_type!r}"
            raise ValueError(msg)
        return self


class NoteBlock(BaseModel):
    """강의 노트 카드 하나(태그·본문)를 담는다."""

    tag: str
    body: str

    model_config = {"extra": "forbid"}


class VisualPreviewResponse(BaseModel):
    """시각 미리보기 API 최상위 응답 객체를 표현한다."""

    topic: str
    # LLM이 빈 슬라이드 목록을 반환하는 것을 방지한다.
    visual_slides: list[VisualSlide] = Field(min_length=1)
    note_blocks: list[NoteBlock]

    # 엄격한 검증을 위해 정의되지 않은 추가 필드를 거부한다.
    model_config = {"extra": "forbid"}
