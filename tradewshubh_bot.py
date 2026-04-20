"""
TradeWithShubh Telegram Bot — v3 (Python 3.13 compatible)
Fixed: asyncio event loop conflict — removed apscheduler entirely,
       uses PTB's built-in JobQueue which works on all Python versions.
"""

import json, logging, pytz
from datetime import datetime, time as dtime
from pathlib import Path

import yfinance as yf
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

# ── CONFIG ────────────────────────────────────────────────────────────────────
TOKEN     = "7684792365:AAGUHs0feHUeZKTiBlXiLNZ9LHEJgvj2yXs"
IST       = pytz.timezone("Asia/Kolkata")
SUBS_FILE = "subscribers.json"

logging.basicConfig(format="%(asctime)s | %(levelname)s | %(message)s", level=logging.INFO)
log = logging.getLogger(__name__)

# ── SUBSCRIBER PERSISTENCE ────────────────────────────────────────────────────
def load_subs() -> set:
    try:
        if Path(SUBS_FILE).exists():
            return set(json.loads(Path(SUBS_FILE).read_text()))
    except Exception:
        pass
    return set()

def save_subs(s: set):
    Path(SUBS_FILE).write_text(json.dumps(list(s)))

subscribers = load_subs()

# ── SYMBOLS ───────────────────────────────────────────────────────────────────
INDICES = [
    ("^NSEI",    "NIFTY 50",  "₹"),
    ("^BSESN",   "SENSEX",    "₹"),
    ("^IXIC",    "NASDAQ",    "$"),
    ("^GSPC",    "S&P 500",   "$"),
    ("GC=F",     "GOLD",      "$"),
    ("USDINR=X", "USD/INR",   "₹"),
]
INDIA = [
    ("RELIANCE.NS",   "Reliance Industries", "Energy"),
    ("SBIN.NS",       "State Bank of India", "Banking"),
    ("HDFCBANK.NS",   "HDFC Bank",           "Banking"),
    ("TATAMOTORS.NS", "Tata Motors",         "Auto"),
    ("INFY.NS",       "Infosys",             "IT"),
    ("WIPRO.NS",      "Wipro",               "IT"),
    ("ICICIBANK.NS",  "ICICI Bank",          "Banking"),
    ("ADANIENT.NS",   "Adani Enterprises",   "Conglomerate"),
]
USA = [
    ("NVDA",  "NVIDIA",         "Semiconductors"),
    ("META",  "Meta Platforms", "Social Media"),
    ("TSLA",  "Tesla",          "EV"),
    ("AAPL",  "Apple",          "Technology"),
    ("AMZN",  "Amazon",         "E-Commerce"),
    ("MSFT",  "Microsoft",      "Technology"),
    ("GOOGL", "Alphabet",       "Technology"),
    ("JPM",   "JPMorgan Chase", "Banking"),
]

# ── DATA FETCH ────────────────────────────────────────────────────────────────
def fetch(symbol: str) -> dict | None:
    try:
        t  = yf.Ticker(symbol)
        fi = t.fast_info
        price = getattr(fi, "last_price", None)
        prev  = getattr(fi, "previous_close", None)
        if not price:
            hist = t.history(period="2d", interval="1d")
            if hist.empty:
                return None
            price = float(hist["Close"].iloc[-1])
            prev  = float(hist["Close"].iloc[-2]) if len(hist) >= 2 else price
        price, prev = float(price), float(prev or price)
        chg    = round(((price - prev) / prev) * 100, 2) if prev else 0.0
        dvol   = float(getattr(fi, "last_volume", 0) or 0)
        avol   = float(getattr(fi, "three_month_average_volume", 0) or 0)
        vratio = round(dvol / avol, 1) if avol > 0 else 1.0
        return {"price": price, "chg": chg, "vratio": vratio}
    except Exception as e:
        log.warning(f"fetch({symbol}): {e}")
        return None

# ── SMC HELPERS ───────────────────────────────────────────────────────────────
def strength(chg: float, vr: float) -> int:
    s = 50
    if abs(chg) > 2: s += 20
    if abs(chg) > 3: s += 10
    if vr > 2:       s += 15
    if vr > 3:       s += 10
    return min(98, max(30, s))

def smc_label(chg: float, vr: float) -> str:
    if chg > 1.5 and vr > 2:  return "📗 Strong Bullish Setup"
    if chg > 0.5:              return "🟢 Mild Bullish Bias"
    if chg < -1.5 and vr > 2: return "📕 Strong Bearish Setup"
    if chg < -0.5:             return "🔴 Mild Bearish Bias"
    return                            "⬜ Neutral / Consolidation"

def bar(pct: int) -> str:
    f = round(pct / 10)
    return "█" * f + "░" * (10 - f)

def pfmt(price: float, cur: str) -> str:
    return f"{cur}{price:,.2f}"

def ts() -> str:
    return datetime.now(IST).strftime("%a %d %b %Y · %I:%M %p IST")

# ── DISCLAIMER ────────────────────────────────────────────────────────────────
DISC = (
    "\n\n─────────────────────────\n"
    "⚠️ <i><b>DISCLAIMER:</b> TradeWithShubh is NOT a SEBI-registered "
    "investment adviser. All content is purely educational and for "
    "informational purposes only. Nothing here constitutes financial, "
    "investment or trading advice. Always do your own research before "
    "making any investment decisions. Trading involves risk of loss.</i>"
)

# ── MESSAGE BUILDERS ──────────────────────────────────────────────────────────
def indices_msg() -> str:
    lines = [f"<b>🌐 GLOBAL INDICES</b>\n<code>{ts()}</code>\n"]
    for sym, name, cur in INDICES:
        q = fetch(sym)
        if q:
            a = "🟢" if q["chg"] >= 0 else "🔴"
            s = "+" if q["chg"] >= 0 else ""
            lines.append(f"{a} <b>{name}</b>:  {pfmt(q['price'], cur)}  <code>({s}{q['chg']}%)</code>")
        else:
            lines.append(f"⚪ <b>{name}</b>: unavailable")
    return "\n".join(lines) + DISC

def stocks_msg(lst, cur, title) -> str:
    flag = "🇮🇳" if cur == "₹" else "🇺🇸"
    lines = [f"<b>{flag} {title}</b>\n<code>{ts()}</code>\n"]
    ok = 0
    for sym, name, sector in lst:
        q = fetch(sym)
        if not q:
            continue
        ok += 1
        st = strength(q["chg"], q["vratio"])
        s  = "+" if q["chg"] >= 0 else ""
        clean = sym.replace(".NS", "")
        lines.append(
            f"\n<b>{clean}</b> · <i>{name}</i>\n"
            f"  {sector}  |  {pfmt(q['price'], cur)}  <code>({s}{q['chg']}%)</code>\n"
            f"  {smc_label(q['chg'], q['vratio'])}\n"
            f"  Vol: {q['vratio']}x avg\n"
            f"  <code>{bar(st)}</code> {st}%"
        )
    if ok == 0:
        lines.append("\n⚠️ Yahoo Finance rate limit. Try again in 30 seconds.")
    return "\n".join(lines) + DISC

def full_report() -> str:
    hdr = (
        f"<b>📈 TRADEWITHSHUBH</b>\n"
        f"<i>Daily Pre-Market Screener</i>\n"
        f"<code>{ts()}</code>\n"
        f"═══════════════════════════\n\n"
    )
    idx = "<b>🌐 GLOBAL INDICES</b>\n"
    for sym, name, cur in INDICES:
        q = fetch(sym)
        if q:
            a = "🟢" if q["chg"] >= 0 else "🔴"
            s = "+" if q["chg"] >= 0 else ""
            idx += f"{a} <b>{name}</b>: {pfmt(q['price'], cur)} <code>({s}{q['chg']}%)</code>\n"
        else:
            idx += f"⚪ <b>{name}</b>: unavailable\n"

    india = "\n<b>🇮🇳 INDIAN STOCKS (NSE)</b>\n"
    for sym, name, sector in INDIA:
        q = fetch(sym)
        if not q:
            continue
        st = strength(q["chg"], q["vratio"])
        s  = "+" if q["chg"] >= 0 else ""
        clean = sym.replace(".NS", "")
        india += (
            f"\n<b>{clean}</b> · <i>{name}</i>\n"
            f"  {pfmt(q['price'], '₹')} <code>({s}{q['chg']}%)</code>  Vol:{q['vratio']}x\n"
            f"  {smc_label(q['chg'], q['vratio'])}\n"
            f"  <code>{bar(st)}</code> {st}%\n"
        )

    usa = "\n<b>🇺🇸 US STOCKS</b>\n"
    for sym, name, sector in USA:
        q = fetch(sym)
        if not q:
            continue
        st = strength(q["chg"], q["vratio"])
        s  = "+" if q["chg"] >= 0 else ""
        usa += (
            f"\n<b>{sym}</b> · <i>{name}</i>\n"
            f"  {pfmt(q['price'], '$')} <code>({s}{q['chg']}%)</code>  Vol:{q['vratio']}x\n"
            f"  {smc_label(q['chg'], q['vratio'])}\n"
            f"  <code>{bar(st)}</code> {st}%\n"
        )

    footer = "\n═══════════════════════════\n🔗 tradewithshubh.in"
    return hdr + idx + india + usa + footer + DISC

# ── SAFE SEND ─────────────────────────────────────────────────────────────────
async def safe_send(target, text: str):
    if len(text) <= 4000:
        await target.reply_text(text, parse_mode="HTML")
        return
    chunk = ""
    for line in text.split("\n"):
        if len(chunk) + len(line) + 1 > 3800:
            await target.reply_text(chunk or "...", parse_mode="HTML")
            chunk = line + "\n"
        else:
            chunk += line + "\n"
    if chunk.strip():
        await target.reply_text(chunk, parse_mode="HTML")

async def safe_send_id(bot, chat_id: int, text: str):
    if len(text) <= 4000:
        await bot.send_message(chat_id=chat_id, text=text, parse_mode="HTML")
        return
    chunk = ""
    for line in text.split("\n"):
        if len(chunk) + len(line) + 1 > 3800:
            await bot.send_message(chat_id=chat_id, text=chunk or "...", parse_mode="HTML")
            chunk = line + "\n"
        else:
            chunk += line + "\n"
    if chunk.strip():
        await bot.send_message(chat_id=chat_id, text=chunk, parse_mode="HTML")

# ── HANDLERS ──────────────────────────────────────────────────────────────────
async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    cid  = update.effective_chat.id
    name = update.effective_user.first_name or "Trader"
    subscribers.add(cid)
    save_subs(subscribers)
    msg = (
        f"👋 <b>Welcome, {name}!</b>\n\n"
        "I'm the <b>TradeWithShubh</b> screener bot 📈\n\n"
        "Every morning before <b>9:00 AM IST</b> I'll send you a "
        "pre-market report with Indian &amp; US stock setups based on "
        "Smart Money Concepts methodology.\n\n"
        "<b>Commands:</b>\n"
        "🔹 /screen — Full India + US screener\n"
        "🔹 /india — Indian stocks (NSE)\n"
        "🔹 /usa — US stocks\n"
        "🔹 /indices — Live global indices\n"
        "🔹 /help — All commands\n"
        + DISC
    )
    await update.message.reply_text(msg, parse_mode="HTML")
    log.info(f"Subscribed: {cid} ({name})")

async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = (
        "<b>📋 TRADEWITHSHUBH — COMMANDS</b>\n\n"
        "/start — Subscribe &amp; welcome\n"
        "/screen — Full pre-market screener\n"
        "/india — Indian stocks (NSE)\n"
        "/usa — US stocks\n"
        "/indices — Live global indices\n"
        "/help — This message\n"
        + DISC
    )
    await update.message.reply_text(msg, parse_mode="HTML")

async def cmd_indices(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⏳ Fetching live indices...")
    await safe_send(update.message, indices_msg())

async def cmd_india(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⏳ Fetching Indian stocks...")
    await safe_send(update.message, stocks_msg(INDIA, "₹", "INDIAN STOCKS (NSE)"))

async def cmd_usa(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⏳ Fetching US stocks...")
    await safe_send(update.message, stocks_msg(USA, "$", "US STOCKS"))

async def cmd_screen(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⏳ Running full screener — takes ~20 seconds...")
    await safe_send(update.message, full_report())

# ── DAILY 8 AM BROADCAST ──────────────────────────────────────────────────────
async def daily_broadcast(ctx: ContextTypes.DEFAULT_TYPE):
    log.info(f"Daily broadcast → {len(subscribers)} subscribers")
    report = full_report()
    dead = set()
    for cid in list(subscribers):
        try:
            await safe_send_id(ctx.bot, cid, report)
            log.info(f"  ✓ {cid}")
        except Exception as e:
            log.warning(f"  ✗ {cid}: {e}")
            if any(x in str(e).lower() for x in ["blocked", "not found", "deactivated"]):
                dead.add(cid)
    subscribers.difference_update(dead)
    save_subs(subscribers)

# ── MAIN (no asyncio.run — PTB handles its own loop) ─────────────────────────
def main():
    app = (
        Application.builder()
        .token(TOKEN)
        .build()
    )

    app.add_handler(CommandHandler("start",   cmd_start))
    app.add_handler(CommandHandler("help",    cmd_help))
    app.add_handler(CommandHandler("screen",  cmd_screen))
    app.add_handler(CommandHandler("india",   cmd_india))
    app.add_handler(CommandHandler("usa",     cmd_usa))
    app.add_handler(CommandHandler("indices", cmd_indices))

    # PTB built-in JobQueue — no apscheduler needed, works on Python 3.13
    app.job_queue.run_daily(
        daily_broadcast,
        time=dtime(hour=8, minute=0, tzinfo=IST),
        name="daily_8am",
    )

    log.info("🤖 Bot running | Daily report @ 08:00 AM IST")
    # run_polling manages its own event loop — do NOT wrap in asyncio.run()
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
