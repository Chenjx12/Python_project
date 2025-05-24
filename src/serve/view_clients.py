import sqlite3

# 连接到 SQLite 数据库
conn = sqlite3.connect('clients.db')
cursor = conn.cursor()

# 查询 clients 表中的所有数据
cursor.execute("SELECT * FROM clients")
rows = cursor.fetchall()

# 打印表头
print("clients 表中的数据：")
print(f"{'user_id':<10} {'username':<20} {'password':<20}")
print("-" * 50)

# 打印每一行数据
for row in rows:
    user_id, username, password = row
    print(f"{user_id:<10} {username:<20} {password:<20}")

# 关闭数据库连接
conn.close()