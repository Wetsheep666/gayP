# 儲存使用者輸入狀態的字典
user_states = {}

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

    # 初始化該使用者的狀態 dict
    if user_id not in user_states:
        user_states[user_id] = {}

    # Step 1：解析「A 到 B」
    if '到' in user_input:
        parts = user_input.split('到')
        if len(parts) == 2:
            origin = parts[0].strip()
            destination = parts[1].strip()
            user_states[user_id]['origin'] = origin
            user_states[user_id]['destination'] = destination

            reply_text = f"✅ 出發地：{origin}\n✅ 目的地：{destination}\n請選擇是否共乘："

            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(
                    text=reply_text,
                    quick_reply=QuickReply(items=[
                        QuickReplyButton(action=MessageAction(label="共乘", text="我選擇共乘")),
                        QuickReplyButton(action=MessageAction(label="不共乘", text="我不共乘")),
                    ])
                )
            )
            return

    # Step 2：選擇共乘與否
    elif user_input in ["我選擇共乘", "我不共乘"]:
        ride_type = "共乘" if "共乘" in user_input else "不共乘"
        user_states[user_id]['ride_type'] = ride_type

        reply_text = f"✅ 你選擇了：{ride_type}\n請選擇你預約的搭乘時間："

        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(
                text=reply_text,
                quick_reply=QuickReply(items=[
                    QuickReplyButton(action=MessageAction(label="12:00", text="我選擇 12:00")),
                    QuickReplyButton(action=MessageAction(label="13:00", text="我選擇 13:00")),
                    QuickReplyButton(action=MessageAction(label="14:00", text="我選擇 14:00")),
                ])
            )
        )
        return

    # Step 3：選擇搭乘時間
    elif user_input.startswith("我選擇 ") and ":" in user_input:
        time = user_input.replace("我選擇 ", "")
        user_states[user_id]['time'] = time

        reply_text = f"✅ 搭乘時間：{time}\n請選擇付款方式："

        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(
                text=reply_text,
                quick_reply=QuickReply(items=[
                    QuickReplyButton(action=MessageAction(label="信用卡", text="我使用 信用卡")),
                    QuickReplyButton(action=MessageAction(label="LINE Pay", text="我使用 LINE Pay")),
                    QuickReplyButton(action=MessageAction(label="現金", text="我使用 現金")),
                ])
            )
        )
        return

    # Step 4：選擇付款方式（最終彙整）
    elif user_input.startswith("我使用 "):
        payment = user_input.replace("我使用 ", "")
        user_states[user_id]['payment'] = payment

        state = user_states[user_id]
        reply_text = f"""🎉 預約完成！

🛫 出發地：{state.get('origin', '未填')}
🛬 目的地：{state.get('destination', '未填')}
🚘 共乘狀態：{state.get('ride_type', '未選')}
🕐 預約時間：{state.get('time', '未選')}
💳 付款方式：{state.get('payment', '未填')}

👉 如果要再預約，請再輸入一次「出發地 到 目的地」
"""

        # 清除該使用者狀態（你也可以選擇保留）
        user_states.pop(user_id, None)

        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=reply_text)
        )
        return

    # 預設回覆
    else:
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text="請輸入格式為「出發地 到 目的地」的訊息")
        )







import os

if __name__ == "__main__":
    port = int(os.environ.get('PORT', 5000))  # Render 會指定 PORT
    app.run(host='0.0.0.0', port=port)

