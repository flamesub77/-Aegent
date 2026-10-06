"""search_knowledge: 지식베이스 섹션 검색. 강종을 주면 해당 강종 절과 공통 인자 절을 먼저 붙인다."""
import re
from functools import lru_cache

from config import KB_PATH
from tools.guard import ensure_allowed


@lru_cache(maxsize=1)
def load_sections(path=KB_PATH) -> list[dict]:
    """'##'/'###' 제목 기준으로 지식베이스를 섹션 목록으로 나눈다."""
    text = ensure_allowed(path).read_text(encoding="utf-8")
    sections, title, buf = [], "머리말", []
    for line in text.splitlines():
        m = re.match(r"^(#{2,3})\s+(.*)", line)
        if m:
            if buf:
                sections.append({"title": title, "content": "\n".join(buf).strip()})
            title, buf = m.group(2).strip(), []
        else:
            buf.append(line)
    if buf:
        sections.append({"title": title, "content": "\n".join(buf).strip()})
    return [s for s in sections if s["content"]]


# 강종 코드 → knowledge_base.md 3장 절 제목 접두어
GRADE_SECTION = {"IF270_IN": "3.1", "IF340_OUT": "3.2", "BH340_OUT": "3.3", "LC340": "3.4", "LC440R": "3.4",
                 "HSLA590C": "3.5"}


FAMILY_SECTION = {"IF": "3.1", "IF_HS": "3.2", "BH": "3.3", "LC": "3.4", "HSLA": "3.5"}


def _family_section(grade: str):
    """업로드 데이터의 강종은 스펙 표의 family로 절을 찾는다."""
    try:
        from tools.datasource import get_source
        return FAMILY_SECTION.get(get_source().grade(grade).get("family"))
    except ValueError:
        return None


def _pick(prefix: str):
    return next((s for s in load_sections() if s["title"].startswith(prefix)), None)


def search_knowledge(query: str = "", top_k: int = 3, grade: str | None = None) -> dict:
    """질의어 토큰이 제목·본문에 등장하는 횟수로 섹션을 점수화해 상위 결과를 반환한다.

    grade를 주면 그 강종의 강화기구 절(3.1~3.5)과 공통 인자 절(3.6)을 점수와 무관하게 먼저 포함한다.
    """
    pinned = []
    if grade:
        sec = GRADE_SECTION.get(grade) or _family_section(grade)
        if not sec:
            return {"error": f"지식베이스에 강종 절이 없습니다: {grade}", "available": list(GRADE_SECTION)}
        pinned = [s for s in (_pick(sec), _pick("3.6")) if s]
        if re.search(r"r값|r̄|rbar|이방성|n값|n_value|가공경화|딥드로|성형", query, re.I):
            pinned.append(_pick("3.7"))
        pinned = [s for s in pinned if s]
    tokens = [t for t in re.split(r"[\s,·/]+", query.lower()) if len(t) >= 2]
    if not tokens and not pinned:
        return {"query": query, "results": [], "message": "검색어가 너무 짧습니다."}
    scored = []
    for s in load_sections():
        if s in pinned:
            continue
        title, body = s["title"].lower(), s["content"].lower()
        score = sum(3 * title.count(t) + body.count(t) for t in tokens)
        if score:
            scored.append((score, s))
    scored.sort(key=lambda x: -x[0])
    results = [{"source": f"knowledge_base.md > {s['title']}", "score": "강종 지정", "content": s["content"]}
               for s in pinned]
    results += [{"source": f"knowledge_base.md > {s['title']}", "score": sc, "content": s["content"]}
                for sc, s in scored[:top_k]]
    return {"query": query, "grade": grade, "results": results}
