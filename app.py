# 儲存使用者輸入狀態的字典
user_states = {}
# 暫存所有使用者的共乘紀錄
ride_records = []


from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.models import MessageEvent, TextMessage, TextSendMessage
import os

app = Flask(__name__)

line_bot_api = LineBotApi(os.getenv('LINE_CHANNEL_ACCESS_TOKEN'))
handler = WebhookHandler(os.getenv('LINE_CHANNEL_SECRET'))

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

from linebot.models import (
    MessageEvent, TextMessage, TextSendMessage,
    QuickReply, QuickReplyButton, MessageAction
)

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    user_id = event.source.user_id
    user_input = event.message.text

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

    # Step 2：選擇共乘 or 不共乘
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

    # Step 4：選擇付款方式 + 共乘配對
    elif user_input.startswith("我使用 "):
        payment = user_input.replace("我使用 ", "")
        user_states[user_id]["payment"] = payment

        # 儲存這筆共乘紀錄
        ride_records.append({
            "user_id": user_id,
            "origin": user_states[user_id].get("origin", ""),
            "destination": user_states[user_id].get("destination", ""),
            "ride_type": user_states[user_id].get("ride_type", ""),
            "time": user_states[user_id].get("time", ""),
            "payment": payment,
        })

        # 嘗試推薦共乘對象
        matched_user = None
        for record in ride_records:
            if record["user_id"] != user_id and record["ride_type"] == "共乘":
                if record["origin"] == user_states[user_id]["origin"] and record["time"] == user_states[user_id]["time"]:
                    matched_user = record
                    break

        # 組合回覆文字
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

        # 清除狀態
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




import os

if __name__ == "__main__":
    port = int(os.environ.get('PORT', 5000))  # Render 會指定 PORT
    app.run(host='0.0.0.0', port=port)

