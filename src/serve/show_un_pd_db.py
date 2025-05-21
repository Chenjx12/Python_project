import sqlite3

# 连接到数据库
conn = sqlite3.connect('clients.db')
cursor = conn.cursor()

# 查询表中的数据
cursor.execute("SELECT * FROM clients")
rows = cursor.fetchall()

# 打印查询结果
for row in rows:
    print(row)

# 关闭连接
conn.close()