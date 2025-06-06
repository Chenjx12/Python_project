import asyncio
import websockets
import json
import sqlite3
import logging
from datetime import datetime
import os
import ssl


logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
CONFIG_FILE = 'client.config'

current_dir = os.getcwd()
cert_path = os.path.join(current_dir, 'source', 'cert.pem')

user_id = ''

# conn = sqlite3.connect('basedata.db', detect_types=sqlite3.PARSE_DECLTYPES)
conn = sqlite3.connect('basedata.db')
cursor = conn.cursor()

cursor.execute('''
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sender_id INTEGER,
    sender_username TEXT,
    message TEXT,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
)
''')
#图片存储数据表，用于后续对接消息内部图片id（由于整体兼容性问题，message的结构可能需要加上首部检测来尽可能不更改当前的数据表结构），
cursor.execute('''
CREATE TABLE IF NOT EXISTS pictures (
    pic_id INTEGER PRIMARY KEY AUTOINCREMENT,
    address TEXT
)
''')

cursor.execute('''
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_name TEXT
)
''')


#用于同步离线信息
async def refresh_message(websocket):
    pass
    with open(CONFIG_FILE, 'r') as f:
        time = json.load(f)['time']
    if time == -1 :
        return
    await websocket.send(time)
    async for msg in websocket:
        rcv = json.loads(msg)
        # cursor.execute("select user_name from users where user_id = ?", rcv[0])
        # res = cursor.fetchall()
        cursor.execute("insert into messages(sender_id, sender_username, message, timestamp) values(?,?,?,?)", (rcv['id'], rcv['name'], rcv['message'], rcv['timestamp']))
    cursor.execute("")

    pass

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
            await websocket.send('Login')
            print("Using saved user ID and password for login.")
        else:
            await websocket.send('Sign')
            print('First login with sign.')
            username = input("Enter your username: ")
            password = input("Enter your password: ")
            await websocket.send(f"sign_msg:{username}:{password}")
            user_id = await websocket.recv()
            user_id = int(user_id)
            print(f'Your user id is:{user_id}')

        # Authenticate with the server
        await websocket.send(f"login_msg:{user_id}:{username}:{password}")
        response = await websocket.recv()
        if response == "LOGIN_SUCCESS":
            print("Login successful.")
        elif response == "REGISTERED":
            print("Registration successful. Saving user ID and password for future logins.")
            with open(CONFIG_FILE, 'w') as f:
                json.dump({'user_id': user_id, 'username': username, 'password': password, 'time':-1}, f)
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
    try:
        async for message in websocket:

            # 消息格式为 "sender_user_id:sender_username:message:time"
            msg = json.loads(message)
            logging.info(f'收到信息：{msg}')
            # print(type(user_id),type(msg['id']))
            # 如果是心跳包或心跳响应，则忽略
            if msg['message'] in ['heartbeat', 'heartbeat_ack']:
                continue
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
    while True:
        # Get user input in a separate thread to avoid blocking the event loop
        message = await asyncio.get_event_loop().run_in_executor(None, input, '')#这里到时候该如何对接图形化呢？
        # Send the message to the server
        await websocket.send(message)

async def heart_beat(websocket):
    while True:
        # 发送心跳包
        await asyncio.sleep(30)
        await websocket.send('heartbeat')

if __name__ == "__main__":
    # 使用 wss:// 协议连接到服务器
    url = 'wss://localhost:9998'
    asyncio.run(ws_client(url))