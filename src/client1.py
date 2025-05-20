import asyncio
import websockets

async def main():
    async with websockets.connect("ws://localhost:8765") as websocket:
        try:
            print("Connected to the server. You can start sending messages.")
            while True:
                # 获取用户输入的消息
                message = input("Enter a message (or type 'exit' to quit): ")
                if message.lower() == 'exit':
                    print("Exiting the chat.")
                    break

                # 发送消息到服务器
                await websocket.send(message)
                print("Message sent to server.")

                # 接收服务器的响应
                response = await websocket.recv()
                print("Received from server:", response)
        except websockets.exceptions.ConnectionClosedError as e:
            print(f"Connection closed: {e}")
        except Exception as e:
            print(f"An error occurred: {e}")

if __name__ == "__main__":
    asyncio.run(main())