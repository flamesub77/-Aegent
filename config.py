"""환경설정: .env에서 API 키와 모델 설정을 읽는다."""
import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
# 사용자 폴더 (PC마다 설치하는 배포라 패키지 폴더 대신 여기에 .env·캐시·매핑을 둔다). API 키는 화면에서 넣은 것을 여기에 쓰지 않는다.
USER_DIR = Path(os.getenv("STEEL_DASHBOARD_HOME") or Path.home() / ".steel_dashboard")
load_dotenv(BASE_DIR / ".env")          # 개발 폴더
load_dotenv(USER_DIR / ".env")          # 설치 후: ~/.steel_dashboard/.env (앞의 값이 있으면 덮어쓰지 않음)

DATA_DIR = BASE_DIR / "files"
DB_PATH = DATA_DIR / "steel.db"
KB_PATH = DATA_DIR / "knowledge_base.md"
SAMPLE_XLSX = Path(os.getenv("STEEL_SAMPLE_XLSX") or DATA_DIR / "coil data(pds).xlsx")  # 샘플 = 회사 양식 가상 데이터
CACHE_DIR = USER_DIR / "cache"

# 에이전트·도구가 절대 읽으면 안 되는 평가용 파일
BLOCKED_FILES = {"anomaly_scenarios.md", "answer_key.csv", "trial_key.csv", "generate_data.py"}

# 실행 모드 (prd_v5 H2): offline = 외부 통신 없음 / ai = AI 모드 (키가 없거나 실패하면 오프라인으로 대신 답함)
# v4 값 auto·agent는 ai로 읽는다
APP_MODE = os.getenv("APP_MODE", "ai").strip().lower()
APP_MODE = "offline" if APP_MODE == "offline" else "ai"

MODEL = os.getenv("OPENAI_MODEL", "gpt-5.5")
# 여러 AI (prd_v5 H3): 제공자 → (화면 이름, .env 키 이름, 기본 모델)
PROVIDERS = {
    "openai": ("OpenAI", "OPENAI_API_KEY", MODEL),
    "anthropic": ("Claude", "ANTHROPIC_API_KEY", os.getenv("ANTHROPIC_MODEL", "claude-sonnet-5-5")),
    "gemini": ("Gemini", "GEMINI_API_KEY", os.getenv("GEMINI_MODEL", "")),
}
DEFAULT_PROVIDER = os.getenv("AI_PROVIDER", "openai").strip().lower()
if DEFAULT_PROVIDER not in PROVIDERS:
    DEFAULT_PROVIDER = "openai"
REASONING_EFFORT = os.getenv("OPENAI_REASONING_EFFORT", "medium")  # 빈 값이면 전달 안 함
MAX_TOKENS = int(os.getenv("OPENAI_MAX_TOKENS", "16000"))
MAX_AGENT_TURNS = int(os.getenv("MAX_AGENT_TURNS", "12"))


# PC마다 설치하는 배포(prd_v3)라 .env 키는 본인 키로 보고 기본 허용. 공용 PC 등에서는 false로
ALLOW_SHARED_KEY = os.getenv("ALLOW_SHARED_KEY", "true").strip().lower() in ("1", "true", "yes")


def resolve_api_key(user_key: str | None = None, provider: str = "openai") -> str | None:
    """쓸 API 키: 화면에서 입력한 키 → (허용 시) .env 키 → 없음. 키는 저장·기록하지 않는다 (prd_v3 U5)."""
    if user_key:
        return user_key
    env = PROVIDERS.get(provider, PROVIDERS["openai"])[1]
    return os.getenv(env) if ALLOW_SHARED_KEY else None


def has_api_key(user_key: str | None = None, provider: str = "openai") -> bool:
    return bool(resolve_api_key(user_key, provider))


def provider_model(provider: str, override: str | None = None) -> str:
    return override or PROVIDERS.get(provider, PROVIDERS["openai"])[2]


def mask_key(key: str | None) -> str:
    """화면 표시용: 앞 3자리·뒤 4자리만."""
    if not key:
        return ""
    return f"{key[:3]}…{key[-4:]}" if len(key) > 8 else "…"
