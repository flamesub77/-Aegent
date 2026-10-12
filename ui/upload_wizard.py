"""회사 데이터 업로드 마법사 (prd_v2 R2): ① 파일 → ② 컬럼 매핑 → ③ 검증 → ④ 적용.

파일은 메모리에서만 처리한다. 매핑 설정만 mappings/에 저장할 수 있다.
"""
import hashlib

import pandas as pd
import streamlit as st

from tools import upload as U
from tools.datasource import REQUIRED, sample_source

SKIP = "(사용 안 함)"
OPTIONS = [SKIP] + [f"{c} · {d}" for c, (d, _, _) in U.STANDARD.items()]
LEVEL_ICON = {"error": "⛔ 오류", "warn": "⚠️ 확인", "info": "ℹ️ 참고"}


def _opt(std):
    return SKIP if not std else next(o for o in OPTIONS if o.split(" · ")[0] == std)


@st.cache_data(show_spinner="파일 읽는 중…", max_entries=4)
def _read(data: bytes, name: str, sheet):
    return U.read_file(data, name, sheet)


def apply_source(src, name: str):
    st.session_state["upload_source"] = src
    st.session_state["source_key"] = f"upload:{name}:{len(src.coils)}:{hashlib.md5(name.encode()).hexdigest()[:6]}"
    st.session_state["ext_ok"] = False  # 새 파일은 외부 전송을 다시 확인받는다


def use_sample():
    st.session_state.pop("upload_source", None)
    st.session_state["source_key"] = "sample"
    st.session_state["upload_msg"] = ("ok", "샘플 데이터로 돌아왔습니다.")


@st.dialog("내 파일 불러오기", width="large")
def upload_dialog():
    st.markdown("#### ① 파일 선택")
    f = st.file_uploader("코일 데이터 (CSV / Excel)", type=["csv", "xlsx", "xls"], key="wz_file",
                         help="파일은 이 PC의 메모리에서만 처리하고 저장하지 않습니다.")
    st.download_button("업로드 양식 받기 (Excel, 컬럼 정의 포함)", U.template_excel(), "coil_upload_template.xlsx",
                       icon=":material/download:")
    if f is None:
        st.caption("필수 컬럼: 코일번호, 생산일, 강종, 라인, 재질 1개 이상. 나머지 공정인자는 있는 만큼만 분석합니다.")
        return
    try:
        raw, sheets = _read(f.getvalue(), f.name, None)
        if len(sheets) > 1:
            sheet = st.selectbox("시트", sheets, key="wz_sheet")
            raw, _ = _read(f.getvalue(), f.name, sheet)
    except Exception as e:  # 읽기 실패는 여기서 보여주고 끝낸다
        st.error(f"파일을 읽지 못했습니다: {e}")
        return
    st.caption(f"{f.name} · {len(raw):,}행 × {len(raw.columns)}열")

    st.markdown("#### ② 컬럼 매핑")
    file_id = hashlib.md5(f.getvalue()[:4096] + f.name.encode()).hexdigest()[:8]
    saved = U.list_mappings()
    c1, c2 = st.columns([2, 1], vertical_alignment="bottom")
    pick = c1.selectbox("저장된 매핑 불러오기", ["자동 인식"] + saved, key=f"wz_saved_{file_id}")
    auto = U.suggest_mapping(raw.columns)
    ppm_default = []
    if pick != "자동 인식":
        loaded = U.load_mapping(pick)
        auto = {c: loaded["mapping"].get(c) for c in raw.columns}
        ppm_default = loaded.get("ppm_columns", [])
    table = pd.DataFrame({"원본 컬럼": list(raw.columns),
                          "예시 값": [str(raw[c].dropna().iloc[0])[:18] if raw[c].notna().any() else "" for c in raw.columns],
                          "표준 컬럼": [_opt(auto[c]) for c in raw.columns]})
    edited = st.data_editor(table, key=f"wz_map_{file_id}_{pick}", hide_index=True, width="stretch", height=300,
                            disabled=["원본 컬럼", "예시 값"],
                            column_config={"표준 컬럼": st.column_config.SelectboxColumn(options=OPTIONS, required=True)})
    mapping = {r["원본 컬럼"]: (None if r["표준 컬럼"] == SKIP else r["표준 컬럼"].split(" · ")[0])
               for _, r in edited.iterrows()}
    dup = pd.Series([v for v in mapping.values() if v]).value_counts()
    if (dup > 1).any():
        st.error("같은 표준 컬럼에 원본 컬럼이 두 개 이상 연결됐습니다: " + ", ".join(dup[dup > 1].index))
        return
    n_auto = sum(1 for v in U.suggest_mapping(raw.columns).values() if v)
    st.caption(f"자동 인식 {n_auto}개 · 연결된 컬럼 {sum(1 for v in mapping.values() if v)}개. 표준 컬럼 칸을 눌러 바꿀 수 있습니다.")
    elems = [c for c in U.ELEMENTS if c in mapping.values()]
    ppm = st.multiselect("ppm 단위 성분 (wt%로 변환)", elems, default=[e for e in ppm_default if e in elems],
                         key=f"wz_ppm_{file_id}") if elems else []
    s1, s2 = st.columns([2, 1], vertical_alignment="bottom")
    name = s1.text_input("이 매핑 저장 이름", placeholder="예: 당진 냉연 품질 DB", key=f"wz_name_{file_id}")
    if s2.button("매핑 저장", disabled=not name, width="stretch"):
        U.save_mapping(name, mapping, ppm)
        st.success(f"'{name}' 매핑을 저장했습니다. 다음에 '저장된 매핑'에서 고를 수 있습니다.")

    st.markdown("#### ③ 검증")
    df = U.apply_mapping(raw, mapping, ppm)
    spec_mode = st.radio("강종 스펙", ["샘플 스펙 사용 (같은 강종 코드만)", "스펙 파일 올리기", "스펙 없이 분포만"],
                         horizontal=True, key=f"wz_spec_{file_id}")
    grades = None
    if spec_mode == "스펙 파일 올리기":
        gf = st.file_uploader("강종 스펙 (grade_master 형식)", type=["csv", "xlsx"], key=f"wz_grade_{file_id}")
        if gf is not None:
            try:
                grades = U.read_grades(gf.getvalue(), gf.name)
            except ValueError as e:
                st.error(str(e))
    elif spec_mode == "샘플 스펙 사용 (같은 강종 코드만)":
        grades = sample_source().grades.reset_index(drop=True)
    rep = U.validate(df, raw, mapping, grades if grades is not None else pd.DataFrame(columns=["grade"]))
    if rep["issues"]:
        st.dataframe(pd.DataFrame([{"구분": LEVEL_ICON[i["level"]], "내용": i["text"], "건수": i["count"],
                                    "예시": ", ".join(map(str, i.get("examples", [])))} for i in rep["issues"]]),
                     hide_index=True, width="stretch")
    else:
        st.success("문제가 없습니다.")
    drop = st.checkbox(f"문제 행 {rep['bad_rows']}개 제외하고 적용", value=True, key=f"wz_drop_{file_id}",
                       disabled=rep["bad_rows"] == 0)

    st.markdown("#### ④ 적용")
    missing = [c for c in REQUIRED if c not in mapping.values()]
    if missing:
        st.info("필수 컬럼을 먼저 연결하세요: " + ", ".join(U.STANDARD[c][0] for c in missing))
    if st.button("이 데이터로 분석하기", type="primary", disabled=not rep["ok"], width="stretch"):
        try:
            src = U.build_source(df, f.name, grades=grades, use_sample_spec=False,
                                 drop_bad=rep["bad_mask"] if drop else None)
        except ValueError as e:
            st.error(str(e))
            return
        apply_source(src, f.name)
        st.session_state["upload_msg"] = ("ok", f"{f.name} · {len(src.coils):,}코일 적용"
                                                + (f" (문제 행 {rep['bad_rows']}개 제외)" if drop and rep["bad_rows"] else ""))
        st.rerun()
