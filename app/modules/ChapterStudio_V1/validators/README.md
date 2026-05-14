# validators

## 모듈 목적
슬라이드와 산출물의 규칙 위반 여부를 검증한다.

## IN·OUT
IN은 생성 또는 후처리된 산출물이며 OUT은 통과 여부와 오류 목록이다.

## 환경변수
해당 없음.

## 의존성
`common.errors`에 의존한다.

## 사용 예시
```python
passed = True
```

## 에러 정책
규칙 위반은 `ValidationFailedError`로 표현한다.
