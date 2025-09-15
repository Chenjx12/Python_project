import sqlite3
from datetime import datetime

# 连接到 SQLite 数据库
conn = sqlite3.connect('clients.db')
cursor = conn.cursor()

# 查询 messages 表中的所有数据
# 修复1: 使用过去的时间戳或者移除时间过滤
# 修复2: 正确的变量解包
result = cursor.execute("""
        SELECT sender_id, sender_username, message, timestamp, type 
        FROM messages 
        ORDER BY timestamp
    """)
rows = cursor.fetchall()

# 打印表头
print("messages 表中的数据：")
print(f"{'sender_id':<10} {'sender_username':<20} {'message':<30} {'timestamp':<20} {'type':<10}")
print("-" * 90)

# 打印每一行数据
for row in rows:
    sender_id, sender_username, message, timestamp, type_ = row
    # 修复3: 修正格式化字符串
    print(f"{sender_id:<10} {sender_username:<20} {message:<30} {timestamp:<20} {type_:<10}")

# 关闭数据库连接
cursor.close()
conn.close()