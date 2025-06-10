import asyncio
import logging
import json
import base64
import os
import ssl
from datetime import datetime
from sqlmg import SqlMG
import websockets

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

CONFIG_FILE = 'client.config'
current_dir = os.getcwd()
cert_path = os.path.join(current_dir, 'source', 'cert.pem')
userid = ''

class WebSocketManager:
    def __init__(self, url='wss://localhost:9998'):
        self.url = url
        self.websocket = None
        self.loop = asyncio.get_event_loop()
        self.message_queue = asyncio.Queue()
        self.ssl_context = ssl.create_default_context()
        self.ssl_context.load_verify_locations(cert_path)  # 加载服务器证书
        self.ssl_context.verify_mode = ssl.CERT_REQUIRED  # 要求验证服务器证书
        self.sql = SqlMG('basedata.db')
        self.sql.client_sql()
        self.is_connected = False
        global userid
        self.user_id = userid
        self.username = None
        self.password = None

    @staticmethod
    def json_create(flag, id, name, message, times):
        msg = {
            "flag": flag,
            "id": id,
            "name": name,
            "message": message,
            "timestamp": times
        }
        return json.dumps(msg)

    @staticmethod
    def now():
        return datetime.now().replace(microsecond=0).isoformat()

    async def refresh_message(self):
        """同步离线信息"""
        if not os.path.exists(CONFIG_FILE):
            return
        with open(CONFIG_FILE, 'r') as f:
            config = json.load(f)
        time = config.get('time', -1)
        if time == -1:
            return
        await self.websocket.send(self.json_create(5, userid, 0, time, 0))
        async for msg in self.websocket:
            rcv = json.loads(msg)
            if rcv['message'] == "sync_complete":
                break
            elif rcv['message'] == "heartbeat":
                continue
            if rcv['flag'] == 0:
                self.sql.exec("INSERT INTO messages(sender_id, sender_username, type, message, timestamp) VALUES (?,?,?,?,?)",
                              (rcv['id'], rcv['name'], rcv['flag'], rcv['message'], rcv['timestamp']))
            elif rcv['flag'] == 8:
                rcv = self.rec_pic_msg(rcv)
                self.sql.exec(
                    "INSERT INTO messages(sender_id, sender_username, type, message, timestamp) VALUES (?,?,?,?,?)",
                    (rcv['id'], rcv['name'], rcv['flag'], rcv['message'], rcv['timestamp']))
        self.update_time(self.now())

    @staticmethod
    def update_time(timestamp):
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, 'r') as f:
                data = json.load(f)
            data['time'] = timestamp
            with open(CONFIG_FILE, 'w') as f:
                json.dump(data, f)

    async def ws_client(self, user_id, username, password):
        global userid
        user_id = userid

        if user_id == 0:
            # 注册新用户
            await self.websocket.send(self.json_create(2, 0, username, password, self.now()))
            response = await self.websocket.recv()
            rcv = json.loads(response)
            if rcv['message'] != 'REGISTERED':
                logger.error("Registration failed")
                return False

            user_id_global = rcv['id']
            logger.info(f'Your user id is: {user_id_global}')
            with open(CONFIG_FILE, 'w') as f:
                json.dump({'user_id': user_id_global, 'username': username, 'password': password, 'time': -1}, f)
        else:
            # 使用保存的用户信息登录
            await self.websocket.send(self.json_create(1, user_id, username, password, self.now()))

        response = await self.websocket.recv()
        response = json.loads(response)
        if response['message'] == "LOGIN_SUCCESS":
            logger.info("Login successful")
            await self.refresh_message()
        else:
            logger.error("Invalid user ID or password")
            return False

        self.is_connected = True
        asyncio.create_task(self.receive_messages())
        asyncio.create_task(self.heart_beat())
        return True

    def load_message_from_db(self):
        all_load = self.sql.fetch("SELECT sender_id, sender_username, message, timestamp, type FROM messages ")
        for row in all_load:
            msg = self.json_create(row['type'], row['sender_id'], row['sender_username'], row['message'], row['timestamp'])
            self.message_queue.put_nowait(msg)

    async def receive_messages(self):
        try:
            async for message in self.websocket:
                msg = json.loads(message)
                logger.info(f'收到信息：{msg}')
                if msg['message'] in ['heartbeat', 'heartbeat_ack']:
                    continue
                if msg['flag'] == 6:
                    self.sql.exec(
                        "INSERT INTO messages (sender_id, sender_username, type, message, timestamp) VALUES (?,?,?,?,?)",
                        (msg['id'], msg['name'], msg['flag'], msg['message'], msg['timestamp']))
                    self.message_queue.put_nowait(message)
                elif msg['flag'] == 7:
                    self.update_time(msg['timestamp'])
                    logging.info("[系统] 离线消息同步完成。")
                elif msg['id'] == userid:
                    if msg['flag'] == 8:
                        self.sql.exec("INSERT INTO messages (sender_id, sender_username, type, message, timestamp) VALUES (?,?,?,?,?)",
                            (msg['id'], msg['name'], msg['flag'] ,msg['message'], msg['timestamp']))
                        msg = self.rec_pic_msg(msg)
                        message = json.dumps(msg)
                    self.message_queue.put_nowait(message)
                elif msg['id'] == '0':
                    self.message_queue.put_nowait(message)
                else:
                    if msg['flag'] == 8:
                        msg = self.rec_pic_msg(msg)
                        message = json.dumps(msg)
                    self.message_queue.put_nowait(message)
        except websockets.ConnectionClosed:
            logger.error("Connection closed.")
            self.is_connected = False

    @staticmethod
    def rec_pic_msg(msg):
        received_folder = os.path.join(current_dir, 'received_pics')
        if not os.path.exists(received_folder):
            os.makedirs(received_folder)
        image_data = msg['message']
        img_name = os.path.basename(image_data)
        save_path = os.path.join(received_folder, img_name)
        with open(save_path, 'wb') as img_file:
            img_file.write(base64.b64decode(image_data))
        msg['message'] = save_path
        return  msg

    async def heart_beat(self):
        while True:
            await asyncio.sleep(30)
            msg = self.json_create(4, userid, "heartbeat", "heartbeat", self.now())
            await self.websocket.send(msg)

    async def connect_ws(self, user_id, username, password):
        try:
            self.websocket = await websockets.connect(self.url, ssl=self.ssl_context)
            return await self.ws_client(user_id, username, password)
        except Exception as e:
            logger.error(f"WebSocket连接失败: {e}")
            return False

    async def send_message(self, message):
        if not self.is_connected:
            logger.error("未连接到WebSocket服务器")
            return False
        msg = self.json_create(0, userid, self.username, message, self.now())
        self.sql.exec("INSERT INTO messages (sender_id, sender_username, tpye, message, timestamp) VALUES (?,?,?,?,?)",
                      (userid, self.username, 0, message, self.now()))
        await self.websocket.send(msg)
        return True

    async def send_image(self, image_path):
        if not self.is_connected:
            logger.error("未连接到WebSocket服务器")
            return False
        if not os.path.exists(image_path):
            logger.error(f"图片文件不存在: {image_path}")
            return False
        with open(image_path, 'rb') as img_file:
            img_data = base64.b64encode(img_file.read()).decode('utf-8')
        msg = self.json_create(8, userid, self.username, img_data, self.now())
        self.sql.exec("INSERT INTO messages (sender_id, sender_username, tpye, message, timestamp) VALUES (?,?,?,?,?)",
                          (userid, self.username, 8, image_path, self.now()))
        await self.websocket.send(msg)
        return True

    async def disconnect(self):
        if self.websocket and self.websocket.open:
            await self.websocket.close()
            self.is_connected = False
            self.sql.close()