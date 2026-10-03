"""매일 갱신 - 시세와 한국 수급만 당긴다.  실행: python update_daily.py

재무(collect_us.py·collect_kr.py)는 분기에 한 번이라 여기 넣지 않는다.
둘 다 이어받기를 지원하므로 중간에 끊겨도 다시 돌리면 남은 것만 받는다.
"""
import collect_flow
import collect_price

if __name__ == "__main__":
    print("① 시세 (Yahoo) ──────────────")
    collect_price.main()
    print("\n② 수급 (네이버·한국) ─────────")
    collect_flow.main()
    print("\n완료 — 시세·수급 갱신 끝. 앱을 새로고침하면 반영됩니다.")
