"""데이터 파일 선택·전환 (prd_v4 L3).

- 기본 파일: 패키지에 들어 있는 `coil data(pds).xlsx` (config.SAMPLE_XLSX). 지울 수 없다.
- 올린 파일: 이번 앱 실행 동안 메모리(session_state["datasets"], ui/session.py가 새로 고침 뒤에도 복원).
  업로드할 때 "이 PC에 보관"을 켠 파일만 사용자 폴더(~/.steel_dashboard/datasets/)에 저장해 앱을 다시 켜도 남는다.
  회사 서버·외부로는 보내지 않는다.
"""
import hashlib
import pickle
import time
from datetime import datetime

import streamlit as st

import config

DEFAULT_ID = "default"
STORE_DIR = config.USER_DIR / "datasets"


def _all() -> dict:
    st.session_state.setdefault("datasets", {})
    if not st.session_state.get("_datasets_loaded"):  # 앱 실행 처음 한 번: 이 PC에 보관한 파일을 목록에 올린다
        st.session_state["_datasets_loaded"] = True
        for path in sorted(STORE_DIR.glob("*.pkl")) if STORE_DIR.exists() else []:
            try:
                item = pickle.loads(path.read_bytes())  # 이 앱이 사용자 폴더에 직접 쓴 파일만 읽는다
            except Exception:  # 깨진 파일은 건너뛴다
                continue
            st.session_state["datasets"].setdefault(item["id"], item)
    return st.session_state["datasets"]


def options() -> list[str]:
    return [DEFAULT_ID] + sorted(_all(), key=lambda k: _all()[k]["uploaded"], reverse=True)


def label(ds_id: str) -> str:
    if ds_id == DEFAULT_ID:
        return f"{config.SAMPLE_XLSX.name} (기본)"
    d = _all().get(ds_id)
    if not d:
        return "(없는 파일)"
    keep = " · 💾" if d.get("saved") else ""
    return f"{d['name']} · {d['n']:,}코일 · {d['period']}{keep}"


def current() -> str:
    ds = st.session_state.get("dataset", DEFAULT_ID)
    return ds if ds == DEFAULT_ID or ds in _all() else DEFAULT_ID


def source():
    """지금 고른 파일의 DataSource (기본이면 None → 샘플 소스)."""
    ds = current()
    return None if ds == DEFAULT_ID else _all()[ds]["source"]


def source_key() -> str:
    return f"ds:{current()}"


def select(ds_id: str):
    st.session_state["dataset"] = ds_id if ds_id == DEFAULT_ID or ds_id in _all() else DEFAULT_ID
    st.session_state["upload_source"] = source()
    st.session_state["source_key"] = source_key()


def register(src, name: str, keep: bool = False) -> str:
    """올린 파일을 목록에 넣고 바로 그 파일로 바꾼다. keep이면 이 PC 사용자 폴더에 저장."""
    lo, hi = src.date_range()
    ds_id = hashlib.md5(f"{name}:{len(src.coils)}:{time.time()}".encode()).hexdigest()[:10]
    item = {"id": ds_id, "name": name, "n": len(src.coils), "period": f"{lo} ~ {hi}",
            "uploaded": datetime.now().strftime("%Y-%m-%d %H:%M"), "saved": keep, "source": src}
    _all()[ds_id] = item
    if keep:
        STORE_DIR.mkdir(parents=True, exist_ok=True)
        (STORE_DIR / f"{ds_id}.pkl").write_bytes(pickle.dumps(item))
    select(ds_id)
    return ds_id


def delete(ds_id: str):
    if ds_id == DEFAULT_ID:
        return
    item = _all().pop(ds_id, None)
    if item and item.get("saved"):
        (STORE_DIR / f"{ds_id}.pkl").unlink(missing_ok=True)
    if st.session_state.get("dataset") == ds_id:
        select(DEFAULT_ID)
