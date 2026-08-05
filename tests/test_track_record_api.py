"""The track-record endpoint's response shape."""

from fastapi.testclient import TestClient

from backend.app import app


def test_track_record_endpoint_returns_summary_shape():
    client = TestClient(app)
    body = client.get("/api/track-record").json()

    assert set(body) >= {"summary", "rows", "as_of"}
    assert set(body["summary"]) == {"total", "resolved", "correct"}
    assert isinstance(body["rows"], list)
    assert body["as_of"].endswith("Z")
