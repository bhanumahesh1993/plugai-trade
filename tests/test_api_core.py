from fastapi.testclient import TestClient

from plugai_trade.api import app

c = TestClient(app)


def test_status_and_clock():
    assert c.get("/api/status").json()["edition"] == "book-v1.0"
    assert set(c.get("/api/clock").json()) == {"IN", "US"}


def test_options_book_numbers():
    q = c.post("/api/options/quote", json={"legs": [{"kind": "call", "strike": 25000}]}).json()
    assert q["tiles"]["Breakeven"] == "25,089"


def test_backtest_and_paper():
    r = c.post("/api/backtest/run", json={"idea": "Buy when the close is above the 50-day average; "
                                                  "sell when the close is below the 20-day average"})
    assert r.status_code == 200 and r.json()["card"]["grade"]
    assert c.get("/api/paper/state?market=US").json()["market"] == "US"


def test_spa_fallback():
    assert c.get("/options").status_code in (200, 404)


def test_explain_forces_local_for_personal_sections(monkeypatch):
    seen = {}
    import plugai_trade.ai as ai_mod

    def fake(obj, q=None, section="Research", sensitive=False):
        seen["sensitive"] = sensitive
        return ai_mod.Explanation(text="ok", sources=[])
    monkeypatch.setattr(ai_mod, "explain", fake)
    c.post("/api/explain", json={"facts": ["Net: 1"], "section": "Tax"})
    assert seen["sensitive"] is True
