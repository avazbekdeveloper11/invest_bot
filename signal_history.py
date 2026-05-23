import json
import os
from datetime import datetime

FILE = "signal_history.json"


def _load() -> list:
    if os.path.exists(FILE):
        with open(FILE) as f:
            return json.load(f)
    return []


def _save(data: list):
    with open(FILE, "w") as f:
        json.dump(data, f, indent=2)


def save_signal(symbol: str, timeframe: str, entry: float, tp: float, sl: float, score: int):
    data = _load()
    data.append({
        "id": len(data) + 1,
        "symbol": symbol,
        "timeframe": timeframe,
        "entry": entry,
        "tp": tp,
        "sl": sl,
        "score": score,
        "result": None,       # "WIN" | "LOSS" | "ACTIVE"
        "exit_price": None,
        "profit_pct": None,
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "closed_at": None,
    })
    _save(data)
    return len(data) - 1   # index


def update_signal_result(index: int, result: str, exit_price: float):
    data = _load()
    if 0 <= index < len(data):
        entry = data[index]["entry"]
        profit_pct = ((exit_price - entry) / entry) * 100
        data[index]["result"] = result
        data[index]["exit_price"] = exit_price
        data[index]["profit_pct"] = profit_pct
        data[index]["closed_at"] = datetime.now().strftime("%Y-%m-%d %H:%M")
        _save(data)


def get_stats() -> dict:
    data = _load()
    closed = [s for s in data if s["result"] in ("WIN", "LOSS")]
    wins = [s for s in closed if s["result"] == "WIN"]
    losses = [s for s in closed if s["result"] == "LOSS"]
    active = [s for s in data if s["result"] is None]

    win_rate = (len(wins) / len(closed) * 100) if closed else 0
    avg_win = sum(s["profit_pct"] for s in wins) / len(wins) if wins else 0
    avg_loss = sum(s["profit_pct"] for s in losses) / len(losses) if losses else 0

    # Oxirgi 10 ta signal
    recent = data[-10:][::-1]

    return {
        "total": len(data),
        "closed": len(closed),
        "wins": len(wins),
        "losses": len(losses),
        "active": len(active),
        "win_rate": win_rate,
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "recent": recent,
    }


def get_active_signals() -> list:
    data = _load()
    return [(i, s) for i, s in enumerate(data) if s["result"] is None]


def get_all() -> list:
    return _load()
