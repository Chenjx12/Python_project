import asyncio
import websockets
import json
import os

CONFIG_FILE = 'client.config'

user_id = ''

async def ws_client(url):
    async with websockets.connect(url) as websocket:
        # 检查是否存在配置文件
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, 'r') as f:
                config = json.load(f)
            user_id = config['user_id']
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
            print(f'Your user id is:{user_id}')

        # Authenticate with the server
        await websocket.send(f"{user_id}:{password}")
        response = await websocket.recv()
        if response == "LOGIN_SUCCESS":
            print("Login successful.")
        elif response == "REGISTERED":
            print("Registration successful. Saving user ID and password for future logins.")
            with open(CONFIG_FILE, 'w') as f:
                json.dump({'user_id': user_id, 'username': username, 'password': password}, f)
        else:
            print("Invalid user ID or password.")
            return

        # 创建一个队列用于存储接收到的消息
        message_queue = asyncio.Queue()

        # 启动一个任务用于接收消息
        asyncio.create_task(receive_messages(websocket, message_queue))

        print("Connected to server. You can start typing messages.")

        # 启动一个任务用于处理用户输入
        asyncio.create_task(handle_user_input(websocket))
        # 启动一个任务用于发送心跳包
        asyncio.create_task(heart_beat(websocket))

        # 等待队列中的消息并打印
        while True:
            message = await message_queue.get()
            print(message)

async def receive_messages(websocket, message_queue):
    try:
        async for message in websocket:
            # 如果是心跳包或心跳响应，则忽略
            if message in ['heartbeat', 'heartbeat_ack']:
                continue
            # 消息格式为 "sender_user_id:sender_username:message"
            sender_user_id, sender_username, msg = message.split(":", 2)
            if sender_user_id == user_id:
                await message_queue.put(f"You: {msg}")
            else:
                await message_queue.put(f"{sender_username}: {msg}")
    except websockets.ConnectionClosed:
        print("Connection closed. Exiting...")
        asyncio.get_event_loop().stop()

async def handle_user_input(websocket):
    while True:
        # Get user input in a separate thread to avoid blocking the event loop
        message = await asyncio.get_event_loop().run_in_executor(None, input)
        # Send the message to the server
        await websocket.send(message)

async def heart_beat(websocket):
    while True:
        # 发送心跳包
        await asyncio.sleep(30)
        await websocket.send('heartbeat')

if __name__ == "__main__":
    url = 'ws://localhost:9998'
    asyncio.run(ws_client(url))