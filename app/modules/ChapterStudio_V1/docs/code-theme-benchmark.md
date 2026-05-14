# 코드 색상 벤치마크

## 기준

ChapterStudio_V1 데모의 fallback 하이라이트는 VS Code semantic token 분류를 기준으로 한다. 키워드, 클래스·타입, 함수·메서드, 변수·파라미터, 프로퍼티, 문자열, 숫자, 주석을 분리한다.

## 참고 테마

| 테마 | 관찰한 배치 | 반영 방식 |
|---|---|---|
| VS Code semantic token | `class`, `variable`, `parameter`, `property`, `function`, `keyword`, `number`, `string`, `comment`를 별도 토큰으로 본다. | fallback tokenizer의 공통 역할 이름으로 사용한다. |
| Dracula | keyword/storage는 pink, function은 green, class/type은 cyan, string은 yellow, number는 orange, comment는 muted 계열이다. | 역할 대비가 강한 팔레트 기준으로 삼는다. |
| One Dark Pro | 어두운 배경, keyword purple, function blue, class/type amber, string green, number orange 조합이 안정적이다. | 실제 코드 카드의 기본 색상 조합으로 채택한다. |
| GitHub VS Code Theme | keyword red, function purple, entity/variable orange, string blue, comment gray 구조다. | 변수와 함수의 구분 원칙을 참고한다. |
| Catppuccin Mocha | mauve, blue, green, peach, yellow, overlay 계열을 부드러운 대비로 쓴다. | comment와 보조 토큰을 과하지 않은 톤으로 보정한다. |

## 적용 팔레트

| 역할 | CSS 변수 | 색상 | 이유 |
|---|---|---|---|
| 배경 | `--code` | `#1B1E26` | 기존 ChapterStudio 어두운 코드면을 유지한다. |
| keyword | `--tok-keyword` | `#C678DD` | One Dark Pro 계열의 보라 키워드가 제어문을 빠르게 찾게 한다. |
| class/type | `--tok-class` | `#E5C07B` | 타입·클래스는 amber로 고정해 함수와 분리한다. |
| function | `--tok-fn` | `#61AFEF` | 함수 호출과 정의는 blue로 눈에 띄게 한다. |
| variable | `--tok-variable` | `#E06C75` | 변수명은 기본 텍스트보다 살짝 따뜻하게 분리한다. |
| parameter | `--tok-param` | `#D19A66` | 함수 입력값은 variable보다 약한 orange로 둔다. |
| property | `--tok-property` | `#56B6C2` | 객체 속성은 cyan으로 class/function과 분리한다. |
| string | `--tok-string` | `#98C379` | 문자열은 green으로 유지해 값 영역을 바로 찾는다. |
| number | `--tok-number` | `#D19A66` | 숫자는 parameter와 같은 orange 계열로 묶는다. |
| comment | `--tok-comment` | `#7F849C` | Catppuccin overlay 계열로 정보 우선순위를 낮춘다. |
| builtin | `--tok-builtin` | `#8BE9FD` | 내장 함수는 Dracula cyan 계열로 표시한다. |
| decorator | `--tok-decorator` | `#CBA6F7` | 데코레이터는 mauve italic으로 문법 장식을 드러낸다. |

## 언어별 fallback

| 언어 | 지원 토큰 |
|---|---|
| Python | keyword, class, function, decorator, builtin, variable, parameter, property, string, number, comment |
| JavaScript/TypeScript | keyword, class-like identifier, function call, variable, property, string, number, comment |
| SQL | keyword, aggregate builtin, identifier, number, string, comment |
| Java/Go/Rust/Kotlin | JavaScript/TypeScript와 같은 일반 문법 fallback을 사용한다. |

Shiki가 설치되어 있으면 Shiki 결과를 우선 사용한다. Shiki 또는 npx가 실패하면 위 fallback이 적용되어 원문을 잃지 않고 학습용 색상 구분을 유지한다.
