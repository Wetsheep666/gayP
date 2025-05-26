import os
import sqlite3
from flask import Flask, request, abort
from dotenv import load_dotenv
from geopy.distance import geodesic
from linebot import LineBotApi, WebhookHandler
from linebot.models import (
    MessageEvent, TextMessage, TextSendMessage,
    QuickReply, QuickReplyButton, MessageAction
)

import urllib.parse
import requests

# 載入 .env
load_dotenv()

app = Flask(__name__)

line_bot_api = LineBotApi(os.getenv("LINE_CHANNEL_ACCESS_TOKEN"))
handler = WebhookHandler(os.getenv("LINE_CHANNEL_SECRET"))

GOOGLE_API_KEY = os.getenv("GOOGLE_MAPS_API_KEY")

user_states = {}

# 建立資料表
def init_db():
    conn = sqlite3.connect("rides.db")
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS ride_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT,
            origin TEXT,
            destination TEXT,
            ride_type TEXT,
            time TEXT,
            payment TEXT,
            origin_lat REAL,
            origin_lng REAL
        )
    ''')
    conn.commit()
    conn.close()

init_db()

# 地理位置查詢
def geocode_location(location):
    encoded = urllib.parse.quote(location)
    url = f"https://maps.googleapis.com/maps/api/geocode/json?address={encoded}&key={GOOGLE_API_KEY}"
    try:
        res = requests.get(url).json()
        if res["status"] == "OK":
            latlng = res["results"][0]["geometry"]["location"]
            return (latlng["lat"], latlng["lng"])
    except:
        return None
    return None

@app.route("/")
def home():
    return "LineBot Running"

@app.route("/callback", methods=["POST"])
def callback():
    signature = request.headers["X-Line-Signature"]
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except:
        abort(400)
    return "OK"

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    user_id = event.source.user_id
    user_input = event.message.text.strip()

    if user_input == "查詢我的預約":
        conn = sqlite3.connect("rides.db")
        c = conn.cursor()
        c.execute("SELECT * FROM ride_records WHERE user_id = ?", (user_id,))
        records = c.fetchall()
        conn.close()
        if not records:
            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage("你目前沒有預約紀錄。")
            )
            return
        latest = records[-1]
        origin, destination, ride_type, time, payment = latest[2:7]

        match = None
        if ride_type == "共乘":
            conn = sqlite3.connect("rides.db")
            c = conn.cursor()
            c.execute("SELECT * FROM ride_records WHERE user_id != ? AND ride_type = '共乘'", (user_id,))
            others = c.fetchall()
            conn.close()
            for o in others:
                other_lat, other_lng = o[7], o[8]
                my_lat, my_lng = latest[7], latest[8]
                if geodesic((my_lat, my_lng), (other_lat, other_lng)).meters <= 500:
                    my_time = latest[5]
                    other_time = o[5]
                    if abs(to_minutes(my_time) - to_minutes(other_time)) <= 10:
                        match = o
                        break

        msg = (
            "📋 最近的預約：\n"
            f"🛫 出發地：{origin}\n"
            f"🛬 目的地：{destination}\n"
            f"🚘 共乘：{ride_type}\n"
            f"🕐 時間：{time}\n"
            f"💳 付款：{payment}\n"
        )
        if match:
            msg += "✅ 已找到共乘對象！"
        else:
            msg += "⏳ 尚未有共乘對象"

        line_bot_api.reply_message(event.reply_token, TextSendMessage(msg))
        return

    if "到" in user_input and "我預約" not in user_input:
        try:
            origin, destination = map(str.strip, user_input.split("到"))
        except:
            line_bot_api.reply_message(event.reply_token, TextSendMessage("請輸入格式為『出發地 到 目的地』"))
            return

        user_states[user_id] = {"origin": origin, "destination": destination}

        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(
                text=f"🚕 你要從 {origin} 到 {destination}。\n請選擇是否共乘：",
                quick_reply=QuickReply(items=[
                    QuickReplyButton(action=MessageAction(label="我要共乘", text="我選擇共乘")),
                    QuickReplyButton(action=MessageAction(label="我要自己搭", text="我不共乘"))
                ])
            )
        )
        return

    if user_input in ["我選擇共乘", "我不共乘"]:
        ride_type = "共乘" if "共乘" in user_input else "不共乘"
        if user_id not in user_states:
            line_bot_api.reply_message(event.reply_token, TextSendMessage("請先輸入『出發地 到 目的地』"))
            return
        user_states[user_id]["ride_type"] = ride_type
        line_bot_api.reply_message(event.reply_token, TextSendMessage("請輸入預約時間，例如：我預約 15:30"))
        return

    if user_input.startswith("我預約"):
        time = user_input.replace("我預約", "").strip()
        if user_id not in user_states or "ride_type" not in user_states[user_id]:
            line_bot_api.reply_message(event.reply_token, TextSendMessage("請先輸入出發地和共乘選項"))
            return
        user_states[user_id]["time"] = time
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(
                text="請選擇付款方式：",
                quick_reply=QuickReply(items=[
                    QuickReplyButton(action=MessageAction(label="LINE Pay", text="我使用 LINE Pay")),
                    QuickReplyButton(action=MessageAction(label="現金", text="我使用 現金")),
                    QuickReplyButton(action=MessageAction(label="悠遊卡", text="我使用 悠遊卡"))
                ])
            )
        )
        return

    if user_input.startswith("我使用"):
        payment = user_input.replace("我使用", "").strip()
        if user_id not in user_states or "time" not in user_states[user_id]:
            line_bot_api.reply_message(event.reply_token, TextSendMessage("請先完成預約流程"))
            return

        data = user_states[user_id]
        origin_coords = geocode_location(data["origin"])
        if not origin_coords:
            line_bot_api.reply_message(event.reply_token, TextSendMessage("查詢地點失敗，請確認地名是否正確"))
            return

        conn = sqlite3.connect("rides.db")
        c = conn.cursor()
        c.execute('''
            INSERT INTO ride_records (user_id, origin, destination, ride_type, time, payment, origin_lat, origin_lng)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            user_id,
            data["origin"],
            data["destination"],
            data["ride_type"],
            data["time"],
            payment,
            origin_coords[0],
            origin_coords[1]
        ))
        conn.commit()
        conn.close()

        route_url = f"https://www.google.com/maps/dir/{urllib.parse.quote(data['origin'])}/{urllib.parse.quote(data['destination'])}"

        msg = (
            "🎉 預約完成！\n"
            f"🛫 出發地：{data['origin']}\n"
            f"🛬 目的地：{data['destination']}\n"
            f"🚘 共乘狀態：{data['ride_type']}\n"
            f"🕐 預約時間：{data['time']}\n"
            f"💳 付款方式：{payment}\n"
            f"📍 路線預覽：{route_url}\n"
            "👉 若要再次預約，請輸入『出發地 到 目的地』"
        )

        user_states.pop(user_id, None)
        line_bot_api.reply_message(event.reply_token, TextSendMessage(msg))
        return

    line_bot_api.reply_message(event.reply_token, TextSendMessage("請輸入格式為『出發地 到 目的地』"))

def to_minutes(tstr):
    try:
        h, m = map(int, tstr.split(":"))
        return h * 60 + m
    except:
        return 0

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
