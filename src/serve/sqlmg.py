import logging
import sqlite3

# 创建一个日志记录器
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)  # 设置最低日志级别为 DEBUG

# 创建终端处理器
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.DEBUG)  # 终端输出 DEBUG 级别及以上
console_formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
console_handler.setFormatter(console_formatter)

# 创建文件处理器
file_handler = logging.FileHandler('app.log')  # 日志文件名
file_handler.setLevel(logging.INFO)  # 文件记录 INFO 级别及以上
file_formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
file_handler.setFormatter(file_formatter)

# 将处理器添加到日志记录器
logger.addHandler(console_handler)
logger.addHandler(file_handler)

class SqlMG():
    def __init__(self, database):
        """SQLite数据库设置"""
        try:
            self.conn = sqlite3.connect(database)
            self.cursor = self.conn.cursor()
            logger.info('SqlMG init successfully.')
        except sqlite3.Error as e:
            logger.error(f'SqlMG init failed: {e}')
            exit(0)

    def sever_sql(self):
        try:
            self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS clients (
                user_id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL,
                password_hash TEXT NOT NULL,  -- 存储密码的哈希值
                salt TEXT NOT NULL            -- 存储盐值
            );
            ''')
            self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sender_id INTEGER,
                sender_username TEXT,
                message TEXT,
                timestamp DATETIME,
                FOREIGN KEY(sender_id) REFERENCES clients(user_id)
            );
            ''')
            self.conn.commit()
            logger.info('sql for server init successfully.')
        except sqlite3.Error as e:
            logger.error(f'sql for server init failed: {e}')
            exit(0)

    def client_sql(self):
        try:
            self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sender_id INTEGER,
                sender_username TEXT,
                message TEXT,
                timestamp DATETIME
            );
            ''')
            self.conn.commit()
            logger.info('sql for client init successfully.')
        except sqlite3.Error as e:
            logger.error(f'sql for client init failed: {e}')
            exit(0)

    def exec(self, sql, params=None):
        """执行sql的插入、更新、删除功能"""
        try:
            if params:
                self.cursor.execute(sql, params)
            else:
                self.cursor.execute(sql)
            self.conn.commit()
            logger.info(f'{sql} with {params} run successfully.')
        except sqlite3.Error as e:
            logger.error(f'{sql} with {params} run failed: {e}')

    def fetch(self, sql, params=None):
        """执行sql的查询功能"""
        try:
            if params:
                self.cursor.execute(sql, params)
            else:
                self.cursor.execute(sql)
            logger.info(f'{sql} with {params} run successfully.')
        except sqlite3.Error as e:
            logger.error(f'{sql} with {params} run failed: {e}')
        return self.cursor.fetchall()

    def close(self):
        """关闭数据库连接"""
        if self.conn:
            self.conn.close()
            logger.info('Database connection closed.')

    def __del__(self):
        """析构函数，确保连接关闭"""
        self.close()