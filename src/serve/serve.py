#!/usr/bin/python3
import asyncio
import json
import websockets
import logging
import sqlite3
import time
from datetime import datetime
import os
import hashlib
import ssl
from sqlmg import SqlMG
from src.client.client1 import user_id

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

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
    #flag字段值对应：
    #0：正常消息；1：登录消息；2：注册；3：服务端心跳；4：客户端心跳
    msg = {
        "flag": flag,
        "id": id,
        "name": name,
        "message": message,
        "timestamp": times
    }
    return json.dumps(msg)


# 检查客户端心跳状态
async def check_client_heartbeats():
    while True:
        current_time = datetime.now()
        for user_id, last_heartbeat in list(client_heartbeats.items()):
            if int(current_time - last_heartbeat) > 60:  # 超过60秒未收到心跳包
                logging.info(f"客户端 {user_id} 超过60秒未发送心跳包，标记为离线。")
                connected_clients.pop(user_id, None)
                client_heartbeats.pop(user_id, None)
        await asyncio.sleep(10)  # 每10秒检查一次

# 验证客户端的用户ID和密码
def authenticate_client(user_id, password) -> bool:
    result = sql.fetch("SELECT password_hash, salt FROM clients WHERE user_id = ?", (user_id,))
    if result:
        password_hash, salt = result[0]['password_hash'], result[0]['salt']
        input_hash = hashlib.sha256((password + salt).encode()).hexdigest()
        return input_hash == password_hash
    return False


# 注册新客户端
def register_client(username, password) -> int | None:
    try:
        salt = os.urandom(16).hex()
        password_hash = hashlib.sha256((password + salt).encode()).hexdigest()
        sql.exec('INSERT INTO clients (username, password_hash, salt) VALUES (?, ?, ?)', (username, password_hash, salt))
        result = sql.fetch('SELECT user_id FROM clients WHERE username = ?', (username,))
        return result[0]['user_id'] if result else None
    except Exception as e:
        logging.error(f"Error: {e}")
        return None


# 获取用户的离线消息
# def get_offline_messages(user_id):
#     cursor.execute("SELECT sender_id, sender_username, message FROM messages WHERE sender_id != ? ORDER BY timestamp", (user_id,))
#     messages = cursor.fetchall()
#     return [f"{sender_id}:{sender_username}:{msg}" for sender_id, sender_username, msg in messages]

def now():
    return datetime.now().replace(microsecond=0).isoformat()

# 存储消息记录
def store_message(sender_id, sender_username, message):
    sql.exec("INSERT INTO messages (sender_id, sender_username, message, timestamp) VALUES (?, ?, ?, datetime('now','localtime'))",
             (sender_id, sender_username, message))


# 定期向客户端发送心跳包
async def send_heartbeats():
    while True:
        for user_id, client in connected_clients.items():
            try:

                await client.send(json_create(0,0,0,"heartbeat",0))
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

                if flag == 4 and user_id is not None:  # 客户端心跳
                    client_heartbeats[user_id] = datetime.now()
                    logging.info(f"收到心跳：{user_id}")
                    continue

                elif flag == 1:  # 登录
                    user_id = int(msg['id'])
                    username = msg['name']
                    password = msg['message']
                    if authenticate_client(user_id, password):
                        await websocket.send(json_create(1, 0, 'server', 'LOGIN_SUCCESS', now()))
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
                    store_message(user_id, sender_username, msg['message'])
                    await broadcast(user_id, sender_username, msg['message'])

                else:
                    logging.warning(f"未知 flag：{flag}")

        except websockets.ConnectionClosed as e:
            logging.info(f"客户端连接已关闭 (用户ID：{user_id})：{e}")
    finally:
        if user_id is not None:
            connected_clients.pop(user_id, None)
            client_heartbeats.pop(user_id, None)
            logging.info(f"已将客户端从连接列表中移除 (用户ID：{user_id})")

# 广播消息给所有已连接的客户端
async def broadcast(sender_user_id, sender_username, message):
    for user_id, client in connected_clients.items():
        msg = json_create(0, sender_user_id, sender_username, message, datetime.now().replace(microsecond=0).isoformat())
        await client.send(msg)
        logging.info(f"向客户端 {user_id} 广播消息：{msg}")

#应当放在连接建立处，与客户端进行通讯拿到时间后查询再返回
async def refresh_msg(user_id, last_time, websocket):
    # with open(CONFIG_FILE, 'r') as f:
    #     time_data = json.load(f)
    # last_time = time_data.get('time', '-1')
    last_time = datetime.fromisoformat(last_time)

    logging.info(f"开始向客户端 {user_id} 同步离线消息，自 {last_time}")
    result = sql.fetch("""
        SELECT sender_id, sender_username, message, timestamp 
        FROM messages 
        WHERE timestamp >= ? 
        ORDER BY timestamp
    """, (last_time,))

    for row in result:
        sender_id = row['sender_id']
        sender_name = row['sender_username']
        message = row['message']
        timestamp = row['timestamp']
        msg = json_create(6, sender_id, sender_name, message, timestamp)
        await websocket.send(msg)

    await websocket.send(json_create(7, 0, "server", "sync_complete", now()))


# 主函数
async def main():
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

if __name__ == "__main__":
    asyncio.run(main())