import asyncio
import websockets

connected_clients = set()

async def handle_client(websocket):
    connected_clients.add(websocket)
    try:
        async for message in websocket:
            print(f"Received message from client: {message}")
            # 广播消息给所有客户端
            for client in connected_clients.copy():  # 使用 copy 避免在迭代时修改集合
                if client.state == websockets.protocol.State.OPEN:  # 检查客户端是否仍然连接
                    await client.send(message)
                else:
                    connected_clients.remove(client)
    except Exception as e:
        print(f"Error handling client: {e}")
    finally:
        # 客户端断开连接时移除
        connected_clients.remove(websocket)
        print(f"Client disconnected: {websocket.remote_address}")

async def main():
    async with websockets.serve(handle_client, "localhost", 8765):
        print("Server started on ws://localhost:8765")
        await asyncio.Future()  # 运行直到被取消

if __name__ == "__main__":
    asyncio.run(main())