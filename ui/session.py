"""새로 고침해도 보던 화면 유지 (prd_v3 F2).

- 필터·탭·모델: URL 쿼리 파라미터 (링크로 공유 가능). 테마는 Streamlit의 embed_options (ui/theme.py)
- 대화·업로드 데이터·API 키: 서버 메모리 세션 저장소. 브라우저마다 무작위 세션 ID(sid, URL에 포함)로 찾는다.
  디스크에 쓰지 않는다. 서버(앱)를 끄거나 8시간 쓰지 않으면 사라진다.
API 키와 업로드 원본은 URL에 넣지 않는다.
"""
import re
import secrets
import time
from datetime import date
from urllib.parse import urlencode

import streamlit as st

TTL = 8 * 3600
KEPT = ["chat", "upload_source", "source_key", "upload_msg", "api_keys", "api_status", "ai_provider", "ai_models", "edit_draft",
        "run_mode", "fab_seen", "datasets", "dataset", "bubble_off", "spc_params"]  # 서버 메모리에 둘 것
# URL 이름 ↔ 상태 키 (짧게)
QP = {"g": "grade", "l": "line", "from": "start", "to": "end", "p": "prop", "v": "view", "m": "model", "f": "factor",
      "d": "defect", "sd": "side", "sc": "spec_col", "scs": "spec_cols", "sp": "specs", "am": "aims", "us": "uses",
      "pl": "plants", "tmin": "thk_min", "tmax": "thk_max", "pos": "coil_pos", "ids": "coil_ids", "idt": "id_type",
      "ps": "props", "sg": "sigma", "dsc": "defect_scope"}  # sc(spec_col)는 v3 링크 호환용 (읽기만)
LISTS = {"specs", "aims", "uses", "plants", "props", "spec_cols"}
DATES = {"start", "end"}
FLOATS = {"thk_min", "thk_max", "sigma"}
READ_ONLY = {"spec_col"}


@st.cache_resource
def _store() -> dict:
    """{sid: {키: 값, "_ts": 마지막 사용 시각}} — 서버 프로세스 메모리 (모든 브라우저 공유, sid로 구분)."""
    return {}


def sid() -> str:
    s = st.query_params.get("sid", "")
    if not re.fullmatch(r"[0-9a-f]{32}", s or ""):
        s = secrets.token_hex(16)  # 128비트, 추측 불가
        st.query_params["sid"] = s
    return s


def restore() -> str | None:
    """세션 첫 실행에 한 번: 서버 메모리 → session_state, URL → 필터. 반환: 만료 안내 문구 또는 None."""
    if st.session_state.get("_restored"):
        return None
    st.session_state["_restored"] = True
    store, key = _store(), sid()
    _purge(store)
    saved = store.get(key)
    if saved:
        for k in KEPT:
            if k in saved:
                st.session_state[k] = saved[k]
    st.session_state["_qp_state"] = from_query()
    if not saved and st.query_params.get("src") == "upload":  # 엄격 모드: 조용히 샘플로 바꾸지 않고 알린다
        return "이전 세션이 만료됐어요. 필터는 복원했고, 업로드 파일은 다시 올려 주세요."
    return None


def save():
    store = _store()
    store[sid()] = {k: st.session_state[k] for k in KEPT if k in st.session_state} | {"_ts": time.time()}


def _purge(store: dict):
    now = time.time()
    for k in [k for k, v in store.items() if now - v.get("_ts", 0) > TTL]:
        store.pop(k, None)


def from_query() -> dict:
    """URL → 상태 dict (검증은 dashboard_state.apply_update가 한다)."""
    out = {}
    for short, key in QP.items():
        v = st.query_params.get(short)
        if v in (None, ""):
            continue
        if key in LISTS:
            out[key] = [x for x in v.split(",") if x]
        elif key in FLOATS:
            try:
                out[key] = float(v)
            except ValueError:
                continue
        else:
            out[key] = v
    return out


KEEP = ("embed", "embed_options", "th")  # 테마 (ui/theme.py)


def query_dict(state: dict, defaults: dict, uploaded: bool) -> dict:
    """상태 → URL 값. 기본값과 같은 항목은 빼서 주소를 짧게 둔다. 테마 옵션은 그대로 둔다."""
    want = {"sid": sid()}
    for short, key in QP.items():
        v = state.get(key)
        if key in READ_ONLY or v == defaults.get(key) or v in (None, "", []):
            continue
        if key in LISTS:
            v = ",".join(v)
        elif key in DATES and isinstance(v, date):
            v = v.isoformat()
        elif key in FLOATS:
            v = f"{v:g}"
        want[short] = str(v)
    if uploaded:
        want["src"] = "upload"
    for k in KEEP:
        if st.query_params.get(k):
            want[k] = st.query_params.get(k)
    return want


def to_query(state: dict, defaults: dict, uploaded: bool):
    want = query_dict(state, defaults, uploaded)
    current = {k: st.query_params.get(k) for k in st.query_params}
    if current != want:
        st.query_params.from_dict(want)


def share_link() -> str:
    """sid를 뺀 현재 주소 (필터만 공유)."""
    params = {k: st.query_params.get(k) for k in st.query_params if k not in ("sid", "src", *KEEP)}
    try:
        base = str(st.context.url).split("?")[0]
    except Exception:
        base = ""
    return base + ("?" + urlencode(params) if params else "")
