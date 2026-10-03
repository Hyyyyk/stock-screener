"""관심종목 저장 — 로컬 JSON 파일에 티커 집합을 둔다.

개인 로컬 도구라 파일 하나면 충분하다. 클라우드(Streamlit) 배포본에서는
재배포 때 초기화되므로, 관심종목은 로컬에서 관리하는 것을 전제로 한다.
"""
import json

from settings import WATCHLIST


def load() -> set[str]:
    try:
        return set(json.loads(WATCHLIST.read_text(encoding="utf-8")))
    except Exception:                                  # 파일 없음·깨짐 → 빈 목록
        return set()


def toggle(ticker: str) -> bool:
    """있으면 빼고 없으면 넣는다. 넣었으면 True(=이제 관심종목)."""
    wl = load()
    added = ticker not in wl
    wl.add(ticker) if added else wl.discard(ticker)
    WATCHLIST.write_text(json.dumps(sorted(wl), ensure_ascii=False), encoding="utf-8")
    return added
