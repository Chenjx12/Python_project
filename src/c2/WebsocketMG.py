import asyncio
import logging
import json
import base64
import os
import ssl
import string
from datetime import datetime
from sqlmg import SqlMG
import websockets
from PIL import Image
import io
import random

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

CONFIG_FILE = 'client.config'
current_dir = os.getcwd()
cert_path = os.path.join(current_dir, 'source', 'cert.pem')

# 消息大小限制（10MB）
MAX_MESSAGE_SIZE = 10 * 1024 * 1024
# 图片压缩质量（1-100）
IMAGE_QUALITY = 85
# 最大图片尺寸
MAX_IMAGE_SIZE = (1920, 1080)


# 全局变量
class GlobalState:
    def __init__(self):
        self.user_id = None
        self.username = None
        self.password = None


global_state = GlobalState()


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

    @staticmethod
    def json_create(flag, id, name, message, times):
        # 如果times是datetime对象，转换为isoformat字符串
        if isinstance(times, datetime):
            times = times.isoformat()
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
            logger.info("配置文件不存在，跳过同步")
            return
        with open(CONFIG_FILE, 'r') as f:
            config = json.load(f)
        time = config.get('time', -1)
        if time == -1:
            logger.info("时间戳为-1，跳过同步")
            self.update_time(self.now())
            return
        logger.info(f"开始请求同步，上次同步时间：{time}")
        try:
            await self.websocket.send(self.json_create(5, global_state.user_id, 0, time, 0))
            logger.info("同步请求已发送")
            async for msg in self.websocket:
                rcv = json.loads(msg)
                rcv['timestamp'] = datetime.fromisoformat(rcv['timestamp'])
                logger.info(f"收到同步消息：{rcv}")
                if rcv['message'] == "sync_complete":
                    logger.info("同步完成")
                    break
                elif rcv['message'] == "heartbeat":
                    continue
                if rcv['flag'] == 0:
                    self.sql.exec(
                        "INSERT INTO messages(sender_id, sender_username, type, message, timestamp) VALUES (?,?,?,?,?)",
                        (rcv['id'], rcv['name'], rcv['flag'], rcv['message'], rcv['timestamp']))
                elif rcv['flag'] == 8:
                    rcv = self.rec_pic_msg(rcv)
                    self.sql.exec(
                        "INSERT INTO messages(sender_id, sender_username, type, message, timestamp) VALUES (?,?,?,?,?)",
                        (rcv['id'], rcv['name'], rcv['flag'], rcv['message'], rcv['timestamp']))
        except Exception as e:
            logger.error(f"同步过程中发生错误：{e}")
            # return
        self.update_time(self.now())
        logger.info("时间戳已更新")
        time = datetime.fromisoformat(time)
        result = self.sql.fetch("""
                SELECT sender_id, sender_username, message, timestamp, type
                FROM messages
                ORDER BY timestamp
            """, )
        logger.info(f"从数据库加载了 {len(result)} 条消息")
        for row in result:
            logger.info(f"加载消息：{row}")
            self.message_queue.put_nowait(
                self.json_create(row['type'], row['sender_id'], row['sender_username'], row['message'],
                               row['timestamp']))
        self.message_queue.put_nowait(self.json_create(7,0,0,0,0))

    @staticmethod
    def update_time(timestamp):
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, 'r') as f:
                data = json.load(f)
            data['time'] = timestamp
            with open(CONFIG_FILE, 'w') as f:
                json.dump(data, f)

    async def ws_client(self, user_id, username, password):
        # 更新全局状态
        global_state.user_id = user_id
        global_state.username = username
        global_state.password = password

        if user_id == 0:
            # 注册新用户
            await self.websocket.send(self.json_create(2, 0, username, password, self.now()))
            response = await self.websocket.recv()
            rcv = json.loads(response)
            if rcv['message'] != 'REGISTERED':
                logger.error("Registration failed")
                return False

            user_id_global = rcv['id']
            global_state.user_id = user_id_global
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
            # 先进行消息同步
            try:
                await self.refresh_message()
                # 同步成功后再启动其他任务
                self.is_connected = True
                asyncio.create_task(self.receive_messages())
                asyncio.create_task(self.heart_beat())
            except Exception as e:
                logger.error(f"同步失败：{e}")
                return False
        else:
            logger.error("Invalid user ID or password")
            return False

        return True

    def load_message_from_db(self):
        all_load = self.sql.fetch("SELECT sender_id, sender_username, message, timestamp, type FROM messages ")
        for row in all_load:
            logger.info(f"加载历史消息：{row}")
            msg = self.json_create(row['type'], row['sender_id'], row['sender_username'], row['message'],
                                   row['timestamp'])
            self.message_queue.put_nowait(msg)

    async def receive_messages(self):
        try:
            async for message in self.websocket:
                msg = json.loads(message)
                logger.info(f'收到信息：{msg}')
                msg['timestamp'] = datetime.fromisoformat(msg['timestamp'])
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
                # elif msg['id'] == global_state.user_id:
                elif msg['flag'] == 8:
                    self.sql.exec(
                        "INSERT INTO messages (sender_id, sender_username, type, message, timestamp) VALUES (?,?,?,?,?)",
                        (msg['id'], msg['name'], msg['flag'], msg['message'], msg['timestamp']))
                    msg = self.rec_pic_msg(msg)
                    msg['timestamp'] = msg['timestamp'].isoformat()
                    message = json.dumps(msg)
                    self.message_queue.put_nowait(message)
                elif msg['id'] == '0':
                    self.message_queue.put_nowait(message)
                elif msg['flag'] == 10:
                    msg = self.rec_pic_msg(msg)



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
        # 此处储存的名称应当改为可读的随机编号
        img_name = 'chat_' + global_state.user_id + '_' + ''.join(
            random.choices(string.ascii_lowercase + string.digits, k=8)) + '.jpg'
        save_path = os.path.join(received_folder, img_name)
        with open(save_path, 'wb') as img_file:
            img_file.write(base64.b64decode(image_data))
        msg['message'] = save_path
        return msg

    async def heart_beat(self):
        while True:
            await asyncio.sleep(30)
            msg = self.json_create(4, global_state.user_id, "heartbeat", "heartbeat", self.now())
            await self.websocket.send(msg)

    async def connect_ws(self, user_id, username, password):
        try:
            # 设置最大消息大小
            self.websocket = await websockets.connect(
                self.url,
                ssl=self.ssl_context,
                max_size=MAX_MESSAGE_SIZE
            )
            return await self.ws_client(user_id, username, password)
        except Exception as e:
            logger.error(f"WebSocket连接失败: {e}")
            return False

    async def send_message(self, message):
        if not self.is_connected:
            logger.error("未连接到WebSocket服务器")
            return False
        try:
            msg = self.json_create(0, global_state.user_id, global_state.username, message, self.now())
            self.sql.exec(
                "INSERT INTO messages (sender_id, sender_username, type, message, timestamp) VALUES (?,?,?,?,?)",
                (global_state.user_id, global_state.username, 0, message, datetime.now()))
            await self.websocket.send(msg)
            return True
        except Exception as e:
            logger.error(f"发送消息失败: {e}")
            self.is_connected = False
            return False

    def compress_image(self, image_path):
        """压缩图片"""
        try:
            # 打开图片
            with Image.open(image_path) as img:
                # 转换为RGB模式（如果是RGBA，去除透明通道）
                if img.mode in ('RGBA', 'P'):
                    img = img.convert('RGB')

                # 调整图片大小
                if img.size[0] > MAX_IMAGE_SIZE[0] or img.size[1] > MAX_IMAGE_SIZE[1]:
                    img.thumbnail(MAX_IMAGE_SIZE, Image.Resampling.LANCZOS)

                # 保存到内存中
                output = io.BytesIO()
                img.save(output, format='JPEG', quality=IMAGE_QUALITY, optimize=True)
                compressed_data = output.getvalue()

                # 检查压缩后的大小
                if len(compressed_data) > MAX_MESSAGE_SIZE:
                    logger.error(f"图片压缩后仍然超过大小限制: {len(compressed_data)} bytes > {MAX_MESSAGE_SIZE} bytes")
                    return None

                return compressed_data
        except Exception as e:
            logger.error(f"压缩图片时出错: {e}")
            return None

    async def send_image(self, image_path):
        if not self.is_connected:
            logger.error("未连接到WebSocket服务器")
            return False
        try:
            if not os.path.exists(image_path):
                logger.error(f"图片文件不存在: {image_path}")
                return False

            # 压缩图片
            compressed_data = self.compress_image(image_path)
            if compressed_data is None:
                return False

            # 转换为base64
            img_data = base64.b64encode(compressed_data).decode('utf-8')

            msg = self.json_create(8, global_state.user_id, global_state.username, img_data, self.now())
            self.sql.exec(
                "INSERT INTO messages (sender_id, sender_username, type, message, timestamp) VALUES (?,?,?,?,?)",
                (global_state.user_id, global_state.username, 8, image_path, datetime.now()))
            await self.websocket.send(msg)
            return True
        except Exception as e:
            logger.error(f"发送图片失败: {e}")
            self.is_connected = False
            return False

    async def disconnect(self):
        if self.websocket and self.websocket.open:
            await self.websocket.close()
            self.is_connected = False
            self.sql.close()
