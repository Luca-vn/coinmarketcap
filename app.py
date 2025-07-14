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
            rate_str = item.get("interestRate")
            if asset in assets and rate_str:
                try:
                    daily_rate = float(rate_str)
                    hourly_rate = daily_rate / 24
                    result[asset] = hourly_rate
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

    # Tạo file nếu chưa có
    file_exists = os.path.exists(FUNDING_LOG_FILE)
    if not file_exists:
        with open(FUNDING_LOG_FILE, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["timestamp", "asset", "funding_rate"])

    # Đọc file cũ để so sánh
    df_old = pd.read_csv(FUNDING_LOG_FILE) if file_exists else pd.DataFrame(columns=["timestamp", "asset", "funding_rate"])
    alert_msgs = []

    # Ghi dữ liệu mới
    with open(FUNDING_LOG_FILE, "a", newline="") as f:
        writer = csv.writer(f)
        for asset, rate in funding_data.items():
            writer.writerow([now, asset, rate])
            df_asset = df_old[df_old["asset"] == asset]
            if not df_asset.empty:
                last_rate = df_asset.iloc[-1]["funding_rate"]
                change = ((rate - last_rate) / abs(last_rate)) * 100 if last_rate != 0 else 0
                if abs(change) >= 0.01:
                    msg = (
                        f"⚠️ Funding Rate Alert\n"
                        f"{asset}: Funding {'tăng' if change > 0 else 'giảm'} {change:.2f}%\n"
                        f"Hiện tại: {rate:.6%}\n"
                        f"Giờ trước: {last_rate:.6%}"
                    )
                    alert_msgs.append(msg)
    # Gửi cảnh báo nếu có
    for msg in alert_msgs:
        send_telegram_message(msg)
        
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
        for asset, rate in margin_data.items():
            f.write(f"{now},{asset},{rate}\n")
            df_asset = df_old[df_old["asset"] == asset]
            if len(df_asset) > 0:
                last_rate = df_asset.iloc[-1]["hourly_rate"]
                change = ((rate - last_rate) / last_rate) * 100 if last_rate else 0
                if abs(change) >= 3:
                    msg = (
                        f"â ï¸ Cross Margin Alert\n"
                        f"{asset}: LÃ£i suáº¥t {'tÄng' if change > 0 else 'giáº£m'} {change:.2f}%\n"
                        f"Hiá»n táº¡i: {rate:.6f}\n"
                        f"Giá» trÆ°á»c: {last_rate:.6f}"
                    )
                    alert_msgs.append(msg)

    for msg in alert_msgs:
        try:
            bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=msg)
        except Exception as e:
            print("[Telegram Error]", e)

def get_last_logged_margin_data():
    if not os.path.exists(LOG_FILE):
        return {}
    try:
        df = pd.read_csv(LOG_FILE)
        latest = df.sort_values("timestamp").drop_duplicates("asset", keep="last")
        return dict(zip(latest["asset"], latest["hourly_rate"]))
    except:
        return {}

@app.route("/")
def index():
    price_data = get_binance_price_volume()
    funding_data = get_funding_rate()
    margin_data = get_last_logged_margin_data()
    btc_price = price_data.get("BTC", {}).get("price")

    data = []
    for coin in assets:
        price = price_data.get(coin, {}).get("price")
        volume = price_data.get(coin, {}).get("volume")
        cross_margin = margin_data.get(coin)
        funding_rate = funding_data.get(coin)
        price_btc = (price / btc_price) if price and btc_price and coin != "BTC" else 1 if coin == "BTC" else None

        data.append({
            "asset": coin,
            "price_usdt": f"{price:,.4f}" if price else "-",
            "price_btc": f"{price_btc:.8f}" if price_btc else "-",
            "volume": f"{volume:,.0f}" if volume else "-",
            "cross_margin": f"{cross_margin:.10f}" if cross_margin else "-",
            "funding_rate": f"{funding_rate * 100:.8f}%" if funding_rate is not None else "-",
            "trap_radar": "-",
            "oi": "-",
            "log_view": f"""
                <a href='/chart/cross/{coin}' target='_blank'>Cross</a> |
                <a href='/chart/funding/{coin}' target='_blank'>Funding</a>
            """,
            "propose": "-"
        })

    return render_template("index.html", data=data)

@app.route("/chart/cross/<asset>")
def chart_cross(asset):
    if not os.path.exists(LOG_FILE):
        return f"No log for {asset}"
    df = pd.read_csv(LOG_FILE)
    df_asset = df[df["asset"] == asset].tail(24).copy()
    df_asset["timestamp"] = pd.to_datetime(df_asset["timestamp"]).dt.tz_localize("UTC").dt.tz_convert("Asia/Bangkok")
    labels = df_asset["timestamp"].dt.strftime("%m-%d %H:%M").tolist()
    values = df_asset["hourly_rate"].tolist()
    return render_template("chart.html", asset=asset, labels=labels, values=values)

@app.route("/chart/funding/<asset>")
def chart_funding(asset):
    try:
        if not os.path.exists(FUNDING_LOG_FILE):
            return f"No log for {asset}"
        df = pd.read_csv(FUNDING_LOG_FILE)
        if df.empty:
            return f"No data available in log"
        df_asset = df[df["asset"] == asset].tail(24).copy()
        if df_asset.empty:
            return f"No funding data found for {asset}"
        df_asset["timestamp"] = pd.to_datetime(df_asset["timestamp"]).dt.tz_localize("UTC").dt.tz_convert("Asia/Bangkok")
        labels = df_asset["timestamp"].dt.strftime("%m-%d %H:%M").tolist()
        values = df_asset["funding_rate"].tolist()
        return render_template("chart.html", asset=asset, labels=labels, values=values)
    except Exception as e:
        print("[ERROR] chart_funding:", e)
        return f"Error generating funding chart: {e}"

@app.route("/logfile")
def download_log():
    return send_file(LOG_FILE, as_attachment=True)

def run_scheduler():
    import time
    while True:
        log_and_alert()
        log_funding_data()
        log_and_alert_volume()
        time.sleep(1800)

VOLUME_LOG_FILE = "volume_history.csv"
VOLUME_ALERT_THRESHOLD = 0.001  # 5%
alert_sent_volume = {}

def log_and_alert_volume():
    now = datetime.utcnow().replace(minute=0, second=0, microsecond=0)
    data = get_binance_price_volume()
    if not data:
        return

    # Ghi log
    if not os.path.exists(VOLUME_LOG_FILE):
        with open(VOLUME_LOG_FILE, "w") as f:
            f.write("timestamp,asset,volume_24h_usdt\n")

    with open(VOLUME_LOG_FILE, "a") as f:
        for asset, info in data.items():
            volume = info["volume"]
            f.write(f"{now},{asset},{volume}\n")

    # Cảnh báo nếu volume tăng ≥ 5%
    try:
        df = pd.read_csv(VOLUME_LOG_FILE)
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        last_hour = now - timedelta(hours=1)

        for asset, info in data.items():
            current = info["volume"]
            df_asset = df[(df["asset"] == asset) & (df["timestamp"] == last_hour)]
            if df_asset.empty:
                continue
            prev = df_asset.iloc[-1]["volume_24h_usdt"]
            if prev == 0:
                continue

            change = (current - prev) / prev
            if change >= VOLUME_ALERT_THRESHOLD:
                last_sent = alert_sent_volume.get(asset)
                if not last_sent or (datetime.now() - last_sent).total_seconds() > 900:
                    msg = (
                        f"⚠️ Volume Alert: {asset}\n"
                        f"Thời gian: {now.strftime('%Y-%m-%d %H:%M')} (GMT+7)\n"
                        f"Volume 24h: {int(prev):,} → {int(current):,} (+{round(change * 100, 2)}%)"
                    )
                    bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=msg)
                    alert_sent_volume[asset] = datetime.now()
    except Exception as e:
        print("[Volume Alert Error]", e)

if __name__ == "__main__":
    Thread(target=run_scheduler).start()
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
