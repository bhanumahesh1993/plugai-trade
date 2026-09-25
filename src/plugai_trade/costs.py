"""Trading costs, India and US, from the dated reference tables.

The same numbers the book prints in Chapters 11, 14 and 21. Every function
returns an itemised dict so screens can show the "Cost preview" line by line.
"""

from __future__ import annotations

from .reference import lookup

PROFILES = ("IN-equity-delivery", "IN-equity-intraday", "IN-futures", "IN-options",
            "US-equity", "US-options")


def _r(x: float) -> float:
    return round(x + 0.0, 2)


def india_round_trip(buy_value: float, sell_value: float, kind: str = "delivery",
                     orders: int = 2) -> dict[str, float]:
    """Charges for one buy + one sell in India. kind: delivery|intraday|futures|options."""
    c = lookup("india.charges")
    stt_key = {"delivery": "delivery", "intraday": "intraday", "futures": "futures",
               "options": "options_premium"}[kind]
    stt_rates = c["stt"][stt_key]
    stt = buy_value * stt_rates.get("buy", 0.0) + sell_value * stt_rates.get("sell", 0.0)
    ex_key = {"delivery": "equity", "intraday": "equity", "futures": "futures",
              "options": "options_premium"}[kind]
    turnover = buy_value + sell_value
    exchange = turnover * c["exchange_txn"][ex_key]
    sebi = turnover * c["sebi_per_crore"] / 1e7
    stamp = buy_value * c["stamp_buy"][{"options": "options"}.get(kind, kind)]
    brokerage = 0.0 if kind == "delivery" else c["brokerage_per_order"] * orders
    gst = (brokerage + exchange + sebi) * c["gst"]
    dp = c["dp_charge_per_scrip_sell"] if kind == "delivery" else 0.0
    items = {"brokerage": brokerage, "stt": stt, "exchange": exchange, "sebi": sebi,
             "stamp": stamp, "gst": gst, "dp": dp}
    items = {k: _r(v) for k, v in items.items()}
    items["total"] = _r(sum(items.values()))
    return items


def us_round_trip(buy_value: float, sell_value: float, contracts: int = 0,
                  spread_cost: float = 0.0) -> dict[str, float]:
    """Charges for one buy + one sell in the US (commission-free equities)."""
    c = lookup("us.charges")
    commission = c["commission_per_trade"] * 2
    options_fee = c["options_contract_fee"] * contracts * 2
    regulatory = sell_value * c["regulatory_per_dollar_sold"]
    items = {"commission": commission, "options_fees": options_fee,
             "regulatory": regulatory, "spread": spread_cost}
    items = {k: _r(v) for k, v in items.items()}
    items["total"] = _r(sum(items.values()))
    return items


def round_trip(profile: str, buy_value: float, sell_value: float, **kw) -> dict[str, float]:
    if profile.startswith("IN-"):
        kind = {"IN-equity-delivery": "delivery", "IN-equity-intraday": "intraday",
                "IN-futures": "futures", "IN-options": "options"}[profile]
        return india_round_trip(buy_value, sell_value, kind)
    return us_round_trip(buy_value, sell_value, **kw)


def rate(profile: str) -> float:
    """Approximate round-trip cost as a fraction of notional (for vectorised backtests)."""
    notional = 1_000_000.0
    return round_trip(profile, notional, notional)["total"] / notional
