#!/usr/bin/python3
import asyncio
import base64
import json
import websockets
import logging
from datetime import datetime
import os
import hashlib
import ssl
from sqlmg import SqlMG

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# 消息大小限制（10MB）
MAX_MESSAGE_SIZE = 10 * 1024 * 1024

# ssl证书
current_dir = os.path.dirname(os.path.abspath(__file__))
cert_path = os.path.join(current_dir, 'serve_source', 'cert.pem')
key_path = os.path.join(current_dir, 'serve_source', 'key.pem')

# 已连接的客户端集合
connected_clients = {}

# 客户端心跳信息
client_heartbeats = {}

# SQLite数据库设置
sql = SqlMG('clients.db')
sql.sever_sql()

def json_create(flag, id, name, message, times):
    """
    | flag | 功能 |
    | 0 | 普通消息 |
    | 1 | 登录消息 |
    | 2 | 注册消息 |
    | 3 | 服务端心跳包 |
    | 4 | 客户端心跳包 |
    | 5 | 服务端同步离线消息 |
    | 6 | 客户端离线消息同步请求 |
    | 7 | 服务端离线消息同步完成 |
    | 8 | 图片消息 |
    | 9 | 文件消息 |
    """
    msg = {
        "flag": flag,
        "id": id,
        "name": name,
        "message": message,
        "timestamp": times
    }
    return json.dumps(msg)

def pic_msg(msg, user_id):
    """处理图片消息"""
    # 确保/pic/文件夹存在，用于存储图片
    pic_folder = os.path.join(current_dir, 'pic')
    if not os.path.exists(pic_folder):
        os.makedirs(pic_folder)

    image_data = msg['message']  # 图片数据，假设是base64编码
    image_name = f"image_{user_id}_{datetime.now().strftime('%Y%m%d%H%M%S')}.jpg"
    image_path = os.path.join(pic_folder, image_name)

    # 解码图片并保存到磁盘
    with open(image_path, 'wb') as img_file:
        img_file.write(base64.b64decode(image_data))  # 假设是base64编码的图片

    return image_path

# 检查客户端心跳状态
async def check_client_heartbeats():
    """检查客户端心跳状态"""
    while True:
        current_time = datetime.now()
        for user_id, last_heartbeat in list(client_heartbeats.items()):
            # 计算时间差（秒）
            time_diff = (current_time - last_heartbeat).total_seconds()
            if time_diff > 60:  # 超过60秒未收到心跳包
                logging.info(f"客户端 {user_id} 超过60秒未发送心跳包，标记为离线。")
                connected_clients.pop(user_id, None)
                client_heartbeats.pop(user_id, None)
        await asyncio.sleep(10)  # 每10秒检查一次

# 验证客户端的用户ID和密码
def authenticate_client(user_id, password) -> bool:
    """验证客户端的用户ID和密码"""
    result = sql.fetch("SELECT password_hash, salt FROM clients WHERE user_id = ?", (user_id,))
    if result:
        password_hash, salt = result[0]['password_hash'], result[0]['salt']
        input_hash = hashlib.sha256((password + salt).encode()).hexdigest()
        return input_hash == password_hash
    return False


# 注册新客户端
def register_client(username, password) -> int | None:
    """注册新客户端"""
    try:
        salt = os.urandom(16).hex()
        password_hash = hashlib.sha256((password + salt).encode()).hexdigest()
        sql.exec('INSERT INTO clients (username, password_hash, salt) VALUES (?, ?, ?)', (username, password_hash, salt))
        result = sql.fetch('SELECT user_id FROM clients WHERE username = ?', (username,))
        return result[0]['user_id'] if result else None
    except Exception as e:
        logging.error(f"Error: {e}")
        return None

def now():
    """返回现在的格式化时间"""
    return datetime.now().replace(microsecond=0).isoformat()

# 存储消息记录
def store_message(message):
    """存储消息记录"""
    sql.exec("INSERT INTO messages (sender_id, sender_username, message, timestamp, type) VALUES (?, ?, ?, ?, ?)",
             ( message['id'], message['name'], message['message'], datetime.fromisoformat(message['timestamp']), message['flag']))


# 定期向客户端发送心跳包
async def send_heartbeats():
    """定期向客户端发送心跳包"""
    while True:
        for user_id, client in connected_clients.items():
            try:
                await client.send(json_create(3, 0, 0, "heartbeat", now()))
                logging.info(f"向客户端 {user_id} 发送心跳包")
            except websockets.ConnectionClosed:
                logging.info(f"客户端 {user_id} 连接已关闭，移除客户端")
                connected_clients.pop(user_id, None)
                client_heartbeats.pop(user_id, None)
        await asyncio.sleep(30)  # 每30秒发送一次心跳包

# WebSocket连接处理函数
async def handler(websocket):
    try:
        try:
            user_id = None
            async for raw_message in websocket:
                msg = json.loads(raw_message)
                flag = msg.get("flag")
                logging.info(msg)

                if flag == 4 and user_id is not None:  # 客户端心跳
                    client_heartbeats[user_id] = datetime.now()
                    logging.info(f"收到心跳：{user_id}")
                    continue

                elif flag == 1:  # 登录
                    user_id = msg['id']
                    username = msg['name']
                    password = msg['message']
                    if authenticate_client(user_id, password):
                        await websocket.send(json_create(1, 0, 'server', 'LOGIN_SUCCESS', now()))
                        await broadcast(0, username, f"用户{username}已上线", 1)
                        logging.info(f"客户端已登录：{user_id}")

                        connected_clients[user_id] = websocket
                        client_heartbeats[user_id] = datetime.now()

                    else:
                        await websocket.send(json_create(1, 0, 'server', 'LOGIN_FAIL', now()))
                        await websocket.close()
                        return

                elif flag == 2:  # 注册
                    username = msg['name']
                    password = msg['message']
                    user_id = register_client(username, password)
                    if user_id is not None:
                        await websocket.send(json_create(2, user_id, username, 'REGISTERED', now()))
                        logging.info(f'register user with id:{user_id}')
                    else:
                        await websocket.send(json_create(2, user_id, username, 'REGISTERED_FAIL', now()))
                        logging.info(f"注册请求失败")


                elif flag == 5 and user_id is not None:  # 同步离线消息
                    await refresh_msg(user_id, msg['message'], websocket)

                elif flag == 0 and user_id is not None:  # 普通消息
                    sender_username = msg['name']
                    store_message(msg)
                    await broadcast(user_id, sender_username, msg['message'])

                # 处理图片消息
                elif flag == 8 and user_id is not None:  # 图片消息
                    image_path = pic_msg(msg, user_id)
                    msg['message'] = image_path
                    sender_username = msg['name']
                    # 将图片路径存入数据库
                    store_message(msg)
                    # 广播图片消息给所有客户端
                    await broadcast(user_id, sender_username, f"{msg['message']}", 8)



                else:
                    logging.warning(f"未知 flag：{flag}")

        except websockets.ConnectionClosed as e:
            logging.info(f"客户端连接已关闭 (用户ID：{user_id})：{e}")
    finally:
        if user_id is not None:
            connected_clients.pop(user_id, None)
            client_heartbeats.pop(user_id, None)
            logging.info(f"已将客户端从连接列表中移除 (用户ID：{user_id})")

async def broadcast(sender_user_id, sender_username, message, flag=0):
    """广播消息给所有已连接的客户端"""
    for user_id, client in connected_clients.items():
        if flag == 0:
            msg = json_create(flag, sender_user_id, sender_username, message, now())
            await client.send(msg)
            logging.info(f"向客户端 {user_id} 广播消息：{msg}")
        elif flag == 1:
            msg = json_create(0, 0, 0, message, now())
            await client.send(msg)
        elif flag == 8:
            msg = json_create(flag, sender_user_id, sender_username, message, now())
            await client.send(msg)
            logging.info(f"向客户端 {user_id} 广播图片消息")

#应当放在连接建立处，与客户端进行通讯拿到时间后查询再返回
async def refresh_msg(user_id, last_time, websocket):
    """"给客户端同步消息"""
    last_time = datetime.fromisoformat(last_time)

    logging.info(f"开始向客户端 {user_id} 同步离线消息，自 {last_time}")
    result = sql.fetch("""
        SELECT sender_id, sender_username, message, timestamp, type 
        FROM messages 
        WHERE timestamp >= ? 
        ORDER BY timestamp
    """, (last_time,))

    for row in result:
        sender_id = row['sender_id']
        sender_name = row['sender_username']
        message = row['message']
        timestamp = row['timestamp']
        flag = row['type']
        msg = json_create(flag, sender_id, sender_name, message, timestamp)
        await websocket.send(msg)

    await websocket.send(json_create(7, 0, "server", "sync_complete", now()))


# 主函数
async def main():
    # 配置 SSL 上下文
    ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ssl_context.load_cert_chain(cert_path, key_path)

    # 启动心跳检查任务
    asyncio.create_task(check_client_heartbeats())
    asyncio.create_task(send_heartbeats())

    # 启动 WebSocket 服务器
    async with websockets.serve(handler, "localhost", 9998, ssl=ssl_context, max_size=MAX_MESSAGE_SIZE):
        logging.info("WebSocket 服务器已启动，监听端口 9998")
        await asyncio.Future()  # 运行直到被取消

if __name__ == "__main__":
    asyncio.run(main())