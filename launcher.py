"""`steel-dashboard` 실행 명령 (prd_v3 배포: 서버 없이 PC마다 설치).

패키지 폴더에서 `streamlit run app.py`를 띄우고 브라우저를 연다. 8501이 사용 중이면 다음 빈 포트를 쓴다.
패키지 폴더를 작업 폴더로 쓰므로 app.py의 `import config`, `from tools import ...`와 .streamlit/config.toml(테마)이 그대로 동작한다.
"""
import socket
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def free_port(start: int = 8501, tries: int = 50) -> int:
    for port in range(start, start + tries):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(("127.0.0.1", port)) != 0:
                return port
    raise RuntimeError(f"{start}~{start + tries - 1} 포트가 모두 사용 중입니다.")


def main() -> int:
    port = free_port()
    print(f"강종 품질 현황 대시보드: http://localhost:{port}  (끄려면 이 창에서 Ctrl+C)")
    cmd = [sys.executable, "-m", "streamlit", "run", str(HERE / "app.py"), "--server.port", str(port),
           "--server.address", "localhost", "--browser.gatherUsageStats", "false", *sys.argv[1:]]
    return subprocess.call(cmd, cwd=HERE)


if __name__ == "__main__":
    sys.exit(main())
