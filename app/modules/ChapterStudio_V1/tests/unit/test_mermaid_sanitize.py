from __future__ import annotations

from app.modules.ChapterStudio_V1.postprocess.mermaid_cli import (
    _sanitize_mermaid_edge_labels,
    _sanitize_mermaid_labels,
    _sanitize_mermaid_source,
)


def test_nested_square_brackets_become_parentheses() -> None:
    source = "graph TD\n B[스택: [1, 2, 3]] --> C[스택: [1, 2]]"

    sanitized = _sanitize_mermaid_labels(source)

    assert "[1, 2, 3]" not in sanitized
    assert "[1, 2]" not in sanitized
    assert "(1, 2, 3)" in sanitized
    assert "(1, 2)" in sanitized
    assert "]]" not in sanitized


def test_unquoted_colon_label_is_quoted() -> None:
    sanitized = _sanitize_mermaid_labels("graph TD\nA[초기 상태: 빈 스택]")

    assert 'A["초기 상태: 빈 스택"]' in sanitized


def test_already_quoted_label_is_unchanged() -> None:
    source = 'graph TD\nA["x"]'

    assert _sanitize_mermaid_labels(source) == source


def test_plain_edge_is_unchanged() -> None:
    source = "graph TD\nA --> B"

    assert _sanitize_mermaid_labels(source) == source


def test_edge_label_text_is_unchanged() -> None:
    source = "graph TD\nA -->|B[값: 1]| C[끝]"

    assert _sanitize_mermaid_labels(source) == source


def test_edge_label_arrow_is_replaced_but_connector_is_preserved() -> None:
    source = "graph TD\nA -->|pop() -> 3| B"

    sanitized = _sanitize_mermaid_edge_labels(source)

    assert "A -->|pop() → 3| B" in sanitized
    assert "A -->|" in sanitized
    assert "|pop() -> 3|" not in sanitized


def test_edge_label_variants_replace_reserved_arrows() -> None:
    source = "graph LR\nA ---|push() -> top| B\nB -.->|peek() -> 1| C"

    sanitized = _sanitize_mermaid_edge_labels(source)

    assert "A ---|push() → top| B" in sanitized
    assert "B -.->|peek() → 1| C" in sanitized


def test_node_and_edge_labels_are_sanitized_together() -> None:
    source = "graph TD\nA[스택: [1, 2, 3]] -->|pop() -> 3| B[결과: (3)]"

    sanitized = _sanitize_mermaid_source(source)

    assert 'A["스택: (1, 2, 3)"] -->|pop() → 3| B["결과: (3)"]' in sanitized
    assert "]]" not in sanitized
    assert "|pop() -> 3|" not in sanitized


def test_mermaid_source_sanitize_is_idempotent() -> None:
    source = "graph TD\nA[스택: [1, 2]] -->|pop() -> 2| B[결과: (2)]"

    sanitized = _sanitize_mermaid_source(source)

    assert _sanitize_mermaid_source(sanitized) == sanitized
