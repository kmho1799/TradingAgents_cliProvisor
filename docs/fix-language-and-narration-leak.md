# 수정 설계: 출력 언어 불일치 + 에이전트 narration 누출

작성일: 2026-06-02
근거 샘플: `reports/ORCL_20260602_133219/complete_report.md`

---

## 1. 문제 정의

한국어를 선택해도 보고서 일부가 (a) 영어로 나오고, (b) 에이전트 내부 동작 설명("I will check the directory...")이 섞여 나온다.

이 둘은 **서로 다른 원인의 별개 결함**이다. 하나를 고쳐도 다른 하나는 그대로 남는다.

### 결함 A — 출력 언어 불일치
선택 언어가 일부 파트에 적용되지 않아 영어로 출력된다.

### 결함 B — narration 누출
에이전트의 중간 tool-use 서술이 최종 보고서 본문에 그대로 박힌다.

---

## 2. 샘플 관측 (ORCL)

| # | 파트 | 에이전트 | 언어 | narration 누출 |
|---|------|---------|------|---------------|
| I | Analysts | market / social / news / fundamentals | 한국어 ✅ | 없음 |
| II | Research | Bull / Bear / Manager | 영어 ❌ | Bull에서 발생 (L259-364) |
| III | Trading | Trader | 영어 ❌ | 없음 |
| IV | Risk | Aggressive / Conservative / Neutral | 영어 ❌ | 없음 |
| V | Portfolio | Portfolio Manager | 한국어 ✅ | 없음 |

누출 예시 (`complete_report.md:259-364`):
```
Bull Analyst: I will check the directory contents...
I will list the current permissions...
I will view the tradingagents/graph/reflection.py file...
```
+ 아티팩트 링크 `file:///C:/Users/kmho1/.gemini/antigravity-cli/brain/.../orcl_bull_thesis.md`

---

## 3. 근본 원인 분석

### 결함 A: 언어 지시문 누락

`get_language_instruction()` ([agent_utils.py:23](../tradingagents/agents/utils/agent_utils.py)) 은
영어가 아니면 `" Write your entire response in {lang}."` 를 반환한다.

이 함수는 **6개 에이전트에만** 호출됨:
- analysts 4종 + portfolio_manager

**미적용 7개 에이전트** (→ 영어 출력):

| 에이전트 | 파일 |
|---------|------|
| bull_researcher | `tradingagents/agents/researchers/bull_researcher.py` |
| bear_researcher | `tradingagents/agents/researchers/bear_researcher.py` |
| research_manager | `tradingagents/agents/managers/research_manager.py` |
| trader | `tradingagents/agents/trader/trader.py` |
| aggressive_debator | `tradingagents/agents/risk_mgmt/aggressive_debator.py` |
| conservative_debator | `tradingagents/agents/risk_mgmt/conservative_debator.py` |
| neutral_debator | `tradingagents/agents/risk_mgmt/neutral_debator.py` |

`agent_utils.py:27-28` docstring에 의도적 설계가 명시돼 있음:
> Internal debate agents stay in English for reasoning quality.

즉 결함 A는 **부분적으로 의도된 동작**이다 (§5의 제품 결정 필요).

**적용 범위**: 모든 provider 공통 (프롬프트 텍스트 문제).

### 결함 B: invoke() vs bind_tools() 추출 비대칭

핵심: analysts가 깨끗한 이유는 **언어 지시문 때문이 아니라 출력 추출 경로가 다르기 때문**이다.

`cli_client.py` 의 두 경로:

1. **bind_tools() 경로** (analysts 사용)
   `_parse_tool_response` → `_loads_json_object` ([cli_client.py:260-274](../tradingagents/llm_clients/cli_client.py))
   `{...}` 만 `find("{")`/`rfind("}")` 로 **외과적 추출** → 주변 narration 폐기.

2. **invoke() 경로** (7개 직접 호출 에이전트 사용)
   `AIMessage(content=result.text)` ([cli_client.py:74](../tradingagents/llm_clients/cli_client.py))
   CLI stdout 원문을 **그대로** content로 사용 → 추출/필터 없음.

agy는 agentic CLI(Antigravity)다. PTY stdout 전체를 캡처([agy_runtime.py:42-44](../tradingagents/ai_runtime/providers/agy_runtime.py))하므로 중간 서술 + 최종 답변이 한 덩어리가 된다. invoke() 경로는 이를 거르지 않는다.

**결론**: 결함 B는 agy 전용도, 7개 에이전트 문제도 아니다. **CLI/agentic provider의 direct-invoke 경로 1곳** 문제다.

**적용 범위**: CLI provider (claude-cli / codex-cli / agy-cli) 만 해당. API provider(openai/anthropic/google)는 무관 (narration 자체가 없음).

---

## 4. 두 결함의 독립성 (중요)

- 7개 에이전트에 언어 지시문을 추가해도 → **narration 누출은 그대로 남는다.**
- direct-invoke 추출을 고쳐도 → **언어는 그대로 영어다.**

따라서 두 수정은 독립적으로 적용·검증한다.

---

## 4-2. 결함 A 해결: 두 가지 아키텍처

언어를 맞추는 방법은 근본적으로 둘이다. **하나만 택한다.**

### 방식 I — 에이전트 지시 (네이티브 생성)
각 에이전트 프롬프트에 `get_language_instruction()` 추가 → 모델이 처음부터 선택 언어로 생성.

### 방식 T — 저장 시 번역 패스
에이전트는 영어로 두고, `save_report_to_disk` ([cli/main.py:640](../cli/main.py)) 에서 각 섹션 문자열을 선택 언어로 번역 후 기록.

### 비교

| 항목 | 방식 I (에이전트 지시) | 방식 T (저장 시 번역) |
|------|----------------------|---------------------|
| 수정 위치 | 에이전트 7개 | `save_report_to_disk` 1곳 (+LLM 핸들 배선) |
| 숫자 정합성 | **안전** (tool 데이터→해당 언어 1회 생성) | **위험** — 2차 전사, 58k 토큰 긴 문맥에서 숫자 무음 변형($248.15→$248.50) |
| 추가 LLM 호출 | 없음 | 섹션당 호출 (비용·지연) |
| 영어 추론 트레이스 | 불가 (전부 선택 언어) | **가능** — 하위폴더/토론 영어 + 최종 한국어 |
| docstring 의도 | 폐기 | 보존 (토론 영어 유지) |
| agy 신뢰성 | 무관 | **번역도 agy 거치면 오염** → 깨끗한 API 모델로 고정 필요 |

### 결정적 고려
- **숫자 정합성이 지배 제약**. 트레이딩 도구에서 가장 중요한 축에서 번역 방식이 더 위험. 네이티브 생성은 숫자 오염 표면이 더 작음.
- 번역 방식은 "숫자 보존" 프롬프트 + **프로그램적 숫자 집합 일치 검사**로 완화 가능하나 제거는 불가.

### 핵심 갈림 질문
> **영어 추론 트레이스(감사 이력)를 보존하고 최종만 번역?** → 방식 T
> **전부 선택 언어로, 가장 싸고 숫자 안전?** → 방식 I

> **권장: 방식 I** — 단, 영어 트레이스 가치 있으면 방식 T.
> **주의**: 번역은 narration 누출(B)의 해결책이 **아니다**. B를 "번역하며 빼라" 로 풀면 구조적 해결을 번역기 판단(확률적)으로 후퇴시키고, 영어 원본 `bull.md`도 오염된 채 남음. **B는 어느 방식이든 추출 계층에서 별도 수정** (§4-1, §결정 2). B를 source에서 고치면 `bull_history`가 깨끗 → 하위폴더 파일 + 번역 입력 둘 다 깨끗 (직교·합성).

---

## 5. 제품 결정 사항 (코드 작성 전 확정 필요)

### 결정 1 — 언어 방식 + 적용 범위
먼저 §4-2에서 방식 I vs T 택1. 방식 I 채택 시 적용 범위 추가 택1
(docstring "토론 에이전트는 추론 품질 위해 영어 유지" 는 의도된 prior):

- **(A) 전체 7개 적용** — 모든 파트 한국어 일관. docstring 의도 폐기.
- **(B) 최종 출력 파트만** — trader 최종 제안 + research_manager 결정만 한국어, 토론 본문(bull/bear/risk)은 영어 유지.

> **권장: 방식 I + (A)**. 사용자 불만은 "선택 언어가 안 지켜진다" 이므로 일관성·숫자 안전 우선. docstring도 함께 갱신.
> 방식 T 채택 시 범위 결정은 무의미(전체 번역).

### 결정 2 — narration 누출 수정 메커니즘 (열린 문제)
analyst 추출이 깨끗한 건 프롬프트가 JSON 객체를 강제하기 때문. 긴 자유형식 마크다운 보고서를 JSON으로 감싸는 건 이스케이프/절단 위험으로 부적절.

핵심 미해결 질문: **agentic CLI에서 자유형식 출력의 "최종 답변만" 깨끗이 얻는 법?**

후보 (우선순위순):
1. **agy 플래그 조사** — 비-agentic / quiet / output-format 옵션 존재 여부 먼저 확인. 있으면 가장 견고.
2. **구분자 프로토콜** — 프롬프트로 `<<<FINAL>>> ... <<<END>>>` 출력 요구 후 그 사이만 추출. agy가 지시를 지킬 때만 동작.
3. **narration 휴리스틱 제거** — `"I will ..."`, `file:///...brain/...` 라인 패턴 제거. 취약, 최후 수단.

> 1번 조사 결과 없이는 B 수정 확정 불가. 조사 → 결정.

---

## 6. 수정 계획

### Phase 1 — 언어 (결함 A)

**방식 I 채택 시** (저위험, 권장):
1. 7개 에이전트 프롬프트 문자열 끝에 `get_language_instruction()` 결과 추가.
   - import 추가: `from tradingagents.agents.utils.agent_utils import get_language_instruction`
   - bull/bear/research_manager/aggressive/conservative/neutral: f-string 프롬프트 말미에 연결.
   - trader: system 메시지 `content` 말미에 연결.
2. `agent_utils.py:27-28` docstring 의도 문구 갱신 (전체 적용으로 변경됨 명시).

**방식 T 채택 시** (중위험):
1. `save_report_to_disk` 에 LLM 핸들 배선 (현재 없음). agy-cli provider면 **깨끗한 API 모델로 고정**.
2. 섹션별 문자열을 번역 함수 통과 후 기록. 프롬프트에 "모든 숫자/티커/날짜 원문 보존" 명시.
3. **프로그램적 숫자 집합 일치 검사** 추가 (원문 vs 번역문 숫자 추출 비교, 불일치 시 경고/원문 유지).
4. 영어 원본 하위폴더 파일은 그대로, `complete_report.md` 만 번역 (또는 양쪽 분리 저장).

### Phase 2 — narration 누출 (결함 B, 조사 선행)
1. agy CLI 출력 옵션 조사 (결정 2 후보 1).
2. 채택 메커니즘을 `cli_client.py` invoke()/`_run` 경로 또는 `agy_runtime` 출력 후처리에 1곳 구현.
3. claude-cli / codex-cli 도 동일 경로 사용하므로 공통 적용 확인.

---

## 7. 검증 (경험적 필수)

문제를 경험적으로 발견했으므로 수정도 경험적으로 확인한다. 가정 금지.

1. 동일 종목 보고서 재생성.
2. **결함 A**: 파트 II/III/IV 본문이 한국어인지 확인.
   - 주의: agy는 agentic이라 "한국어로 답해" 지시를 무시할 수 있음. 영어로 계속 나오면 지시문 위치(프롬프트 앞으로 이동) 또는 강도 강화 필요.
3. **결함 B**: `"I will "`, `file:///...brain/` 패턴이 보고서에서 사라졌는지 grep 확인.
4. 두 항목 독립 확인 (하나만 고쳐지고 다른 건 남을 수 있음).

---

## 8. 요약

| 결함 | 원인 | 해결 방식 | 위험 | 선행 작업 |
|------|------|----------|------|----------|
| A. 언어 | 지시문 누락 | I:에이전트 지시(권장) / T:저장 시 번역 | I=낮음 / T=중간(숫자) | 결정 1 (I vs T) |
| B. 누출 | direct-invoke 추출 없음 (CLI provider만) | 추출 계층 1곳 수정 | 중간 | 결정 2 + agy 플래그 조사 |

A·B는 **직교**. B를 source(추출 계층)에서 고치면 방식 I·T 어느 쪽과도 깨끗이 합성됨.
