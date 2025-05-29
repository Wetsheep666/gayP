
import os
import sqlite3
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage, TemplateSendMessage, ButtonsTemplate,     PostbackAction


app = Flask(__name__)
line_bot_api = LineBotApi(os.getenv("LINE_CHANNEL_ACCESS_TOKEN"))
handler = WebhookHandler(os.getenv("LINE_CHANNEL_SECRET"))

conn = sqlite3.connect('reservations.db', check_same_thread=False)
c = conn.cursor()
c.execute('''CREATE TABLE IF NOT EXISTS reservations
             (user_id TEXT, start TEXT, end TEXT, time TEXT, carpool TEXT, pay TEXT)''')
conn.commit()

user_states = {}

@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers['X-Line-Signature']
    body = request.get_data(as_text=True)

    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return 'OK'

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    user_id = event.source.user_id
    text = event.message.text

    if user_id not in user_states:
        user_states[user_id] = {}

    state = user_states[user_id]

    if text.lower() == "查詢預約":
        c.execute("SELECT * FROM reservations WHERE user_id=?", (user_id,))
        reservation = c.fetchone()
        if reservation:
            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text=f"您的預約：\n出發地：{reservation[1]}\n目的地：{reservation[2]}\n時間：{reservation[3]}\n共乘：{reservation[4]}\n付款：{reservation[5]}")
            )
        else:
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text="目前沒有預約紀錄。"))
        return

    if text.lower() == "取消預約":
        c.execute("DELETE FROM reservations WHERE user_id=?", (user_id,))
        conn.commit()
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text="您的預約已取消。"))
        return

    if "start" not in state:
        if " 到 " in text:
            start, end = text.split(" 到 ")
            state["start"] = start.strip()
            state["end"] = end.strip()
            line_bot_api.reply_message(
                event.reply_token,
                TemplateSendMessage(
                    alt_text='是否共乘',
                    template=ButtonsTemplate(
                        text="是否需要共乘？",
                        actions=[
                            PostbackAction(label="我要共乘", data="carpool_yes"),
                            PostbackAction(label="不用了", data="carpool_no")
                        ]
                    )
                )
            )
        else:
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text="請輸入格式：起點 到 終點"))
        return

    if "carpool" in state and "time" not in state:
        state["time"] = text.strip()
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(
                text=f"🕒 預約時間：{state['time']}\n🛫 出發地：{state['start']}\n🛬 目的地：{state['end']}\n請選擇付款方式以完成預約"
            )
        )
        return

    if "time" in state and "pay" not in state:
        state["pay"] = text.strip()
        c.execute("INSERT INTO reservations (user_id, start, end, time, carpool, pay) VALUES (?, ?, ?, ?, ?, ?)",
                  (user_id, state["start"], state["end"], state["time"], state["carpool"], state["pay"]))
        conn.commit()
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text="預約成功！正在為您配對共乘..."))
        try_match(user_id)
        user_states[user_id] = {}

@handler.add(MessageEvent, message=TextMessage)
def handle_postback(event):
    user_id = event.source.user_id
    data = event.postback.data

    if user_id not in user_states:
        user_states[user_id] = {}

    if data == "carpool_yes":
        user_states[user_id]["carpool"] = "是"
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text="請輸入預約時間（例如：13:30）："))
    elif data == "carpool_no":
        user_states[user_id]["carpool"] = "否"
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text="請輸入預約時間（例如：13:30）："))

def try_match(current_user_id):
    c.execute("SELECT * FROM reservations WHERE user_id=?", (current_user_id,))
    current = c.fetchone()
    if not current:
        return

    c.execute("SELECT * FROM reservations WHERE user_id!=? AND carpool='是'", (current_user_id,))
    others = c.fetchall()

    for other in others:
        if current[1] == other[1] and current[2] == other[2] and current[3] == other[3]:
            line_bot_api.push_message(current_user_id, TextSendMessage(text=f"已為您配對到共乘對象！出發地：{other[1]}，目的地：{other[2]}，時間：{other[3]}"))
            line_bot_api.push_message(other[0], TextSendMessage(text=f"已為您配對到共乘對象！出發地：{current[1]}，目的地：{current[2]}，時間：{current[3]}"))
            return

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)

