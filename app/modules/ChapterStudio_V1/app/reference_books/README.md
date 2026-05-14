# Reference Books

사용자 참고도서 PDF를 OCR한 뒤, 강의 생성에 필요한 page-anchored 발췌만 전달하는 모듈이다.

- 입력: OCR 파이프라인 결과의 `pages/page_results` 또는 벤치마크 JSONL의 `page/text`
- 처리: page 단위 lexical retrieval, top-k 발췌
- 출력: `ReferenceBookContext`
- 사용처: 암기노트, 과제, 음성대본, Codex 생성 프롬프트

이 모듈은 참고도서가 있을 때만 동작한다. OCR 결과가 없거나 매칭 발췌가 없으면 빈 컨텍스트를 반환하고 기존 ChapterStudio 생성 흐름은 그대로 유지한다.
