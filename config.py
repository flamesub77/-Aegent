"""환경설정: .env에서 API 키와 모델 설정을 읽는다."""
import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

DATA_DIR = BASE_DIR / "files"
DB_PATH = DATA_DIR / "steel.db"
KB_PATH = DATA_DIR / "knowledge_base.md"

# 에이전트·도구가 절대 읽으면 안 되는 평가용 파일
BLOCKED_FILES = {"anomaly_scenarios.md", "answer_key.csv", "trial_key.csv", "generate_data.py"}

# 실행 모드 (prd_v2 R4): auto = 키가 있으면 에이전트, 실패하면 오프라인 / agent / offline = 외부 통신 없음
APP_MODE = os.getenv("APP_MODE", "auto").strip().lower()
if APP_MODE not in ("auto", "agent", "offline"):
    APP_MODE = "auto"

MODEL = os.getenv("OPENAI_MODEL", "gpt-5.5")
REASONING_EFFORT = os.getenv("OPENAI_REASONING_EFFORT", "medium")  # 빈 값이면 전달 안 함
MAX_TOKENS = int(os.getenv("OPENAI_MAX_TOKENS", "16000"))
MAX_AGENT_TURNS = int(os.getenv("MAX_AGENT_TURNS", "12"))


def has_api_key() -> bool:
    return bool(os.getenv("OPENAI_API_KEY"))
