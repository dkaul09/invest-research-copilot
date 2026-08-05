"""Structured view extraction: ticker provenance and defensive JSON parsing."""

from backend.view_extract import extract_view, parse_view_json, tickers_from_tool_calls


def test_tickers_pulled_from_recorded_calls():
    calls = [
        {"tool": "compute_metrics", "args": {"ticker": "nvda"}},
        {"tool": "get_quote", "args": {"ticker": "NVDA"}},
        {"tool": "get_portfolio_snapshot", "args": {}},
    ]
    assert tickers_from_tool_calls(calls) == ["NVDA"]


def test_tickers_preserve_first_seen_ordering():
    calls = [
        {"tool": "get_quote", "args": {"ticker": "MSFT"}},
        {"tool": "get_quote", "args": {"ticker": "AAPL"}},
    ]
    assert tickers_from_tool_calls(calls) == ["MSFT", "AAPL"]


def test_parse_view_json_reads_fenced_payload():
    raw = '```json\n{"rating": "bullish", "change_my_mind": ["margin < 70%"]}\n```'
    parsed = parse_view_json(raw)
    assert parsed["rating"] == "bullish"
    assert parsed["change_my_mind"] == ["margin < 70%"]


def test_parse_view_json_rejects_unknown_rating():
    parsed = parse_view_json('{"rating": "strong conviction", "change_my_mind": []}')
    assert parsed["rating"] is None


def test_parse_view_json_survives_garbage():
    assert parse_view_json("no json here")["rating"] is None


def test_parse_view_json_survives_malformed_json():
    assert parse_view_json('{"rating": "bullish",,,}')["rating"] is None


class _FakeBlock:
    type = "text"

    def __init__(self, text):
        self.text = text


class _FakeReply:
    def __init__(self, text):
        self.content = [_FakeBlock(text)]


class _FakeMessages:
    def __init__(self, text=None, boom=False):
        self._text = text
        self._boom = boom

    def create(self, **kwargs):
        if self._boom:
            raise RuntimeError("model unavailable")
        return _FakeReply(self._text)


class _FakeClient:
    def __init__(self, text=None, boom=False):
        self.messages = _FakeMessages(text, boom)


def test_extract_view_attaches_only_observed_prices():
    client = _FakeClient('{"rating": "bullish", "change_my_mind": ["margin < 70%"]}')
    calls = [
        {"tool": "get_quote", "args": {"ticker": "NVDA"}},
        {"tool": "compute_metrics", "args": {"ticker": "AAPL"}},
    ]
    view = extract_view(client, "## View\nBullish.", calls, {"NVDA": 180.0}, "m")

    assert view["rating"] == "bullish"
    assert view["tickers"] == ["NVDA", "AAPL"]
    # AAPL was discussed but never quoted, so it carries no recorded price.
    assert view["view_price"] == {"NVDA": 180.0}


def test_extract_view_degrades_when_the_model_call_fails():
    client = _FakeClient(boom=True)
    calls = [{"tool": "get_quote", "args": {"ticker": "NVDA"}}]
    view = extract_view(client, "## View\nBullish.", calls, {"NVDA": 180.0}, "m")

    assert view["rating"] is None
    assert view["tickers"] == ["NVDA"]
