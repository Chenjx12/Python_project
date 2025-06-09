import sqlite3

# 连接到 SQLite 数据库
conn = sqlite3.connect('clients.db')
cursor = conn.cursor()

# 查询 messages 表中的所有数据
cursor.execute("SELECT * FROM messages")
rows = cursor.fetchall()

# 打印表头
print("messages 表中的数据：")
print(f"{'id':<5} {'sender_id':<10} {'sender_username':<20} {'message':<30} {'timestamp':<20}")
print("-" * 80)

# 打印每一行数据
for row in rows:
    msg_id, sender_id, sender_username, message, timestamp = row
    print(f"{msg_id:<5} {sender_id:<10} {sender_username:<20} {message:<30} {timestamp:<20}")

# 关闭数据库连接
conn.close()