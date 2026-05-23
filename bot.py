import logging
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    ContextTypes, MessageHandler, filters,
)
from config import BOT_TOKEN, TOP_SYMBOLS, SIGNAL_INTERVAL_MINUTES, OWNER_ID
from analyzer import analyze, get_price, get_top_buy_opportunities, get_market_summary
from news import get_crypto_news
from positions import add_position, get_positions, remove_position, get_all_positions, update_alert_flags
from currency import get_uzs_rate, usd_to_uzs, format_uzs
from signal_history import save_signal, get_stats, get_active_signals, update_signal_result

logging.basicConfig(format='%(asctime)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

subscribers: set[int] = set()
pending_buy: dict[int, dict] = {}


def fp(price: float) -> str:
    """Format price: USD"""
    if price >= 1:
        return f"${price:,.4f}"
    return f"${price:.8f}"


def fp_uzs(price: float) -> str:
    """Format price: UZS"""
    uzs = usd_to_uzs(price)
    return format_uzs(uzs)


def fp_both(price: float) -> str:
    """USD va UZS birga"""
    return f"`{fp(price)}` ({fp_uzs(price)})"


def min_invest_advice(price: float, sl: float) -> str:
    """Minimal invest tavsiyasi"""
    risk_per_coin = price - sl
    if risk_per_coin <= 0:
        return "~$10"
    # Bir savdoda max $5 yo'qotish uchun minimal invest
    min_10 = (10 / risk_per_coin) * price
    min_50 = (50 / risk_per_coin) * price
    rate = get_uzs_rate()
    return (
        f"Kam xavf: `${min_10:.0f}` ({format_uzs(min_10 * rate)})\n"
        f"   O'rtacha: `${min_50:.0f}` ({format_uzs(min_50 * rate)})"
    )


def pnl_emoji(pct: float) -> str:
    if pct >= 5: return "🚀"
    if pct >= 2: return "📈"
    if pct >= 0: return "🟡"
    if pct >= -3: return "⚠️"
    return "🔴"


def build_analysis_text(data: dict) -> str:
    price = data['price']
    tp = data['take_profit']
    sl = data['stop_loss']
    rr = abs((tp - price) / max(price - sl, 0.0001))

    # Potentsial foydani hisoblash
    potential_pct = ((tp - price) / price) * 100
    potential_uzs_100 = usd_to_uzs((tp - price) / price * 100)   # $100 invest bilan

    lines = [
        f"{data['emoji']} *{data['symbol']}* — {data['action']}",
        f"",
        f"💰 *Hozirgi narx:*",
        f"   {fp_both(price)}",
        f"⏱ Interval: `{data['timeframe']}`",
        "",
        "📊 *Texnik ko'rsatkichlar:*",
    ]
    for s in data['signals']:
        lines.append(f"  {s}")

    lines += [
        "",
        f"🎯 *Maksimal maqsad (Take-Profit):*",
        f"   {fp_both(tp)} (+{potential_pct:.1f}%)",
        f"",
        f"🛑 *Stop-Loss:*",
        f"   {fp_both(sl)}",
        f"⚖️ Risk/Reward: `1:{rr:.1f}`",
        f"",
        f"💵 *Minimal invest tavsiyasi:*",
        f"   {min_invest_advice(price, sl)}",
        f"",
        f"📈 *$100 invest bilan potentsial foyda:*",
        f"   `+${(tp-price)/price*100:.2f}` ({format_uzs(potential_uzs_100)})",
        f"",
        f"🔢 Signal kuchi: `{data['score']}/6`",
        f"🕐 {datetime.now().strftime('%H:%M:%S')}",
    ]
    return "\n".join(lines)


def main_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("💰 Narxni tekshir", callback_data="prices"),
            InlineKeyboardButton("📊 Analiz", callback_data="signals"),
        ],
        [
            InlineKeyboardButton("🚀 BUY imkoniyatlar", callback_data="buy_opps"),
            InlineKeyboardButton("🌍 Bozor holati", callback_data="market"),
        ],
        [
            InlineKeyboardButton("📰 Yangiliklar", callback_data="news"),
            InlineKeyboardButton("💼 Pozitsiyalarim", callback_data="my_positions"),
        ],
        [
            InlineKeyboardButton("📊 Statistika", callback_data="signal_stats"),
            InlineKeyboardButton("🔔 Auto-signal", callback_data="sub_toggle"),
        ],
    ])


def coin_keyboard(action: str) -> InlineKeyboardMarkup:
    rows = []
    row = []
    for sym in TOP_SYMBOLS:
        coin = sym.replace('/USDT', '')
        row.append(InlineKeyboardButton(coin, callback_data=f"{action}_{sym}"))
        if len(row) == 4:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([InlineKeyboardButton("🔙 Orqaga", callback_data="back")])
    return InlineKeyboardMarkup(rows)


def timeframe_keyboard(symbol: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("5 daqiqa", callback_data=f"tf_{symbol}_5m"),
            InlineKeyboardButton("15 daqiqa", callback_data=f"tf_{symbol}_15m"),
            InlineKeyboardButton("1 soat", callback_data=f"tf_{symbol}_1h"),
        ],
        [
            InlineKeyboardButton("4 soat", callback_data=f"tf_{symbol}_4h"),
            InlineKeyboardButton("1 kun", callback_data=f"tf_{symbol}_1d"),
            InlineKeyboardButton("1 hafta", callback_data=f"tf_{symbol}_1w"),
        ],
        [InlineKeyboardButton("🔙 Orqaga", callback_data="back")],
    ])


def is_owner(update: Update) -> bool:
    uid = update.effective_user.id if update.effective_user else 0
    return OWNER_ID == 0 or uid == OWNER_ID


BLOCKED_TEXT = (
    "⛔ Bu bot shaxsiy foydalanish uchun.\n\n"
    "Botga kirish narxi: *$100*\n"
    "Sotib olish uchun: @mavlonov\\_avazbek ga yozing"
)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update):
        await update.message.reply_text(BLOCKED_TEXT, parse_mode='Markdown')
        return
    uid = update.effective_user.id
    rate = get_uzs_rate()
    text = (
        "👋 *Crypto BUY Signal Bot*\n\n"
        f"💱 Kurs: `$1 = {format_uzs(rate)}`\n\n"
        "Real vaqtda kripto bozorini kuzatib, "
        "faqat *sotib olish* imkoniyatlarini topib beradi.\n\n"
        "• 📊 RSI, MACD, EMA, Bollinger tahlili\n"
        "• 💵 Narx USD va UZS da\n"
        "• 🎯 Maksimal maqsad narx\n"
        "• 💡 Minimal invest tavsiyasi\n"
        "• 💼 Pozitsiyani saqlash va kuzatish\n"
        "• ⚠️ Zarar xavfi bo'lsa ogohlantirish\n\n"
        "Quyidagi tugmalardan foydalaning:"
    )
    await update.message.reply_text(text, parse_mode='Markdown', reply_markup=main_keyboard())


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not is_owner(update):
        await query.answer("⛔ Ruxsat yo'q", show_alert=True)
        return
    await query.answer()
    data = query.data
    chat_id = query.message.chat_id

    if data == "back":
        await query.edit_message_text("🏠 *Asosiy menyu*", parse_mode='Markdown', reply_markup=main_keyboard())

    elif data == "prices":
        await query.edit_message_text("💰 *Qaysi koin narxini ko'rmoqchisiz?*",
                                       parse_mode='Markdown', reply_markup=coin_keyboard("price"))

    elif data.startswith("price_"):
        symbol = data[6:]
        p = get_price(symbol)
        if p:
            change = p['change_24h'] or 0
            arrow = "📈" if change >= 0 else "📉"
            rate = get_uzs_rate()
            text = (
                f"💰 *{symbol}*\n\n"
                f"Narx: {fp_both(p['price'])}\n"
                f"{arrow} 24s o'zgarish: `{change:+.2f}%`\n"
                f"📊 24s yuqori: {fp_both(p['high_24h'])}\n"
                f"📊 24s past: {fp_both(p['low_24h'])}\n"
                f"💹 Hajm: `${p['volume_24h']:,.0f}` ({format_uzs(usd_to_uzs(p['volume_24h']))})\n"
                f"💱 Kurs: `$1 = {format_uzs(rate)}`\n\n"
                f"🕐 {datetime.now().strftime('%H:%M:%S')}"
            )
        else:
            text = "❌ Ma'lumot olishda xatolik."
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("🔄 Yangilash", callback_data=f"price_{symbol}"),
            InlineKeyboardButton("📊 Analiz", callback_data=f"coin_{symbol}"),
            InlineKeyboardButton("🔙 Orqaga", callback_data="back"),
        ]])
        await query.edit_message_text(text, parse_mode='Markdown', reply_markup=kb)

    elif data == "signals":
        await query.edit_message_text("📊 *Qaysi koin uchun analiz kerak?*",
                                       parse_mode='Markdown', reply_markup=coin_keyboard("coin"))

    elif data.startswith("coin_"):
        symbol = data[5:]
        await query.edit_message_text(f"⏱ *{symbol}* — vaqt oralig'ini tanlang:",
                                       parse_mode='Markdown', reply_markup=timeframe_keyboard(symbol))

    elif data.startswith("tf_"):
        last = data.rfind("_")
        timeframe = data[last + 1:]
        symbol = data[3:last]
        await query.edit_message_text("⏳ Tahlil qilinmoqda...", parse_mode='Markdown')
        result = analyze(symbol, timeframe)
        if result:
            # Signalni tarixga saqlash
            sig_idx = save_signal(symbol, timeframe, result['price'],
                                   result['take_profit'], result['stop_loss'], result['score'])

            text = build_analysis_text(result)
            # $100 invest bilan foydani ko'rsatish
            for invest in [50, 100, 500]:
                pot = (result['take_profit'] - result['price']) / result['price'] * invest
                text += f"\n💡 ${invest} → `+${pot:.1f}` foyda ({format_uzs(usd_to_uzs(pot))})"

            if result['score'] < 2:
                text += "\n\n⚠️ _Hozir BUY uchun qulay vaqt emas. Kuting._"
            buttons = [[
                InlineKeyboardButton("🔄 Yangilash", callback_data=f"tf_{symbol}_{timeframe}"),
                InlineKeyboardButton("📊 Statistika", callback_data="signal_stats"),
                InlineKeyboardButton("🔙 Orqaga", callback_data="back"),
            ]]
            if result['score'] >= 2:
                buttons.insert(0, [InlineKeyboardButton(
                    "✅ Shu narxda sotib oldim", callback_data=f"bought_{symbol}"
                )])
            await query.edit_message_text(text, parse_mode='Markdown',
                                           reply_markup=InlineKeyboardMarkup(buttons))
        else:
            await query.edit_message_text("❌ Xatolik. Qayta urinib ko'ring.", reply_markup=main_keyboard())

    elif data.startswith("bought_"):
        symbol = data[7:]
        result = analyze(symbol)
        if result:
            pending_buy[chat_id] = {
                "symbol": symbol,
                "buy_price": result['price'],
                "take_profit": result['take_profit'],
                "stop_loss": result['stop_loss'],
            }
            context.user_data['waiting_amount'] = True
            await query.edit_message_text(
                f"💰 *{symbol}*\n"
                f"Narx: {fp_both(result['price'])}\n\n"
                f"Qancha USDT ga sotib oldingiz?\n"
                f"_(Masalan: 50 yoki 100.5)_",
                parse_mode='Markdown'
            )

    elif data == "buy_opps":
        await query.edit_message_text("🔍 Eng yaxshi BUY imkoniyatlar qidirilmoqda...", parse_mode='Markdown')
        buys = get_top_buy_opportunities()
        if buys:
            lines = [f"🚀 *TOP BUY SIGNALLAR* — {datetime.now().strftime('%H:%M')}\n"]
            for i, r in enumerate(buys, 1):
                pot_pct = ((r['take_profit'] - r['price']) / r['price']) * 100
                lines.append(
                    f"{i}. ✅ *{r['symbol']}*\n"
                    f"   💰 {fp_both(r['price'])}\n"
                    f"   🎯 Maqsad: {fp_both(r['take_profit'])} (+{pot_pct:.1f}%)\n"
                    f"   🛑 SL: {fp_both(r['stop_loss'])}\n"
                    f"   💡 Min invest: {min_invest_advice(r['price'], r['stop_loss']).split(chr(10))[0].replace('Kam xavf: ', '')}\n"
                    f"   RSI: {r['rsi']:.1f} | Kuch: {r['score']}/6\n"
                )
            text = "\n".join(lines)
            buttons = []
            for r in buys:
                buttons.append([InlineKeyboardButton(
                    f"✅ {r['symbol']} sotib oldim", callback_data=f"bought_{r['symbol']}"
                )])
            buttons.append([
                InlineKeyboardButton("🔄 Yangilash", callback_data="buy_opps"),
                InlineKeyboardButton("🔙 Orqaga", callback_data="back"),
            ])
        else:
            text = "😐 *Hozircha kuchli BUY signal yo'q.*\n\nBozor neytral. Biroz kuting."
            buttons = [[
                InlineKeyboardButton("🔄 Yangilash", callback_data="buy_opps"),
                InlineKeyboardButton("🔙 Orqaga", callback_data="back"),
            ]]
        await query.edit_message_text(text, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(buttons))

    elif data == "my_positions":
        positions = get_positions(chat_id)
        if not positions:
            text = "💼 *Ochiq pozitsiyalar yo'q.*\n\nSignal bo'yicha sotib olganingizda \"Sotib oldim\" tugmasini bosing."
            kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Orqaga", callback_data="back")]])
        else:
            lines = [f"💼 *Ochiq pozitsiyalar* ({len(positions)} ta)\n"]
            for i, p in enumerate(positions):
                cur = get_price(p['symbol'])
                if cur:
                    cur_price = cur['price']
                    cur_val = p['coins'] * cur_price
                    pnl_usd = cur_val - p['amount_usd']
                    pnl_pct = (pnl_usd / p['amount_usd']) * 100
                    em = pnl_emoji(pnl_pct)
                    lines.append(
                        f"{i+1}. {em} *{p['symbol']}*\n"
                        f"   Kirish: {fp_both(p['buy_price'])}\n"
                        f"   Hozir: {fp_both(cur_price)}\n"
                        f"   Miqdor: `${p['amount_usd']:.1f}` → `${cur_val:.2f}`\n"
                        f"   PnL: `{pnl_usd:+.2f}$` ({format_uzs(usd_to_uzs(abs(pnl_usd)))}) `({pnl_pct:+.1f}%)`\n"
                        f"   🎯 Maqsad: {fp_both(p['take_profit'])}\n"
                        f"   📅 {p['opened_at']}\n"
                    )
                else:
                    lines.append(f"{i+1}. *{p['symbol']}* — narx olinmadi\n")
            text = "\n".join(lines)
            close_buttons = [
                [InlineKeyboardButton(f"❌ {i+1}. {p['symbol']} yopish", callback_data=f"close_pos_{i}")]
                for i, p in enumerate(positions)
            ]
            close_buttons.append([
                InlineKeyboardButton("🔄 Yangilash", callback_data="my_positions"),
                InlineKeyboardButton("🔙 Orqaga", callback_data="back"),
            ])
            kb = InlineKeyboardMarkup(close_buttons)
        await query.edit_message_text(text, parse_mode='Markdown', reply_markup=kb)

    elif data.startswith("close_pos_"):
        idx = int(data[10:])
        positions = get_positions(chat_id)
        if 0 <= idx < len(positions):
            p = positions[idx]
            cur = get_price(p['symbol'])
            if cur:
                cur_price = cur['price']
                pnl_usd = (p['coins'] * cur_price) - p['amount_usd']
                pnl_pct = (pnl_usd / p['amount_usd']) * 100
                em = pnl_emoji(pnl_pct)
                result_text = (
                    f"{em} *{p['symbol']}* pozitsiya yopildi\n\n"
                    f"Kirish: {fp_both(p['buy_price'])}\n"
                    f"Chiqish: {fp_both(cur_price)}\n"
                    f"Natija: `{pnl_usd:+.2f}$` ({format_uzs(usd_to_uzs(pnl_usd))}) `({pnl_pct:+.1f}%)`\n"
                )
            else:
                result_text = f"*{p['symbol']}* pozitsiya yopildi."
            remove_position(chat_id, idx)
            kb = InlineKeyboardMarkup([[
                InlineKeyboardButton("💼 Pozitsiyalarim", callback_data="my_positions"),
                InlineKeyboardButton("🔙 Menyu", callback_data="back"),
            ]])
            await query.edit_message_text(result_text, parse_mode='Markdown', reply_markup=kb)

    elif data == "market":
        await query.edit_message_text("🌍 Bozor tahlil qilinmoqda...", parse_mode='Markdown')
        results = get_market_summary()
        bullish = sum(1 for r in results if r['score'] >= 2)
        bearish = sum(1 for r in results if r['score'] <= -2)
        neutral = len(results) - bullish - bearish
        mood = "🟢 BULLISH — Sotib olish vaqti!" if bullish > bearish else \
               "🔴 BEARISH — Ehtiyot bo'ling" if bearish > bullish else "🟡 NEYTRAL — Kuting"
        rate = get_uzs_rate()
        lines = [
            f"🌍 *Bozor holati:* {mood}\n",
            f"💱 Kurs: `$1 = {format_uzs(rate)}`\n",
            f"🟢 BUY signal: *{bullish}* ta",
            f"🟡 Neytral: *{neutral}* ta",
            f"🔴 Pastga: *{bearish}* ta\n",
            "🚀 *BUY uchun tayyor koinlar:*",
        ]
        for r in [x for x in results if x['score'] >= 2][:6]:
            pot = ((r['take_profit'] - r['price']) / r['price']) * 100
            lines.append(
                f"  ✅ *{r['symbol']}*: {fp_both(r['price'])}\n"
                f"     🎯 Maqsad: {fp_both(r['take_profit'])} (+{pot:.1f}%)"
            )
        if not any(r['score'] >= 2 for r in results):
            lines.append("  😐 Hozircha yo'q")
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("🔄 Yangilash", callback_data="market"),
            InlineKeyboardButton("🔙 Orqaga", callback_data="back"),
        ]])
        await query.edit_message_text("\n".join(lines), parse_mode='Markdown', reply_markup=kb)

    elif data == "news":
        await query.edit_message_text("📰 Yangiliklar yuklanmoqda...", parse_mode='Markdown')
        news = get_crypto_news(5)
        if news:
            lines = ["📰 *So'nggi kripto yangiliklari:*\n"]
            for i, n in enumerate(news, 1):
                lines.append(f"{i}. [{n['title'][:75]}...]({n['url']})\n   📌 _{n['source']}_\n")
            text = "\n".join(lines)
        else:
            text = "❌ Yangiliklar yuklanmadi."
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("🔄 Yangilash", callback_data="news"),
            InlineKeyboardButton("🔙 Orqaga", callback_data="back"),
        ]])
        await query.edit_message_text(text, parse_mode='Markdown', reply_markup=kb, disable_web_page_preview=True)

    elif data == "signal_stats":
        stats = get_stats()
        if stats['closed'] == 0:
            text = (
                "📊 *Signal statistikasi*\n\n"
                "Hali yopilgan signal yo'q.\n"
                f"🟡 Faol signallar: *{stats['active']}* ta\n\n"
                "_Signallar TP yoki SL ga tegishi bilan natija chiqadi._"
            )
        else:
            bar_w = round(stats['win_rate'] / 10)
            bar = "🟢" * bar_w + "🔴" * (10 - bar_w)
            text_lines = [
                "📊 *Signal statistikasi*\n",
                f"{bar}",
                f"🎯 To'g'ri signal: *{stats['win_rate']:.1f}%* ({stats['wins']}/{stats['closed']})\n",
                f"✅ G'alaba: *{stats['wins']}* ta | avg +{stats['avg_win']:.1f}%",
                f"❌ Zarar: *{stats['losses']}* ta | avg {stats['avg_loss']:.1f}%",
                f"🟡 Faol: *{stats['active']}* ta\n",
                "🕐 *Oxirgi signallar:*",
            ]
            for s in stats['recent'][:7]:
                if s['result'] == 'WIN':
                    icon = "✅"
                    res = f"+{s['profit_pct']:.1f}%"
                elif s['result'] == 'LOSS':
                    icon = "❌"
                    res = f"{s['profit_pct']:.1f}%"
                else:
                    icon = "🟡"
                    res = "faol"
                text_lines.append(f"  {icon} *{s['symbol']}* ({s['timeframe']}) — {res} | {s['created_at'][:10]}")
            text = "\n".join(text_lines)
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("🔄 Yangilash", callback_data="signal_stats"),
            InlineKeyboardButton("🔙 Orqaga", callback_data="back"),
        ]])
        await query.edit_message_text(text, parse_mode='Markdown', reply_markup=kb)

    elif data == "sub_toggle":
        if chat_id in subscribers:
            subscribers.discard(chat_id)
            msg = "🔕 Auto-signal *o'chirildi*."
        else:
            subscribers.add(chat_id)
            msg = (
                f"🔔 Auto-signal *yoqildi!*\n\n"
                f"Har *{SIGNAL_INTERVAL_MINUTES} daqiqada* kuchli BUY signallar yuboriladi.\n"
                "Signal yo'q bo'lsa xabar kelmaydi."
            )
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Orqaga", callback_data="back")]])
        await query.edit_message_text(msg, parse_mode='Markdown', reply_markup=kb)


async def amount_input_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update):
        await update.message.reply_text(BLOCKED_TEXT, parse_mode='Markdown')
        return
    chat_id = update.message.chat_id
    if chat_id not in pending_buy:
        return
    text = update.message.text.strip().replace(",", ".")
    try:
        amount_usd = float(text)
        if amount_usd <= 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text(
            "❌ Noto'g'ri miqdor. Faqat raqam kiriting. Masalan: `50` yoki `120.5`",
            parse_mode='Markdown'
        )
        return
    info = pending_buy.pop(chat_id)
    add_position(
        chat_id=chat_id,
        symbol=info['symbol'],
        buy_price=info['buy_price'],
        amount_usd=amount_usd,
        take_profit=info['take_profit'],
        stop_loss=info['stop_loss'],
    )
    coins = amount_usd / info['buy_price']
    pot_usd = (info['take_profit'] - info['buy_price']) / info['buy_price'] * amount_usd
    await update.message.reply_text(
        f"✅ *Pozitsiya saqlandi!*\n\n"
        f"🪙 *{info['symbol']}*\n"
        f"💰 Kirish narxi: {fp_both(info['buy_price'])}\n"
        f"💵 Miqdor: `${amount_usd:.2f}` ({format_uzs(usd_to_uzs(amount_usd))})\n"
        f"🪙 Koin: `{coins:.6f}`\n"
        f"🎯 Maqsad: {fp_both(info['take_profit'])}\n"
        f"📈 Potentsial foyda: `+${pot_usd:.2f}` ({format_uzs(usd_to_uzs(pot_usd))})\n"
        f"🛑 Stop-Loss: {fp_both(info['stop_loss'])}\n\n"
        f"Narx o'zgarganda sizga xabar beraman! 🔔",
        parse_mode='Markdown',
        reply_markup=main_keyboard()
    )


async def auto_signal_job(context: ContextTypes.DEFAULT_TYPE):
    if not subscribers:
        return
    buys = get_top_buy_opportunities()
    if not buys:
        return
    lines = [f"⚡ *BUY SIGNAL* — {datetime.now().strftime('%H:%M')}\n"]
    for r in buys[:4]:
        pot_pct = ((r['take_profit'] - r['price']) / r['price']) * 100
        lines.append(
            f"✅ *{r['symbol']}*\n"
            f"   💰 {fp_both(r['price'])}\n"
            f"   🎯 {fp_both(r['take_profit'])} (+{pot_pct:.1f}%)\n"
            f"   🛑 {fp_both(r['stop_loss'])}\n"
        )
    text = "\n".join(lines)
    buttons = [[InlineKeyboardButton(f"✅ {r['symbol']} sotib oldim", callback_data=f"bought_{r['symbol']}")]
               for r in buys[:4]]
    buttons.append([InlineKeyboardButton("💼 Pozitsiyalarim", callback_data="my_positions")])
    for chat_id in list(subscribers):
        try:
            await context.bot.send_message(chat_id, text, parse_mode='Markdown',
                                            reply_markup=InlineKeyboardMarkup(buttons))
        except Exception as e:
            logger.warning(f"Chat {chat_id}: {e}")
            subscribers.discard(chat_id)


async def signal_result_tracker_job(context: ContextTypes.DEFAULT_TYPE):
    """Faol signallarni kuzatib TP yoki SL ga tegishini belgilash"""
    active = get_active_signals()
    for idx, sig in active:
        cur = get_price(sig['symbol'])
        if not cur:
            continue
        cur_price = cur['price']
        if cur_price >= sig['tp']:
            update_signal_result(idx, "WIN", cur_price)
        elif cur_price <= sig['sl']:
            update_signal_result(idx, "LOSS", cur_price)


async def position_monitor_job(context: ContextTypes.DEFAULT_TYPE):
    all_data = get_all_positions()
    for str_chat_id, positions in all_data.items():
        chat_id = int(str_chat_id)
        for i, p in enumerate(positions):
            cur = get_price(p['symbol'])
            if not cur:
                continue
            cur_price = cur['price']
            pnl_pct = ((cur_price - p['buy_price']) / p['buy_price']) * 100
            pnl_usd = p['coins'] * cur_price - p['amount_usd']
            sl_dist_pct = ((cur_price - p['stop_loss']) / p['buy_price']) * 100

            if not p.get('alerted_sl') and sl_dist_pct <= 5:
                msg = (
                    f"🚨 *ZARAR OGOHLANTIRISH!*\n\n"
                    f"*{p['symbol']}* stop-loss ga yaqinlashdi!\n\n"
                    f"📉 Hozir: {fp_both(cur_price)}\n"
                    f"🛑 Stop-Loss: {fp_both(p['stop_loss'])}\n"
                    f"📏 Masofa: `{sl_dist_pct:.1f}%`\n"
                    f"💸 PnL: `{pnl_usd:+.2f}$` ({format_uzs(usd_to_uzs(pnl_usd))}) `({pnl_pct:+.1f}%)`\n\n"
                    f"⚠️ *Sotishni ko'rib chiqing!*"
                )
                kb = InlineKeyboardMarkup([[
                    InlineKeyboardButton(f"❌ {p['symbol']} yopish", callback_data=f"close_pos_{i}"),
                    InlineKeyboardButton("💼 Pozitsiyalar", callback_data="my_positions"),
                ]])
                try:
                    await context.bot.send_message(chat_id, msg, parse_mode='Markdown', reply_markup=kb)
                    update_alert_flags(chat_id, i, sl=True)
                except Exception as e:
                    logger.warning(f"Monitor {chat_id}: {e}")

            elif not p.get('alerted_tp') and cur_price >= p['take_profit']:
                msg = (
                    f"🎯 *MAQSAD NARXGA YETDI!*\n\n"
                    f"*{p['symbol']}* take-profit ga yetdi!\n\n"
                    f"📈 Hozir: {fp_both(cur_price)}\n"
                    f"🎯 Maqsad: {fp_both(p['take_profit'])}\n"
                    f"💰 Foyda: `+{pnl_usd:.2f}$` ({format_uzs(usd_to_uzs(pnl_usd))}) `({pnl_pct:+.1f}%)`\n\n"
                    f"✅ *Sotishni ko'rib chiqing!*"
                )
                kb = InlineKeyboardMarkup([[
                    InlineKeyboardButton(f"✅ {p['symbol']} yopish (foyda)", callback_data=f"close_pos_{i}"),
                ]])
                try:
                    await context.bot.send_message(chat_id, msg, parse_mode='Markdown', reply_markup=kb)
                    update_alert_flags(chat_id, i, tp=True)
                except Exception as e:
                    logger.warning(f"Monitor tp {chat_id}: {e}")

            elif cur_price < p['stop_loss'] and not p.get('alerted_sl'):
                msg = (
                    f"🔴 *STOP-LOSS OSHDI!*\n\n"
                    f"*{p['symbol']}* SL dan past tushdi!\n\n"
                    f"📉 Hozir: {fp_both(cur_price)}\n"
                    f"🛑 Stop-Loss: {fp_both(p['stop_loss'])}\n"
                    f"💸 Zarar: `{pnl_usd:+.2f}$` ({format_uzs(usd_to_uzs(abs(pnl_usd)))}) `({pnl_pct:+.1f}%)`\n\n"
                    f"❗ *Zudlik bilan sotishni ko'rib chiqing!*"
                )
                kb = InlineKeyboardMarkup([[
                    InlineKeyboardButton(f"❌ {p['symbol']} yopish", callback_data=f"close_pos_{i}"),
                ]])
                try:
                    await context.bot.send_message(chat_id, msg, parse_mode='Markdown', reply_markup=kb)
                    update_alert_flags(chat_id, i, sl=True)
                except Exception as e:
                    logger.warning(f"Monitor sl {chat_id}: {e}")


async def myid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    await update.message.reply_text(f"Sizning ID ingiz: `{uid}`", parse_mode='Markdown')


def main():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("myid", myid))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, amount_input_handler))
    app.job_queue.run_repeating(auto_signal_job, interval=SIGNAL_INTERVAL_MINUTES * 60, first=60)
    app.job_queue.run_repeating(position_monitor_job, interval=5 * 60, first=30)
    app.job_queue.run_repeating(signal_result_tracker_job, interval=10 * 60, first=120)
    logger.info("Bot ishga tushdi!")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
