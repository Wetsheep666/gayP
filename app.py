import os
import sqlite3
import uuid
from flask import Flask, request, abort
from dotenv import load_dotenv
from linebot import LineBotApi, WebhookHandler
from linebot.models import (
    MessageEvent, TextMessage, TextSendMessage,
    QuickReply, QuickReplyButton, MessageAction
)
from datetime import datetime

load_dotenv()
app = Flask(__name__)

line_bot_api = LineBotApi(os.getenv("LINE_CHANNEL_ACCESS_TOKEN"))
handler = WebhookHandler(os.getenv("LINE_CHANNEL_SECRET"))
user_states = {}

def init_db():
    conn = sqlite3.connect("rides.db")
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS ride_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT,
            origin TEXT,
            destination TEXT,
            ride_type TEXT,
            time TEXT,
            payment TEXT,
            status TEXT DEFAULT 'waiting',
            matched_group_id TEXT,
            price INTEGER
        )
    """)
    conn.commit()
    conn.close()

init_db()

@app.route("/")
def home():
    return "LineBot with SQLite is running!"

@app.route("/callback", methods=["POST"])
def callback():
    signature = request.headers["X-Line-Signature"]
    body = request.get_data(as_text=True)

    try:
        handler.handle(body, signature)
    except:
        abort(400)
    return "OK"

def try_match(user_id):
    conn = sqlite3.connect("rides.db")
    c = conn.cursor()

    c.execute("SELECT * FROM ride_records WHERE user_id = ? AND status = 'waiting'", (user_id,))
    user = c.fetchone()
    if not user:
        conn.close()
        return None

    origin, destination, user_time_str = user[2], user[3], user[5]
    try:
        user_time = datetime.strptime(user_time_str, "%H:%M")
    except:
        conn.close()
        return None

    c.execute("""
        SELECT * FROM ride_records
        WHERE user_id != ?
        AND status = 'waiting'
        AND ride_type = '共乘'
        AND origin = ?
        AND destination = ?
    """, (user_id, origin, destination))
    matches = []
    for row in c.fetchall():
        try:
            match_time = datetime.strptime(row[5], "%H:%M")
            if abs((match_time - user_time).total_seconds()) <= 600:
                matches.append(row)
        except:
            continue

    if matches:
        group_id = str(uuid.uuid4())[:8]
        matched_ids = [user_id] + [m[1] for m in matches]
        price = 200 // len(matched_ids)

        for uid in matched_ids:
            c.execute("""
                UPDATE ride_records
                SET status = 'matched', matched_group_id = ?, price = ?
                WHERE user_id = ? AND status = 'waiting'
            """, (group_id, price, uid))
        conn.commit()
        conn.close()
        return (group_id, price, matched_ids)
    else:
        conn.close()
        return None

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    user_id = event.source.user_id
    user_input = event.message.text.strip()

    if user_input == "查詢我的預約":
        conn = sqlite3.connect("rides.db")
        c = conn.cursor()
        c.execute("SELECT * FROM ride_records WHERE user_id = ?", (user_id,))
        user_rides = c.fetchall()
        conn.close()

        if not user_rides:
            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text="你目前沒有預約紀錄。")
            )
            return

        latest = user_rides[-1]
        origin, destination, ride_type, time, payment, status, price = latest[2:9]

        reply = f"""📋 你最近的預約如下：
🛫 出發地：{origin}
🛬 目的地：{destination}
🚘 共乘狀態：{ride_type}
🕐 預約時間：{time}
💳 付款方式：{payment}
📦 狀態：{status}
💰 分擔費用：{price if price else '尚未配對'}
"""
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=reply)
        )
        return

    if user_input == "取消預約":
        conn = sqlite3.connect("rides.db")
        c = conn.cursor()
        c.execute("DELETE FROM ride_records WHERE user_id = ? AND status = 'waiting'", (user_id,))
        conn.commit()
        conn.close()

        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text="❌ 已取消等待中的預約。")
        )
        return

    if "到" in user_input and "我預約" not in user_input and "我使用" not in user_input:
        try:
            origin, destination = map(str.strip, user_input.split("到"))
        except ValueError:
            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text="請輸入格式為『出發地 到 目的地』")
            )
            return

        user_states[user_id] = {
            "origin": origin,
            "destination": destination
        }

        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(
                text=f"🚕 你要從 {origin} 到 {destination}\n請選擇是否共乘：",
                quick_reply=QuickReply(items=[
                    QuickReplyButton(action=MessageAction(label="我要共乘", text="我選擇共乘")),
                    QuickReplyButton(action=MessageAction(label="我要自己搭", text="我不共乘")),
                ])
            )
        )
        return

    if user_input in ["我選擇共乘", "我不共乘"]:
        ride_type = "共乘" if "共乘" in user_input else "不共乘"
        if user_id not in user_states:
            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text="請先輸入『出發地 到 目的地』")
            )
            return

        user_states[user_id]["ride_type"] = ride_type

        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text="請輸入你想預約的時間，例如：我預約 15:30")
        )
        return

    if user_input.startswith("我預約"):
        time = user_input.replace("我預約", "").strip()
        if user_id not in user_states or "ride_type" not in user_states[user_id]:
            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text="請先輸入『出發地 到 目的地』並選擇共乘狀態")
            )
            return

        user_states[user_id]["time"] = time

        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(
                text=f"🕐 你選擇的時間是 {time}\n請選擇付款方式：",
                quick_reply=QuickReply(items=[
                    QuickReplyButton(action=MessageAction(label="LINE Pay", text="我使用 LINE Pay")),
                    QuickReplyButton(action=MessageAction(label="現金", text="我使用 現金")),
                    QuickReplyButton(action=MessageAction(label="悠遊卡", text="我使用 悠遊卡")),
                ])
            )
        )
        return

    if user_input.startswith("我使用"):
        payment = user_input.replace("我使用", "").strip()
        if user_id not in user_states or "time" not in user_states[user_id]:
            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text="請先完成前面的預約步驟")
            )
            return

        user_states[user_id]["payment"] = payment
        data = user_states[user_id]

        conn = sqlite3.connect("rides.db")
        c = conn.cursor()
        c.execute("""
            INSERT INTO ride_records (user_id, origin, destination, ride_type, time, payment)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            user_id,
            data["origin"],
            data["destination"],
            data["ride_type"],
            data["time"],
            payment
        ))
        conn.commit()
        conn.close()

        match_result = try_match(user_id)
        route_url = f"https://www.google.com/maps/dir/{data['origin']}/{data['destination']}"

        reply = f"""🎉 預約完成！
🛫 出發地：{data['origin']}
🛬 目的地：{data['destination']}
🚘 共乘狀態：{data['ride_type']}
🕐 預約時間：{data['time']}
💳 付款方式：{payment}"""

        if match_result:
            group_id, price, matched_ids = match_result
            reply += f"\n✅ 配對成功！你已與其他 {len(matched_ids)-1} 位乘客共乘。\n💰 每人應付：{price} 元"
        else:
            reply += "\n⏳ 尚未找到共乘對象，你現在正在等待中...\n輸入『取消預約』可退出配對等待。"

        reply += f"\n\n📍 路線預覽：\n{route_url}\n👉 想再預約，請輸入『出發地 到 目的地』"

        user_states.pop(user_id, None)

        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=reply)
        )
        return

    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(text="請輸入格式為『出發地 到 目的地』的訊息")
    )

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
