import os
import sqlite3
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.models import MessageEvent, TextMessage, TextSendMessage

# 初始化 Flask 應用
app = Flask(__name__)

# 初始化 LINE Bot
line_bot_api = LineBotApi(os.getenv('LINE_CHANNEL_ACCESS_TOKEN'))
handler = WebhookHandler(os.getenv('LINE_CHANNEL_SECRET'))

# 初始化 SQLite 資料庫
def init_db():
    conn = sqlite3.connect('rides.db')
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS ride_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT,
            message TEXT
        )
    ''')
    conn.commit()
    conn.close()

init_db()

@app.route("/")
def home():
    return "LineBot is running!"

# 資料庫查看用
@app.route("/dump")
def dump():
    conn = sqlite3.connect('rides.db')
    c = conn.cursor()
    c.execute('SELECT * FROM ride_records')
    records = c.fetchall()
    conn.close()
    return "<pre>" + "\n".join(str(r) for r in records) + "</pre>"

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

    # 寫入資料庫
    conn = sqlite3.connect('rides.db')
    c = conn.cursor()
    c.execute('INSERT INTO ride_records (user_id, message) VALUES (?, ?)', (user_id, user_input))
    conn.commit()
    conn.close()

    reply_text = f"你的訊息「{user_input}」已儲存到資料庫中！"
    line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_text))

# 啟動 Flask 伺服器
if __name__ == "__main__":
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
