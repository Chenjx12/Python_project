import json
import mimetypes
import os.path
import sys

import qasync
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QGridLayout,
    QLabel, QPushButton, QLineEdit, QHBoxLayout, QTextEdit, QVBoxLayout, QScrollArea, QSizePolicy, QLayout,
    QMessageBox
)
from PyQt5.QtCore import Qt, pyqtSignal, QTimer
from PyQt5.QtGui import QFont, QPixmap
import humanize
import WebsocketMG
import asyncio

CONFIG_FILE = 'client.config'


def insert_soft_breaks(text):
    return '\u200b'.join(text)



class LoginWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.main_window = None
        self.init_ui()
        self.ws_manager = WebsocketMG.WebSocketManager()
        self.msg={}

    def init_ui(self):
        file_path=os.path.join(os.getcwd(), CONFIG_FILE)
        if not self.config_empty(file_path):
            self.try_login(self.msg['username'], self.msg['password'], self.msg['user_id'])
        self.setWindowTitle("用户登录")
        # self.setGeometry(100, 100, 300, 200)
        self.setFixedSize(300, 200)

        font = QFont()
        font.setPointSize(11)

        self.label_username = QLabel("用户名:")
        self.input_username = QLineEdit()
        self.input_username.setPlaceholderText("请输入用户名")

        self.label_password = QLabel("密码:")
        self.input_password = QLineEdit()
        self.input_password.setPlaceholderText("请输入密码")
        self.input_password.setEchoMode(QLineEdit.Password)
        self.input_password.returnPressed.connect(self.handle_login)

        self.login_button = QPushButton("登录")
        self.login_button.clicked.connect(self.handle_login)
        self.input_username.returnPressed.connect(self.focus_password)
        layout = QVBoxLayout()
        layout.addWidget(self.label_username)
        layout.addWidget(self.input_username)
        layout.addWidget(self.label_password)
        layout.addWidget(self.input_password)
        layout.addStretch()
        layout.addWidget(self.login_button)

        self.setLayout(layout)


    def focus_password(self):
        self.input_password.setFocus()

    def handle_login(self):
        username = self.input_username.text().strip()
        password = self.input_password.text().strip()
        print(password,username)
        if not username or not password:
            QMessageBox.warning(self, "错误", "请输入用户名和密码。")
            return
        print('1')
        # 启动异步任务，不阻塞 GUI
        asyncio.create_task(self.try_login(username, password))

    async def try_login(self, username, password, user_id=0):
        print(username,password)
        success = await self.ws_manager.connect_ws(user_id, username=username, password=password)

        if success:
            QTimer.singleShot(100, self.open_main_window)
        else:
            QMessageBox.warning(self, "登录失败", "用户名或密码错误或连接失败。")

    def open_main_window(self):
        print('2')
        self.main_window = GridLayoutWindow(self.ws_manager)
        self.main_window.show()
        self.close()  # 关闭登录窗口

    def config_empty(self,file_path):
        """检查.config文件是否为空（文件不存在、大小为0或仅包含空白字符）"""
        try:
            # 检查文件是否存在
            if not os.path.exists(file_path):
                print(f"错误：文件 '{file_path}' 不存在")
                return True
            # 检查文件大小
            if os.path.getsize(file_path) == 0:
                print(f"文件 '{file_path}' 是空文件（0字节）")
                return True
            # 读取文件内容
            with open(file_path, 'r', encoding='utf-8') as file:
                # 尝试解析JSON（验证有效性）
                try:
                    self.msg=json.load(file)
                except json.JSONDecodeError as e:
                    print(f"文件 '{file_path}' 包含无效JSON: {e}")
                    return True  # 非空但格式错误

            return False  # 文件非空且有效

        except Exception as e:
            print(f"处理文件时出错: {e}")
            return True

class MessageBubble(QWidget):
    def __init__(self, content, msg_type="text", is_sender=True):
        super().__init__()
        self.is_sender = is_sender
        self.msg_type = msg_type
        self.content = content
        self.current_max_width = -1

        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(10, 10, 10, 10)
        self.layout.setSpacing(5)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        if msg_type == "text":
            self._build_text()
        elif msg_type == "image":
            self._build_image()
        elif msg_type == "file":
            self._build_file()

        self.setMinimumSize(60, 30)

    def _build_text(self):
        self.label = QLabel(insert_soft_breaks(self.content))
        self.label.setWordWrap(True)
        self.label.setStyleSheet(f"""
            background-color: {'#DCF8C6' if self.is_sender else '#E5E5EA'};
            border-radius: 10px;
            padding: 8px;
        """)
        self.label.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        self.layout.addWidget(self.label)

    def _build_image(self):
        self.label = QLabel()
        pixmap = QPixmap(self.content)
        print(self.content)
        if pixmap.isNull():
            self.label.setText("无法加载图片")
            return
        max_width = 300  # 最大宽度
        scaled_pixmap = pixmap.scaledToWidth(max_width, Qt.SmoothTransformation)
        self.label.setPixmap(scaled_pixmap)
        self.label.setScaledContents(False)
        self.label.setStyleSheet("border-radius: 10px;")
        self.label.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.label.mousePressEvent = lambda e: os.startfile(self.content)
        self.layout.addWidget(self.label)

    def _build_file(self):
        file_name = os.path.basename(self.content)
        print(self.content)
        file_size = humanize.naturalsize(os.path.getsize(self.content))
        self.label = QLabel(f"📎 <b>{file_name}</b><br><small>{file_size}</small>")
        self.label.setStyleSheet(f"""
            background-color: {'#DCF8C6' if self.is_sender else '#E5E5EA'};
            border-radius: 10px;
            padding: 8px;
        """)
        self.label.setTextInteractionFlags(Qt.TextBrowserInteraction)
        self.label.setOpenExternalLinks(False)
        self.label.mousePressEvent = lambda e: os.startfile(self.content)
        self.layout.addWidget(self.label)

    def adjust_bubble_width(self, max_width):
        if self.current_max_width == max_width:
            return

        self.current_max_width = max_width
        if hasattr(self, 'label') and self.msg_type == "text":
            self.label.setMaximumWidth(max_width)
            self.label.adjustSize()
            self.adjustSize()


class SendOnEnterTextEdit(QTextEdit):
    file_dropped = pyqtSignal(str)  # 新增信号用于文件传输

    def __init__(self, send_callback, parent=None):
        super().__init__(parent)
        self.send_callback = send_callback
        self.setAcceptDrops(True)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            if event.modifiers() == Qt.ShiftModifier:
                super().keyPressEvent(event)
            else:
                self.send_callback()
        else:
            super().keyPressEvent(event)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event):
        urls = event.mimeData().urls()
        if urls:
            local_path = urls[0].toLocalFile()
            if os.path.isfile(local_path):
                # 只接受图片和常见文档类型
                ext = os.path.splitext(local_path)[1].lower()
                if ext in ['.jpg', '.jpeg', '.png', '.gif', '.bmp', '.pdf', '.doc', '.docx']:
                    self.file_dropped.emit(local_path)


class GridLayoutWindow(QMainWindow):
    def __init__(self,web):
        super().__init__()
        self.bubbles = []
        self.setWindowTitle("三列网格布局 - 列宽定制")
        self.setGeometry(1100, 100, 900, 600)
        self.web=web
        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        main_grid = QGridLayout(central_widget)
        main_grid.setSpacing(15)
        main_grid.setContentsMargins(0, 0, 0, 20)

        self.text = SendOnEnterTextEdit(send_callback=self.send_text)
        self.text.file_dropped.connect(self.send_file)
        self.text.setAlignment(Qt.AlignLeft)
        self.text.setStyleSheet("""
            background-color: transparent;
            color: black;
            padding: 15px;
            border-radius: 8px;
        """)
        self.text.setFixedHeight(int(self.height() * 0.15))
        main_grid.addWidget(self.text, 8, 0, 1, 4)

        self.button = QPushButton('发送')
        self.button.clicked.connect(self.send_text)
        self.button.setStyleSheet("""
            QPushButton {
                background-color: #E5E5EA;
                border: none;
                color: black;
            }
            QPushButton:hover {
                border: 1px solid #0078D7;
                border-radius: 4px;
            }
        """)
        self.button.setFixedHeight(45)
        self.button.setFixedWidth(80)
        main_grid.addWidget(self.button, 9, 3, Qt.AlignCenter)

        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.chat_area_widget = QWidget()
        self.chat_area_layout = QVBoxLayout(self.chat_area_widget)
        self.chat_area_layout.setSizeConstraint(QLayout.SetMinAndMaxSize)  # 添加这一句
        self.chat_area_layout.addStretch()
        self.scroll_area.setWidget(self.chat_area_widget)
        main_grid.addWidget(self.scroll_area, 0, 0, 7, 4)

        for i in range(7):
            main_grid.setRowStretch(i, 1)
        main_grid.setRowStretch(8, 0)
        main_grid.setRowStretch(9, 0)
        self.scroll_area.setMinimumHeight(200)

        if web:
            asyncio.create_task(self.listen_messages())


    def send_text(self):
        text = self.text.toPlainText().strip()
        if text:
            self.add_message(text, "text", is_sender=True)
            asyncio.create_task(self.web.send_masssage(text))
            #self.add_message("收到：" + text, "text", is_sender=False)
        self.text.clear()

    def send_file(self, file_path):
        mime, _ = mimetypes.guess_type(file_path)
        is_image = mime and mime.startswith("image")

        if is_image:
            # 发送图片消息

            self.add_message(file_path, "image", is_sender=True)
            asyncio.create_task(self.web.send_image(file_path))
        else:
            # 发送文件消息
            self.add_message(file_path, "file", is_sender=True)

        #self.add_message("收到文件: " + os.path.basename(file_path), "text", is_sender=False)


    def add_message(self, content, msg_type="text",time=0,name='me',is_sender=True):
        bubble = MessageBubble(content, msg_type=msg_type, is_sender=is_sender)
        self.bubbles.append(bubble)
        bubble.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Minimum)
        container = QWidget()
        container_layout = QHBoxLayout(container)
        container.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        container_layout.setContentsMargins(0, 0, 0, 0)

        avatar_label = QLabel()
        avatar_path = os.getcwd() + "/resource/img.png"
        pixmap = QPixmap(avatar_path)
        avatar_label.setPixmap(pixmap.scaled(40, 40, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        avatar_label.setStyleSheet("border-radius: 20px;")

        name_label = QLabel(name)
        name_label.setStyleSheet("color: gray; font-size: 12px;")
        name_label.setAlignment(Qt.AlignLeft if not is_sender else Qt.AlignRight)

        # 用户名 + 气泡 垂直排布
        bubble_container = QWidget()
        bubble_layout = QVBoxLayout(bubble_container)
        bubble_layout.setContentsMargins(0, 0, 10, 0)
        bubble_layout.setSpacing(2)
        bubble_layout.addWidget(name_label)
        bubble_layout.addWidget(bubble, alignment=Qt.AlignRight if is_sender else Qt.AlignLeft)

        if is_sender:
            container_layout.addStretch(1)
            container_layout.addWidget(bubble_container, 0, Qt.AlignRight)
            container_layout.addWidget(avatar_label, 0, Qt.AlignTop | Qt.AlignRight)
        else:
            container_layout.addWidget(avatar_label, 0, Qt.AlignTop | Qt.AlignLeft)
            container_layout.addWidget(bubble_container, 0, Qt.AlignLeft)
            container_layout.addStretch(1)

        self.chat_area_layout.insertWidget(self.chat_area_layout.count() - 1, container)
        self.scroll_area.verticalScrollBar().setValue(
            self.scroll_area.verticalScrollBar().maximum()
        )


    def resizeEvent(self, event):
        super().resizeEvent(event)
        max_bubble_width = int(self.width() * 0.6)
        for bubble in self.bubbles:
            bubble.adjust_bubble_width(max_bubble_width)

    async def listen_messages(self):
        while True:
            mess = await self.web.message_queue.get()
            #msg = {"flag": flag,"id": id',"name": name,"message": message,"timestamp": times
            data=json.loads(mess)
            msg=data['message']
            name=data['name']
            flag=data['flag']
            time=data['timestamp']
            '''
            0 text 1 登录消息 2 注册消息 8 图片消息 9 文件消息
            '''

            # 如果是图片提示
            if flag==0:
                self.add_message(msg, "text",name=name,time=time, is_sender=False)
            elif flag==8 and os.path.exists(msg):
                self.add_message(msg, "image", name=name,time=time,is_sender=False)
            elif flag==9:
                self.add_message(msg, "text",name=name,time=time, is_sender=False)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    loop = qasync.QEventLoop(app)
    asyncio.set_event_loop(loop)
    window = LoginWindow()
    window.show()
    with loop:
        loop.run_forever()
    sys.exit(app.exec_())
