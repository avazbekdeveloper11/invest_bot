import ccxt
import pandas as pd
import ta
from datetime import datetime

exchange = ccxt.binance({'enableRateLimit': True})


def get_ohlcv(symbol: str, timeframe: str = '15m', limit: int = 200) -> pd.DataFrame | None:
    try:
        ohlcv = exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
        df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        return df
    except Exception:
        return None


def get_price(symbol: str) -> dict | None:
    try:
        ticker = exchange.fetch_ticker(symbol)
        return {
            'price': ticker['last'],
            'change_24h': ticker['percentage'],
            'high_24h': ticker['high'],
            'low_24h': ticker['low'],
            'volume_24h': ticker['quoteVolume'],
        }
    except Exception:
        return None


def analyze(symbol: str, timeframe: str = '15m') -> dict | None:
    df = get_ohlcv(symbol, timeframe, limit=150)
    if df is None or len(df) < 50:
        return None

    close = df['close']
    high = df['high']
    low = df['low']
    volume = df['volume']

    # RSI
    rsi = ta.momentum.RSIIndicator(close, window=14).rsi().iloc[-1]

    # MACD
    macd_ind = ta.trend.MACD(close)
    macd = macd_ind.macd().iloc[-1]
    macd_signal = macd_ind.macd_signal().iloc[-1]
    macd_hist = macd_ind.macd_diff().iloc[-1]

    # EMA
    ema20 = ta.trend.EMAIndicator(close, window=20).ema_indicator().iloc[-1]
    ema50 = ta.trend.EMAIndicator(close, window=50).ema_indicator().iloc[-1]

    # Bollinger Bands
    bb = ta.volatility.BollingerBands(close, window=20, window_dev=2)
    bb_upper = bb.bollinger_hband().iloc[-1]
    bb_lower = bb.bollinger_lband().iloc[-1]

    # ATR (stop-loss/take-profit uchun)
    atr = ta.volatility.AverageTrueRange(high, low, close, window=14).average_true_range().iloc[-1]

    price = close.iloc[-1]

    # Volume analiz
    avg_volume = volume.tail(20).mean()
    cur_volume = volume.iloc[-1]
    volume_surge = cur_volume > avg_volume * 1.5

    # Signal hisoblash
    score = 0
    signals = []

    # RSI
    if rsi < 30:
        score += 2
        signals.append(f"📉 RSI={rsi:.1f} — Oversold (Sotib olish!)")
    elif rsi < 40:
        score += 1
        signals.append(f"📊 RSI={rsi:.1f} — Pastda")
    elif rsi > 70:
        score -= 2
        signals.append(f"📈 RSI={rsi:.1f} — Overbought (Sotish!)")
    elif rsi > 60:
        score -= 1
        signals.append(f"📊 RSI={rsi:.1f} — Balandda")
    else:
        signals.append(f"📊 RSI={rsi:.1f} — Neytral")

    # MACD
    if macd > macd_signal and macd_hist > 0:
        score += 2
        signals.append("🟢 MACD — Yuqoriga kesib o'tdi (Bullish)")
    elif macd < macd_signal and macd_hist < 0:
        score -= 2
        signals.append("🔴 MACD — Pastga kesib o'tdi (Bearish)")
    else:
        signals.append("⚪ MACD — Neytral")

    # EMA
    if ema20 > ema50 and price > ema20:
        score += 1
        signals.append("🟢 EMA20 > EMA50 — Trend yuqori")
    elif ema20 < ema50 and price < ema20:
        score -= 1
        signals.append("🔴 EMA20 < EMA50 — Trend pastki")

    # Bollinger Bands
    if price <= bb_lower:
        score += 1
        signals.append("💙 BB pastki — Bounce kutilmoqda")
    elif price >= bb_upper:
        score -= 1
        signals.append("🔴 BB yuqori — Qaytish kutilmoqda")

    if volume_surge:
        signals.append(f"🔥 Hajm surge! ({cur_volume/avg_volume:.1f}x o'rtacha)")

    # Yakuniy qaror
    if score >= 4:
        action = "🚀 KUCHLI SOTIB OL"
        emoji = "🟢"
    elif score >= 2:
        action = "✅ SOTIB OL"
        emoji = "🟢"
    elif score <= -4:
        action = "⚠️ KUCHLI SOT"
        emoji = "🔴"
    elif score <= -2:
        action = "❌ SOT"
        emoji = "🔴"
    else:
        action = "⏳ KUTING / NEYTRAL"
        emoji = "🟡"

    stop_loss = price - (atr * 1.5)
    take_profit = price + (atr * 2.5)

    return {
        'symbol': symbol,
        'price': price,
        'rsi': rsi,
        'macd': macd,
        'macd_signal': macd_signal,
        'ema20': ema20,
        'ema50': ema50,
        'bb_upper': bb_upper,
        'bb_lower': bb_lower,
        'score': score,
        'action': action,
        'emoji': emoji,
        'signals': signals,
        'stop_loss': stop_loss,
        'take_profit': take_profit,
        'volume_surge': volume_surge,
        'timeframe': timeframe,
    }


def get_market_summary() -> list[dict]:
    from config import TOP_SYMBOLS
    results = []
    for symbol in TOP_SYMBOLS:
        try:
            result = analyze(symbol)
            if result:
                results.append(result)
        except Exception:
            continue
    results.sort(key=lambda x: abs(x['score']), reverse=True)
    return results


def get_top_buy_opportunities() -> list[dict]:
    results = get_market_summary()
    return [r for r in results if r['score'] >= 2][:5]
