@echo off
rem 강종 품질 현황 대시보드 실행 (PC마다 설치, prd_v3 배포)
rem - 처음 실행: 이 폴더에 .venv를 만들고 패키지를 설치합니다.
rem   wheels 폴더가 있으면 인터넷 없이 그 안의 파일로만 설치합니다 (--no-index).
rem - 다음부터: 바로 실행합니다.
chcp 65001 >nul
cd /d %~dp0
if not exist .venv\Scripts\steel-dashboard.exe (
  echo [1/2] 설치 중...
  python -m venv .venv || goto :error
  if exist wheels (
    .venv\Scripts\python -m pip install --no-index --find-links wheels steel-quality-dashboard || goto :error
  ) else (
    .venv\Scripts\python -m pip install . || goto :error
  )
)
echo [2/2] 대시보드를 엽니다. 이 창을 닫으면 종료돼요.
.venv\Scripts\steel-dashboard
goto :eof
:error
echo 설치에 실패했어요. 파이썬 3.10 이상이 설치돼 있는지 확인하세요.
pause
