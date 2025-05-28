import os
import sqlite3
import uuid
from flask import Flask, request, abort
from dotenv import load_dotenv
from linebot.v3 import WebhookHandler
from linebot.v3.messaging import Configuration, ApiClient, MessagingApi, ReplyMessageRequest, TextMessage, QuickReply, QuickReplyItem, MessageAction
from linebot.v3.exceptions import InvalidSignatureError
from datetime import datetime
import logging

# 設定日誌記錄
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

load_dotenv()
app = Flask(__name__)

# 從環境變數讀取 LINE Bot 設定
LINE_CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
LINE_CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET")

if not LINE_CHANNEL_ACCESS_TOKEN or not LINE_CHANNEL_SECRET:
    logging.error("LINE_CHANNEL_ACCESS_TOKEN or LINE_CHANNEL_SECRET not set in environment variables.")
    # 在實際部署中，你可能希望應用程式在此處失敗或採取其他措施
    # For now, let it proceed so it doesn't crash immediately if run locally without .env for some reason
    # but Line API calls will fail.

configuration = Configuration(access_token=LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

# 資料庫路徑，優先從環境變數讀取，若無則使用本地的 rides.db
# 在 Render 上，請設定環境變數 DATABASE_PATH 指向 Persistent Disk 的路徑，例如 /var/data/rides.db
DATABASE_PATH = os.getenv("DATABASE_PATH", "rides.db")
logging.info(f"使用資料庫路徑: {DATABASE_PATH}")

# 使用者狀態暫存 (若應用程式重啟，此資料會遺失)
user_states = {}

def init_db():
    """初始化資料庫，如果表格不存在則創建它"""
    # 確保資料庫檔案所在的目錄存在 (主要針對 Render Persistent Disk)
    db_dir = os.path.dirname(DATABASE_PATH)
    if db_dir and not os.path.exists(db_dir):
        try:
            os.makedirs(db_dir)
            logging.info(f"成功創建資料庫目錄: {db_dir}")
        except OSError as e:
            logging.error(f"創建資料庫目錄失敗 {db_dir}: {e}")
            # 根據情況，你可能希望應用程式在此處停止
            return


    conn = None # 初始化 conn
    try:
        conn = sqlite3.connect(DATABASE_PATH)
        c = conn.cursor()
        c.execute("""
            CREATE TABLE IF NOT EXISTS ride_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                origin TEXT NOT NULL,
                destination TEXT NOT NULL,
                ride_type TEXT NOT NULL,
                time TEXT NOT NULL,
                payment TEXT,
                status TEXT DEFAULT 'waiting', /* waiting, matched, cancelled, completed */
                matched_group_id TEXT,
                price INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()
        logging.info("資料庫初始化成功 (表格 ride_records 已確認/創建)。")
    except sqlite3.Error as e:
        logging.error(f"資料庫初始化/連接失敗: {e}")
    finally:
        if conn:
            conn.close()

init_db() # 應用程式啟動時初始化資料庫

@app.route("/")
def home():
    return "LineBot with SQLite is running!"

@app.route("/callback", methods=["POST"])
def callback():
    signature = request.headers["X-Line-Signature"]
    body = request.get_data(as_text=True)
    logging.info(f"Request body: {body}")

    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        logging.error("Invalid signature. Please check your channel secret and access token.")
        abort(400)
    except Exception as e:
        logging.error(f"Error handling request: {e}")
        abort(400)
    return "OK"

def reply_message_v3(reply_token, messages):
    """使用 v3 SDK 發送回覆訊息"""
    if not LINE_CHANNEL_ACCESS_TOKEN: # 檢查 Token 是否存在
        logging.error("無法發送訊息：LINE_CHANNEL_ACCESS_TOKEN 未設定。")
        return
    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
        try:
            line_bot_api.reply_message(
                ReplyMessageRequest(
                    reply_token=reply_token,
                    messages=messages
                )
            )
        except Exception as e:
            logging.error(f"LINE API 發送訊息失敗: {e}")


def try_match(user_id_to_match):
    """嘗試為指定使用者配對共乘"""
    conn = None
    try:
        conn = sqlite3.connect(DATABASE_PATH)
        c = conn.cursor()

        # 取得提出配對請求的使用者資訊
        c.execute("SELECT id, origin, destination, time, ride_type FROM ride_records WHERE user_id = ? AND status = 'waiting' ORDER BY created_at DESC LIMIT 1", (user_id_to_match,))
        user_record = c.fetchone()

        if not user_record:
            logging.info(f"使用者 {user_id_to_match} 沒有等待中的預約可供配對。")
            return None
        
        user_db_id, origin, destination, user_time_str, ride_type = user_record

        if ride_type != '共乘':
            logging.info(f"使用者 {user_id_to_match} 的預約類型為 '{ride_type}'，非 '共乘'，不進行配對。")
            return None

        try:
            user_time_obj = datetime.strptime(user_time_str, "%H:%M").time()
        except ValueError:
            logging.error(f"無法解析使用者 {user_id_to_match} 的預約時間: {user_time_str}")
            return None

        # 尋找其他符合條件的等待中共乘使用者
        # 條件：不同使用者、狀態為 waiting、類型為共乘、相同起點和終點
        c.execute("""
            SELECT id, user_id, time FROM ride_records
            WHERE user_id != ?
            AND status = 'waiting'
            AND ride_type = '共乘'
            AND origin = ?
            AND destination = ?
        """, (user_id_to_match, origin, destination))
        
        potential_matches = c.fetchall()
        valid_matches = [] # 儲存真正符合時間條件的配對者 (包含資料庫ID和user_id)

        for match_candidate in potential_matches:
            candidate_db_id, candidate_user_id, candidate_time_str = match_candidate
            try:
                candidate_time_obj = datetime.strptime(candidate_time_str, "%H:%M").time()
                # 計算時間差 (轉換為分鐘)
                time_diff_seconds = abs(
                    (datetime.combine(datetime.today(), candidate_time_obj) - datetime.combine(datetime.today(), user_time_obj)).total_seconds()
                )
                if time_diff_seconds <= 600: # 10 分鐘內
                    valid_matches.append({'db_id': candidate_db_id, 'user_id': candidate_user_id})
            except ValueError:
                logging.warning(f"無法解析潛在配對者 {candidate_user_id} 的時間: {candidate_time_str}")
                continue
        
        if valid_matches:
            group_id = str(uuid.uuid4())[:8] # 產生一個簡短的群組ID
            
            # 包含原始請求者和所有配對成功者
            all_matched_records_db_ids = [user_db_id] + [m['db_id'] for m in valid_matches]
            all_matched_user_ids = [user_id_to_match] + [m['user_id'] for m in valid_matches]
            
            # 假設基礎價格為 200，由所有共乘者均分 (這部分可依需求調整)
            price_per_person = 200 // len(all_matched_user_ids) if len(all_matched_user_ids) > 0 else 200

            for db_id_to_update in all_matched_records_db_ids:
                c.execute("""
                    UPDATE ride_records
                    SET status = 'matched', matched_group_id = ?, price = ?
                    WHERE id = ? AND status = 'waiting' 
                """, (group_id, price_per_person, db_id_to_update))
            
            conn.commit()
            logging.info(f"配對成功！群組ID: {group_id}, 成員: {all_matched_user_ids}, 每人費用: {price_per_person}")
            
            # 通知所有配對成功的成員 (除了發起者，因為發起者會在主流程中被通知)
            for matched_user_id in all_matched_user_ids:
                if matched_user_id != user_id_to_match:
                    # 取得該配對成員的最新預約資訊來建立通知訊息
                    c.execute("SELECT origin, destination, time, payment FROM ride_records WHERE user_id = ? AND matched_group_id = ? ORDER BY created_at DESC LIMIT 1", (matched_user_id, group_id))
                    matched_user_ride_info = c.fetchone()
                    if matched_user_ride_info:
                        msg_origin, msg_dest, msg_time, msg_payment = matched_user_ride_info
                        notify_text = f"🎉 配對成功！\n你的預約 {msg_origin} 到 {msg_dest} ({msg_time}) 已找到共乘夥伴。\n群組ID: {group_id}\n💰 每人應付：{price_per_person} 元"
                        reply_message_v3(matched_user_id, [TextMessage(text=notify_text)]) # 注意：這裡的 matched_user_id 應為 reply_token，但我們沒有，所以直接用 user_id (push message)
                        # 實際上，LINE Bot 無法在非回覆情境下主動用 user_id 發訊息給任意使用者，除非使用 Push API (需付費)
                        # 或使用者先前有互動，取得了 reply_token。
                        # 這裡的作法是示意，實際應用中，通知其他已配對成員可能需要不同機制或等待他們下次互動時告知。
                        # 一個簡化的作法是，當這些被動配對者下次查詢預約時，會看到已配對的狀態。
                        logging.info(f"已嘗試通知使用者 {matched_user_id} 配對成功 (注意: 此處為示意，實際主動通知需 Push API 或其他機制)")


            return (group_id, price_per_person, all_matched_user_ids)
        else:
            logging.info(f"使用者 {user_id_to_match} ({origin} 到 {destination} 時間 {user_time_str}) 未找到合適的共乘對象。")
            return None

    except sqlite3.Error as e:
        logging.error(f"嘗試配對時資料庫錯誤 ({user_id_to_match}): {e}")
        return None
    finally:
        if conn:
            conn.close()


@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    user_id = event.source.user_id
    user_input = event.message.text.strip()
    reply_token = event.reply_token
    
    logging.info(f"收到來自使用者 {user_id} 的訊息: {user_input}")

    current_state_data = user_states.get(user_id, {})

    if user_input == "查詢我的預約":
        conn = None
        try:
            conn = sqlite3.connect(DATABASE_PATH)
            c = conn.cursor()
            # 查詢最新一筆，或特定狀態的預約
            c.execute("SELECT origin, destination, ride_type, time, payment, status, matched_group_id, price FROM ride_records WHERE user_id = ? ORDER BY created_at DESC LIMIT 1", (user_id,))
            latest_ride = c.fetchone()
            
            if not latest_ride:
                reply_message_v3(reply_token, [TextMessage(text="你目前沒有預約紀錄。")])
                return

            origin, destination, ride_type, time, payment, status, group_id, price = latest_ride
            
            price_text = f"{price} 元" if price is not None else "尚未配對"
            if status == 'matched' and group_id:
                status_text = f"已配對 (群組ID: {group_id})"
            elif status == 'waiting':
                status_text = "等待配對中"
            else:
                status_text = status.capitalize()


            reply_text = f"""📋 你最近的預約如下：
🛫 出發地：{origin}
🛬 目的地：{destination}
🚘 共乘狀態：{ride_type}
🕐 預約時間：{time}
💳 付款方式：{payment if payment else '未指定'}
📦 狀態：{status_text}
💰 分擔費用：{price_text}"""
            
            quick_reply_items = []
            if status == 'waiting':
                 quick_reply_items.append(QuickReplyItem(action=MessageAction(label="取消此預約", text="取消我的等待中預約")))

            reply_message_v3(reply_token, [TextMessage(text=reply_text, quick_reply=QuickReply(items=quick_reply_items) if quick_reply_items else None)])

        except sqlite3.Error as e:
            logging.error(f"查詢預約時資料庫錯誤 ({user_id}): {e}")
            reply_message_v3(reply_token, [TextMessage(text="查詢預約時發生錯誤，請稍後再試。")])
        finally:
            if conn:
                conn.close()
        return

    if user_input == "取消我的等待中預約": # 與上面 QuickReply 對應
        conn = None
        updated_rows = 0
        try:
            conn = sqlite3.connect(DATABASE_PATH)
            c = conn.cursor()
            # 只取消 'waiting' 狀態的最新預約
            c.execute("SELECT id FROM ride_records WHERE user_id = ? AND status = 'waiting' ORDER BY created_at DESC LIMIT 1", (user_id,))
            last_waiting_ride = c.fetchone()

            if last_waiting_ride:
                ride_id_to_cancel = last_waiting_ride[0]
                c.execute("UPDATE ride_records SET status = 'cancelled' WHERE id = ?", (ride_id_to_cancel,))
                # 或者直接刪除: c.execute("DELETE FROM ride_records WHERE id = ?", (ride_id_to_cancel,))
                conn.commit()
                updated_rows = c.rowcount
            
            if updated_rows > 0:
                reply_message_v3(reply_token, [TextMessage(text="❌ 已取消你最近的等待中預約。")])
                logging.info(f"使用者 {user_id} 取消了預約 ID: {last_waiting_ride[0] if last_waiting_ride else 'N/A'}")
            else:
                reply_message_v3(reply_token, [TextMessage(text="目前沒有可取消的等待中預約。")])

        except sqlite3.Error as e:
            logging.error(f"取消預約時資料庫錯誤 ({user_id}): {e}")
            reply_message_v3(reply_token, [TextMessage(text="取消預約時發生錯誤，請稍後再試。")])
        finally:
            if conn:
                conn.close()
        user_states.pop(user_id, None) # 清理可能存在的狀態
        return

    # 預約流程開始：輸入 "出發地 到 目的地"
    if "到" in user_input and "我預約" not in user_input and "我使用" not in user_input and "取消" not in user_input and "查詢" not in user_input:
        try:
            parts = user_input.split("到", 1) # 只分割一次
            if len(parts) == 2:
                origin, destination = map(str.strip, parts)
                if not origin or not destination: # 確保起點和終點都不是空的
                    raise ValueError("起點或終點不可為空")
            else:
                raise ValueError("格式不符")
                
            user_states[user_id] = {
                "origin": origin,
                "destination": destination,
                "stage": "ask_ride_type" # 新增一個階段標記
            }
            logging.info(f"使用者 {user_id} 設定起訖點: {origin} -> {destination}")

            reply_message_v3(
                reply_token,
                [TextMessage(
                    text=f"🚕 你要從 {origin} 到 {destination}\n請選擇是否共乘：",
                    quick_reply=QuickReply(items=[
                        QuickReplyItem(action=MessageAction(label="我要共乘", text="我選擇共乘")),
                        QuickReplyItem(action=MessageAction(label="我要自己搭", text="我不共乘")),
                    ])
                )]
            )
        except ValueError as e:
            logging.warning(f"使用者 {user_id} 輸入起訖點格式錯誤: {user_input} ({e})")
            reply_message_