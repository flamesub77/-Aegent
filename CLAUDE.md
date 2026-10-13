# CLAUDE.md

강종 품질 현황 대시보드 + AI 분석 도우미 (Streamlit + OpenAI·Claude·Gemini 중 선택, 오프라인 해석기). v2까지 이름은 "냉연강판 재질 편차 대시보드".
재질(YP/TS/EL/BH, r̄·n)의 SPEC·평균·편차·생산량을 그래프로 보여주고, 원인 인자를 순위화하며, 에이전트가 질문을 해석해 대시보드 조건을 바꾸고 원인을 설명한다.

- 요구사항: v1 = [prd.md](prd.md), v2 = [prd_v2.md](prd_v2.md), v3 = [prd_v3.md](prd_v3.md), v4 = [prd_v4.md](prd_v4.md), v5 = [prd_v5.md](prd_v5.md), v6 = [prd_v6.md](prd_v6.md), v7 = [prd_v7.md](prd_v7.md), **v8(구현된 기준) = [prd_v8.md](prd_v8.md)**
  - v3는 v2를 덮어쓴다: 문체 3종(R5)과 Δr 폐기, 회사 양식 `coil data(pds).xlsx`를 표준 데이터 구조로 사용
- 단계별 개발 프롬프트: [prompts.md](prompts.md), [prompts_v2.md](prompts_v2.md), [prompts_v3.md](prompts_v3.md)
- 도메인 지식: [files/knowledge_base.md](files/knowledge_base.md)

## 명령어

```bash
pip install -r requirements.txt
streamlit run app.py                    # 앱 실행 (8501을 다른 프로그램이 쓰면 --server.port 8502)
python -m pytest                        # 테스트 (API 키 불필요, 외부 통신 없음)
python -m pytest tests/test_v2.py -k pds   # 단일 테스트
python -m eval.model_compare            # 원인 순위 모델 5종 × S1~S6 (API 불필요) → eval/model_results.md
python -m eval.run_scenarios            # 에이전트로 S1~S6 평가 (OpenAI API 사용, 비용 발생) → eval/results.md
pip install anthropic google-genai      # (선택) AI 모드에서 Claude·Gemini 쓰기
python files/make_pds_sample.py [저장 경로]   # 샘플(회사 양식) 재생성. 엑셀로 열려 있으면 저장 실패
python -m pip wheel . --no-deps -w dist # PC 설치용 패키지 → pip install 후 `steel-dashboard`
```

환경변수 `.env` (`.env.example` 참고): `OPENAI_API_KEY`, `OPENAI_MODEL`(기본 gpt-5.5), `OPENAI_REASONING_EFFORT`, `MAX_AGENT_TURNS`,
`ANTHROPIC_API_KEY`, `ANTHROPIC_MODEL`(기본 claude-sonnet-5-5), `GEMINI_API_KEY`, `GEMINI_MODEL`(배포 시 지정), `AI_PROVIDER`(기본 openai),
`APP_MODE`(ai | offline, v4 값 auto·agent는 ai), `ALLOW_SHARED_KEY`(.env 키 허용, 기본 true), `STEEL_SAMPLE_XLSX`(샘플 파일 경로 바꾸기),
`STEEL_DASHBOARD_HOME`(사용자 폴더, 기본 `~/.steel_dashboard`: 캐시·매핑·설치 후 `.env`).

## 구조

| 경로 | 역할 |
| --- | --- |
| `app.py` | 화면 구성: 왼쪽 📂·★·🔎, 맨 위 고정 상단바(탭 · AI 보고서 · ◐·🔑·AI 스위치·🔗), 제목 + 조건 칩, 탭별 그래프 카드(이모지 결론 제목+(?) → 고정 높이 그래프 → 해석 한 줄). 강종개요 카드 클릭 = 오른쪽 큰 그래프(`gk_card`·`pc_card`) |
| `config.py` | 환경변수, 경로, `BLOCKED_FILES`, `APP_MODE`, API 키 선택(`resolve_api_key`)·가리기(`mask_key`) |
| `launcher.py`, `pyproject.toml`, `run.bat` | PC 설치 배포. 설치 시 평평한 폴더를 `steel_dashboard` 패키지로 묶고 그 폴더에서 `streamlit run app.py` |
| `ui/header.py` | 상단바 도구 `toolbar()`: ◐ 테마 · 🔑 AI 키(OpenAI·Claude·Gemini 탭, 거부된 키 표시) · AI on/off 스위치(app.py `mode_switch`) · 🔗 링크 |
| `ui/ai.py` | 오프라인/AI 모드, 쓸 AI(제공자)·제공자별 키·모델 (세션 메모리) |
| `ui/session.py` | 새로 고침 유지: 필터는 URL 쿼리, 대화·업로드·API 키는 `sid`별 서버 메모리(8시간) |
| `ui/theme.py` | 테마(embed_options 링크 방식), Plotly 템플릿으로 차트 출력(`show`), 공통 CSS(🤖 아이콘·팝업 위치·빨간 카드) |
| `ui/chat.py` | 🤖 떠 있는 아이콘 → `st.dialog` 팝업. 답한 뒤 앱 전체를 다시 그리고 팝업을 다시 연다 |
| `ui/coil_view.py`, `ui/upload_wizard.py`, `ui/common.py` | 코일분석(조건 카드 ① 코일 ② 비교 양산: 기간·같은 라인/공장/두께 pills·SS/CT 허용폭 드롭다운 → **분석 실행** 버튼, 재질 위치 + ⚙️ 공정 위치 그래프 6개), 업로드(회사 양식이면 매핑 건너뜀), 배지 |
| `ui/datasets.py`, `ui/favorites.py` | 데이터 파일 목록·전환(기본 파일 + 올린 파일), 필터 즐겨찾기 (사용자 폴더) |
| `ui/report.py`, `tools/report_ppt.py` | 🤖 AI 보고서: 항목 체크리스트 → 미리보기 → `files/PPT 양식.pptx`로 PPT (장수 제한 없음, 한 장에 그래프 2개, KPI 타일·쪽 번호). AI 모드면 문장을 AI가 씀 |
| `tools/spc.py` | EWMA·CUSUM 재질 조기 감시 (기준 = 직전 6개월, EWMA는 3점 연속일 때 경보). `PRESETS` 추천 조건 3종: 보통(기본)·둔감(헛경보 줄이기)·민감(작은 변화도 빨리) |
| `static/HDharmony-*.ttf` | 현대하모니 L·M·B (원본 `files/현대하모니+L·M·B.ttf`). `.streamlit/config.toml` fontFaces로 등록 |
| `agent/agent.py`, `agent/router.py` | OpenAI 함수 호출 루프 / 모드(ai·offline)·제공자 선택, 실패 시 오프라인 대체 |
| `agent/providers/` | 제공자 어댑터: OpenAI(agent.py 사용) · Claude(Messages API 직접 루프, fallbacks) · Gemini(google-genai). SDK는 필요할 때만 import |
| `agent/offline.py`, `agent/prompts.py`, `agent/report.py` | 규칙 기반 질문 해석기, 시스템 프롬프트, 구조화 결과 |
| `tools/pds.py` | 회사 양식 읽기: 블록 위치로 같은 이름 열 구분, SPEC("185~265", "34↑") 파싱, 추가 열, 강종 단위 SPEC·지시값 |
| `tools/datasource.py` | 샘플(회사 양식 xlsx → 사용자 캐시 pickle) / 업로드 데이터를 같은 인터페이스로. `get_source()`, `use_source()` |
| `tools/analysis.py` | 분석 엔진 (분포 진단, 인자 비교, 결함 추적, 연도별 생산량). 필터는 `where={컬럼: [값]}` |
| `tools/ranking.py` | 원인 순위 모델 5종(effect·spearman·rf·gbm·lasso), 같은 결과 형식(`score`·`rank`). 화면 첫 값 `START`=lasso(다중회귀), 계산 불가 시 `DEFAULT`=effect |
| `tools/narrative.py`, `tools/terms.py` | 쉬운 말 문장, 그래프 카드 문구(`note_*`), 용어 (style 인자는 호환용·무시) |
| `tools/domain.py` | 인자 이름·단위·공정(회사 양식 인자 포함), 야금 원리, 제어 조치 |
| `tools/charts.py` | Plotly 차트 (파랑 계열, 연도별 생산량 포함) |
| `tools/dashboard_state.py` | 필터·화면 상태와 변경 검증 (화면·에이전트·오프라인 공용). `subset_args()`가 두께·시편 위치·코드 필터 |
| `tools/upload.py`, `coil_lookup.py`, `registry.py`, `db.py`, `guard.py` | 업로드 매핑·검증, 단일 코일(`same_ss`·`same_ct` = True(기본 ±10·±20℃) 또는 허용폭 숫자, 30개 미만이면 CT→SS→두께→공장→라인→기간 순 완화), 에이전트 도구, steel.db 읽기, 정답지 차단 |
| `eval/` | 시나리오 평가, 모델 비교(`model_compare.py`), v1 호환 확인 |
| `tests/` | pytest (`test_v2.py` 끝부분이 v3: pds·결측 30%·필터·모델·API 키·카드 문구) |
| `files/coil data(pds).xlsx` | 샘플 = 회사 양식 가상 데이터 2019~2026년 29,800코일, 13강종·4라인·3공장·결함 7종 (2026년 값은 v1 샘플 그대로) |
| `files/grade_family.csv` | 강종 → 계열(IF·BH·LC·HSLA·DP·TRIP·MART)·이름 (steel.db grade_master 보충) |
| `files/` 기타 | `steel.db`(grade_master, v1 평가), `use_codes.csv`(용도코드표), 지식베이스, 평가용 정답 파일 |

## 반드시 지킬 규칙

- **평가용 파일 격리**: `files/anomaly_scenarios.md`, `files/answer_key.csv`, `files/trial_key.csv`, `files/generate_data.py`는 앱·에이전트·도구 코드에서 읽지 않는다 (`config.BLOCKED_FILES`, `tools/guard.py`). 정답은 `eval/`만 읽는다. 데이터 생성 스크립트(`files/make_pds_sample.py`)만 생성 모델로 `generate_data.py`를 불러온다. 배포 패키지에도 넣지 않는다.
- **수치는 분석 엔진이 계산하고, LLM은 해석과 서술만** 한다.
- **S1~S6 유지**: 샘플의 2026년 값과 정답은 바뀌면 안 된다. 평가 기준 모델("차이 크기", `ranking.DEFAULT`)은 S1~S4 1순위 4/4, S5·S6 결함 추적 1순위를 유지한다 (`eval.model_compare`).
- **오프라인 모드는 외부 통신 0건**. `app.py`·`ui/`에 `import openai`·`anthropic`·`google.genai`를 넣지 않는다 (SDK 없는 PC에서도 떠야 함). AI 보고서도 분석 요약만 보낸다(원본 행 X).
- **고정값 하드코딩 금지**: 기간, 강종, 라인, 코드 목록은 현재 데이터 소스에서 읽는다. 컬럼이 없으면 에러 없이 건너뛴다.
- **회사 양식은 블록 위치로 읽는다**. 같은 이름의 열(`Heat번호`, `두께`, `YP`)은 공정 블록마다 반복된다. 재질·SPEC·제품 값은 냉연 블록. 양식에 없는 항목(합금화 온도, 냉연 결함 등)은 맨 뒤 추가 열(`tools/pds.EXTRA`).
- **결측치로 멈추지 않는다**. 필수 열(냉연코일번호, 생산일자, 냉연규격, 라인)이 빈 행만 빼고, 값이 있는 코일만 쓴다. 값이 10개 미만인 인자는 순위에서 빼고 `insufficient`로 알린다.
- **문장은 쉬운 말 하나**. 전문가·통계 문체를 다시 만들지 않는다. 통계 수치(σ, 효과크기, p값)는 표·툴팁·도움말에만.
- **용어·도움말은 `tools/terms.py` 한 곳에서** (예: 이탈군 → 문제 코일, 교란 요인 → 비교 조건 차이, 계보 → 공정 순서, 균열온도 → 소둔온도). 항복강도는 화면에서 YP, 내부 코드는 YS.
  카드 (?)는 `CARD_HELP`, 강종개요 구역은 `SECTIONS`, 탭 설명은 `DESC`, 이모지는 `EMOJI` (한 제목에 하나, 같은 뜻은 같은 이모지).
- **탭 이름(v5)**: 강종개요·공정분석·결함분석·코일분석·데이터 (`ds.VIEWS`). 옛 이름(재질 현황·원인 분석·표면결함·단일 코일 분석·Raw Data)은 `VIEW_ALIASES`로 받는다.
- **Δr은 삭제**됐다. r̄은 데이터 `r-bar` 값, 비어 있으면 (r0 + 2·r45 + r90) / 4.
- **AI 키(3개 제공자)와 업로드 원본·데이터 수정본**은 서버 메모리에만 (수정본은 "이 PC에 보관"을 켤 때만 사용자 폴더). 파일·로그·URL·리포트·에러 메시지에 남기지 않고, 화면에는 앞 3자리·뒤 4자리만.
- **원인 순위 모델은 같은 결과 형식**. 트리 모델은 `random_state` 고정, 표본 30개·인자 3개 미만이면 "차이 크기"로 돌아간다.
- **재질(v6)**: 사람이 고르지 않는다. 고정 순서 `domain.PROP_ORDER`(YS·TS·EL·n_value·r0·r45·r90·rbar·BH) 중 값이 있는 재질을 모두 보여준다.
  `prop`은 공정분석·조기 감시 기준(기본 TS). `props` 상태는 에이전트·URL 호환용으로만 남아 있다. 내부 코드는 YS, 화면은 YP.
- **불량률(v6)**: 강종개요·고정카드는 σ가 아니라 SPEC 밖 비율(`analysis.defect_rate`, 5% 이상 강조). σ는 공정분석에서만, 공정분석은 `basis`(sigma 기본 | spec)로 고르고 스펙 불량이 5개 미만이면 σ로 돌아간다.
- **규격약호(v4)**: `spec_cols`(압연·정정 함께) + `specs` 값은 `roll:코드`/`fin:코드`. 두 열은 OR (`where["__any__"]`).
- **문제 코일 기준(v4)**: `sigma` 기본 1.0 (S1~S6 평가 기준). 스펙 이탈 코일은 σ와 상관없이 문제 코일.
- **글꼴(v4)**: 화면·차트·PPT 모두 현대하모니. L(400) 기본, M(500) 탭·버튼·라벨, B(700) 제목·KPI 숫자. 다른 글꼴을 새로 쓰지 않는다.
- **사용자 폴더**(`~/.steel_dashboard/`)에는 캐시·즐겨찾기·"이 PC에 보관"한 파일만. API 키는 쓰지 않는다.
- 단일 코일 분석의 양산 비교값은 **중앙값**과 MAD 기반 z. 값 종류가 적은 열은 표준편차를 쓴다. 치수(두께·폭)는 비교 조건이라 원인 후보에서 뺀다.

## 스타일

- 코드 주석·docstring·UI 문구는 한국어.
- 색: 기본 파랑 계열, 평소보다 높게 = 주황(유일한 강조색), 낮게 = 진한 파랑, 비교 대상 = 연회색, SPEC선·결함 = 빨강. 차트는 `ui.theme.show()`로 출력(테마별 Plotly 템플릿).
- 화면(v5, 연구개발자용): 그래프 먼저, 카드 제목은 이모지 + 숫자 든 결론(`ui.theme.card_title`, 두 줄 높이 고정), 해석은 카드 아래 한 줄(`narrative.note_*`가 한 줄 반환, 숫자·화살표 먼저).
  읽는 법·원리 설명은 (?)(`help=terms.CARD_HELP[...]`)로. 그래프 높이는 `card(height=)` 고정(기본 360, 조기 감시 460). 카드 안 선택 상자는 `card(control=...)`. 긴 해석 문단을 새로 만들지 않는다.
- Streamlit 위젯을 CSS로 고정할 때는 키를 단 컨테이너의 감싸개(`stLayoutWrapper:has(> .st-key-...)`)를 잡는다 (탭바 sticky).
- 강종개요 카드는 모두 같은 크기·글꼴(재질 카드 기준): 폭 `calc(15% - 16px)`·높이 138px, 간격 16px, 글꼴 4단계(제목 0.86rem 굵게 · 숫자 1.5rem · 상태 0.8rem · 보조 0.75rem). `ui/theme.py` 끝 "강종개요 통일" 규칙.
  카드 키는 `gk_`·`pc_`·`gkbtn_`·`pcbtn_` 접두어가 CSS 선택자와 겹치므로, 다른 컨테이너 키에 이 접두어를 쓰지 않는다 (예: 격자는 `gkgrid`·`pcgrid`).
- 카드 안 HTML(`st.markdown`)은 Streamlit이 아래 여백 -1rem을 주므로, 줄 간격이 필요하면 감싸는 컨테이너에서 `stMarkdownContainer` margin-bottom을 0으로.
- 페이지 스크립트는 `st.html(..., unsafe_allow_javascript=True)` (components.v1.html은 사용 중단 예정).
- 테마 전환은 CSS 덮어쓰기가 아니라 주소의 `embed=true&embed_options=dark_theme|light_theme`(+ `th=`)로 다시 연다. CSS 덮어쓰기는 입력칸 글씨가 안 보이는 문제가 있었다.
- 테스트는 API 키 없이 돌아가야 한다. 기능을 바꾸면 `python -m pytest`로 회귀를 확인한다.

## 현재 단계

**v8 구현 완료** ([prd_v8.md](prd_v8.md) 7장, 사용자 시안 기반). pytest 101개 통과, 기본 모델 S1~S4 4/4 ([eval/model_results.md](eval/model_results.md)).
화면 점검 스크린샷 `review/screenshots/v8_*` (저장소 제외). pyproject 5.0.0 (wheel 다시 빌드 필요).
v8 후속(2026-10-13): 코일분석 조건 카드 재설계(실행 버튼, SS ±10℃·CT ±20℃ 기본, 링크·AI가 넣은 번호는 `coil_autorun`으로 바로 분석, 조건이 바뀌면 "이전 조건 결과" 표시), 공정 위치 그래프, 공정분석 원인 순위 첫 값 다중회귀, 결함분석 첫 결함 = 발생률 1위, 감시 조건 프리셋 이름 변경, 강종개요 카드 크기·글꼴·간격 통일, 두께별 막대 x축 3줄 가로 표기.
배치(v8): 맨 위 고정 상단바 한 줄(탭 / 🤖 AI 보고서 · 코일 수 | 강종 · ◐ · 🔑 · AI on/off 스위치 · 🔗, `header.toolbar`) → 제목 + 조건 칩(✕) →
강종개요 탭: 🏷 기본 정보(📦 생산·제품 / 🏭 라인·규격·용도 / 🧪 재질 카드 4열 + 큰 그래프(카드 클릭, 분포 ↔ 두께별 막대 전환 `gk_view`) / 🔥 공정 조건 카드 + 큰 시계열(카드 클릭, `charts.process_timeseries`)). 재질현황·생산량·두께별 재질현황 구역과 "강종개요" 구역 제목은 삭제(v8 후속). 🚨 조기 감시는 공정분석 탭 체크리스트 위.
데이터 탭은 v4 Raw Data(AgGrid). 기본 정보는 엑셀 열 값만. 화면 용어는 "불량 코일"(σ 기준이면 "(σ 기준)").

남은 이슈:
- KPI 미니 히스토그램을 눌러 그 재질 그래프로 이동하는 동작은 없다 (툴팁만).
- 현대하모니 글꼴을 wheel에 넣었다. 다른 PC에 나눠 주기 전에 사내 글꼴 라이선스를 확인한다.
- PPT의 글자(제목·해석)는 받는 PC에 현대하모니가 없으면 다른 글꼴로 보인다 (그래프 그림은 글꼴째 그려 영향 없음).
- 에이전트 모드(실제 OpenAI 호출)는 비용 때문에 화면 점검을 하지 않았다. `.env`에 키가 있다.
- 가상 데이터는 이상이 1일부터 계단처럼 시작해, EWMA·CUSUM이 스펙 이탈보다 먼저 울리는지는 실데이터로 확인해야 한다.

- 2026-10-13 확인: `.env`의 OpenAI 키는 OpenAI가 거부한다(401 `invalid_api_key`, 만료·폐기). 키를 바꾸기 전까지 AI 모드는 오프라인으로 답한다.
  거부된 키는 세션 동안 기억해(`ui/ai.mark_rejected`, `env_bad`) 🔑에 "키 거부됨", 모드 배지에 "키 오류"로 보이고 다시 호출하지 않는다.
- AI 보고서 장수 제한 없음 (고른 항목 수만큼, 한 장에 2개).
- Claude·Gemini 어댑터는 가짜 SDK로 도구 루프만 테스트했다. 실제 키로 돌린 적이 없고, 제공자별 S1~S6 평가(`eval.run_scenarios --provider`)는 아직 만들지 않았다. 또 `anthropic`·`google-genai`는 이 PC에 설치돼 있지 않다.
- 샘플 2026년은 v1 데이터를 그대로 써서 월 생산량이 2019~2025년보다 2~3배 많다 (연도별 생산량 그래프에 계단처럼 보임).
- 데이터 탭 열 이름은 회사 양식 이름이지만 같은 이름이 여러 공정에 있으면 앞에 공정명이 붙는다.
- 강종개요는 재질 9개 × (분포·월별) 그래프를 접는 칸 안에서도 모두 계산한다. 강종 전체 기간(8년)이면 첫 화면이 몇 초 걸린다.
- `st.cache_data`는 app.py 함수 코드만 보고 캐시한다. `tools/` 분석 코드를 바꾼 뒤에는 앱을 다시 켜야 결과가 바뀐다.

## 참고

- GitHub: https://github.com/flamesub77/-Aegent (기본 브랜치 `main`)
- `.env`(API 키)는 절대 커밋하지 않는다. 보고서 `*.docx`, `files.zip`, 하위 사본 폴더 `미니 프로젝트/`, `review/screenshots/`, `dist/`·`build/`·`.venv/`·`wheels/`도 저장소에서 제외한다 (`.gitignore`).
- 하위 `미니 프로젝트/` 폴더는 예전 사본이다. 코드는 최상위 폴더 기준으로 수정한다.
