"""시각 데모 Pydantic 스키마 단위 테스트.

참고: build_visual_preview 통합 테스트(test_preview_*)와
직렬화 라운드트립 테스트(test_serialization_roundtrip)는 LLM 생성이
비결정적이므로 제거함. 스키마 검증 단위 테스트만 유지한다.
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.modules.ChapterStudio_V1.app.visual_demo_types import (
    BarChartItem,
    BarChartSpec,
    ConceptMapEdge,
    ConceptMapNode,
    ConceptMapSpec,
    FlowchartEdge,
    FlowchartNode,
    FlowchartSpec,
    MermaidSpec,
    NoteBlock,
    VisualPreviewResponse,
    VisualSlide,
)
from app.modules.ChapterStudio_V1.app.visual_demo_types_ext import (
    ComparisonSpec,
    RadarChartSpec,
    RadarDataset,
    TableSpec,
    TimelineSpec,
    TreeNode,
    TreeSpec,
)

# ── 판별 유니온 역직렬화 테스트 ──

# (spec_type 값, 딕셔너리 페이로드, 예상 클래스) 목록
_UNION_CASES: list[tuple[str, dict, type]] = [
    (
        "flowchart",
        {
            "spec_type": "flowchart",
            "nodes": [{"id": "A", "label": "시작", "x": 0, "y": 0}],
            "edges": [{"from": "A", "to": "A"}],
        },
        FlowchartSpec,
    ),
    (
        "bar_chart",
        {
            "spec_type": "bar_chart",
            "title": "제목",
            "x_label": "X",
            "y_label": "Y",
            "data": [{"label": "항목", "value": 1, "color": "#000"}],
        },
        BarChartSpec,
    ),
    (
        "concept_map",
        {
            "spec_type": "concept_map",
            "nodes": [{"id": "n1", "label": "노드", "size": 20}],
            "edges": [{"from": "n1", "to": "n1"}],
        },
        ConceptMapSpec,
    ),
    (
        "mermaid",
        {"spec_type": "mermaid", "diagram_type": "flowchart", "code": "graph LR\nA-->B"},
        MermaidSpec,
    ),
    (
        "timeline",
        {
            "spec_type": "timeline",
            "events": [{"year": "2024", "event": "출시", "detail": "상세"}],
        },
        TimelineSpec,
    ),
    (
        "table",
        {
            "spec_type": "table",
            "title": "표",
            "headers": ["A", "B"],
            "rows": [["1", "2"]],
        },
        TableSpec,
    ),
    (
        "radar_chart",
        {
            "spec_type": "radar_chart",
            "axes": ["축1", "축2"],
            "datasets": [{"label": "L", "values": [50, 80], "color": "#FFF"}],
        },
        RadarChartSpec,
    ),
    (
        "tree",
        {"spec_type": "tree", "root": {"label": "루트", "children": []}},
        TreeSpec,
    ),
    (
        "comparison",
        {
            "spec_type": "comparison",
            "left": {"title": "좌", "points": ["a"]},
            "right": {"title": "우", "points": ["b"]},
        },
        ComparisonSpec,
    ),
]


@pytest.mark.parametrize("spec_type,payload,expected_cls", _UNION_CASES, ids=[c[0] for c in _UNION_CASES])
def test_discriminated_union_parses_correct_class(
    spec_type: str, payload: dict, expected_cls: type
) -> None:
    """spec_type 값에 따라 올바른 사양 클래스로 역직렬화되는지 검증한다."""
    slide = VisualSlide(
        slide_idx=0,
        title="테스트",
        visual_type=spec_type,
        visual_spec=payload,
        voice_script="스크립트",
    )
    assert isinstance(slide.visual_spec, expected_cls)


def test_discriminated_union_unknown_spec_type_raises() -> None:
    """알 수 없는 spec_type 값은 ValidationError를 발생시켜야 한다."""
    with pytest.raises(ValidationError):
        VisualSlide(
            slide_idx=0,
            title="테스트",
            visual_type="unknown",
            visual_spec={"spec_type": "nonexistent", "data": "x"},
            voice_script="스크립트",
        )


# ── extra=forbid 검증 ──

@pytest.mark.parametrize(
    "spec_cls,valid_kwargs,extra_field",
    [
        (
            FlowchartSpec,
            {"nodes": [], "edges": []},
            {"title": "침입 필드"},  # BarChartSpec의 필드
        ),
        (
            ConceptMapSpec,
            {"nodes": [], "edges": []},
            {"data": []},  # BarChartSpec의 필드
        ),
        (
            BarChartSpec,
            {"title": "t", "x_label": "x", "y_label": "y", "data": []},
            {"nodes": []},  # FlowchartSpec의 필드
        ),
        (
            MermaidSpec,
            {"diagram_type": "flowchart", "code": "A"},
            {"extra_key": "값"},
        ),
        (
            TimelineSpec,
            {"events": []},
            {"title": "침입"},
        ),
        (
            TableSpec,
            {"title": "표", "headers": [], "rows": []},
            {"nodes": []},
        ),
        (
            RadarChartSpec,
            {"axes": [], "datasets": []},
            {"extra_field": 1},
        ),
        (
            TreeSpec,
            {"root": {"label": "루트", "children": []}},
            {"extra_key": "x"},
        ),
        (
            ComparisonSpec,
            {
                "left": {"title": "좌", "points": []},
                "right": {"title": "우", "points": []},
            },
            {"extra_key": "x"},
        ),
    ],
    ids=[
        "flowchart_extra",
        "concept_map_extra",
        "bar_chart_extra",
        "mermaid_extra",
        "timeline_extra",
        "table_extra",
        "radar_chart_extra",
        "tree_extra",
        "comparison_extra",
    ],
)
def test_extra_forbid_rejects_unknown_fields(
    spec_cls: type, valid_kwargs: dict, extra_field: dict
) -> None:
    """extra='forbid' 설정이 미정의 필드를 거부하는지 검증한다."""
    with pytest.raises(ValidationError):
        spec_cls(**valid_kwargs, **extra_field)


# ── alias 직렬화 검증 ──

def test_flowchart_edge_alias_dump() -> None:
    """FlowchartEdge.model_dump(by_alias=True)가 'from' 키를 사용하는지 검증한다."""
    edge = FlowchartEdge(from_id="A", to="B")
    dumped = edge.model_dump(by_alias=True)
    assert dumped == {"from": "A", "to": "B"}
    assert "from_id" not in dumped


def test_concept_map_edge_alias_dump() -> None:
    """ConceptMapEdge.model_dump(by_alias=True)가 'from' 키를 사용하는지 검증한다."""
    edge = ConceptMapEdge(from_id="n1", to="n2")
    dumped = edge.model_dump(by_alias=True)
    assert dumped == {"from": "n1", "to": "n2"}
    assert "from_id" not in dumped


def test_flowchart_edge_construction_via_alias() -> None:
    """alias 'from'으로 FlowchartEdge를 생성할 수 있어야 한다."""
    edge = FlowchartEdge(**{"from": "X", "to": "Y"})
    assert edge.from_id == "X"
    assert edge.to == "Y"


def test_concept_map_edge_construction_via_alias() -> None:
    """alias 'from'으로 ConceptMapEdge를 생성할 수 있어야 한다."""
    edge = ConceptMapEdge(**{"from": "m1", "to": "m2"})
    assert edge.from_id == "m1"


# ── spec_type 기본값 검증 ──

@pytest.mark.parametrize(
    "spec_cls,init_kwargs,expected_type",
    [
        (FlowchartSpec, {"nodes": [], "edges": []}, "flowchart"),
        (BarChartSpec, {"title": "t", "x_label": "x", "y_label": "y", "data": []}, "bar_chart"),
        (ConceptMapSpec, {"nodes": [], "edges": []}, "concept_map"),
        (MermaidSpec, {"diagram_type": "flowchart", "code": "A"}, "mermaid"),
        (TimelineSpec, {"events": []}, "timeline"),
        (TableSpec, {"title": "표", "headers": [], "rows": []}, "table"),
        (RadarChartSpec, {"axes": [], "datasets": []}, "radar_chart"),
        (TreeSpec, {"root": {"label": "루트", "children": []}}, "tree"),
        (
            ComparisonSpec,
            {
                "left": {"title": "좌", "points": []},
                "right": {"title": "우", "points": []},
            },
            "comparison",
        ),
    ],
    ids=["flowchart", "bar_chart", "concept_map", "mermaid", "timeline", "table", "radar_chart", "tree", "comparison"],
)
def test_spec_type_default(spec_cls: type, init_kwargs: dict, expected_type: str) -> None:
    """각 사양 클래스의 spec_type 기본값이 올바른지 검증한다."""
    spec = spec_cls(**init_kwargs)
    assert spec.spec_type == expected_type


# ── TreeNode 재귀 구조 검증 ──

def test_tree_node_recursive_parse() -> None:
    """TreeNode가 중첩 children 구조를 올바르게 파싱하는지 검증한다."""
    node = TreeNode(
        label="루트",
        children=[
            TreeNode(label="1차", children=[TreeNode(label="2차")]),
        ],
    )
    assert node.children[0].label == "1차"
    assert node.children[0].children[0].label == "2차"


def test_tree_node_empty_children() -> None:
    """children이 없는 리프 노드는 빈 리스트를 갖는지 검증한다."""
    node = TreeNode(label="리프")
    assert node.children == []


def test_tree_node_dump_structure() -> None:
    """TreeNode.model_dump()가 올바른 중첩 구조를 반환하는지 검증한다."""
    node = TreeNode(label="루트", children=[TreeNode(label="자식")])
    dumped = node.model_dump()
    assert dumped == {"label": "루트", "children": [{"label": "자식", "children": []}]}


# ── visual_type / spec_type 불일치 검증 ──


def test_visual_type_spec_type_mismatch_raises() -> None:
    """visual_type과 spec_type이 불일치하면 ValidationError가 발생해야 한다."""
    with pytest.raises(ValidationError):
        VisualSlide(
            slide_idx=0,
            title="불일치",
            visual_type="table",
            visual_spec={"spec_type": "flowchart", "nodes": [], "edges": []},
            voice_script="스크립트",
        )


# ── 하위 모델 extra=forbid 검증 ──


@pytest.mark.parametrize(
    "model_cls,valid_kwargs,extra",
    [
        (FlowchartNode, {"id": "A", "label": "노드", "x": 0, "y": 0}, {"color": "red"}),
        (BarChartItem, {"label": "항목", "value": 1, "color": "#000"}, {"extra": 1}),
        (ConceptMapNode, {"id": "n1", "label": "노드", "size": 20}, {"weight": 5}),
        (NoteBlock, {"tag": "핵심", "body": "내용"}, {"extra": "x"}),
    ],
    ids=["flowchart_node", "bar_chart_item", "concept_map_node", "note_block"],
)
def test_child_models_reject_extra_fields(
    model_cls: type, valid_kwargs: dict, extra: dict
) -> None:
    """하위 모델도 미정의 필드를 거부해야 한다."""
    with pytest.raises(ValidationError):
        model_cls(**valid_kwargs, **extra)


# ── spec_type 누락 검증 ──


def test_spec_type_missing_raises() -> None:
    """spec_type이 누락된 페이로드는 ValidationError를 발생시켜야 한다."""
    with pytest.raises(ValidationError):
        VisualSlide(
            slide_idx=0,
            title="테스트",
            visual_type="flowchart",
            visual_spec={"nodes": [], "edges": []},
            voice_script="스크립트",
        )


# ── P2-4: FlowchartNode 좌표 범위 제한 검증 ──


@pytest.mark.parametrize(
    "x,y",
    [(-1, 0), (0, -1), (2001, 0), (0, 2001), (3000, 3000)],
    ids=["x_negative", "y_negative", "x_over", "y_over", "both_over"],
)
def test_flowchart_node_rejects_out_of_bounds_coords(x: int, y: int) -> None:
    """FlowchartNode는 0~2000 범위를 벗어난 좌표를 거부해야 한다."""
    with pytest.raises(ValidationError):
        FlowchartNode(id="A", label="노드", x=x, y=y)


def test_flowchart_node_accepts_boundary_coords() -> None:
    """FlowchartNode는 경계값(0, 2000)을 허용해야 한다."""
    node = FlowchartNode(id="A", label="노드", x=0, y=2000)
    assert node.x == 0
    assert node.y == 2000


# ── P2-5: 색상 형식 검증 ──


@pytest.mark.parametrize(
    "invalid_color",
    ["not-a-color", "red", "rgb(0,0,0)", "#GGG", "#12", "000000"],
    ids=["word", "named_color", "rgb_func", "invalid_hex", "too_short", "no_hash"],
)
def test_bar_chart_item_rejects_invalid_color(invalid_color: str) -> None:
    """BarChartItem은 유효하지 않은 hex 색상 형식을 거부해야 한다."""
    with pytest.raises(ValidationError):
        BarChartItem(label="항목", value=1, color=invalid_color)


def test_bar_chart_item_accepts_valid_colors() -> None:
    """BarChartItem은 유효한 hex 색상 코드를 허용해야 한다."""
    # 3자리, 6자리, 8자리 hex 모두 허용됨
    for color in ("#FFF", "#000000", "#FF000080"):
        item = BarChartItem(label="항목", value=1, color=color)
        assert item.color == color


@pytest.mark.parametrize(
    "invalid_color",
    ["not-a-color", "blue", "#ZZZ"],
    ids=["word", "named_color", "invalid_hex"],
)
def test_radar_dataset_rejects_invalid_color(invalid_color: str) -> None:
    """RadarDataset은 유효하지 않은 hex 색상 형식을 거부해야 한다."""
    with pytest.raises(ValidationError):
        RadarDataset(label="L", values=[50], color=invalid_color)


def test_radar_dataset_accepts_valid_color() -> None:
    """RadarDataset은 유효한 hex 색상 코드를 허용해야 한다."""
    ds = RadarDataset(label="L", values=[50], color="#ABC")
    assert ds.color == "#ABC"


# ── P2-6: VisualPreviewResponse 빈 슬라이드 목록 거부 검증 ──


def test_visual_preview_response_rejects_empty_slides() -> None:
    """VisualPreviewResponse는 빈 visual_slides 목록을 거부해야 한다."""
    with pytest.raises(ValidationError):
        VisualPreviewResponse(
            topic="주제",
            visual_slides=[],
            note_blocks=[],
        )


def test_visual_preview_response_accepts_one_slide() -> None:
    """VisualPreviewResponse는 최소 1개의 슬라이드를 허용해야 한다."""
    resp = VisualPreviewResponse(
        topic="주제",
        visual_slides=[
            VisualSlide(
                slide_idx=0,
                title="테스트",
                visual_type="flowchart",
                visual_spec={
                    "spec_type": "flowchart",
                    "nodes": [{"id": "A", "label": "시작", "x": 0, "y": 0}],
                    "edges": [],
                },
                voice_script="스크립트",
            )
        ],
        note_blocks=[],
    )
    assert len(resp.visual_slides) == 1


# ── P2-7: TreeSpec 깊이 제한 검증 ──


def _build_deep_tree(depth: int) -> dict:
    """지정된 깊이의 트리 딕셔너리를 생성한다."""
    node: dict = {"label": f"depth_{depth}", "children": []}
    for d in range(depth - 1, 0, -1):
        node = {"label": f"depth_{d}", "children": [node]}
    return node


def test_tree_spec_rejects_depth_over_10() -> None:
    """TreeSpec은 깊이가 10을 초과하는 트리를 거부해야 한다."""
    deep_root = _build_deep_tree(11)
    with pytest.raises(ValidationError, match="트리 깊이가 10을 초과합니다"):
        TreeSpec(root=deep_root)


def test_tree_spec_accepts_depth_10() -> None:
    """TreeSpec은 깊이가 정확히 10인 트리를 허용해야 한다."""
    root = _build_deep_tree(10)
    spec = TreeSpec(root=root)
    assert spec.root.label == "depth_1"
