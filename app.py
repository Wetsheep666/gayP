import os
import sqlite3
from flask import Flask, request, abort
from dotenv import load_dotenv
from linebot import LineBotApi, WebhookHandler
from linebot.models import (
    MessageEvent, TextMessage, TextSendMessage,
    QuickReply, QuickReplyButton, MessageAction
)

# 載入 .env 檔案中的環境變數
load_dotenv()

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
    user_input = event.message.text.strip()

    # Step 1：輸入出發地與目的地
    if '到' in user_input:
        origin, destination = user_input.split('到')
        user_states[user_id] = {
            "origin": origin.strip(),
            "destination": destination.strip()
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

    # Step 2：共乘 or 不共乘
    elif user_input in ["我選擇共乘", "我不共乘"]:
        ride_type = "共乘" if "共乘" in user_input else "不共乘"
        if user_id in user_states:
            user_states[user_id]["ride_type"] = ride_type

            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(
                    text="✅ 你選擇了共乘方式，請選擇預約時間：",
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
        if user_id in user_states:
            user_states[user_id]["time"] = time

            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(
                    text="🕐 你選擇了時間，請選擇付款方式：",
                    quick_reply=QuickReply(items=[
                        QuickReplyButton(action=MessageAction(label="LINE Pay", text="我使用 LINE Pay")),
                        QuickReplyButton(action=MessageAction(label="現金", text="我使用 現金")),
                        QuickReplyButton(action=MessageAction(label="悠遊卡", text="我使用 悠遊卡")),
                    ])
                )
            )

    # Step 4：付款並儲存進 SQLite
    elif user_input.startswith("我使用 "):
        payment = user_input.replace("我使用 ", "")
        if user_id in user_states:
            user_states[user_id]["payment"] = payment

            # 儲存資料到 SQLite
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

            reply_text = f"""🎉 預約完成！

🛫 出發地：{user_states[user_id]['origin']}
🛬 目的地：{user_states[user_id]['destination']}
🚘 共乘狀態：{user_states[user_id]['ride_type']}
🕐 預約時間：{user_states[user_id]['time']}
💳 付款方式：{payment}
👉 若要再預約，請重新輸入「出發地 到 目的地」
"""
            user_states.pop(user_id, None)

            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text=reply_text)
            )

    # 查詢預約
    elif user_input == "查詢我的預約":
        conn = sqlite3.connect('rides.db')
        c = conn.cursor()
        c.execute('SELECT * FROM ride_records WHERE user_id = ?', (user_id,))
        results = c.fetchall()
        conn.close()

        if not results:
            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text="❗你目前沒有任何預約紀錄")
            )
            return

        latest = results[-1]
        reply = f"""📋 你最近的預約如下：

🛫 出發地：{latest[2]}
🛬 目的地：{latest[3]}
🚘 共乘狀態：{latest[4]}
🕐 預約時間：{latest[5]}
💳 付款方式：{latest[6]}
"""
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=reply)
        )

    # 預設回應
    else:
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text="請輸入「出發地 到 目的地」來開始預約流程 🚖")
        )

# 啟動伺服器
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
