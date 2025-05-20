#!/usr/bin/python3
# 主要功能：创建一个基本的websocket server，符合asyncio开发要求
import asyncio
import websockets
import logging
import sqlite3

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# 已连接的客户端集合
connected_clients = {}

# 用于存储每个客户端的离线消息的字典
offline_messages = {}

# SQLite数据库设置
conn = sqlite3.connect('clients.db')
cursor = conn.cursor()
cursor.execute('''
CREATE TABLE IF NOT EXISTS clients (
    username TEXT PRIMARY KEY,
    password TEXT NOT NULL
)
''')
conn.commit()

# 验证客户端的用户名和密码
def authenticate_client(username, password):
    cursor.execute("SELECT username FROM clients WHERE username = ? AND password = ?", (username, password))
    return cursor.fetchone() is not None

# 注册新客户端
def register_client(username, password):
    cursor.execute("INSERT INTO clients (username, password) VALUES (?, ?)", (username, password))
    conn.commit()

# WebSocket连接处理函数
async def handler(websocket):
    # 验证客户端
    auth_message = await websocket.recv()
    username, password = auth_message.split(":")
    if authenticate_client(username, password):
        logging.info(f"客户端已登录：{username}")
    else:
        logging.info(f"新客户端已注册：{username}")
        register_client(username, password)

    # 存储客户端的用户名
    connected_clients[username] = websocket

    # 将任何离线消息发送给客户端
    if username in offline_messages:
        messages = offline_messages.pop(username, [])
        for message in messages:
            await websocket.send(message)
            logging.info(f"向客户端 {username} 发送离线消息：{message}")

    try:
        # 持续监听客户端发送的消息
        async for message in websocket:
            # 记录收到的消息
            logging.info(f"从客户端 {username} 收到消息：{message}")
            # 将消息广播给所有已连接的客户端
            await broadcast(username, message)
    except websockets.ConnectionClosed as e:
        # 记录连接关闭事件
        logging.info(f"客户端连接已关闭 (用户名：{username})：{e}")
    finally:
        # 从已连接的客户端集合中移除该客户端
        connected_clients.pop(username, None)
        logging.info(f"已将客户端从连接列表中移除 (用户名：{username})")

# 广播消息给所有已连接的客户端
async def broadcast(sender_username, message):
    # 将消息广播给所有已连接的客户端
    for username, client in connected_clients.items():
        await client.send(f"{sender_username}: {message}")
        logging.info(f"向客户端 {username} 广播消息：{sender_username}: {message}")

    # 为离线客户端存储消息
    for username in connected_clients.keys():
        if username not in offline_messages:
            offline_messages[username] = []
        offline_messages[username].append(f"{sender_username}: {message}")

# 主函数
async def main():
    async with websockets.serve(handler, "localhost", 9998):
        await asyncio.Future()  # 持续运行

if __name__ == "__main__":
    asyncio.run(main())