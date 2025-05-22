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

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    user_input = event.message.text

    if '到' in user_input:
        parts = user_input.split('到')
        if len(parts) == 2:
            origin = parts[0].strip()
            destination = parts[1].strip()
            reply = f"✅ 出發地：{origin}\n✅ 目的地：{destination}"
        else:
            reply = "請使用「出發地 到 目的地」格式，例如：東吳大學到士林捷運站"
    else:
        reply = "請輸入格式為「出發地 到 目的地」的訊息"

    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(text=reply)
    )


import os

if __name__ == "__main__":
    port = int(os.environ.get('PORT', 5000))  # Render 會指定 PORT
    app.run(host='0.0.0.0', port=port)

