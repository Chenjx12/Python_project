#!/usr/bin/python3
import asyncio
import websockets
import logging
import os
import hashlib
import ssl
import time

import sqlite3
from sqlmg import SqlMG  # 导入 SqlMG 类

# 创建一个日志记录器
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)  # 设置最低日志级别为 DEBUG

# 创建终端处理器
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.DEBUG)  # 终端输出 DEBUG 级别及以上
console_formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
console_handler.setFormatter(console_formatter)

# 创建文件处理器
file_handler = logging.FileHandler('app.log')  # 日志文件名
file_handler.setLevel(logging.INFO)  # 文件记录 INFO 级别及以上
file_formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
file_handler.setFormatter(file_formatter)

# 将处理器添加到日志记录器
logger.addHandler(console_handler)
logger.addHandler(file_handler)

# SSL证书
current_dir = os.path.dirname(os.path.abspath(__file__))
cert_path = os.path.join(current_dir, 'serve_source', 'cert.pem')
key_path = os.path.join(current_dir, 'serve_source', 'key.pem')

# 已连接的客户端集合
connected_clients = {}

# 客户端心跳信息
client_heartbeats = {}

# 初始化 SqlMG 类
db_manager = SqlMG('clients.db')
db_manager.sever_sql()  # 初始化服务器端的数据库表

# 检查客户端心跳状态
async def check_client_heartbeats():
    while True:
        current_time = time.time()
        for user_id, last_heartbeat in list(client_heartbeats.items()):
            if current_time - last_heartbeat > 60:  # 超过60秒未收到心跳包
                logger.info(f"客户端 {user_id} 超过60秒未发送心跳包，标记为离线。")
                connected_clients.pop(user_id, None)
                client_heartbeats.pop(user_id, None)
        await asyncio.sleep(10)  # 每10秒检查一次

# 验证客户端的用户ID和密码
def authenticate_client(user_id, password) -> bool:
    result = db_manager.fetch("SELECT password_hash, salt FROM clients WHERE user_id = ?", (user_id,))
    if result:
        password_hash, salt = result[0]
        input_hash = hashlib.sha256((password + salt).encode()).hexdigest()
        return input_hash == password_hash
    return False

# 注册新客户端
def register_client(username, password) -> int:
    try:
        salt = os.urandom(16).hex()
        password_hash = hashlib.sha256((password + salt).encode()).hexdigest()
        db_manager.exec('INSERT INTO clients (username, password_hash, salt) VALUES (?, ?, ?)', (username, password_hash, salt))
        user_id = db_manager.fetch("SELECT last_insert_rowid()")[0][0]
    except sqlite3.IntegrityError as e:
        logger.error(f"Error: {e}")
        user_id = None
    return user_id

# 获取用户的离线消息
def get_offline_messages(user_id):
    messages = db_manager.fetch("SELECT sender_id, sender_username, message FROM messages WHERE sender_id != ? ORDER BY timestamp", (user_id,))
    return [f"{sender_id}:{sender_username}:{msg}" for sender_id, sender_username, msg in messages]

# 存储消息记录
def store_message(sender_id, sender_username, message):
    timestamp = time.strftime('%Y-%m-%d %H:%M:%S')
    db_manager.exec("INSERT INTO messages (sender_id, sender_username, message, timestamp) VALUES (?, ?, ?, ?)", (sender_id, sender_username, message, timestamp))

# 定期向客户端发送心跳包
async def send_heartbeats():
    while True:
        for user_id, client in connected_clients.items():
            try:
                await client.send('heartbeat')
                logger.info(f"向客户端 {user_id} 发送心跳包")
            except websockets.ConnectionClosed:
                logger.info(f"客户端 {user_id} 连接已关闭，移除客户端")
                connected_clients.pop(user_id, None)
                client_heartbeats.pop(user_id, None)
        await asyncio.sleep(30)  # 每30秒发送一次心跳包

# WebSocket连接处理函数
async def handler(websocket):
    user_id = None
    try:
        login_or_sign = await websocket.recv()
        if login_or_sign == 'Login':
            auth_message = await websocket.recv()
            lg_msg, user_id, username, password = auth_message.split(":")
            if authenticate_client(user_id, password):
                await websocket.send('LOGIN_SUCCESS')
                logger.info(f"客户端已登录：{user_id}")
            else:
                logger.info(f"用户ID或密码错误：{user_id}")
                await websocket.send("LOGIN_FAIL")
                await websocket.close()
                return
        elif login_or_sign == 'Sign':
            logger.info('new user sign up.')
            auth_message = await websocket.recv()
            sign_msg, user_name, password = auth_message.split(":")
            user_id = register_client(user_name, password)
            await websocket.send(f'{user_id}')
            await websocket.send('REGISTERED')
            logger.info(f'register user with id:{user_id}')

        if user_id is not None:
            connected_clients[user_id] = websocket
            client_heartbeats[user_id] = time.time()

            offline_msgs = get_offline_messages(user_id)
            for message in offline_msgs:
                await websocket.send(message)
                logger.info(f"向客户端 {user_id} 发送离线消息：{message}")

            try:
                async for message in websocket:
                    if message == 'heartbeat':
                        logger.info(f"从客户端 {user_id} 收到心跳包")
                        client_heartbeats[user_id] = time.time()
                        continue
                    elif message.startswith('sign_msg'):
                        pass
                    elif message.startswith('login_msg'):
                        user_login_name = message.split(':')[2]
                        await broadcast(0, user_login_name, f'用户{user_login_name}已上线')
                    else:
                        logger.info(f"从客户端 {user_id} 收到消息：{message}")
                        sender_username = db_manager.fetch("SELECT username FROM clients WHERE user_id = ?", (user_id,))[0][0]
                        store_message(user_id, sender_username, message)
                        await broadcast(user_id, sender_username, message)
            except websockets.ConnectionClosed as e:
                logger.info(f"客户端连接已关闭 (用户ID：{user_id})：{e}")
    finally:
        if user_id is not None:
            connected_clients.pop(user_id, None)
            client_heartbeats.pop(user_id, None)
            logger.info(f"已将客户端从连接列表中移除 (用户ID：{user_id})")

# 广播消息给所有已连接的客户端
async def broadcast(sender_user_id, sender_username, message):
    for user_id, client in connected_clients.items():
        await client.send(f"{sender_user_id}:{sender_username}:{message}")
        logger.info(f"向客户端 {user_id} 广播消息：{sender_user_id}:{sender_username}:{message}")

# 主函数
async def main():
    try:
        # 配置 SSL 上下文
        ssl_context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
        ssl_context.load_cert_chain(certfile=cert_path, keyfile=key_path)

        # 启动心跳检测任务
        asyncio.create_task(check_client_heartbeats())
        # 启动心跳发送任务
        asyncio.create_task(send_heartbeats())

        # 启动 WebSocket 服务并启用 SSL
        async with websockets.serve(handler, "localhost", 9998, ssl=ssl_context):
            await asyncio.Future()  # 持续运行
    except Exception as e:
        logger.error(f"程序异常退出: {e}")
    finally:
        # 确保数据库连接关闭
        db_manager.close()

if __name__ == "__main__":
    asyncio.run(main())