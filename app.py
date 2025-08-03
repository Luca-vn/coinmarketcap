import os
import requests
import pandas as pd
from flask import Flask, render_template, send_file
from datetime import datetime
import pytz
import csv
from threading import Thread
import telegram
import time
from flask import send_file
import asyncio
from datetime import datetime, timezone
from datetime import timezone
from apscheduler.schedulers.background import BackgroundScheduler

FUNDING_LOG_FILE = "funding_history.csv"
LOG_FILE = "crossmargin_history.csv"
BOT_LOG_FILE = "bot_chart_log.csv"
PRICE_LOG_FILE = "price_volume_history.csv"

app = Flask(__name__)

assets = [
    "USDT", "USDC", "BTC", "ETH", "SOL", "SUI", "XRP", "BNB", "DOGE", "AVAX", "ADA", "ASR", "ENA", "ERA", "PENGU", "SPK", "LINK", "CKB", "HBAR", "OP", "TRX"
]

TELEGRAM_TOKEN = "7701228926:AAEq3YpX-Os5chx6BVlP0y0nzOzSOdAhN14"
TELEGRAM_CHAT_ID = "6664554824"
bot = telegram.Bot(token=TELEGRAM_TOKEN)

def send_telegram_message(text):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        payload = {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": text
        }
        response = requests.post(url, json=payload)
        if response.status_code == 200:
            print("[TELEGRAM ✅] Sent BOT ACTION alert")
        else:
            print("[TELEGRAM ❌]", response.text)
        time.sleep(0.2)  # tránh spam quá nhanh bị block
    except Exception as e:
        print(f"[TELEGRAM ERROR] {e}")
        
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
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:00:00")
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
                    if abs(change) >= 1.5:
                        msg = f"⚠️ Cross Margin Alert\n{asset}: Lãi suất {'tăng' if change > 0 else 'giảm'} {change:.2f}%\nHiện tại: {rate:.6f}\nGiờ trước: {last_rate:.6f}"
                        alert_msgs.append(msg)
            else:
                print(f"[LOG CROSS] ⚠️ Không có dữ liệu cho {asset}")

    for msg in alert_msgs:
        try:
            asyncio.run(bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=msg))
            print(f"[TELEGRAM] ✅ Sent CROSS MARGIN alert: {msg}")
        except Exception as e:
            print("[Telegram Error]", e)
def get_order_book_bias(symbol):
    url = f"https://fapi.binance.com/fapi/v1/depth?symbol={symbol.upper()}&limit=10"
    try:
        response = requests.get(url, timeout=5)
        data = response.json()
        bid_volume = sum(float(bid[1]) for bid in data.get("bids", []))
        ask_volume = sum(float(ask[1]) for ask in data.get("asks", []))
        if ask_volume == 0:
            return "⚪ Cân bằng"

        ratio = bid_volume / ask_volume
        if ratio > 1.5:
            return "🟢 Cầu mạnh"
        elif ratio < 0.67:
            return "🔴 Cung mạnh"
        else:
            return "⚪ Cân bằng"
    except Exception as e:
        print(f"[ORDER BOOK] Lỗi khi lấy dữ liệu {symbol}: {e}")
        return "N/A"

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

    # Đọc log cũ để tính % thay đổi
    df_old = safe_read_csv(BOT_LOG_FILE)
    df_old["asset"] = df_old["asset"].str.upper()

    with open(BOT_LOG_FILE, "a", newline='') as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow(["timestamp", "asset", "price", "volume", "price_pct", "volume_pct", "bot_action"])

        for coin in assets:
            info = price_data.get(coin.upper(), {})
            price = info.get("price")
            volume = info.get("volume")

            if price is not None and volume is not None:
                df_coin = df_old[df_old["asset"] == coin.upper()].sort_values("timestamp")

                if len(df_coin) >= 1:
                    last_price = float(df_coin.iloc[-1]["price"])
                    last_volume = float(df_coin.iloc[-1]["volume"])

                    price_pct = ((price - last_price) / last_price) * 100 if last_price else 0
                    volume_pct = ((volume - last_volume) / last_volume) * 100 if last_volume else 0
                else:
                    price_pct = 0
                    volume_pct = 0

                # Gọi hàm detect bot action
                bot_action = detect_bot_action_v2(price_pct, volume_pct)

                writer.writerow([now, coin.upper(), price, volume, price_pct, volume_pct, bot_action])
                print(f"[BOT LOG] ✅ {coin.upper()} | {bot_action}")
            else:
                writer.writerow([now, coin.upper(), "", "", "", "", "⚪ Không rõ"])
                print(f"[BOT LOG] ⚠️ {coin.upper()} không có dữ liệu - log trống")

def detect_bot_action_v2(price_pct, volume_pct, funding_rate=None, cross_margin=None, order_book_bias=None):
    try:
        if price_pct is None or volume_pct is None:
            return "⚪ Không rõ"

        # 🔴 Xả mạnh
        if price_pct < -0.3 and volume_pct > 1.5:
            return "🔴 Xả mạnh"

        # 🔵 Gom mạnh
        if price_pct > 0.3 and volume_pct > 1.5:
            return "🔵 Gom mạnh"

        # 🟡 Gom âm thầm
        if 0 < price_pct < 0.3 and 0.5 < volume_pct < 1.5:
            return "🟡 Gom âm thầm"

        # 🖤 Xả âm thầm
        if -0.5 < price_pct < 0 and 0.5 < volume_pct < 1.5:
            return "🖤 Xả âm thầm"

        # 📋 Trap
        if price_pct > 0.3 and volume_pct < -0.4:
            return "📋 Trap"

        # 🔸 Rung lắc
        if abs(price_pct) < 0.4 and 1.0 <= volume_pct <= 2.0:
            return "🔸 Rung lắc"

        # ⚪ Bình thường
        if abs(price_pct) < 0.2 and abs(volume_pct) < 0.5:
            return "⚪ Bình thường"

        return "⚪ Không rõ"
    except:
        return "❓Không xác định"
        
@app.route("/")
def index():
    price_data = get_binance_price_volume()

    try:
        df_log = safe_read_csv("bot_chart_log.csv")
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

        # Tính phần trăm thay đổi giá
        if len(df_coin) >= 2:
            try:
                last_price = float(df_coin.iloc[-2]["price"])
                price = float(price)
                price_pct = ((price - last_price) / last_price) * 100 if last_price else 0
            except:
                price_pct = 0
        else:
            price_pct = 0

        # Tính phần trăm thay đổi volume
        if len(df_coin) >= 2:
            try:
                last_volume = float(df_coin.iloc[-2]["volume"])
                volume = float(volume)
                volume_pct = ((volume - last_volume) / last_volume) * 100 if last_volume else 0
            except:
                volume_pct = 0
        else:
            volume_pct = 0

        # ✅ Gán các biến phụ trợ trước khi gọi hàm bot_action_v2
        cross = margin_data.get(coin, {})
        cross_margin = cross.get("current")
        next_margin = cross.get("next")
        funding_rate = funding_data.get(coin)
        order_book_bias = get_order_book_bias(coin + "USDT")

        # ✅ Gọi bot_action_v2
        bot_action = detect_bot_action_v2(price_pct, volume_pct, funding_rate, cross_margin, order_book_bias)

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
            "order_book_bias": order_book_bias,
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
        df = safe_read_csv("bot_chart_log.csv")
        df_asset = df[df["asset"] == asset.upper()].copy()

        if df_asset.empty:
            return f"No bot chart data for {asset}"

        df_asset.dropna(subset=["price", "volume"], inplace=True)
        df_asset["timestamp"] = pd.to_datetime(df_asset["timestamp"])
        df_asset["timestamp"] = df_asset["timestamp"].dt.tz_localize("UTC").dt.tz_convert("Asia/Ho_Chi_Minh")
        df_asset.sort_values("timestamp", inplace=True)

        # ✅ Dùng trực tiếp các cột đã được log sẵn
        df_asset["price_pct"] = df_asset["price_pct"].astype(float).round(2)
        df_asset["volume_pct"] = df_asset["volume_pct"].astype(float).round(2)
        df_asset["bot_action"] = df_asset["bot_action"].fillna("⚪ Không rõ")

        labels = df_asset["timestamp"].dt.strftime("%m-%d %H:%M").tolist()
        price_pct = df_asset["price_pct"].tolist()
        volume_pct = df_asset["volume_pct"].tolist()
        bot_actions = df_asset["bot_action"].tolist()
        prices = df_asset["price"].round(4).tolist()  # ✅ Dùng giá làm chú thích điểm

        # ✅ Thống kê số lần các hành vi bot
        actions = df_asset["bot_action"].value_counts().to_dict()
        gom_manh = actions.get("🔵 Gom mạnh", 0)
        xa_manh = actions.get("🔴 Xả mạnh", 0)
        gom_am_tham = actions.get("🟡 Gom âm thầm", 0)
        xa_am_tham = actions.get("🖤 Xả âm thầm", 0)
        trap = actions.get("📋 Trap", 0)

        # ✅ Tạo danh sách vùng đánh dấu theo hành vi bot
        annotations = []
        for _, row in df_asset.iterrows():
            ts = row["timestamp"]
            action = row["bot_action"]
            if action in ["🔴 Xả mạnh", "🔵 Gom mạnh", "📋 Trap", "🖤 Xả âm thầm", "🟡 Gom âm thầm"]:
                color_map = {
                    "🔴 Xả mạnh": "rgba(255, 99, 132, 0.2)",
                    "🔵 Gom mạnh": "rgba(54, 162, 235, 0.2)",
                    "📋 Trap": "rgba(255, 192, 203, 0.25)",  # Hồng nhạt
                    "🖤 Xả âm thầm": "rgba(128,128,128,0.2)",
                    "🟡 Gom âm thầm": "rgba(255, 206, 86, 0.2)"
                }
                ts_start = (ts - pd.Timedelta(minutes=15)).strftime("%Y-%m-%d %H:%M:%S")
                ts_end = (ts + pd.Timedelta(minutes=15)).strftime("%Y-%m-%d %H:%M:%S")
                annotations.append({
                    "xMin": ts_start,
                    "xMax": ts_end,
                    "backgroundColor": color_map[action],
                    "label": {"content": action, "enabled": True}
                })

        return render_template("chart_bot.html",
                               asset=asset,
                               timestamps=labels,
                               price_pct=price_pct,
                               volume_pct=volume_pct,
                               bot_actions=bot_actions,
                               prices=prices,
                               gom_manh=gom_manh,
                               xa_manh=xa_manh,
                               gom_am_tham=gom_am_tham,
                               xa_am_tham=xa_am_tham,
                               trap=trap,
                               annotations=annotations)
    
    except Exception as e:
        return f"Lỗi chart bot: {str(e)}"

def log_bot_action():
    try:
        df = safe_read_csv(BOT_LOG_FILE)
        df["asset"] = df["asset"].str.upper()

        ALERT_KEYWORDS = ["Gom mạnh", "Xả mạnh", "Gom âm thầm", "Xả âm thầm", "Trap"]

        # ✅ Gọi lại nếu sau này muốn phân tích thêm
        funding_data = get_funding_rate()
        margin_data = get_cross_margin_data()

        for coin in assets:
            try:
                df_coin = df[df["asset"] == coin.upper()].copy()
                df_coin = df_coin.sort_values("timestamp")

                if len(df_coin) >= 1:
                    last_row = df_coin.iloc[-1]
                    bot_action = last_row.get("bot_action", "⚪ Không rõ")
                    price_pct = last_row.get("price_pct", 0)
                    volume_pct = last_row.get("volume_pct", 0)

                    # Có thể mở rộng ở đây: phân tích thêm funding/cross nếu cần

                    if any(keyword in bot_action for keyword in ALERT_KEYWORDS):
                        msg = f"📊 [BOT ACTION] {coin.upper()}: {bot_action}\nGiá: {float(price_pct):.2f}% | Volume: {float(volume_pct):.2f}%"
                        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
                        payload = {"chat_id": TELEGRAM_CHAT_ID, "text": msg}
                        response = requests.post(url, json=payload)

                        if response.status_code == 200:
                            print(f"[TELEGRAM] ✅ Sent ALERT for {coin.upper()} → {bot_action}")
                        else:
                            print(f"[TELEGRAM ❌] {coin.upper()}: {response.text}")

                        time.sleep(1.5)
                    else:
                        print(f"[BOT ACTION] ⏩ {coin.upper()} hành vi bình thường ({bot_action}) → Không gửi")
            except Exception as e:
                print(f"[BOT ACTION ERROR] {coin.upper()}: {e}")

    except Exception as e:
        print("[BOT ACTION READ ERROR]:", e)

def log_and_analyze_bot_action():
    log_bot_data()
    log_bot_action()
        

def schedule_jobs():
    scheduler = BackgroundScheduler(timezone="Asia/Bangkok")
    scheduler.add_job(log_and_alert, "interval", hours=1)
    scheduler.add_job(log_funding_data, "interval", minutes=30)
    scheduler.add_job(log_price_volume_data, "interval", minutes=30)
    scheduler.add_job(log_and_analyze_bot_action, "interval", minutes=30)
    scheduler.start()
    
def test_telegram():
    TEST_MESSAGE = "✅ Luca test gửi tin nhắn Telegram thành công rồi nè!"
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": TEST_MESSAGE
    }
    try:
        response = requests.post(url, data=payload)
        if response.status_code == 200:
            print("✅ Gửi Telegram test thành công!")
        else:
            print(f"❌ Lỗi khi gửi Telegram: {response.status_code}, {response.text}")
    except Exception as e:
        print("❌ Lỗi kết nối Telegram:", e)

@app.route("/download/<filename>")
def download_file(filename):
    try:
        return send_file(filename, as_attachment=True)
    except Exception as e:
        return f"❌ Không thể tải file: {e}"

if __name__ == "__main__":
    test_telegram()
    schedule_jobs()
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
