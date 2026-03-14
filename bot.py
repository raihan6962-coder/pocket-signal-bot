import logging
import asyncio
import threading
import os
import yfinance as yf
from datetime import datetime
from flask import Flask
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler, ContextTypes
)

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")

logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO)

flask_app = Flask(__name__)

@flask_app.route("/")
def home():
    return "✅ Signal Bot is Running!"

def run_flask():
    flask_app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))

PAIRS = {
    "BTC/USD 🪙": "BTC-USD",
    "ETH/USD 🔷": "ETH-USD",
    "EUR/USD 💶": "EURUSD=X",
    "GBP/USD 💷": "GBPUSD=X",
    "USD/JPY 💴": "JPY=X",
    "AUD/USD 🦘": "AUDUSD=X",
    "Gold 🥇":    "GC=F",
    "Oil 🛢️":     "CL=F",
}

user_selected_pair = {}
user_monitoring    = {}

def calculate_rsi(series, period=14):
    delta    = series.diff()
    gain     = delta.where(delta > 0, 0.0)
    loss     = -delta.where(delta < 0, 0.0)
    avg_gain = gain.rolling(window=period).mean()
    avg_loss = loss.rolling(window=period).mean()
    rs       = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

def calculate_macd(series, fast=12, slow=26, signal=9):
    ema_fast    = series.ewm(span=fast,   adjust=False).mean()
    ema_slow    = series.ewm(span=slow,   adjust=False).mean()
    macd_line   = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    return macd_line, signal_line

def analyze(symbol):
    try:
        df = yf.download(symbol, interval="1m", period="1d", progress=False)
        if df.empty or len(df) < 30:
            return None, None, None
        close = df['Close'].squeeze()
        rsi       = calculate_rsi(close)
        ema9      = close.ewm(span=9,  adjust=False).mean()
        ema21     = close.ewm(span=21, adjust=False).mean()
        macd, sig = calculate_macd(close)
        r   = float(rsi.iloc[-1])
        ef  = float(ema9.iloc[-1]);  es  = float(ema21.iloc[-1])
        pef = float(ema9.iloc[-2]);  pes = float(ema21.iloc[-2])
        m   = float(macd.iloc[-1]);  sl  = float(sig.iloc[-1])
        pm  = float(macd.iloc[-2]); psl  = float(sig.iloc[-2])
        price = float(close.iloc[-1])
        ema_cross_up    = pef < pes and ef > es
        ema_cross_down  = pef > pes and ef < es
        macd_cross_up   = pm < psl and m > sl
        macd_cross_down = pm > psl and m < sl
        buy_score  = sum([r < 35, ema_cross_up,   macd_cross_up])
        sell_score = sum([r > 65, ema_cross_down, macd_cross_down])
        if buy_score >= 2:
            strength = "STRONG 💪💪" if buy_score == 3 else "MEDIUM ✅"
            return "BUY 🟢 (CALL ⬆️)", strength, price
        if sell_score >= 2:
            strength = "STRONG 💪💪" if sell_score == 3 else "MEDIUM ✅"
            return "SELL 🔴 (PUT ⬇️)", strength, price
        return "WAIT ⏳", "", price
    except Exception:
        return None, None, None

def format_signal(pair_name, signal, strength, price):
    now = datetime.now().strftime("%H:%M:%S")
    return (
        f"📊 *POCKET OPTION SIGNAL*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🕐 Time     : `{now}`\n"
        f"💱 Pair     : *{pair_name}*\n"
        f"💰 Price    : `{price:.5f}`\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📌 Signal   : *{signal}*\n"
        f"⚡ Strength : {strength}\n"
        f"⏱️ Expiry   : *1 Minute*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"⚠️ _Demo account এ আগে test করো!_"
    )

async def monitor_loop(chat_id, context):
    while user_monitoring.get(chat_id, False):
        if chat_id in user_selected_pair:
            pair_name, symbol = user_selected_pair[chat_id]
            signal, strength, price = analyze(symbol)
            if signal and signal != "WAIT ⏳":
                msg = format_signal(pair_name, signal, strength, price)
                await context.bot.send_message(chat_id=chat_id, text=msg, parse_mode="Markdown")
        await asyncio.sleep(60)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = []
    row = []
    for i, pair_name in enumerate(PAIRS.keys()):
        row.append(InlineKeyboardButton(pair_name, callback_data=f"pair_{pair_name}"))
        if len(row) == 2:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)
    await update.message.reply_text(
        "🤖 *Pocket Option Signal Bot*\n\nনিচে থেকে একটা Pair select করো:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query   = update.callback_query
    await query.answer()
    chat_id = query.message.chat_id
    data    = query.data

    if data.startswith("pair_"):
        pair_name = data.replace("pair_", "")
        symbol    = PAIRS.get(pair_name)
        if not symbol:
            await query.edit_message_text("❌ Pair পাওয়া যায়নি!")
            return
        user_selected_pair[chat_id] = (pair_name, symbol)
        keyboard = [
            [
                InlineKeyboardButton("▶️ Start Signal", callback_data="start_monitor"),
                InlineKeyboardButton("⏹️ Stop Signal",  callback_data="stop_monitor"),
            ],
            [InlineKeyboardButton("🔙 Pair পরিবর্তন করো", callback_data="change_pair")]
        ]
        await query.edit_message_text(
            f"✅ Selected: *{pair_name}*\n\n▶️ Start এ click করলে প্রতি 60 সেকেন্ডে signal পাবে।",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )

    elif data == "start_monitor":
        if chat_id not in user_selected_pair:
            await query.edit_message_text("❌ আগে একটা pair select করো!")
            return
        user_monitoring[chat_id] = True
        pair_name, _ = user_selected_pair[chat_id]
        await query.edit_message_text(
            f"✅ *Monitoring শুরু হয়েছে!*\n\nPair: *{pair_name}*\nপ্রতি 60 সেকেন্ডে signal আসবে।\n\nবন্ধ করতে /stop লেখো।",
            parse_mode="Markdown"
        )
        asyncio.create_task(monitor_loop(chat_id, context))

    elif data == "stop_monitor":
        user_monitoring[chat_id] = False
        await query.edit_message_text("⏹️ Signal বন্ধ করা হয়েছে।\n\nআবার শুরু করতে /start লেখো।")

    elif data == "change_pair":
        user_monitoring[chat_id] = False
        keyboard = []
        row = []
        for i, pair_name in enumerate(PAIRS.keys()):
            row.append(InlineKeyboardButton(pair_name, callback_data=f"pair_{pair_name}"))
            if len(row) == 2:
                keyboard.append(row)
                row = []
        if row:
            keyboard.append(row)
        await query.edit_message_text("💱 নতুন pair select করো:", reply_markup=InlineKeyboardMarkup(keyboard))

async def stop_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat_id
    user_monitoring[chat_id] = False
    await update.message.reply_text("⏹️ Signal বন্ধ করা হয়েছে।\nআবার শুরু করতে /start লেখো।")

def main():
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("stop",  stop_cmd))
    app.add_handler(CallbackQueryHandler(button_handler))
    print("🤖 Bot চালু হয়েছে...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
