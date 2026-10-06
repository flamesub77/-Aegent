# 냉연강판 재질 편차 대시보드 + 원인분석 에이전트

v2 ([prd_v2.md](prd_v2.md)): r값·n값, 회사 데이터 업로드, 코일 단건 분석(시생산 vs 양산), 오프라인 모드, 해석 문체 3종, 쉬운 용어.

재질(YS/TS/EL/BH) 편차와 원인 그래프를 대시보드로 보여주고, 옆의 OpenAI 에이전트에게 질문하면 해석하고 그래프 조건·변수를 바꿔줍니다. 요구사항은 [prd.md](prd.md) 참고.

## 실행

```bash
pip install -r requirements.txt
cp .env.example .env        # OPENAI_API_KEY 입력
streamlit run app.py
python -m pytest            # 테스트 (API 키 불필요)
python -m eval.run_scenarios   # 시나리오 S1~S6 평가 (API 사용) → eval/results.md
python -m eval.check_v1_compat <v1 데이터 폴더>   # 데이터 재생성 후 v1 값·정답지 동일 여부
```

API 없이 쓰려면 `.env`에 `APP_MODE=offline` (외부 통신 없음). 키가 없거나 연결이 안 되면 자동 모드도 오프라인으로 답합니다.

## 화면

| 영역 | 내용 |
| --- | --- |
| 사이드바 | 데이터 요약, 데모 질문 S1~S6(클릭 시 바로 분석), 강종·라인·기간·재질 필터, 그래프 변수(원인 인자, 이탈군 방향, 결함 유형) |
| KPI | 코일 수, 평균(기준 대비 이동), 스펙 만족률, Cpk, 판정(1σ 기준) |
| 해석 및 인사이트 | 규칙 기반 판정 문장, 원인 상위 인자와 지식베이스 메커니즘, 공정제어 제안, 교란 요인 경고 |
| 재질 편차 | 강종×월 편차 히트맵, 분포 히스토그램(스펙선), 월별 박스플롯, 재질별 통계표 |
| 원인 분석 | 인자 기여도(효과크기), 원인 인자 산점도, 인자 일별 추이, 교란 요인 구성비, 인자 순위표 |
| 표면결함 | 월별 결함 발생률, 결함 원인 인자 |
| Raw Data | 열마다 필터·정렬되는 표(AG Grid), 필터 결과 CSV/Excel 다운로드 |
| 분석 에이전트 | 질문 → 단계별 진행 표시 → 판정·원인 요약 배지 + 답변, 대시보드 조건·그래프 변수 자동 변경, 분석 과정 보기, 리포트(MD) 다운로드 |

비교 방식: 기간을 고르면 대상 기간 vs 나머지 기간, 전체 기간이면 스펙/평균±1σ 이탈 코일 vs 나머지.

색상 규칙: 상향 = 주황, 하향 = 파랑, 중립 비교군 = 슬레이트, 기준 = 연회색, 스펙선·결함 = 빨강. 차트 배경은 투명이라 라이트/다크 테마(`.streamlit/config.toml`)를 따릅니다.

## 구조

| 경로 | 역할 |
| --- | --- |
| app.py | Streamlit 대시보드 + 에이전트 패널 |
| agent/agent.py | OpenAI Responses API function calling 루프 |
| agent/prompts.py | 시스템 프롬프트 |
| agent/report.py | 도구 출력으로 구조화 결과(판정·원인 순위·차트 목록·본문) 생성 |
| eval/run_scenarios.py | 데모 질문 6개 실행 후 정답지로 채점 (정답지를 읽는 유일한 코드) |
| tools/analysis.py | 분석 엔진 (분포 진단, 인자 비교, 결함 추적, 인사이트 문장) |
| tools/domain.py | 인자 이름·단위, 지식베이스 3~4장의 영향 방향과 제어 조치 |
| tools/charts.py | Plotly 차트 |
| tools/dashboard_state.py | 대시보드 상태와 변경 검증 (사이드바·에이전트 공용) |
| tools/registry.py | 에이전트 도구 스키마와 실행 |
| tools/db.py, guard.py | steel.db 읽기 전용 접근, 정답지 파일 차단 |
| agent/offline.py | 오프라인 질문 해석기 (키워드 → 대시보드 변경 + 규칙 기반 답변) |
| agent/router.py | 실행 모드 선택, 에이전트 실패 시 오프라인으로 대신 답변 |
| tools/datasource.py | 데이터 소스 (샘플 DB / 업로드 파일), r̄·Δr 파생 |
| tools/upload.py | 파일 읽기(CSV 인코딩 자동·XLSX), 컬럼 자동 매핑, 검증, 양식 |
| tools/coil_lookup.py | 코일 단건 분석: 계보, 양산 기준(중앙값·MAD), 재질·공정 차이 |
| tools/terms.py | 화면 용어 (문체별). 회사 용어는 이 파일만 고치면 됨 |
| tools/narrative.py | 해석 문장 (쉬운 말 / 전문가 / 통계) |
| config.py | 환경변수 (APP_MODE, 모델 기본값 gpt-5.5) |

## 규칙

- `files/anomaly_scenarios.md`, `files/answer_key.csv`, `files/trial_key.csv`, `files/generate_data.py`는 평가용이며 앱·에이전트·도구 코드에서 읽지 않습니다. 평가 스크립트만 읽습니다.
- 모든 수치는 분석 엔진이 계산하고, LLM은 해석과 서술만 합니다.
