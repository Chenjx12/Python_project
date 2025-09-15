import asyncio
import websockets


async def ws_client(url, username, password):
    async with websockets.connect(url) as websocket:
        # Authenticate with the server
        await websocket.send(f"{username}:{password}")
        # 创建一个队列用于存储接收到的消息
        message_queue = asyncio.Queue()

        # 启动一个任务用于接收消息
        asyncio.create_task(receive_messages(websocket, message_queue))

        print("Connected to server. You can start typing messages.")

        # 启动一个任务用于处理用户输入
        asyncio.create_task(handle_user_input(websocket))

        # 等待队列中的消息并打印
        while True:
            message = await message_queue.get()
            print(message)


async def receive_messages(websocket, message_queue):
    try:
        async for message in websocket:
            if message.startswith("session_id:"):
                # Store the session ID for future use
                session_id = message.split(":")[1]
                print(f"Received session ID: {session_id}")
                continue  # Ignore session ID messages
             # 消息格式为 "sender_username: message"
            sender, msg = message.split(": ", 1)
            if sender == username:
                print(f"You: {msg}")
            else:
                await message_queue.put(f"{sender}: {msg}")
    except websockets.ConnectionClosed:
        print("Connection closed. Exiting...")
        asyncio.get_event_loop().stop()


async def handle_user_input(websocket):
    while True:
        # Get user input in a separate thread to avoid blocking the event loop
        message = await asyncio.get_event_loop().run_in_executor(None, input)
        # Send the message to the server
        await websocket.send(message)


if __name__ == "__main__":
    url = 'ws://localhost:9998'
    username = input("Enter your username: ")
    password = input("Enter your password: ")
    asyncio.run(ws_client(url, username, password))
