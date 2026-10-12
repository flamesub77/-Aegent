# CLAUDE.md

냉연강판 재질 편차 대시보드 + 원인분석 에이전트 (Streamlit + OpenAI Responses API).
재질(YS/TS/EL/BH, r̄·n·Δr) 편차와 원인 인자를 대시보드로 보여주고, 에이전트가 질문을 해석해 대시보드 조건을 바꾸고 원인을 설명한다.

- 요구사항: v1 = [prd.md](prd.md), v2(현재 작업 기준) = [prd_v2.md](prd_v2.md)
- 단계별 개발 프롬프트: [prompts.md](prompts.md), [prompts_v2.md](prompts_v2.md)
- 도메인 지식: [files/knowledge_base.md](files/knowledge_base.md)

## 명령어

```bash
pip install -r requirements.txt
streamlit run app.py                    # 앱 실행
python -m pytest                        # 테스트 (API 키 불필요, 외부 통신 없음)
python -m pytest tests/test_v2.py -k rbar   # 단일 테스트
python -m eval.run_scenarios            # 시나리오 S1~S6 평가 (API 사용) → eval/results.md, results.json
python -m eval.check_v1_compat <v1 스냅샷 폴더>   # 데이터 재생성 후 v1 컬럼·정답지 불변 확인
```

환경변수는 `.env` (`.env.example` 참고): `OPENAI_API_KEY`, `OPENAI_MODEL`(기본 gpt-5.5), `OPENAI_REASONING_EFFORT`, `MAX_AGENT_TURNS`, `APP_MODE`(auto | agent | offline).

## 구조

| 경로 | 역할 |
| --- | --- |
| `app.py` | Streamlit 대시보드 + 에이전트 패널 |
| `config.py` | 환경변수, 경로, `BLOCKED_FILES`, `APP_MODE` |
| `agent/agent.py` | OpenAI Responses API function calling 루프 (openai는 지연 import) |
| `agent/router.py` | 에이전트 ↔ 오프라인 분기, 실패 시 오프라인 대체 |
| `agent/offline.py` | API 없이 동작하는 규칙 기반 질문 해석기 |
| `agent/prompts.py` | 시스템 프롬프트 (데이터 설명은 현재 데이터 소스에서 생성) |
| `agent/report.py` | 도구 출력 → 구조화 결과(판정·원인 순위·차트·본문) |
| `tools/datasource.py` | 샘플(steel.db) / 업로드 데이터를 같은 인터페이스로 제공. `get_source()`, `use_source()` |
| `tools/analysis.py` | 분석 엔진 (분포 진단, 인자 비교, 결함 추적, 인사이트) |
| `tools/coil_lookup.py` | 코일·슬라브 단건 분석 (시생산 vs 양산 비교) |
| `tools/domain.py` | 인자 이름·단위, 영향 방향, 메커니즘, 제어 조치 |
| `tools/narrative.py`, `tools/terms.py` | 인사이트 문체(easy/expert/stat)와 용어 대응표 |
| `tools/upload.py` | CSV/Excel 업로드, 컬럼 매핑, 인코딩(cp949) 처리 |
| `tools/charts.py` | Plotly 차트 |
| `tools/dashboard_state.py` | 대시보드 상태와 변경 검증 (사이드바·에이전트 공용) |
| `tools/registry.py` | 에이전트 도구 스키마와 실행 (`run_tool`) |
| `tools/db.py`, `tools/guard.py` | steel.db 읽기 전용 접근, 평가용 파일 차단 |
| `ui/` | v2 3단계 화면 모듈 (업로드 단계 화면, 코일 단건, 에이전트 대화, 공통 배지). 아직 `app.py`에 연결 전 |
| `eval/` | 시나리오 평가, v1 호환 확인 |
| `tests/` | pytest (`test_v2.py`가 v2 기능, `fixtures/`에 업로드 테스트 파일) |
| `files/` | 샘플 데이터(steel.db, csv/xlsx), 지식베이스, 평가용 정답 파일 |
| `files/coil data(pds).xlsx` | 회사 업로드 양식(165열: 제강→연주→열연→냉연)에 가상 데이터 500행. `python files/make_pds_sample.py`로 재생성 |

## 반드시 지킬 규칙

- **평가용 파일 격리**: `files/anomaly_scenarios.md`, `files/answer_key.csv`, `files/trial_key.csv`, `files/generate_data.py`는 앱·에이전트·도구 코드에서 읽지 않는다 (`config.BLOCKED_FILES`, `tools/guard.py`). 정답지를 읽는 곳은 `eval/run_scenarios.py`뿐이다.
- **수치는 분석 엔진이 계산하고, LLM은 해석과 서술만** 한다. 프롬프트나 에이전트 출력에서 수치를 만들어내게 하지 않는다.
- **v1 호환 유지**: 샘플 데이터의 기존 컬럼 값과 S1~S6 정답은 바뀌면 안 된다. `generate_data.py`에 컬럼을 추가할 때는 별도 난수 시드로 기존 생성이 끝난 뒤 만든다.
- **오프라인 모드는 외부 통신 0건**. `openai`가 설치되지 않은 PC에서도 앱이 떠야 하므로 openai import는 필요한 곳에서만 한다.
- **고정값 하드코딩 금지**: 기간, 강종, 라인 목록은 현재 데이터 소스에서 읽는다 (업로드 데이터로 교체될 수 있음). 공정인자 컬럼이 없으면 에러 없이 건너뛴다.
- **용어는 `tools/terms.py` 한 곳에서** 관리한다. 화면·인사이트·프롬프트·리포트는 직접 문자열을 쓰지 말고 이것을 참조한다 (예: "이탈군" → "문제 코일", "교란 요인" → "비교 조건 차이"). 통계 문체에서만 기존 통계 용어를 쓴다.
- 업로드 파일은 메모리·로컬 임시파일에만 두고 외부로 보내지 않는다.
- r̄ = (r0 + 2·r45 + r90) / 4, Δr = (r0 − 2·r45 + r90) / 2 는 입력받지 않고 계산한다.
- 코일 단건 분석에서 양산 비교값은 **중앙값**과 MAD 기반 z다. "평균"이라고 쓰지 않는다.

## 스타일

- 코드 주석·docstring·UI 문구는 한국어.
- 차트 색상: 상향 = 주황, 하향 = 파랑, 중립 비교군 = 슬레이트, 기준 = 연회색, 스펙선·결함 = 빨강. 차트 배경은 투명 (라이트/다크 테마는 `.streamlit/config.toml`).
- 테스트는 API 키 없이 돌아가야 한다. 기능을 바꾸면 `python -m pytest`로 회귀를 확인한다.

## 현재 단계

v2 2단계(R1~R5 기능)까지 완료, 3단계(UI 디자인, [prompts_v2.md](prompts_v2.md))를 진행 중이다.
남은 일: `ui/` 모듈을 `app.py`에 연결, R6 용어 화면 전면 적용, 방향별 r값 차트, Playwright 화면 점검(`review/screenshots/v2_*`).
`app.py`의 "3단계에서 다듬는다" 주석이 남은 곳이 미완성 부분이다.

## 참고

- GitHub: https://github.com/flamesub77/-Aegent (기본 브랜치 `main`)
- `.env`(API 키)는 절대 커밋하지 않는다. 보고서 `*.docx`, `files.zip`, 하위 사본 폴더 `미니 프로젝트/`, `review/screenshots/`도 저장소에서 제외한다 (`.gitignore`).
- 하위 `미니 프로젝트/` 폴더는 예전 사본이다. 코드는 최상위 폴더 기준으로 수정한다.
