# 시각 자료 사양(visual_spec) JSON 계약

LLM이 생성하는 JSON과 프론트엔드 렌더러가 기대하는 구조의 단일 진실 원천이다.
백엔드 Pydantic 모델, LLM 프롬프트 지시문, 프론트엔드 렌더러가 모두 이 문서를 기준으로 삼는다.

---

## 공통 규칙

- 모든 spec 모델은 미정의 필드를 **거부**한다 (`extra: "forbid"`).
- `spec_type` 값은 `visual_type`과 반드시 일치해야 한다 — discriminated union이 이를 강제한다.
- 엣지 필드는 JSON 키 `"from"`을 사용한다 (`"from_id"` 아님).
- 색상 값은 hex 형식 `#RRGGBB`만 허용한다.
- 레이더 차트 값 범위: 0–100 정수. `axes` 배열 길이와 `values` 배열 길이는 반드시 일치해야 한다.
- 트리 깊이는 렌더링 가독성을 위해 최대 3단계를 권장한다.

---

## 1. flowchart — 흐름도

```json
{
  "spec_type": "flowchart",
  "nodes": [
    {"id": "str (필수)", "label": "str (필수)", "x": "int (필수)", "y": "int (필수)"}
  ],
  "edges": [
    {"from": "str (필수, 출발 노드 id)", "to": "str (필수, 도착 노드 id)"}
  ]
}
```

예시:
```json
{
  "spec_type": "flowchart",
  "nodes": [
    {"id": "A", "label": "시작", "x": 100, "y": 50},
    {"id": "B", "label": "처리", "x": 100, "y": 200},
    {"id": "C", "label": "종료", "x": 100, "y": 350}
  ],
  "edges": [
    {"from": "A", "to": "B"},
    {"from": "B", "to": "C"}
  ]
}
```

---

## 2. bar_chart — 막대 차트

```json
{
  "spec_type": "bar_chart",
  "title": "str (필수)",
  "x_label": "str (필수)",
  "y_label": "str (필수)",
  "data": [
    {"label": "str (필수)", "value": "int (필수)", "color": "str hex (필수)"}
  ]
}
```

예시:
```json
{
  "spec_type": "bar_chart",
  "title": "월별 판매량",
  "x_label": "월",
  "y_label": "판매량 (개)",
  "data": [
    {"label": "1월", "value": 320, "color": "#4A90D9"},
    {"label": "2월", "value": 410, "color": "#E67E22"},
    {"label": "3월", "value": 290, "color": "#2ECC71"}
  ]
}
```

---

## 3. concept_map — 개념 맵

```json
{
  "spec_type": "concept_map",
  "nodes": [
    {"id": "str (필수)", "label": "str (필수)", "size": "int (필수, 노드 크기)"}
  ],
  "edges": [
    {"from": "str (필수)", "to": "str (필수)"}
  ]
}
```

예시:
```json
{
  "spec_type": "concept_map",
  "nodes": [
    {"id": "n1", "label": "광합성", "size": 40},
    {"id": "n2", "label": "빛에너지", "size": 28},
    {"id": "n3", "label": "포도당", "size": 28}
  ],
  "edges": [
    {"from": "n2", "to": "n1"},
    {"from": "n1", "to": "n3"}
  ]
}
```

---

## 4. mermaid — Mermaid 다이어그램

```json
{
  "spec_type": "mermaid",
  "diagram_type": "str (필수, 아래 허용값 중 하나)",
  "code": "str (필수, Mermaid DSL 전체 코드)"
}
```

`diagram_type` 허용값: `sequenceDiagram` | `flowchart` | `classDiagram` | `erDiagram` | `gantt`

예시:
```json
{
  "spec_type": "mermaid",
  "diagram_type": "sequenceDiagram",
  "code": "sequenceDiagram\n  Client->>Server: HTTP 요청\n  Server-->>Client: JSON 응답"
}
```

---

## 5. timeline — 타임라인

```json
{
  "spec_type": "timeline",
  "events": [
    {"year": "str (필수)", "event": "str (필수)", "detail": "str (필수)"}
  ]
}
```

`year` 필드는 문자열이다 — "1945년", "20세기 초" 같은 표현도 허용된다.

예시:
```json
{
  "spec_type": "timeline",
  "events": [
    {"year": "1876", "event": "전화기 발명", "detail": "알렉산더 그레이엄 벨이 최초로 특허 획득"},
    {"year": "1969", "event": "인터넷 전신 ARPANET 구축", "detail": "미국 국방부 주도로 4개 거점 연결"}
  ]
}
```

---

## 6. table — 테이블

```json
{
  "spec_type": "table",
  "title": "str (필수)",
  "headers": ["str (필수, 열 이름 배열)"],
  "rows": [["str (필수, 각 행의 셀 값 배열)"]]
}
```

`rows`의 각 배열 길이는 `headers` 길이와 일치해야 한다.

예시:
```json
{
  "spec_type": "table",
  "title": "운영체제 비교",
  "headers": ["항목", "Windows", "macOS", "Linux"],
  "rows": [
    ["라이선스", "유료", "무료", "무료"],
    ["오픈소스", "아니오", "부분", "예"],
    ["주요 용도", "업무·게임", "크리에이티브", "서버·개발"]
  ]
}
```

---

## 7. radar_chart — 레이더 차트

```json
{
  "spec_type": "radar_chart",
  "axes": ["str (필수, 축 이름 배열)"],
  "datasets": [
    {
      "label": "str (필수)",
      "values": ["int 0-100 (필수, axes와 동일 길이)"],
      "color": "str hex (필수)"
    }
  ]
}
```

예시:
```json
{
  "spec_type": "radar_chart",
  "axes": ["속도", "안정성", "보안", "확장성", "비용"],
  "datasets": [
    {"label": "서비스 A", "values": [80, 70, 90, 60, 50], "color": "#4A90D9"},
    {"label": "서비스 B", "values": [60, 85, 75, 80, 70], "color": "#E67E22"}
  ]
}
```

---

## 8. tree — 트리

```json
{
  "spec_type": "tree",
  "root": {
    "label": "str (필수)",
    "children": [
      {
        "label": "str (필수)",
        "children": []
      }
    ]
  }
}
```

`children`은 재귀 구조다. 리프 노드는 `"children": []`로 표기한다. 깊이는 최대 3단계를 권장한다.

예시:
```json
{
  "spec_type": "tree",
  "root": {
    "label": "동물",
    "children": [
      {
        "label": "포유류",
        "children": [
          {"label": "고래", "children": []},
          {"label": "박쥐", "children": []}
        ]
      },
      {
        "label": "조류",
        "children": [
          {"label": "독수리", "children": []}
        ]
      }
    ]
  }
}
```

---

## 9. comparison — 좌우 비교

```json
{
  "spec_type": "comparison",
  "left": {
    "title": "str (필수)",
    "points": ["str (필수, 항목 배열)"]
  },
  "right": {
    "title": "str (필수)",
    "points": ["str (필수, 항목 배열)"]
  }
}
```

예시:
```json
{
  "spec_type": "comparison",
  "left": {
    "title": "관계형 DB",
    "points": ["스키마 고정", "ACID 트랜잭션", "SQL 표준", "수직 확장 중심"]
  },
  "right": {
    "title": "NoSQL DB",
    "points": ["유연한 스키마", "최종 일관성 허용", "다양한 쿼리 방식", "수평 확장 용이"]
  }
}
```

---

## LLM 프롬프트 삽입 가이드

LLM에게 시각 자료 JSON을 생성하게 할 때 아래 패턴을 프롬프트에 삽입한다.

**삽입 위치**: 시스템 프롬프트 또는 유저 프롬프트의 출력 포맷 지시 섹션

**프롬프트 예시 (일부)**:
```
시각 자료는 반드시 아래 9종 타입 중 하나로 생성한다.
각 타입의 JSON 구조는 다음을 정확히 따른다. 정의되지 않은 필드는 절대 추가하지 않는다.

[flowchart]
{ "spec_type": "flowchart", "nodes": [{"id": "...", "label": "...", "x": 0, "y": 0}], "edges": [{"from": "...", "to": "..."}] }

[bar_chart]
{ "spec_type": "bar_chart", "title": "...", "x_label": "...", "y_label": "...", "data": [{"label": "...", "value": 0, "color": "#RRGGBB"}] }

(나머지 타입도 동일 방식으로 나열)

규칙:
- spec_type은 visual_type과 동일해야 한다.
- 엣지 키는 "from"을 쓴다 ("from_id" 금지).
- 색상은 #RRGGBB 형식만 허용한다.
- radar_chart의 values 길이는 axes 길이와 반드시 같아야 한다.
- tree의 리프 노드는 "children": []로 명시한다.
```

**검증 흐름**: LLM 출력 → `VisualSpecUnion` Pydantic 파싱 → 실패 시 에러 반환 (재생성 요청).
