import os
import requests
import pandas as pd
from flask import Flask, render_template, send_file
from datetime import datetime
import pytz
import csv
from threading import Thread
import telegram

FUNDING_LOG_FILE = "funding_history.csv"
LOG_FILE = "crossmargin_history.csv"

app = Flask(__name__)

assets = [
    "USDT", "USDC", "BTC", "ETH", "SOL", "SUI", "XRP", "BNB", "DOGE", "PEPE", "LTC", "ADA", "AVAX",
    "TRUMP", "LINK", "WLD", "OP", "ARB", "TON", "BLUR", "MAGIC", "MATIC", "PYTH", "INJ", "TIA",
    "ZRO", "ZETA", "DYM", "JUP", "MANTA", "ONDO", "LISTA", "ENA", "ZK", "XLM", "BONK", "WBTC",
    "TRX", "FIL", "GMX", "TAO", "EDU"
]

TELEGRAM_TOKEN = "7701228926:AAEq3YpX-Os5chx6BVlP0y0nzOzSOdAhN14"
TELEGRAM_CHAT_ID = "6664554824"
bot = telegram.Bot(token=TELEGRAM_TOKEN)

def get_binance_price_volume():
    url = "https://api.binance.com/api/v3/ticker/24hr"
    try:
        res = requests.get(url, timeout=10)
        res.raise_for_status()
        data = res.json()
        result = {}
        for item in data:
            symbol = item["symbol"]
            for coin in assets:
                if symbol == coin + "USDT":
                    result[coin] = {
                        "price": float(item["lastPrice"]),
                        "volume": float(item["quoteVolume"])
                    }
        return result
    except Exception as e:
        print("[ERROR] get_binance_price_volume:", e)
        return {}

def get_cross_margin_data():
    url = "https://www.binance.com/bapi/margin/v1/public/margin/interest-rate"
    try:
        res = requests.get(url, timeout=10)
        res.raise_for_status()
        data = res.json().get("data", [])
        result = {}
        for item in data:
            asset = item.get("asset")
            if asset in assets:
                try:
                    current = float(item.get("interestRate", 0)) / 24
                    next_rate = float(item.get("nextInterestRate", 0)) / 24
                    result[asset] = {"current": current, "next": next_rate}
                except:
                    continue
        return result
    except Exception as e:
        print("[ERROR] fetch_cross_margin_data:", e)
        return {}

def get_funding_rate():
    url = "https://fapi.binance.com/fapi/v1/premiumIndex"
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        res = requests.get(url, headers=headers, timeout=10)
        res.raise_for_status()
        data = res.json()
        result = {}
        for coin in assets:
            symbol = coin + "USDT"
            item = next((i for i in data if i["symbol"] == symbol), None)
            if item:
                try:
                    rate = float(item["lastFundingRate"])
                    result[coin] = rate
                except:
                    continue
        return result
    except Exception as e:
        print("[ERROR] get_funding_rate:", e)
        return {}

def log_funding_data():
    now = datetime.utcnow().strftime("%Y-%m-%d %H:00:00")
    funding_data = get_funding_rate()
    if not funding_data:
        return

    if not os.path.exists(FUNDING_LOG_FILE):
        with open(FUNDING_LOG_FILE, "w") as f:
            f.write("timestamp,asset,funding_rate\n")

    with open(FUNDING_LOG_FILE, "a") as f:
        for asset, rate in funding_data.items():
            f.write(f"{now},{asset},{rate}\n")

def log_and_alert():
    now = datetime.now().strftime("%Y-%m-%d %H:00:00")
    margin_data = get_cross_margin_data()
    if not margin_data: return

    if not os.path.exists(LOG_FILE):
        with open(LOG_FILE, "w") as f:
            f.write("timestamp,asset,hourly_rate\n")

    df_old = pd.read_csv(LOG_FILE)
    alert_msgs = []

    with open(LOG_FILE, "a") as f:
        for asset, rates in margin_data.items():
            rate = rates.get("current")
            f.write(f"{now},{asset},{rate}\n")
            df_asset = df_old[df_old["asset"] == asset]
            if len(df_asset) > 0:
                last_rate = df_asset.iloc[-1]["hourly_rate"]
                change = ((rate - last_rate) / last_rate) * 100 if last_rate else 0
                if abs(change) >= 3:
                    msg = f"⚠️ Cross Margin Alert\n{asset}: Lãi suất {'tăng' if change > 0 else 'giảm'} {change:.2f}%\nHiện tại: {rate:.6f}\nGiờ trước: {last_rate:.6f}"
                    alert_msgs.append(msg)

    for msg in alert_msgs:
        try:
            bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=msg)
        except Exception as e:
            print("[Telegram Error]", e)

def safe_read_csv(filepath):
    try:
        if not os.path.exists(filepath):
            return pd.DataFrame()
        return pd.read_csv(filepath)
    except Exception as e:
        print(f"[ERROR] Reading CSV {filepath}:", e)
        return pd.DataFrame()

@app.route("/")
def index():
    price_data = get_binance_price_volume()
    funding_data = get_funding_rate()
    margin_data = get_cross_margin_data()
    btc_price = price_data.get("BTC", {}).get("price")

    data = []
    for coin in assets:
        price = price_data.get(coin, {}).get("price")
        volume = price_data.get(coin, {}).get("volume")
        cross = margin_data.get(coin, {})
        cross_margin = cross.get("current")
        next_margin = cross.get("next")
        funding_rate = funding_data.get(coin)
        price_btc = (price / btc_price) if price and btc_price and coin != "BTC" else 1 if coin == "BTC" else None

        data.append({
            "asset": coin,
            "price_usdt": f"{price:,.4f}" if price else "-",
            "price_btc": f"{price_btc:.8f}" if price_btc else "-",
            "volume": f"{volume:,.0f}" if volume else "-",
            "cross_margin": f"{cross_margin:.10f}" if cross_margin else "-",
            "next_margin": f"{next_margin:.10f}" if next_margin else "-",
            "funding_rate": f"{funding_rate * 100:.8f}%" if funding_rate is not None else "-",
            "trap_radar": "-",
            "oi": "-",
            "log_view": f"<a href='/chart/cross/{coin}' target='_blank'>Cross</a> | <a href='/chart/funding/{coin}' target='_blank'>Funding</a>",
            "propose": "-"
        })

    return render_template("index.html", data=data)

@app.route("/chart/cross/<asset>")
def chart_cross(asset):
    try:
        df = safe_read_csv(LOG_FILE)
        df_asset = df[df["asset"] == asset].tail(24).copy()
        if df_asset.empty:
            return f"No cross margin data for {asset}"
        df_asset["timestamp"] = pd.to_datetime(df_asset["timestamp"]).dt.tz_localize("UTC").dt.tz_convert("Asia/Bangkok")
        labels = df_asset["timestamp"].dt.strftime("%m-%d %H:%M").tolist()
        values = df_asset["hourly_rate"].tolist()
        return render_template("chart.html", asset=asset, labels=labels, values=values)
    except Exception as e:
        return f"Error generating chart: {e}"

@app.route("/chart/funding/<asset>")
def chart_funding(asset):
    try:
        df = safe_read_csv(FUNDING_LOG_FILE)
        df_asset = df[df["asset"] == asset].tail(24).copy()
        if df_asset.empty:
            return f"No funding data for {asset}"
        df_asset["timestamp"] = pd.to_datetime(df_asset["timestamp"]).dt.tz_localize("UTC").dt.tz_convert("Asia/Bangkok")
        labels = df_asset["timestamp"].dt.strftime("%m-%d %H:%M").tolist()
        values = df_asset["funding_rate"].tolist()
        return render_template("chart.html", asset=asset, labels=labels, values=values)
    except Exception as e:
        return f"Error generating funding chart: {e}"

@app.route("/logfile")
def download_log():
    return send_file(LOG_FILE, as_attachment=True)

def run_scheduler():
    import time
    while True:
        try:
            log_and_alert()
            log_funding_data()
        except Exception as e:
            print("[LOG ERROR]", e)
        time.sleep(1800)

if __name__ == "__main__":
    Thread(target=run_scheduler, daemon=True).start()
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)