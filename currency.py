import requests

_cached_rate: float = 12800.0
_cache_time: float = 0.0

def get_uzs_rate() -> float:
    """USD → UZS kursini olish (cache: 1 soat)"""
    import time
    global _cached_rate, _cache_time
    if time.time() - _cache_time < 3600:
        return _cached_rate
    try:
        resp = requests.get(
            "https://cdn.jsdelivr.net/npm/@fawazahmed0/currency-api@latest/v1/currencies/usd.json",
            timeout=5
        )
        if resp.status_code == 200:
            rate = resp.json().get("usd", {}).get("uzs")
            if rate:
                _cached_rate = float(rate)
                _cache_time = time.time()
    except Exception:
        pass
    return _cached_rate


def usd_to_uzs(usd: float) -> float:
    return usd * get_uzs_rate()


def format_uzs(amount: float) -> str:
    if amount >= 1_000_000:
        return f"{amount/1_000_000:.2f} mln so'm"
    if amount >= 1_000:
        return f"{amount:,.0f} so'm"
    return f"{amount:.1f} so'm"
