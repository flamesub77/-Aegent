"""평가용 정답지 파일 접근 차단."""
from pathlib import Path

from config import BLOCKED_FILES


class BlockedFileError(PermissionError):
    pass


def ensure_allowed(path) -> Path:
    """차단 목록에 있는 파일이면 BlockedFileError를 던진다."""
    p = Path(path)
    if p.name.lower() in {name.lower() for name in BLOCKED_FILES}:
        raise BlockedFileError(f"접근이 차단된 파일입니다: {p.name}")
    return p
