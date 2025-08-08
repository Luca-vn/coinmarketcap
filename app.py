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
import math
from datetime import datetime, timezone
from datetime import timezone
from datetime import datetime, timedelta
from apscheduler.schedulers.background import BackgroundScheduler

FUNDING_LOG_FILE = "funding_history.csv"
LOG_FILE = "crossmargin_history.csv"
BOT_LOG_FILE = "bot_chart_log.csv"
PRICE_LOG_FILE = "price_volume_history.csv"

app = Flask(__name__)

assets = [
    "USDT", "USDC", "BTC", "ETH", "SOL", "SUI", "XRP", "BNB", "DOGE", "AVAX", "ADA", "ASR", "DOT", "ENA", "ERA", "PENGU", "SPK", "LINK", "CKB", "HBAR", "OP", "TRX"
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

def log_cross_margin_data(filename="cross_margin_history.csv"):
    try:
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:00:00")
        cross_data = get_cross_margin_data()

        if not cross_data:
            print("[LOG CROSS] Không có dữ liệu cross margin.")
            return

        if not os.path.exists(filename):
            with open(filename, "w") as f:
                f.write("timestamp,asset,hourly_rate\n")

        with open(filename, "a") as f:
            for asset in assets:
                rate_info = cross_data.get(asset.replace("USDT", ""))
                if rate_info:
                    rate = rate_info.get("current")
                    if rate is not None:
                        f.write(f"{now},{asset},{rate}\n")
                        print(f"[LOG CROSS] ✅ Đã ghi {asset} - {rate}")
                    else:
                        print(f"[LOG CROSS] ⚠️ Không có rate cho {asset}")
                else:
                    print(f"[LOG CROSS] ⚠️ Không có dữ liệu cho {asset}")
    except Exception as e:
        print(f"[LOG CROSS] ❌ Lỗi ghi cross margin: {e}")
        
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

        # 1. Giá tăng mạnh, volume tăng mạnh => Gom mạnh
        if price_pct > 0.3 and volume_pct > 1.5:
            return "🔵 Gom mạnh"

        # 2. Giá giảm mạnh, volume tăng mạnh => Xả mạnh
        if price_pct < -0.3 and volume_pct > 1.5:
            return "🔴 Xả mạnh"

        # 3. Giá tăng vừa, volume tăng vừa => Gom âm thầm
        if 0.05 < price_pct <= 0.3 and 0.5 < volume_pct <= 1.5:
            return "🟡 Gom âm thầm"

        # 4. Giá giảm vừa, volume tăng vừa => Xả âm thầm
        if -0.3 <= price_pct < -0.05 and 0.5 < volume_pct <= 1.5:
            return "🖤 Xả âm thầm"

        # 5. Giá tăng, volume giảm => Trap short
        if price_pct > 0.1 and volume_pct < -0.2:
            return "📈 Trap Short"

        # 6. Giá giảm, volume giảm => Trap long
        if price_pct < -0.1 and volume_pct < -0.2:
            return "📉 Trap Long"

        # 7. Giá tăng, volume giữ nguyên (rất thấp) => Giá tăng không volume
        if price_pct > 0.2 and abs(volume_pct) < 0.1:
            return "⚫ Giá tăng không volume"

        # 8. Giá giảm, volume giữ nguyên (rất thấp) => Giá giảm không volume
        if price_pct < -0.2 and abs(volume_pct) < 0.1:
            return "⚫ Giá giảm không volume"

        # 9. Giá giữ nguyên, volume tăng => Volume tăng nhưng giá không đổi
        if abs(price_pct) < 0.05 and volume_pct > 0.5:
            return "⚫ Volume tăng bất thường"

        # 10. Giá giữ nguyên, volume giảm => Volume giảm nhưng giá không đổi
        if abs(price_pct) < 0.05 and volume_pct < -0.5:
            return "⚫ Volume giảm bất thường"

        # 11. Giá & volume đều giảm nhẹ => Có thể là giảm yếu
        if -0.2 < price_pct < 0 and -0.5 < volume_pct < 0:
            return "⚫ Giảm nhẹ"

        # 12. Giá & volume đều tăng nhẹ => Có thể là tăng yếu
        if 0 < price_pct < 0.2 and 0 < volume_pct < 0.5:
            return "⚫ Tăng nhẹ"

        # Mặc định không rõ
        return "⚪ Không rõ"
    except:
        return "⚪ Không rõ"
        
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

        try:
            df_decision = pd.read_csv("decision_log.csv")
            last_decision = df_decision.sort_values("timestamp").groupby("asset").tail(1)
            decision_data = last_decision.to_dict(orient="records")
        except:
            decision_data = []

    return render_template("index.html", data=data, decision_data=decision_data)
    
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
        df["asset"] = df["asset"].str.upper()
        df_asset = df[df["asset"] == asset.upper()].copy()

        if df_asset.empty:
            return f"No bot chart data for {asset}"

        df_asset.dropna(subset=["price", "volume"], inplace=True)
        df_asset["timestamp"] = pd.to_datetime(df_asset["timestamp"])
        df_asset["timestamp"] = df_asset["timestamp"].dt.tz_localize("UTC").dt.tz_convert("Asia/Ho_Chi_Minh")
        df_asset.sort_values("timestamp", inplace=True)

        # ✅ Bỏ dòng đầu tiên nếu %price và %volume đều = 0 (fix kiểu dữ liệu)
        if len(df_asset) > 1:
            first_row = df_asset.iloc[0]
            try:
                price_pct_0 = float(first_row.get("price_pct", 0))
                volume_pct_0 = float(first_row.get("volume_pct", 0))
                if abs(price_pct_0) == 0 and abs(volume_pct_0) == 0:
                    df_asset = df_asset.iloc[1:]
            except:
                pass

        df_asset["price_pct"] = df_asset["price_pct"].astype(float).round(2)
        df_asset["volume_pct"] = df_asset["volume_pct"].astype(float).round(2)
        df_asset["bot_action"] = df_asset["bot_action"].fillna("⚪ Không rõ")

        labels = df_asset["timestamp"].dt.strftime("%m-%d %H:%M").tolist()
        price_pct = df_asset["price_pct"].tolist()
        volume_pct = df_asset["volume_pct"].tolist()
        bot_actions = df_asset["bot_action"].tolist()
        prices = df_asset["price"].round(4).tolist()

        actions = df_asset["bot_action"].value_counts().to_dict()
        gom_manh = actions.get("🔵 Gom mạnh", 0)
        xa_manh = actions.get("🔴 Xả mạnh", 0)
        gom_am_tham = actions.get("🟡 Gom âm thầm", 0)
        xa_am_tham = actions.get("🖤 Xả âm thầm", 0)
        trap_long = actions.get("📉 Trap Long", 0)
        trap_short = actions.get("📈 Trap Short", 0)
        trap_total = trap_long + trap_short

        annotations = []
        for _, row in df_asset.iterrows():
            ts = row["timestamp"]
            action = row["bot_action"]
            price = round(row["price"], 4) if "price" in row and not pd.isna(row["price"]) else None
            if action in ["🔴 Xả mạnh", "🔵 Gom mạnh", "📋 Trap", "📈 Trap Short", "📉 Trap Long", "🖤 Xả âm thầm", "🟡 Gom âm thầm"]:
                color_map = {
                    "🔴 Xả mạnh": "rgba(255, 99, 132, 0.2)",
                    "🔵 Gom mạnh": "rgba(54, 162, 235, 0.2)",
                    "📋 Trap": "rgba(255, 192, 203, 0.25)",
                    "📈 Trap Short": "rgba(255, 192, 203, 0.25)",
                    "📉 Trap Long": "rgba(255, 192, 203, 0.25)",
                    "🖤 Xả âm thầm": "rgba(128,128,128,0.2)",
                    "🟡 Gom âm thầm": "rgba(255, 206, 86, 0.2)"
                }
                ts_start = (ts - pd.Timedelta(minutes=15)).strftime("%Y-%m-%d %H:%M:%S")
                ts_end = (ts + pd.Timedelta(minutes=15)).strftime("%Y-%m-%d %H:%M:%S")
                annotations.append({
                    "xMin": ts_start,
                    "xMax": ts_end,
                    "backgroundColor": color_map[action],
                    "label": {"content": f"{action} @ {price}", "enabled": True}
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
                               trap=trap_total,
                               trap_long=trap_long,
                               trap_short=trap_short,
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

                    if any(keyword in bot_action for keyword in ALERT_KEYWORDS):
                        # ✅ Phân biệt Trap Long / Trap Short
                        if "Trap" in bot_action:
                            if price_pct > 0:
                                trap_type = "📈 Trap Short (giá giảm rồi kéo)"
                            else:
                                trap_type = "📉 Trap Long (giá tăng rồi đạp)"
                            msg = f"{trap_type} tại {coin.upper()}\nGiá: {float(price_pct):.2f}% | Volume: {float(volume_pct):.2f}%"
                        else:
                            msg = f"📊 [TRAFFIC] {coin.upper()}: {bot_action}\nGiá: {float(price_pct):.2f}% | Volume: {float(volume_pct):.2f}%"

                        # ✅ Gửi Telegram
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
        

def get_bot_action_summary(asset, hours=12, min_records=6):
    try:
        df = safe_read_csv(BOT_LOG_FILE)
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        df = df[df["asset"] == asset.upper()]
        df = df[df["timestamp"] >= datetime.utcnow() - timedelta(hours=hours)]

        if df.shape[0] < min_records:
            return "⚪ Thiếu log bot"

        counts = df["bot_action"].value_counts()
        total = df.shape[0]
        gom_pct = (counts.get("🔵 Gom mạnh", 0) + counts.get("🟡 Gom âm thầm", 0)) / total
        xa_pct = (counts.get("🔴 Xả mạnh", 0) + counts.get("🖤 Xả âm thầm", 0)) / total
        trap = counts.get("📈 Trap Short", 0) + counts.get("📉 Trap Long", 0)

        if trap > 0:
            return "🚨 Trap"
        if gom_pct >= 0.6:
            return "🟢 MUA"
        elif xa_pct >= 0.6:
            return "🔴 BÁN"
        else:
            return "🟡 CHỜ"
    except Exception as e:
        print(f"[BOT SUMMARY ERROR] {asset}: {e}")
        return "⚪ Lỗi"
        
def get_avg_metric(asset, filepath, colname="funding_rate", hours=12, min_records=3):
    try:
        df = safe_read_csv(filepath)
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        df = df[df["asset"] == asset.upper()]
        df = df[df["timestamp"] >= datetime.utcnow() - timedelta(hours=hours)]
        if df.shape[0] < min_records:
            return None
        return df[colname].astype(float).mean()
    except Exception as e:
        print(f"[AVG METRIC ERROR] {asset} in {filepath}: {e}")
        return None

def get_orderbook_summary(asset, minutes=30):
    try:
        df = safe_read_csv("summary_30m.csv")
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        df = df[df["asset"] == asset.upper()]
        if df.empty:
            return None
        
        last_row = df.sort_values("timestamp").iloc[-1]

        signal = last_row["last_signal"]
        trap_short = last_row["trap_short_count"]
        trap_long = last_row["trap_long_count"]

        return {
            "signal": signal,
            "trap": trap_short + trap_long,
            "bias": float(last_row["bias_avg_30m"])
        }
    except Exception as e:
        print(f"[ORDERBOOK SUMMARY ERROR] {asset}: {e}")
        return None

def log_orderbook():
    log_file = "orderbook_log.csv"
    if not os.path.exists(log_file):
        with open(log_file, "w") as f:
            f.write("timestamp,asset,top_bid_price,top_ask_price,bid_volume,ask_volume,orderbook_bias,spread,top3_bid_qty,top3_ask_qty\n")

    for asset in assets:
        try:
            url = f"https://api.binance.com/api/v3/depth?symbol={asset}USDT&limit=5"
            response = requests.get(url)
            data = response.json()

            bids = data["bids"]
            asks = data["asks"]

            top_bid_price = float(bids[0][0])
            top_ask_price = float(asks[0][0])
            spread = top_ask_price - top_bid_price

            bid_volume = sum(float(bid[1]) for bid in bids)
            ask_volume = sum(float(ask[1]) for ask in asks)

            orderbook_bias = (bid_volume - ask_volume) / (bid_volume + ask_volume + 1e-9)

            top3_bid_qty = sum(float(bid[1]) for bid in bids[:3])
            top3_ask_qty = sum(float(ask[1]) for ask in asks[:3])

            timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")

            with open(log_file, "a") as f:
                f.write(f"{timestamp},{asset}USDT,{top_bid_price},{top_ask_price},{bid_volume:.6f},{ask_volume:.6f},{orderbook_bias:.6f},{spread:.2f},{top3_bid_qty:.6f},{top3_ask_qty:.6f}\n")

            print(f"[OB ✅] {asset} | Bid={bid_volume:.2f} | Ask={ask_volume:.2f} | Spread={spread:.2f}")
        except Exception as e:
            print(f"[OB ❌] {asset}: {e}")
            
def log_trade_history():
    log_file = "trade_history.csv"
    if not os.path.exists(log_file):
        with open(log_file, "w") as f:
            f.write("timestamp,asset,buy_volume,sell_volume,total_volume\n")

    for asset in assets:
        try:
            url = f"https://api.binance.com/api/v3/trades?symbol={asset}USDT&limit=1000"
            response = requests.get(url)
            data = response.json()

            buy_volume = 0
            sell_volume = 0

            for trade in data:
                qty = float(trade["qty"])
                if trade["isBuyerMaker"]:
                    sell_volume += qty
                else:
                    buy_volume += qty

            total_volume = buy_volume + sell_volume
            timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")

            with open(log_file, "a") as f:
                f.write(f"{timestamp},{asset}USDT,{buy_volume:.6f},{sell_volume:.6f},{total_volume:.6f}\n")

            print(f"[TR ✅] {asset}: Buy={buy_volume:.2f}, Sell={sell_volume:.2f}")
        except Exception as e:
            print(f"[TR ❌] {asset}: {e}")

def generate_orderbook_signal_v4(df_coin):
    result = []
    demand_streak = 0
    supply_streak = 0

    for _, row in df_coin.iterrows():
        if row["real_demand"]:
            demand_streak += 1
            supply_streak = 0
        elif row["real_supply"]:
            supply_streak += 1
            demand_streak = 0
        else:
            demand_streak = 0
            supply_streak = 0

        if row["trap_short"] and row["real_demand"]:
            signal = "✅ Long (trap + gom)"
        elif row["trap_long"] and row["real_supply"]:
            signal = "🔻 Short (trap + xả)"
        elif demand_streak >= 3:
            signal = "🟢 Long mạnh (gom lặp lại)"
        elif supply_streak >= 3:
            signal = "🔴 Short mạnh (xả lặp lại)"
        elif row["real_demand"] and row["orderbook_bias"] > 0.2:
            signal = "🟢 Long nhẹ"
        elif row["real_supply"] and row["orderbook_bias"] < -0.2:
            signal = "🔴 Short nhẹ"
        elif row["real_demand"] and row["real_supply"]:
            if row["orderbook_bias"] > 0:
                signal = "🟡 Gom âm thầm"
            else:
                signal = "🖤 Xả âm thầm"
        elif row["real_demand"]:
            signal = "🟡 Gom âm thầm"
        elif row["real_supply"]:
            signal = "🖤 Xả âm thầm"
        else:
            signal = "⚠️ Tránh"

        result.append(signal)

    return result

def analyze_and_combine():
    try:
        trade_df = pd.read_csv("trade_history.csv")
        orderbook_df = pd.read_csv("orderbook_log.csv")

        trade_df["timestamp"] = pd.to_datetime(trade_df["timestamp"]).dt.floor("min")
        orderbook_df["timestamp"] = pd.to_datetime(orderbook_df["timestamp"]).dt.floor("min")

        df = pd.merge(trade_df, orderbook_df, on=["timestamp", "asset"], how="inner")

        df["buy_vs_bid"] = df["buy_volume"] / (df["bid_volume"] + 1e-9)
        df["sell_vs_ask"] = df["sell_volume"] / (df["ask_volume"] + 1e-9)

        df["real_demand"] = df["buy_vs_bid"] > 1.01
        df["real_supply"] = df["sell_vs_ask"] > 1.01

        df["trap_long"] = (df["orderbook_bias"] < -0.2) & (df["buy_vs_bid"] < 0.5)
        df["trap_short"] = (df["orderbook_bias"] > 0.2) & (df["sell_vs_ask"] < 0.5)

        df["recommendation_orderbook"] = (
            df.groupby("asset").apply(generate_orderbook_signal_v4, include_groups=False).explode().values
        )

        df.to_csv("combined_order_analysis.csv", index=False)
        print(f"[✅] {datetime.now().strftime('%H:%M:%S')} - Đã cập nhật combined_order_analysis.csv")

    except Exception as e:
        print(f"[❌] Phân tích lỗi: {e}")

def generate_summary_30m():
    try:
        df = pd.read_csv("combined_order_analysis.csv")
        df["timestamp"] = pd.to_datetime(df["timestamp"])

        now = datetime.utcnow()
        window_start = now - timedelta(minutes=30)
        df = df[df["timestamp"] >= window_start]

        summary = []
        for asset in df["asset"].unique():
            df_coin = df[df["asset"] == asset]
            row = {
                "timestamp": now.strftime("%Y-%m-%d %H:%M:%S"),
                "asset": asset,
                "bias_avg_30m": df_coin["orderbook_bias"].mean(),
                "spread_avg_30m": df_coin["spread"].mean(),
                "buy_vs_bid_avg_30m": df_coin["buy_vs_bid"].mean(),
                "sell_vs_ask_avg_30m": df_coin["sell_vs_ask"].mean(),
                "real_demand_count": df_coin["real_demand"].sum(),
                "real_supply_count": df_coin["real_supply"].sum(),
                "trap_short_count": df_coin["trap_short"].sum(),
                "trap_long_count": df_coin["trap_long"].sum(),
                "last_signal": df_coin.sort_values("timestamp").iloc[-1]["recommendation_orderbook"]
            }
            summary.append(row)

        pd.DataFrame(summary).to_csv("summary_30m.csv", index=False)
        print(f"[📊] Đã ghi summary_30m.csv với {len(summary)} coin")

    except Exception as e:
        print(f"[❌] Lỗi summary 30m: {e}")

        for h in [12, 6, 3]:
            cross = get_avg_metric(asset, LOG_FILE, "hourly_rate", hours=h)
            if cross is not None:
                break

# ✅ Logic khuyến nghị (lùi ra bên ngoài vòng for)
    if (
        "MUA" in bot_action and 
        funding is not None and funding < -0.0003 and 
        cross and cross > 0.00005 and 
        "Long" in signal_orderbook
    ):
        signal = "💰 MUA mạnh"

    elif (
        "BÁN" in bot_action and 
        funding is not None and funding > 0.0003 and 
        cross and cross > 0.00005 and 
        "Short" in signal_orderbook
    ):
        signal = "⚠️ BÁN mạnh"

    elif "Trap" in bot_action or "Trap" in signal_orderbook or "Tránh" in signal_orderbook:
        signal = "🚨 TRÁNH"

    else:
        signal = "🤔 CHỜ"

    result.append({
        "timestamp": now.strftime("%Y-%m-%d %H:%M:%S"),
        "asset": coin,
        "bot_action": bot_action,
        "funding_rate": f"{funding * 100:.4f}%" if funding is not None else "-",
        "cross_margin": f"{cross:.6f}" if cross is not None else "-",
        "signal": signal
    })

    # ✅ Ghi vào decision_log.csv
    log_path = "decision_log.csv"
    file_exists = os.path.exists(log_path)
    with open(log_path, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=result[0].keys())
        if not file_exists:
            writer.writeheader()
        writer.writerows(result)

    print(f"[DECISION] ✅ Đã ghi {len(result)} khuyến nghị.")
    log_path = "decision_log.csv"
    file_exists = os.path.exists(log_path)
    with open(log_path, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=result[0].keys())
        if not file_exists:
            writer.writeheader()
        writer.writerows(result)

    print(f"[DECISION] ✅ Đã ghi {len(result)} khuyến nghị.")

def generate_recommendation():
    now = datetime.now()
    current_time = now.strftime("%H:%M")

    if current_time not in ["06:00", "18:00"]:
        return  # Chỉ chạy 2 khung giờ cố định

    LOG_FILE = "cross_margin_history.csv"
    FUNDING_FILE = "funding_history.csv"
    BOT_FILE = "bot_chart_log.csv"
    OUTPUT_FILE = "decision_log.csv"
    TRADE_FILE = "trade_history.csv"

    fieldnames = [
        "timestamp", "asset",
        "price", "price_pct", "volume_pct",
        "bot_action", "funding", "cross_margin",
        "orderbook_signal", "orderbook_bias",
        "buy_vs_sell_ratio",
        "recommendation"
    ]

    timestamp = now.strftime("%Y-%m-%d %H:%M:%S")
    result = []

    for coin in assets:  # 🟢 Phải có dòng này để định nghĩa `coin`
        price = get_price(coin)
        price_pct, volume_pct = get_latest_pct_change(coin, hours=3)
        bot_action = get_bot_action_summary(coin, hours=12)
        funding = get_funding_rate(coin)
        # 🔍 Lấy dữ liệu Buy/Sell Volume gần nhất
        buy_vs_sell_ratio = None
        try:
            df_trade = pd.read_csv(TRADE_FILE)
            df_trade = df_trade[df_trade["asset"] == coin + "USDT"]
            latest_trade = df_trade.sort_values("timestamp").iloc[-1]
            buy_vol = latest_trade["buy_volume"]
            sell_vol = latest_trade["sell_volume"]
            buy_vs_sell_ratio = buy_vol / (sell_vol + 1e-6)
        except Exception as e:
            print(f"[TRADE RATIO ERROR] {coin}: {e}")

        cross = None
        for h in [12, 6, 3]:
            cross = get_avg_metric(coin, LOG_FILE, "hourly_rate", hours=h)
            if cross is not None:
                break

        orderbook = get_orderbook_summary(coin)
        signal_orderbook = orderbook["signal"] if orderbook else "⚠️ Tránh"
        bias_orderbook = orderbook["bias"] if orderbook else 0

        # ✅ Tín hiệu khuyến nghị
        if (
            "MUA" in bot_action and 
            funding is not None and funding < -0.0003 and 
            cross and cross > 0.00005 and 
            "Long" in signal_orderbook and
            buy_vs_sell_ratio is not None and buy_vs_sell_ratio > 1.2
        ):
            signal = "💰 MUA mạnh"

        elif (
            "BÁN" in bot_action and 
            funding is not None and funding > 0.0003 and 
            cross and cross > 0.00005 and 
            "Short" in signal_orderbook and
            buy_vs_sell_ratio is not None and buy_vs_sell_ratio < 0.8
        ):
            signal = "⚠️ BÁN mạnh"

        elif "Trap" in bot_action or "Trap" in signal_orderbook or "Tránh" in signal_orderbook:
            signal = "🚨 TRÁNH"
        else:
            signal = "🤔 CHỜ"

        result.append({
            "timestamp": timestamp,
            "asset": coin,
            "price": price,
            "price_pct": price_pct,
            "volume_pct": volume_pct,
            "bot_action": bot_action,
            "funding": funding,
            "cross_margin": cross,
            "orderbook_signal": signal_orderbook,
            "orderbook_bias": f"{bias_orderbook:.3f}",
            "buy_vs_sell_ratio": round(buy_vs_sell_ratio, 2) if buy_vs_sell_ratio is not None else "-",
            "recommendation": signal
        })

    # ✅ Ghi log
    file_exists = os.path.isfile(OUTPUT_FILE)
    with open(OUTPUT_FILE, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if not file_exists:
            writer.writeheader()
        writer.writerows(result)

    print(f"[✅] {timestamp} - Đã sinh khuyến nghị vào {OUTPUT_FILE}")

def schedule_jobs():
    scheduler = BackgroundScheduler(timezone="Asia/Bangkok")
    scheduler.add_job(log_and_alert, "interval", hours=1)
    scheduler.add_job(log_cross_margin_data, "interval", minutes=60)
    scheduler.add_job(log_funding_data, "interval", minutes=30)
    scheduler.add_job(log_price_volume_data, "interval", minutes=30)
    scheduler.add_job(log_and_analyze_bot_action, "interval", minutes=30)
    scheduler.add_job(generate_recommendation, "cron", hour="6,18", minute=0)
    scheduler.add_job(log_orderbook, "interval", minutes=5)
    scheduler.add_job(log_trade_history, "interval", minutes=5)
    scheduler.add_job(analyze_and_combine, "interval", minutes=10)
    scheduler.add_job(generate_summary_30m, "interval", minutes=30)
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
            print("✅ Gửi Telegram test thành công. !")
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
        
test_telegram()
schedule_jobs()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)

