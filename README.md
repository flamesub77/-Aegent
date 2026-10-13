# 강종 품질 현황 대시보드 + AI 분석 도우미

연구개발자용 냉연강판 재질(YP·TS·EL·BH·r̄·n) 대시보드입니다. 그래프마다 숫자 먼저 한 줄로 해석하고, 자세한 설명은 (?)에 둡니다.
EWMA·CUSUM으로 재질 흐름이 바뀌는 시점을 조기 감시하고, 데이터 탭에서 이상치를 빼 다시 계산하며, 회사 PPT 양식으로 2~3장 AI 보고서를 만듭니다.
오른쪽 아래 🤖 아이콘은 오프라인 해석기 또는 AI(OpenAI·Claude·Gemini 중 선택)로 원인을 찾고 대시보드 조건을 바꿔 줍니다.

- 요구사항: v5 [prd_v5.md](prd_v5.md) (현재) · v4 [prd_v4.md](prd_v4.md) · v3 [prd_v3.md](prd_v3.md) · v2 [prd_v2.md](prd_v2.md) · v1 [prd.md](prd.md)
- 데이터: 회사 양식 [files/coil data(pds).xlsx](files/coil%20data%28pds%29.xlsx) (제강 → 연주 → 열연 → 냉연 165열 + 추가 열). 샘플은 2019~2026년 가상 데이터 29,800코일 (13강종·4라인·3공장)

## 실행

**개발 폴더에서**

```bash
pip install -r requirements.txt
streamlit run app.py
```

**PC에 설치해서 (서버 없이 PC마다)**

```bash
python -m pip wheel . --no-deps -w dist
pip install dist/steel_quality_dashboard-5.0.0-py3-none-any.whl
steel-dashboard
```

- `steel-dashboard`는 빈 포트(8501부터)를 찾아 앱을 띄우고 브라우저를 엽니다.
- 인터넷이 없는 PC: 인터넷 되는 PC에서 `pip download -r requirements.txt -d wheels`와 wheel 파일을 `wheels/`에 모아 함께 복사한 뒤 `run.bat`을 실행하면 인터넷 없이 설치·실행합니다.
- 설치 후 설정·캐시·매핑은 사용자 폴더 `~/.steel_dashboard/`에 둡니다 (`.env`도 여기에 둘 수 있음).

**테스트·평가**

```bash
python -m pytest                 # 테스트 (API 키 불필요, 외부 통신 없음)
python -m eval.model_compare     # 원인 순위 모델 5종 × 시나리오 S1~S6 (API 불필요) → eval/model_results.md
python -m eval.run_scenarios     # 에이전트로 S1~S6 평가 (OpenAI API 사용) → eval/results.md
python files/make_pds_sample.py  # 샘플 데이터(회사 양식) 다시 만들기
```

`.env` (`.env.example` 참고): `APP_MODE`(ai | offline), `AI_PROVIDER`, `OPENAI_API_KEY`·`OPENAI_MODEL`, `ANTHROPIC_API_KEY`·`ANTHROPIC_MODEL`,
`GEMINI_API_KEY`·`GEMINI_MODEL`, `ALLOW_SHARED_KEY`(.env 키 허용, 기본 true). Claude·Gemini는 `pip install anthropic google-genai`(선택).
AI 키는 화면 오른쪽 위 🔑에서 제공자별로 넣을 수도 있습니다 (메모리에만 보관, 파일·로그·주소창에 남기지 않음).

## 화면

| 영역 | 내용 |
| --- | --- |
| 왼쪽 | 📂 데이터 파일(기본 + 올린 파일 + ✏️ 수정본 바로 전환, 🗑, 새 파일 올리기), ★ 즐겨찾기, 🔎 필터(기간·냉연규격·규격약호·출강목표·용도코드·라인·공장·두께·시편 위치) |
| 머리글 | "{강종} 품질 현황", 같은 크기 버튼 ◐ 테마 · 🔑 AI 키(OpenAI·Claude·Gemini) · 🤖 AI 보고서 · 🔗 링크 |
| 고정바 | 📊 재질개요 · ⚙️ 공정분석 · 🧩 결함분석 · 🔬 코일분석 · 🗂 데이터, 지금 조건, 🔒 오프라인 / 🤖 AI 모드. 재질개요·공정분석에서는 재질 버튼(기본 YP·TS·EL)과 재질 고정카드(SPEC·평균·증감·작은 히스토그램·만족률) |
| 📊 재질개요 | ① 📦 생산량(연도별·월별) ② 🧪 재질현황(재질별 분포·월별 추이, 🚨 EWMA·CUSUM 조기 감시 + 추천 조건, 강종×월 편차, r값) ③ 📏 두께별 재질현황(상자그림 + 표) |
| ⚙️ 공정분석 | 분석 재질, 문제 코일 기준 σ(0.5~3.0, 0.1 단위, 기본 1.0), 🚨 경보 배지, 🏆 원인 순위(계산 방법 선택), 🔗 인자 관계, 📈 추이, ⚖️ 비교 조건 + 그 조건만 보기, ✅ 체크리스트 |
| 🧩 결함분석 | 🥇 강종 안 결함 유형 순위(파레토), 🆚 같은 결함 강종 비교(강종×월 히트맵 전환), 🗓 월별, 🏆 결함 원인 순위 |
| 🔬 코일분석 | 번호(냉연·열연·슬라브·히트)로 조회, 공정 순서 표, 양산 분포 위 이 코일, 공정 차이, 리포트 MD/Excel |
| 🗂 데이터 | 엑셀처럼 값 고치기, "제외" 체크, 이상치 도우미(평균±kσ·SPEC 50%), 되돌리기, 기록, [분석에 반영] → `원본명 (수정 n건)` 새 파일, Excel |
| 🤖 AI 보고서 | 항목 체크리스트(4~6개) → 미리보기 → `files/PPT 양식.pptx`로 2~3장(KPI 타일·구역 색·쪽 번호). AI 모드면 문장을 AI가 씀 |
| AI 분석 도우미 | 오른쪽 아래 🤖. 화면이 바뀌면 추천 질문 말풍선, 누르면 팝업에서 답함. 오프라인이면 규칙 해석기 |

카드는 **이모지 + 숫자 든 결론 제목 (?) → 같은 높이 그래프 → 해석 한 줄** 순서입니다. 읽는 법·원리 설명은 (?)에 있습니다.
새로 고침해도 필터·탭·모델·테마(주소창)와 대화·업로드·수정본·AI 키·모드(앱 메모리, 8시간)가 유지됩니다.

색상: 기본 파랑 계열, 평소보다 높게 = 주황, 낮게 = 진한 파랑, 비교 대상 = 연회색, SPEC선·결함 = 빨강.
글꼴: 현대하모니 (L 본문, M 탭·버튼·라벨, B 제목·숫자). 화면·차트·PPT 공통.

## 구조

| 경로 | 역할 |
| --- | --- |
| app.py | 화면 구성 (필터·요약 카드·탭·그래프 카드) |
| launcher.py, pyproject.toml, run.bat | PC 설치 배포 (`steel-dashboard` 명령) |
| ui/ | header(제목·테마·AI 키·보고서·링크), ai(모드·제공자·키), session(새로 고침 유지), theme(테마·글꼴·차트 출력·CSS), chat(🤖 아이콘·말풍선·팝업), datasets(파일 전환), favorites(즐겨찾기), report(AI 보고서 팝업), coil_view(코일분석), upload_wizard(업로드) |
| tools/spc.py, tools/report_ppt.py, tools/edits.py | EWMA·CUSUM 조기 감시(추천 조건), AI 보고서 PPT, 데이터 탭 편집·수정본 |
| static/ | 현대하모니 글꼴 (화면 등록용 영문 이름 사본) |
| agent/ | agent(OpenAI 함수 호출 루프), providers/(OpenAI·Claude·Gemini 어댑터), router(모드·제공자 선택, 실패 시 오프라인), offline(규칙 기반 해석기), prompts, report |
| tools/pds.py | 회사 양식 읽기 (공정 블록 위치로 같은 이름 열 구분, SPEC 파싱, 추가 열) |
| tools/datasource.py | 샘플(회사 양식, 캐시) / 업로드 데이터를 같은 형식으로 |
| tools/analysis.py | 분석 엔진 (분포 진단, 인자 비교, 결함 추적, 연도별 생산량) |
| tools/ranking.py | 원인 순위 모델 5종 (같은 결과 형식) |
| tools/narrative.py, terms.py | 쉬운 말 문장·그래프 카드 해석, 용어 |
| tools/domain.py | 인자 이름·단위·공정, 야금 원리, 제어 조치 |
| tools/charts.py | Plotly 차트 (파랑 계열) |
| tools/dashboard_state.py | 필터·화면 상태와 변경 검증 (화면·에이전트 공용) |
| tools/upload.py, coil_lookup.py, registry.py, db.py, guard.py | 업로드 매핑·검증, 단일 코일, 에이전트 도구, DB 읽기, 정답지 차단 |
| eval/ | 시나리오 평가, 모델 비교, v1 호환 확인 |
| files/ | 샘플 데이터(회사 양식 xlsx, steel.db), 용도코드표, 지식베이스, 평가용 정답 |

## 규칙

- `files/anomaly_scenarios.md`, `files/answer_key.csv`, `files/trial_key.csv`, `files/generate_data.py`는 평가용이며 앱·에이전트·도구 코드에서 읽지 않습니다. 배포 패키지에도 넣지 않습니다.
- 모든 수치는 분석 엔진이 계산하고, LLM은 해석과 서술만 합니다.
- 오프라인 모드에서는 외부 통신이 없습니다. API 키와 업로드 원본은 디스크·로그·주소창에 남기지 않습니다.
