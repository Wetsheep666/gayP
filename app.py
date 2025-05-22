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

from linebot.models import QuickReply, QuickReplyButton, MessageAction

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    user_input = event.message.text

    # 【Step 1】判斷是否是「A 到 B」格式
    if '到' in user_input:
        parts = user_input.split('到')
        if len(parts) == 2:
            origin = parts[0].strip()
            destination = parts[1].strip()

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

    # 【Step 2】使用者選擇共乘與否
    elif user_input in ["我選擇共乘", "我不共乘"]:
        ride_type = "共乘" if "共乘" in user_input else "不共乘"
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

    # 【其他】格式錯誤預設訊息
    else:
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text="請輸入格式為「出發地 到 目的地」的訊息")
        )




import os

if __name__ == "__main__":
    port = int(os.environ.get('PORT', 5000))  # Render 會指定 PORT
    app.run(host='0.0.0.0', port=port)

