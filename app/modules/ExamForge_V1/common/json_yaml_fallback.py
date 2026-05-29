"""JSON 유사 YAML 파싱 보조 함수."""
from __future__ import annotations

from typing import Any


def parse_yaml_jsonish(text: str) -> Any | None:
    """JSON에 가까운 YAML을 마지막 수단으로 파싱한다."""
    try:
        import yaml
    except ImportError:
        return None
    try:
        data = yaml.safe_load(text)
    except (yaml.YAMLError, TypeError, ValueError):
        return None
    return data if isinstance(data, (dict, list)) else None
