"""필터 즐겨찾기 (prd_v4 L4). 사용자 폴더 ~/.steel_dashboard/favorites.json에 필터 값만 저장한다 (데이터는 넣지 않음)."""
import json
from datetime import date

import config

PATH = config.USER_DIR / "favorites.json"
MAX = 10
KEYS = ["grade", "line", "start", "end", "props", "prop", "spec_cols", "specs", "aims", "uses", "plants",
        "thk_min", "thk_max", "coil_pos", "view", "model", "sigma", "side", "defect", "defect_scope"]


def load() -> list[dict]:
    try:
        data = json.loads(PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (OSError, ValueError):
        return []


def _save(items: list[dict]):
    PATH.parent.mkdir(parents=True, exist_ok=True)
    PATH.write_text(json.dumps(items[:MAX], ensure_ascii=False, indent=1), encoding="utf-8")


def default_name(state: dict) -> str:
    start, end = state["start"], state["end"]
    period = start.strftime("%Y-%m") if (start.year, start.month) == (end.year, end.month) else f"{start:%y.%m}~{end:%y.%m}"
    line = "" if state.get("line") in (None, "전체") else f" · {state['line']}"
    return f"{state['grade']} · {period}{line}"


def add(name: str, state: dict) -> list[dict]:
    snap = {k: (v.isoformat() if isinstance(v, date) else v) for k, v in state.items() if k in KEYS}
    items = [f for f in load() if f.get("name") != name]
    items.insert(0, {"name": name.strip() or default_name(state), "state": snap})
    _save(items)
    return items


def remove(name: str) -> list[dict]:
    items = [f for f in load() if f.get("name") != name]
    _save(items)
    return items
