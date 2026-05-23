import json
import os
from datetime import datetime

FILE = "positions.json"


def _load() -> dict:
    if os.path.exists(FILE):
        with open(FILE) as f:
            return json.load(f)
    return {}


def _save(data: dict):
    with open(FILE, "w") as f:
        json.dump(data, f, indent=2)


def add_position(chat_id: int, symbol: str, buy_price: float, amount_usd: float, take_profit: float, stop_loss: float):
    data = _load()
    key = str(chat_id)
    if key not in data:
        data[key] = []
    data[key].append({
        "symbol": symbol,
        "buy_price": buy_price,
        "amount_usd": amount_usd,
        "coins": amount_usd / buy_price,
        "take_profit": take_profit,
        "stop_loss": stop_loss,
        "opened_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "alerted_sl": False,   # stop-loss ogohlantirish yuborildimi
        "alerted_tp": False,   # take-profit ogohlantirish yuborildimi
    })
    _save(data)


def get_positions(chat_id: int) -> list:
    data = _load()
    return data.get(str(chat_id), [])


def remove_position(chat_id: int, index: int):
    data = _load()
    key = str(chat_id)
    if key in data and 0 <= index < len(data[key]):
        data[key].pop(index)
        _save(data)


def update_alert_flags(chat_id: int, index: int, sl: bool = None, tp: bool = None):
    data = _load()
    key = str(chat_id)
    if key in data and 0 <= index < len(data[key]):
        if sl is not None:
            data[key][index]["alerted_sl"] = sl
        if tp is not None:
            data[key][index]["alerted_tp"] = tp
        _save(data)


def get_all_positions() -> dict:
    return _load()
