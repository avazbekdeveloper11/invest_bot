import logging
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    ContextTypes,
)
from config import BOT_TOKEN, TOP_SYMBOLS, SIGNAL_INTERVAL_MINUTES
from analyzer import analyze, get_top_buy_opportunities, get_market_summary
from news import get_crypto_news

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

subscribers: set[int] = set()


def format_price(price: float) -> str:
    if price >= 1:
        return f"${price:,.4f}"
    return f"${price:.8f}"


def build_analysis_text(data: dict) -> str:
    price_str = format_price(data['price'])
    tp_str = format_price(data['take_profit'])
    sl_str = format_price(data['stop_loss'])
    rr = abs((data['take_profit'] - data['price']) / max(data['price'] - data['stop_loss'], 0.0001))

    lines = [
        f"{data['emoji']} *{data['symbol']}* — {data['action']}",
        f"💰 Narx: `{price_str}`",
        f"⏱ Interval: `{data['timeframe']}`",
        "",
        "📊 *Texnik ko'rsatkichlar:*",
    ]
    for s in data['signals']:
        lines.append(f"  {s}")
    lines += [
        "",
        f"🎯 Take-Profit: `{tp_str}`",
        f"🛑 Stop-Loss: `{sl_str}`",
        f"⚖️ Risk/Reward: `1:{rr:.1f}`",
        f"🔢 Signal kuchi: `{data['score']}/6`",
        "",
        f"🕐 {datetime.now().strftime('%H:%M:%S')}",
    ]
    return "\n".join(lines)


def main_keyboard() -> InlineKeyboardMarkup:
    buttons = [
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
            InlineKeyboardButton("🔔 Auto-signal", callback_data="sub_toggle"),
        ],
    ]
    return InlineKeyboardMarkup(buttons)


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
    tfs = [('5m', '5 daqiqa'), ('15m', '15 daqiqa'), ('1h', '1 soat'), ('4h', '4 soat')]
    buttons = [[InlineKeyboardButton(label, callback_data=f"tf_{symbol}_{tf}") for tf, label in tfs]]
    buttons.append([InlineKeyboardButton("🔙 Orqaga", callback_data="back")])
    return InlineKeyboardMarkup(buttons)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "👋 *Crypto BUY Signal Bot*\n\n"
        "Real vaqtda kripto bozorini kuzatib, "
        "faqat *sotib olish* imkoniyatlarini topib beradi.\n\n"
        "• 📊 RSI, MACD, EMA, Bollinger tahlili\n"
        "• 🎯 Take-Profit va Stop-Loss avtomatik\n"
        "• 🔔 Har 15 daqiqada yangi BUY signal\n"
        "• 20 ta top koin kuzatiladi\n\n"
        "Quyidagi tugmalardan foydalaning:"
    )
    await update.message.reply_text(text, parse_mode='Markdown', reply_markup=main_keyboard())


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "back":
        await query.edit_message_text(
            "🏠 *Asosiy menyu*",
            parse_mode='Markdown',
            reply_markup=main_keyboard()
        )

    elif data == "prices":
        await query.edit_message_text(
            "💰 *Qaysi koin narxini ko'rmoqchisiz?*",
            parse_mode='Markdown',
            reply_markup=coin_keyboard("price")
        )

    elif data.startswith("price_"):
        symbol = data[6:]
        from analyzer import get_price
        p = get_price(symbol)
        if p:
            change = p['change_24h'] or 0
            arrow = "📈" if change >= 0 else "📉"
            text = (
                f"💰 *{symbol}*\n\n"
                f"Narx: `{format_price(p['price'])}`\n"
                f"{arrow} 24s o'zgarish: `{change:+.2f}%`\n"
                f"📊 24s yuqori: `{format_price(p['high_24h'])}`\n"
                f"📊 24s past: `{format_price(p['low_24h'])}`\n"
                f"💹 Hajm: `${p['volume_24h']:,.0f}`\n\n"
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
        await query.edit_message_text(
            "📊 *Qaysi koin uchun analiz kerak?*",
            parse_mode='Markdown',
            reply_markup=coin_keyboard("coin")
        )

    elif data.startswith("coin_"):
        symbol = data[5:]
        await query.edit_message_text(
            f"⏱ *{symbol}* — vaqt oralig'ini tanlang:",
            parse_mode='Markdown',
            reply_markup=timeframe_keyboard(symbol)
        )

    elif data.startswith("tf_"):
        last_underscore = data.rfind("_")
        timeframe = data[last_underscore + 1:]
        symbol = data[3:last_underscore]

        await query.edit_message_text("⏳ Tahlil qilinmoqda...", parse_mode='Markdown')
        result = analyze(symbol, timeframe)
        if result:
            text = build_analysis_text(result)
            # Faqat BUY bo'lsa alohida eslatma
            if result['score'] < 2:
                text += "\n\n⚠️ _Hozir BUY uchun qulay vaqt emas. Kuting._"
            kb = InlineKeyboardMarkup([[
                InlineKeyboardButton("🔄 Yangilash", callback_data=f"tf_{symbol}_{timeframe}"),
                InlineKeyboardButton("🔙 Orqaga", callback_data="back"),
            ]])
            await query.edit_message_text(text, parse_mode='Markdown', reply_markup=kb)
        else:
            await query.edit_message_text("❌ Xatolik. Qayta urinib ko'ring.", reply_markup=main_keyboard())

    elif data == "buy_opps":
        await query.edit_message_text("🔍 Eng yaxshi BUY imkoniyatlar qidirilmoqda...", parse_mode='Markdown')
        buys = get_top_buy_opportunities()
        if buys:
            lines = [f"🚀 *TOP BUY SIGNALLAR* — {datetime.now().strftime('%H:%M')}\n"]
            for i, r in enumerate(buys, 1):
                lines.append(
                    f"{i}. ✅ *{r['symbol']}*\n"
                    f"   💰 {format_price(r['price'])}\n"
                    f"   🎯 TP: {format_price(r['take_profit'])} | 🛑 SL: {format_price(r['stop_loss'])}\n"
                    f"   RSI: {r['rsi']:.1f} | Kuch: {r['score']}/6\n"
                )
            text = "\n".join(lines)
        else:
            text = (
                "😐 *Hozircha kuchli BUY signal yo'q.*\n\n"
                "Bozor neytral yoki pastga ketmoqda.\n"
                "Biroz kuting va qayta tekshiring."
            )
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("🔄 Yangilash", callback_data="buy_opps"),
            InlineKeyboardButton("🔙 Orqaga", callback_data="back"),
        ]])
        await query.edit_message_text(text, parse_mode='Markdown', reply_markup=kb)

    elif data == "market":
        await query.edit_message_text("🌍 Bozor tahlil qilinmoqda...", parse_mode='Markdown')
        results = get_market_summary()
        bullish = sum(1 for r in results if r['score'] >= 2)
        bearish = sum(1 for r in results if r['score'] <= -2)
        neutral = len(results) - bullish - bearish

        mood = "🟢 BULLISH — Sotib olish vaqti!" if bullish > bearish else \
               "🔴 BEARISH — Ehtiyot bo'ling" if bearish > bullish else \
               "🟡 NEYTRAL — Kuting"

        lines = [
            f"🌍 *Bozor holati:* {mood}\n",
            f"🟢 BUY signal: *{bullish}* ta koin",
            f"🟡 Neytral: *{neutral}* ta koin",
            f"🔴 Pastga: *{bearish}* ta koin\n",
            "🚀 *BUY uchun tayyor koinlar:*",
        ]
        buy_ready = [r for r in results if r['score'] >= 2][:8]
        if buy_ready:
            for r in buy_ready:
                lines.append(f"  ✅ *{r['symbol']}*: {format_price(r['price'])} | Ball: {r['score']}")
        else:
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
        await query.edit_message_text(text, parse_mode='Markdown', reply_markup=kb,
                                       disable_web_page_preview=True)

    elif data == "sub_toggle":
        chat_id = query.message.chat_id
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


async def auto_signal_job(context: ContextTypes.DEFAULT_TYPE):
    if not subscribers:
        return
    buys = get_top_buy_opportunities()
    if not buys:
        return

    lines = [f"⚡ *BUY SIGNAL* — {datetime.now().strftime('%H:%M')}\n"]
    for r in buys[:4]:
        lines.append(
            f"✅ *{r['symbol']}*\n"
            f"   💰 {format_price(r['price'])} | 🎯 {format_price(r['take_profit'])} | 🛑 {format_price(r['stop_loss'])}\n"
            f"   RSI: {r['rsi']:.1f} | Kuch: {r['score']}/6\n"
        )

    text = "\n".join(lines)
    for chat_id in list(subscribers):
        try:
            await context.bot.send_message(chat_id, text, parse_mode='Markdown', reply_markup=main_keyboard())
        except Exception as e:
            logger.warning(f"Chat {chat_id}: {e}")
            subscribers.discard(chat_id)


def main():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.job_queue.run_repeating(auto_signal_job, interval=SIGNAL_INTERVAL_MINUTES * 60, first=60)
    logger.info("Bot ishga tushdi!")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
