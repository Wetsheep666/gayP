import os
import sqlite3
from flask import Flask, request, abort
from dotenv import load_dotenv
from linebot import LineBotApi, WebhookHandler
from linebot.models import (
    MessageEvent, TextMessage, TextSendMessage,
    QuickReply, QuickReplyButton, MessageAction
)

# 載入 .env
load_dotenv()

# 初始化 Flask
app = Flask(__name__)

# 讀取環境變數並檢查
access_token = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
secret = os.getenv("LINE_CHANNEL_SECRET")

if not access_token or not secret:
    raise EnvironmentError("❌ LINE_CHANNEL_ACCESS_TOKEN 或 LINE_CHANNEL_SECRET 未正確設置於 .env 檔案中")

line_bot_api = LineBotApi(access_token)
handler = WebhookHandler(secret)

# 暫存使用者狀態（僅記憶體內）
user_states = {}

# 初始化 SQLite 資料庫
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
            payment TEXT
        )
    ''')
    conn.commit()
    conn.close()

init_db()

@app.route("/")
def home():
    return "LineBot with SQLite is running!"

@app.route("/callback", methods=["POST"])
def callback():
    signature = request.headers.get("X-Line-Signature")
    body = request.get_data(as_text=True)

    try:
        handler.handle(body, signature)
    except Exception as e:
        print(f"[Webhook Error] {e}")
        abort(400)
    return "OK"

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    user_id = event.source.user_id
    user_input = event.message.text.strip()

    # 查詢預約紀錄
    if user_input == "查詢我的預約":
        conn = sqlite3.connect("rides.db")
        conn.row_factory = sqlite3.Row
        c = conn.cursor()

        c.execute("SELECT * FROM ride_records WHERE user_id = ?", (user_id,))
        user_rides = c.fetchall()

        if not user_rides:
            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text="你目前沒有預約紀錄。")
            )
            conn.close()
            return

        latest = user_rides[-1]
        origin = latest["origin"]
        destination = latest["destination"]
        ride_type = latest["ride_type"]
        time = latest["time"]
        payment = latest["payment"]

        c.execute('''
            SELECT * FROM ride_records
            WHERE user_id != ? AND ride_type = '共乘' AND origin = ? AND time = ?
        ''', (user_id, origin, time))
        match_found = c.fetchone() is not None
        conn.close()

        reply = f"""📋 你最近的預約如下：
🛫 出發地：{origin}
🛬 目的地：{destination}
🚘 共乘狀態：{ride_type}
🕐 預約時間：{time}
💳 付款方式：{payment}
👥 共乘配對狀態：{"✅ 已找到共乘對象！" if match_found else "⏳ 尚未有共乘對象"}
"""
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=reply)
        )
        return

    # Step 1：輸入「出發地 到 目的地」
    if "到" in user_input:
        try:
            origin, destination = map(str.strip, user_input.split("到"))
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
        except:
            pass

    # Step 2：選擇共乘與否
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
            TextSendMessage(text="請輸入你想要的搭乘時間，例如：我預約 14:30")
        )
        return

    # Step 3：輸入預約時間
    if user_input.startswith("我預約 "):
        time = user_input.replace("我預約 ", "").strip()
        if user_id not in user_states:
            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text="請先輸入『出發地 到 目的地』")
            )
            return

        user_states[user_id]["time"] = time

        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(
                text=f"🕐 你選擇的時間是：{time}\n請選擇付款方式：",
                quick_reply=QuickReply(items=[
                    QuickReplyButton(action=MessageAction(label="LINE Pay", text="我使用 LINE Pay")),
                    QuickReplyButton(action=MessageAction(label="現金", text="我使用 現金")),
                    QuickReplyButton(action=MessageAction(label="悠遊卡", text="我使用 悠遊卡")),
                ])
            )
        )
        return

    # Step 4：輸入付款方式並儲存
    if user_input.startswith("我使用 "):
        payment = user_input.replace("我使用 ", "").strip()
        if user_id not in user_states:
            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text="請先輸入『出發地 到 目的地』")
            )
            return

        user_states[user_id]["payment"] = payment
        data = user_states[user_id]

        conn = sqlite3.connect("rides.db")
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute('''
            INSERT INTO ride_records (user_id, origin, destination, ride_type, time, payment)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (
            user_id,
            data["origin"],
            data["destination"],
            data["ride_type"],
            data["time"],
            payment
        ))
        conn.commit()

        # 查找是否已有共乘對象
        c.execute('''
            SELECT * FROM ride_records
            WHERE user_id != ? AND ride_type = '共乘' AND origin = ? AND time = ?
        ''', (user_id, data["origin"], data["time"]))
        match = c.fetchone()
        conn.close()

        reply = f"""🎉 預約完成！
🛫 出發地：{data['origin']}
🛬 目的地：{data['destination']}
🚘 共乘狀態：{data['ride_type']}
🕐 預約時間：{data['time']}
💳 付款方式：{payment}
"""
        if match:
            reply += "\n🚨 發現共乘對象！你和另一位使用者搭乘相同班次！"
        reply += "\n\n👉 想再預約，請再輸入「出發地 到 目的地」"

        user_states.pop(user_id, None)

        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=reply)
        )
        return

    # 預設回覆
    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(text="請輸入格式為「出發地 到 目的地」的訊息")
    )

# ✅ 對 Render 正確綁定 PORT
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
