"""Yahoo 주가 응답 파싱 점검."""
import pandas as pd

from market_data import parse_chart


def test_parse_chart_drops_missing_close_and_keeps_volume():
    payload = {"chart": {"result": [{
        "meta": {"currency": "USD"},
        "timestamp": [1704067200, 1704153600, 1704240000],
        "indicators": {"quote": [{"close": [10.0, None, 12.0], "volume": [100, 200, 300]}]},
    }]}}
    frame, currency = parse_chart(payload)
    assert currency == "USD"
    assert frame.종가.tolist() == [10.0, 12.0]
    assert frame.거래량.tolist() == [100, 300]
    assert pd.api.types.is_datetime64_any_dtype(frame.날짜)


def test_parse_chart_handles_api_error():
    frame, currency = parse_chart({"chart": {"result": None, "error": {"code": "Not Found"}}})
    assert frame.empty and currency is None


if __name__ == "__main__":
    test_parse_chart_drops_missing_close_and_keeps_volume()
    test_parse_chart_handles_api_error()
    print("ok")
