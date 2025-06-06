import asyncio
import websockets
import json
import sqlite3
import logging
from datetime import datetime
import os
import ssl
from sqlmg import SqlMG

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
CONFIG_FILE = 'client.config'

current_dir = os.getcwd()
cert_path = os.path.join(current_dir, 'source', 'cert.pem')

user_id = ''

# conn = sqlite3.connect('basedata.db', detect_types=sqlite3.PARSE_DECLTYPES)
sql = SqlMG('basedata.db')
sql.client_sql()

def json_create(flag, id, name, message, times):
    #flag字段值对应：
    #0：正常消息；1：登录消息；2：注册；3：服务端心跳；4：客户端心跳
    msg = {
        'flag': flag,
        'id': id,
        'name': name,
        'message': message,
        'timestamp': times
    }
    return json.dumps(msg)

def now():
    return datetime.now().replace(microsecond=0).isoformat()

#用于同步离线信息
async def refresh_message(websocket):
    with open(CONFIG_FILE, 'r') as f:
        time = json.load(f)['time']
    if time == -1 :
        return
    await websocket.send(time)
    async for msg in websocket:
        rcv = json.loads(msg)
        # cursor.execute("select user_name from users where user_id = ?", rcv[0])
        # res = cursor.fetchall()
        sql.exec("insert into messages(sender_id, sender_username, message, timestamp) values(?,?,?,?)", (rcv['id'], rcv['name'], rcv['message'], rcv['timestamp']))

def update_time(timestamp):
    with open(CONFIG_FILE, 'r') as f:
        data = json.load(f)
    data['time'] = timestamp

    with open(CONFIG_FILE, 'w') as f:
        json.dump(data, f)

async def ws_client(url):
    global user_id
    # 创建 SSL 上下文
    ssl_context = ssl.create_default_context()
    ssl_context.load_verify_locations(cert_path)  # 加载服务器证书
    ssl_context.verify_mode = ssl.CERT_REQUIRED  # 要求验证服务器证书

    async with websockets.connect(url, ssl=ssl_context) as websocket:
        # 检查是否存在配置文件
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, 'r') as f:
                config = json.load(f)
            user_id = config['user_id']
            username = config['username']
            password = config['password']
            await websocket.send(json_create(1, user_id, username, password, now()))
            print("Using saved user ID and password for login.")
        else:
            print('First login with sign.')
            username = input("Enter your username: ")
            password = input("Enter your password: ")
            await websocket.send(json_create(2, 0, username, password, now()))
            rcv = await websocket.recv()
            rcv = json.loads(rcv)
            if rcv['message'] != 'REGISTERED':
                return

            user_id = rcv['id']
            print(f'Your user id is:{user_id}')
            with open(CONFIG_FILE, 'w') as f:
                json.dump({'user_id': user_id, 'username': username, 'password': password, 'time': -1}, f)
            await websocket.send(json_create(1, user_id, username, password, now()))


        # Authenticate with the server

        response = await websocket.recv()
        response = json.loads(response)['message']
        if response == "LOGIN_SUCCESS":
            print("Login successful.")
        else:
            print("Invalid user ID or password.")
            return

        # 创建一个队列用于存储接收到的消息
        message_queue = asyncio.Queue()

        # 启动一个任务用于接收消息
        asyncio.create_task(receive_messages(websocket, message_queue))

        print("Connected to server. You can start typing messages.")
        # await refresh_message(websocket)
        # 启动一个任务用于处理用户输入
        asyncio.create_task(handle_user_input(websocket))
        # 启动一个任务用于发送心跳包
        asyncio.create_task(heart_beat(websocket))

        # 等待队列中的消息并打印
        while True:
            message = await message_queue.get()
            update_time(datetime.now().replace(microsecond=0).isoformat())
            print(message)

async def receive_messages(websocket, message_queue):
    print(user_id)
    try:
        async for message in websocket:
            # 消息格式为 "sender_user_id:sender_username:message:time"
            msg = json.loads(message)
            logging.info(f'收到信息：{msg}')
            # print(type(user_id),type(msg['id']))
            # 如果是心跳包或心跳响应，则忽略
            if msg['message'] in ['heartbeat', 'heartbeat_ack']:
                continue
            if msg['flag'] == 6:
                # 离线消息
                sql.exec("INSERT INTO messages (sender_id, sender_username, message, timestamp) VALUES (?,?,?,?)",
                               (msg['id'], msg['name'], msg['message'], msg['timestamp']))
                await message_queue.put(f"[离线] {msg['name']}: {msg['message']}")
            elif msg['flag'] == 7:
                update_time(msg['timestamp'])
                print("[系统] 离线消息同步完成。")
            if msg['id'] == user_id:
                await message_queue.put(f"You: {msg['message']}")
            elif msg['id'] == '0':
                await message_queue.put(f"server: {msg['message']}")
            else:
                await message_queue.put(f"{msg['name']}: {msg['message']}")
    except websockets.ConnectionClosed:
        print("Connection closed. Exiting...")
        asyncio.get_event_loop().stop()

async def handle_user_input(websocket):
    global user_id
    with open(CONFIG_FILE, 'r') as f:
        config = json.load(f)
    username = config['username']

    while True:
        message = await asyncio.get_event_loop().run_in_executor(None, input, '')
        msg = json_create(0, user_id, username, message, datetime.now().replace(microsecond=0).isoformat())
        await websocket.send(msg)


async def heart_beat(websocket):
    while True:
        await asyncio.sleep(30)
        msg = json_create(4, user_id, "heartbeat", "heartbeat", now())
        await websocket.send(msg)


if __name__ == "__main__":
    # 使用 wss:// 协议连接到服务器
    url = 'wss://localhost:9998'
    asyncio.run(ws_client(url))