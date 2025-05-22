import os
import sqlite3
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.models import (
    MessageEvent, TextMessage, TextSendMessage,
    QuickReply, QuickReplyButton, MessageAction
)

# 初始化 Flask app
app = Flask(__name__)

# 初始化 LINE Bot
line_bot_api = LineBotApi(os.getenv('LINE_CHANNEL_ACCESS_TOKEN'))
handler = WebhookHandler(os.getenv('LINE_CHANNEL_SECRET'))

# 初始化使用者狀態記憶
user_states = {}

# 初始化 SQLite 資料庫
def init_db():
    conn = sqlite3.connect('rides.db')
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS ride_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT,
            origin TEXT,
            destination TEXT,
            ride_type TEXT,
            time TEXT,
            payment TEXT
        )
    ''')
    conn.commit()
    conn.close()

init_db()

@app.route("/")
def home():
    return "LineBot is running!"

@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers['X-Line-Signature']
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except:
        abort(400)
    return 'OK'

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    user_id = event.source.user_id
    user_input = event.message.text

    # 查詢預約
    if user_input == "查詢我的預約":
        conn = sqlite3.connect('rides.db')
        c = conn.cursor()
        c.execute('SELECT * FROM ride_records WHERE user_id = ?', (user_id,))
        user_rides = c.fetchall()
        conn.close()

        if not user_rides:
            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text="你目前尚未建立任何預約。")
            )
            return

        latest_ride = user_rides[-1]
        origin = latest_ride[2]
        destination = latest_ride[3]
        ride_type = latest_ride[4]
        time = latest_ride[5]
        payment = latest_ride[6]

        # 嘗試找是否有其他共乘配對
        conn = sqlite3.connect('rides.db')
        c = conn.cursor()
        c.execute('''
            SELECT * FROM ride_records
            WHERE user_id != ? AND ride_type = '共乘' AND origin = ? AND time = ?
        ''', (user_id, origin, time))
        match_found = c.fetchone() is not None
        conn.close()

        reply_text = f"""📋 你最近的預約如下：
🛫 出發地：{origin}
🛬 目的地：{destination}
🚘 共乘狀態：{ride_type}
🕐 預約時間：{time}
💳 付款方式：{payment}
👥 共乘配對狀態：{"已找到共乘對象！" if match_found else "尚未有共乘對象"}
"""
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=reply_text)
        )
        return

    # Step 1：輸入出發地和目的地
    if '到' in user_input:
        origin, destination = user_input.split('到')
        origin = origin.strip()
        destination = destination.strip()
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

    # Step 2：共乘選擇
    elif user_input in ["我選擇共乘", "我不共乘"]:
        ride_type = "共乘" if "共乘" in user_input else "不共乘"
        user_states[user_id]["ride_type"] = ride_type

        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(
                text=f"✅ 你選擇了：{ride_type}\n請選擇你預約的搭乘時間：",
                quick_reply=QuickReply(items=[
                    QuickReplyButton(action=MessageAction(label="12:00", text="我選擇 12:00")),
                    QuickReplyButton(action=MessageAction(label="13:00", text="我選擇 13:00")),
                    QuickReplyButton(action=MessageAction(label="14:00", text="我選擇 14:00")),
                ])
            )
        )

    # Step 3：選擇時間
    elif user_input.startswith("我選擇 "):
        time = user_input.replace("我選擇 ", "")
        user_states[user_id]["time"] = time

        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(
                text=f"🕐 你選擇的搭乘時間是：{time}\n請選擇付款方式：",
                quick_reply=QuickReply(items=[
                    QuickReplyButton(action=MessageAction(label="LINE Pay", text="我使用 LINE Pay")),
                    QuickReplyButton(action=MessageAction(label="現金", text="我使用 現金")),
                    QuickReplyButton(action=MessageAction(label="悠遊卡", text="我使用 悠遊卡")),
                ])
            )
        )

    # Step 4：付款並儲存資料
    elif user_input.startswith("我使用 "):
        payment = user_input.replace("我使用 ", "")
        user_states[user_id]["payment"] = payment

        conn = sqlite3.connect('rides.db')
        c = conn.cursor()
        c.execute('''
            INSERT INTO ride_records (user_id, origin, destination, ride_type, time, payment)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (
            user_id,
            user_states[user_id].get("origin", ""),
            user_states[user_id].get("destination", ""),
            user_states[user_id].get("ride_type", ""),
            user_states[user_id].get("time", ""),
            payment
        ))
        conn.commit()
        conn.close()

        # 查詢是否有共乘推薦
        conn = sqlite3.connect('rides.db')
        c = conn.cursor()
        c.execute('''
            SELECT * FROM ride_records
            WHERE user_id != ? AND ride_type = '共乘' AND origin = ? AND time = ?
        ''', (user_id, user_states[user_id]["origin"], user_states[user_id]["time"]))
        matched_user = c.fetchone()
        conn.close()

        reply_text = f"""🎉 預約完成！
🛫 出發地：{user_states[user_id]['origin']}
🛬 目的地：{user_states[user_id]['destination']}
🚘 共乘狀態：{user_states[user_id]['ride_type']}
🕐 預約時間：{user_states[user_id]['time']}
💳 付款方式：{payment}
"""

        if matched_user:
            reply_text += "\n🚨 發現可共乘使用者！你和「某位用戶」在同一時間、同一地點發車！"

        reply_text += "\n\n👉 如果要再預約，請再輸入一次「出發地 到 目的地」"

        user_states.pop(user_id, None)

        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=reply_text)
        )

    # 預設錯誤訊息
    else:
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text="請輸入格式為「出發地 到 目的地」的訊息")
        )

# 啟動 Flask 伺服器
if __name__ == "__main__":
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
