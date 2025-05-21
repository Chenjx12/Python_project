#!/usr/bin/python3
import asyncio
import websockets
import logging
import sqlite3
import time
import uuid

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# 已连接的客户端集合
connected_clients = {}

# 客户端心跳信息
client_heartbeats = {}

# SQLite数据库设置
conn = sqlite3.connect('clients.db')
cursor = conn.cursor()
cursor.execute('''
CREATE TABLE IF NOT EXISTS clients (
    user_id TEXT PRIMARY KEY,
    username TEXT NOT NULL,
    password TEXT NOT NULL
)
''')
cursor.execute('''
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sender_id TEXT,
    sender_username TEXT,
    message TEXT,
    timestamp TEXT,
    FOREIGN KEY(sender_id) REFERENCES clients(user_id)
)
''')
conn.commit()

# 检查客户端心跳状态
async def check_client_heartbeats():
    while True:
        current_time = time.time()
        for user_id, last_heartbeat in list(client_heartbeats.items()):
            if current_time - last_heartbeat > 60:  # 超过60秒未收到心跳包
                logging.info(f"客户端 {user_id} 超过60秒未发送心跳包，标记为离线。")
                # 从已连接的客户端集合中移除该客户端
                connected_clients.pop(user_id, None)
                # 从心跳检查列表中移除
                client_heartbeats.pop(user_id, None)
        await asyncio.sleep(10)  # 每10秒检查一次

# 验证客户端的用户ID和密码
def authenticate_client(user_id, password):
    cursor.execute("SELECT user_id FROM clients WHERE user_id = ? AND password = ?", (user_id, password))
    return cursor.fetchone() is not None

# 注册新客户端
def register_client(username, password):
    user_id = str(uuid.uuid4())  # 生成唯一ID
    cursor.execute("INSERT INTO clients (user_id, username, password) VALUES (?, ?, ?)", (user_id, username, password))
    conn.commit()
    return user_id

# 获取用户的离线消息
def get_offline_messages(user_id):
    cursor.execute("SELECT sender_id, sender_username, message FROM messages WHERE sender_id != ? ORDER BY timestamp", (user_id,))
    messages = cursor.fetchall()
    return [f"{sender_id}:{sender_username}:{msg}" for sender_id, sender_username, msg in messages]

# 存储消息记录
def store_message(sender_id, sender_username, message):
    timestamp = time.strftime('%Y-%m-%d %H:%M:%S')
    cursor.execute("INSERT INTO messages (sender_id, sender_username, message, timestamp) VALUES (?, ?, ?, ?)", (sender_id, sender_username, message, timestamp))
    conn.commit()

# 定期向客户端发送心跳包
async def send_heartbeats():
    while True:
        for user_id, client in connected_clients.items():
            try:
                # 向客户端发送心跳包
                await client.send('heartbeat')
                logging.info(f"向客户端 {user_id} 发送心跳包")
            except websockets.ConnectionClosed:
                logging.info(f"客户端 {user_id} 连接已关闭，移除客户端")
                connected_clients.pop(user_id, None)
                client_heartbeats.pop(user_id, None)
        await asyncio.sleep(30)  # 每30秒发送一次心跳包

# WebSocket连接处理函数
async def handler(websocket):
    # 验证客户端
    auth_message = await websocket.recv()
    user_id, password = auth_message.split(":")
    if authenticate_client(user_id, password):
        logging.info(f"客户端已登录：{user_id}")
    else:
        logging.info(f"用户ID或密码错误：{user_id}")
        await websocket.send("LOGIN_FAIL")
        await websocket.close()
        return

    # 存储客户端的用户ID
    connected_clients[user_id] = websocket

    # 初始化心跳时间
    client_heartbeats[user_id] = time.time()

    # 获取并发送离线消息
    offline_msgs = get_offline_messages(user_id)
    for message in offline_msgs:
        await websocket.send(message)
        logging.info(f"向客户端 {user_id} 发送离线消息：{message}")

    try:
        # 持续监听客户端发送的消息
        async for message in websocket:
            # 如果收到心跳包
            if message == 'heartbeat':
                logging.info(f"从客户端 {user_id} 收到心跳包")
                # 更新心跳时间
                client_heartbeats[user_id] = time.time()
                continue  # 不处理心跳包，直接跳过

            # 记录收到的消息
            logging.info(f"从客户端 {user_id} 收到消息：{message}")
            # 将消息存储到数据库
            cursor.execute("SELECT username FROM clients WHERE user_id = ?", (user_id,))
            sender_username = cursor.fetchone()[0]
            store_message(user_id, sender_username, message)
            # 将消息广播给所有已连接的客户端
            await broadcast(user_id, sender_username, message)
    except websockets.ConnectionClosed as e:
        # 记录连接关闭事件
        logging.info(f"客户端连接已关闭 (用户ID：{user_id})：{e}")
    finally:
        # 从已连接的客户端集合中移除该客户端
        connected_clients.pop(user_id, None)
        # 从心跳检查列表中移除
        client_heartbeats.pop(user_id, None)
        logging.info(f"已将客户端从连接列表中移除 (用户ID：{user_id})")

# 广播消息给所有已连接的客户端
async def broadcast(sender_user_id, sender_username, message):
    # 将消息广播给所有已连接的客户端
    for user_id, client in connected_clients.items():
        await client.send(f"{sender_user_id}:{sender_username}:{message}")
        logging.info(f"向客户端 {user_id} 广播消息：{sender_user_id}:{sender_username}:{message}")

# 主函数
async def main():
    # 启动心跳检测任务
    asyncio.create_task(check_client_heartbeats())
    # 启动心跳发送任务
    asyncio.create_task(send_heartbeats())

    async with websockets.serve(handler, "localhost", 9998):
        await asyncio.Future()  # 持续运行

if __name__ == "__main__":
    asyncio.run(main())