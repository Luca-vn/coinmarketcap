import os
import requests
import pandas as pd
from flask import Flask, render_template, send_file
from datetime import datetime
import pytz
import csv
from threading import Thread
import telegram
from datetime import datetime, timezone
from datetime import timezone
from apscheduler.schedulers.background import BackgroundScheduler

FUNDING_LOG_FILE = "funding_history.csv"
LOG_FILE = "crossmargin_history.csv"
BOT_LOG_FILE = "bot_chart_log.csv"
PRICE_LOG_FILE = "price_volume_history.csv"

app = Flask(__name__)

assets = [
    "USDT", "USDC", "BTC", "ETH", "SOL", "SUI", "BNB", "SAHARA", "SPK", "ADA", "SUI", "PENGU",
    "TRX", "PEPE", "BONK", "NEWT", "LTC", "XLM"
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
            if symbol.endswith("USDT"):
                coin_name = symbol.replace("USDT", "")
                if coin_name.upper() in assets:
                    result[coin_name.upper()] = {
                        "price": float(item["lastPrice"]),
                        "volume": float(item["quoteVolume"]),
                        "price_pct": float(item["priceChangePercent"])
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
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:00:00")
    funding_data = get_funding_rate()
    if not funding_data:
        print("[LOG FUNDING] Không có dữ liệu funding.")
        return

    if not os.path.exists(FUNDING_LOG_FILE):
        with open(FUNDING_LOG_FILE, "w") as f:
            f.write("timestamp,asset,funding_rate\n")

    with open(FUNDING_LOG_FILE, "a") as f:
        for asset in assets:
            rate = funding_data.get(asset)
            if rate is not None:
                f.write(f"{now},{asset},{rate}\n")
                print(f"[LOG FUNDING] ✅ Đã ghi {asset} - {rate}")
            else:
                print(f"[LOG FUNDING] ⚠️ Không có dữ liệu cho {asset}")

def log_and_alert():
    now =  datetime.now(timezone.utc).strftime("%Y-%m-%d %H:00:00")
    margin_data = get_cross_margin_data()
    if not margin_data:
        print("[LOG CROSS] Không có dữ liệu cross margin.")
        return

    if not os.path.exists(LOG_FILE):
        with open(LOG_FILE, "w") as f:
            f.write("timestamp,asset,hourly_rate\n")

    df_old = pd.read_csv(LOG_FILE)
    alert_msgs = []

    with open(LOG_FILE, "a") as f:
        for asset in assets:
            rate = margin_data.get(asset, {}).get("current")
            if rate is not None:
                f.write(f"{now},{asset},{rate}\n")
                print(f"[LOG CROSS] ✅ Đã ghi {asset} - {rate}")
                df_asset = df_old[df_old["asset"] == asset]
                if len(df_asset) > 0:
                    last_rate = df_asset.iloc[-1]["hourly_rate"]
                    change = ((rate - last_rate) / last_rate) * 100 if last_rate else 0
                    if abs(change) >= 3:
                        msg = f"⚠️ Cross Margin Alert\n{asset}: Lãi suất {'tăng' if change > 0 else 'giảm'} {change:.2f}%\nHiện tại: {rate:.6f}\nGiờ trước: {last_rate:.6f}"
                        alert_msgs.append(msg)
            else:
                print(f"[LOG CROSS] ⚠️ Không có dữ liệu cho {asset}")

    for msg in alert_msgs:
        try:
            bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=msg)
        except Exception as e:
            print("[Telegram Error]", e)
            
def safe_read_csv(filepath):
    try:
        if not os.path.exists(filepath):
            return pd.DataFrame()
        return pd.read_csv(filepath, encoding="utf-8", on_bad_lines="skip")
    except Exception as e:
        print(f"[ERROR] Reading CSV {filepath}:", e)
        return pd.DataFrame()

def log_bot_data():
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    price_data = get_binance_price_volume()
    file_exists = os.path.exists(BOT_LOG_FILE)
    with open(BOT_LOG_FILE, "a", newline='') as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow(["timestamp", "asset", "price", "volume"])
        for coin in assets:
            info = price_data.get(coin.upper())
            if info:
                price = info.get("price")
                volume = info.get("volume")
                if price is not None and volume is not None:
                    writer.writerow([now, coin.upper(), price, volume])
                    print(f"[BOT LOG] ✅ {coin.upper()} - Price: {price}, Volume: {volume}")
                else:
                    print(f"[BOT LOG] ⚠️ {coin.upper()} skipped")
                    
def detect_bot_action(price_pct, volume_pct):
    if volume_pct >= 5:
        if price_pct >= 0.5:
            return "🟢 Gom hàng mạnh"
        elif abs(price_pct) <= 0.3:
            return "🟡 Gom âm thầm"
        elif price_pct < 0:
            return "🔴 Xả có lực"
    elif volume_pct <= -5:
        if price_pct < 0:
            return "⚫ Bỏ mặc"
        elif price_pct > 0:
            return "⚠️ Trap"
    return "⚪ Bình thường"

# ... các import giữ nguyên ...

@app.route("/")
def index():
    price_data = get_binance_price_volume()

    try:
        df_log = pd.read_csv("price_volume_history.csv")
    except Exception:
        df_log = pd.DataFrame()

    funding_data = get_funding_rate()
    margin_data = get_cross_margin_data()
    btc_price = price_data.get("BTC", {}).get("price")

    data = []
    for coin in assets:
        info = price_data.get(coin, {})
        price = info.get("price")
        volume = info.get("volume")

        # Lấy dữ liệu log trước đó để tính % thay đổi
        df_coin = df_log[df_log["asset"] == coin]
        df_coin = df_coin.sort_values("timestamp")

        last_price = df_coin.iloc[-2]["price"] if len(df_coin) >= 2 else None
        last_volume = df_coin.iloc[-2]["volume"] if len(df_coin) >= 2 else None

        try:
            price = float(price)
            last_price = float(last_price)
            price_pct = ((price - last_price) / last_price) * 100
        except:
            price_pct = 0

        try:
            volume = float(volume)
            last_volume = float(last_volume)
            volume_pct = ((volume - last_volume) / last_volume) * 100
        except:
            volume_pct = 0

        bot_action = detect_bot_action(price_pct, volume_pct)

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
            "price_pct": f"{price_pct:.2f}%",
            "volume_pct": f"{volume_pct:.2f}%",
            "bot_action": bot_action,
            "cross_margin": f"{cross_margin:.10f}" if cross_margin else "-",
            "next_margin": f"{next_margin:.10f}" if next_margin else "-",
            "funding_rate": f"{funding_rate * 100:.8f}%" if funding_rate is not None else "-",
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

def log_price_volume_data():
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:00:00")
    price_data = get_binance_price_volume()

    if not price_data:
        print("[LOG PRICE/VOLUME] Không có dữ liệu.")
        return

    file_path = "price_volume_history.csv"
    if not os.path.exists(file_path):
        with open(file_path, "w") as f:
            f.write("timestamp,asset,price,volume\n")

    with open(file_path, "a") as f:
        for asset in assets:
            info = price_data.get(asset, {})
            price = info.get("price")
            volume = info.get("volume")
            if price and volume:
                f.write(f"{now},{asset},{price},{volume}\n")

@app.route("/chart/bot/<asset>")
def chart_bot(asset):
    try:
        # FIX: bỏ qua dòng lỗi (nếu có)
        df = pd.read_csv("bot_chart_log.csv", encoding="utf-8", on_bad_lines="skip")

        df_asset = df[df["asset"] == asset].copy()
        if df_asset.empty:
            return f"No bot chart data for {asset}"

        df_asset["timestamp"] = pd.to_datetime(df_asset["timestamp"])
        df_asset.sort_values("timestamp", inplace=True)
        df_asset["price_pct"] = df_asset["price"].pct_change() * 100
        df_asset["volume_pct"] = df_asset["volume"].pct_change() * 100
        df_asset.dropna(inplace=True)

        df_asset["timestamp"] = df_asset["timestamp"].dt.tz_localize("UTC").dt.tz_convert("Asia/Bangkok")
        labels = df_asset["timestamp"].dt.strftime("%m-%d %H:%M").tolist()
        price_pct = df_asset["price_pct"].round(2).tolist()
        volume_pct = df_asset["volume_pct"].round(2).tolist()

        return render_template("chart_bot.html", asset=asset, labels=labels, price_pct=price_pct, volume_pct=volume_pct)

    except Exception as e:
        return f"Error generating bot chart: {e}"

def schedule_jobs():
    scheduler = BackgroundScheduler(timezone="Asia/Bangkok")
    scheduler.add_job(log_and_alert, "interval", hours=1)
    scheduler.add_job(log_funding_data, "interval", minutes=10)
    scheduler.add_job(log_price_volume_data, "interval", minutes=10)
    scheduler.add_job(log_bot_data, "interval", minutes=10)
    scheduler.start()

if __name__ == "__main__":
    schedule_jobs()
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
