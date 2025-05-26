#!/usr/bin/python3
import asyncio
import websockets
import logging
import sqlite3
import time
import os
import hashlib

# from src.serve.view_clients import username

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
    user_id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL,
    password_hash TEXT NOT NULL,  -- 存储密码的哈希值
    salt TEXT NOT NULL            -- 存储盐值
)
''')
cursor.execute('''
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sender_id INTEGER,
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
def authenticate_client(user_id, password) -> bool:
    cursor.execute("SELECT password_hash, salt FROM clients WHERE user_id = ?", (user_id,))
    result = cursor.fetchone()
    if result:
        password_hash, salt = result
        # 将输入的密码与盐值拼接后进行哈希处理
        input_hash = hashlib.sha256((password + salt).encode()).hexdigest()
        # 比较哈希值
        return input_hash == password_hash
    return False

# 注册新客户端
def register_client(username, password) -> int:
    """创建新用户，并返回自增 ID"""
    try:
        # 生成随机盐值
        salt = os.urandom(16).hex()  # 生成16字节的随机盐值并转换为十六进制字符串
        # 将密码与盐值拼接后进行哈希处理
        password_hash = hashlib.sha256((password + salt).encode()).hexdigest()
        # 插入用户数据
        cursor.execute('INSERT INTO clients (username, password_hash, salt) VALUES (?, ?, ?)', (username, password_hash, salt))
        user_id = cursor.lastrowid  # 获取自增 ID
        conn.commit()
    except sqlite3.IntegrityError as e:
        logging.info(f"Error: {e}")
        user_id = None
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
    login_or_sign = await  websocket.recv()
    if login_or_sign == 'Login':
        auth_message = await websocket.recv()
        lg_msg, user_id, username, password = auth_message.split(":")
        if authenticate_client(user_id, password):
            await websocket.send('LOGIN_SUCCESS')
            logging.info(f"客户端已登录：{user_id}")
        else:
            logging.info(f"用户ID或密码错误：{user_id}")
            await websocket.send("LOGIN_FAIL")
            await websocket.close()
            return
    elif login_or_sign == 'Sign':
        logging.info('new user sign up.')
        auth_message = await websocket.recv()
        sign_msg,user_name, password = auth_message.split(":")
        user_id = register_client(user_name, password)
        await websocket.send(f'{user_id}')
        await websocket.send('REGISTERED')
        logging.info(f'register user with id:{user_id}')

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
            elif message.startswith('sign_msg'):
                # 用户注册信息不应该广播……
                pass
            elif message.startswith('login_msg'):
                # 用户登录信息
                user_login_name = message.split(':')[2]
                await broadcast(0, user_login_name, f'用户{user_login_name}已上线')
            else:
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