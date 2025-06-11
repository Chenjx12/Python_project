import json
import logging
import mimetypes
import os.path
import sys
import shutil
import qasync
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QGridLayout,
    QLabel, QPushButton, QLineEdit, QHBoxLayout, QTextEdit, QVBoxLayout, QScrollArea, QSizePolicy, QLayout,
    QMessageBox, QFileDialog
)
from PyQt5.QtCore import Qt, pyqtSignal, QTimer
from PyQt5.QtGui import QFont, QPixmap, QIcon
import humanize
import WebsocketMG
import asyncio

CONFIG_FILE = 'client.config'

user_id = 0


def insert_soft_breaks(text):
    return '\u200b'.join(text)


class CustomTitleBar(QWidget):
    def __init__(self, parent):
        super().__init__(parent)
        self.parent = parent
        self.setFixedHeight(40)
        self.setStyleSheet("""
            QWidget {
                background-color: #2c2c2c;
                color: white;
            }
            QLabel {
                color: white;
                font-size: 16px;
                font-weight: bold;
            }
            QPushButton {
                background-color: transparent;
                color: white;
                border: none;
                font-size: 16px;
                padding: 5px 10px;
            }
            QPushButton:hover {
                background-color: #e0e0e0;
                color: #333333;
            }
        """)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(0)

        # 标题
        self.title_label = QLabel(parent.windowTitle())
        self.title_label.setStyleSheet("""
            QLabel {
                color: white;
                font-size: 16px;
                font-weight: bold;
                background-color: transparent;
            }
        """)

        # 控制按钮
        self.min_button = QPushButton("—")
        self.close_button = QPushButton("×")

        for button in [self.min_button, self.close_button]:
            button.setFixedSize(30, 30)

        self.min_button.clicked.connect(parent.showMinimized)
        self.close_button.clicked.connect(parent.close)

        layout.addWidget(self.title_label)
        layout.addStretch()
        layout.addWidget(self.min_button)
        layout.addWidget(self.close_button)

        self.old_pos = None

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.old_pos = event.globalPos()

    def mouseMoveEvent(self, event):
        if self.old_pos:
            delta = event.globalPos() - self.old_pos
            self.parent.move(self.parent.pos() + delta)
            self.old_pos = event.globalPos()

    def mouseReleaseEvent(self, event):
        self.old_pos = None


class CustomWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowFlags(Qt.FramelessWindowHint)
        self.setWindowIcon(QIcon())
        self.setStyleSheet("""
            QMainWindow {
                background-color: white;
                border: 1px solid #cccccc;
            }
        """)
        
        # 创建标题栏
        self.title_bar = CustomTitleBar(self)
        
        # 创建中央窗口
        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        
        # 主布局
        self.main_layout = QVBoxLayout(self.central_widget)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.setSpacing(0)
        self.main_layout.addWidget(self.title_bar)


class LoginWindow(CustomWindow):
    def __init__(self):
        super().__init__()
        self.ws_manager = WebsocketMG.WebSocketManager()
        self.msg = {}
        self.init_ui()

    def init_ui(self):
        self.setWindowTitle("登录")
        self.setFixedSize(400, 600)
        
        # 创建登录表单容器
        login_container = QWidget()
        login_container.setStyleSheet("""
            QWidget {
                background-color: white;
            }
            QLabel {
                font-size: 16px;
                color: #333333;
            }
            QLineEdit {
                font-size: 16px;
                padding: 10px;
                border: 1px solid #cccccc;
                border-radius: 5px;
                background-color: #f5f5f5;
            }
            QPushButton {
                font-size: 16px;
                padding: 10px 20px;
                background-color: #07C160;
                color: white;
                border: none;
                border-radius: 5px;
            }
            QPushButton:hover {
                background-color: #e0e0e0;
                color: #333333;
            }
        """)
        
        layout = QVBoxLayout(login_container)
        layout.setContentsMargins(40, 40, 40, 40)
        layout.setSpacing(20)
        
        # 标题
        title_label = QLabel("欢迎登录")
        title_label.setStyleSheet("font-size: 36px; font-weight: bold; color: #333333;")
        title_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(title_label)
        
        # 添加弹性空间，将输入框推到底部
        layout.addStretch()
        
        # 创建输入框容器
        input_container = QWidget()
        input_layout = QVBoxLayout(input_container)
        input_layout.setSpacing(30)
        
        # 用户名输入
        self.label_username = QLabel("用户名:")
        self.input_username = QLineEdit()
        self.input_username.setPlaceholderText("请输入用户名")
        self.input_username.setMinimumHeight(45)
        
        # 密码输入
        self.label_password = QLabel("密码:")
        self.input_password = QLineEdit()
        self.input_password.setPlaceholderText("请输入密码")
        self.input_password.setEchoMode(QLineEdit.Password)
        self.input_password.setMinimumHeight(45)
        self.input_password.returnPressed.connect(self.handle_login)
        
        # 登录按钮
        self.login_button = QPushButton("登录")
        self.login_button.setMinimumHeight(50)
        self.login_button.clicked.connect(self.handle_login)
        self.input_username.returnPressed.connect(self.focus_password)
        
        input_layout.addWidget(self.label_username)
        input_layout.addWidget(self.input_username)
        input_layout.addWidget(self.label_password)
        input_layout.addWidget(self.input_password)
        input_layout.addWidget(self.login_button)
        
        # 将输入框容器添加到主布局
        layout.addWidget(input_container)
        
        self.main_layout.addWidget(login_container)
        
        file_path = os.path.join(os.getcwd(), CONFIG_FILE)
        print(file_path)
        if not self.config_empty(file_path):
            QTimer.singleShot(0,
                              lambda: asyncio.create_task(self.try_login(self.msg['username'], self.msg['password'])))

    def focus_password(self):
        self.input_password.setFocus()

    def handle_login(self):
        username = self.input_username.text().strip()
        password = self.input_password.text().strip()
        if not username or not password:
            QMessageBox.warning(self, "错误", "请输入用户名和密码。")
            return
        QTimer.singleShot(0, lambda: asyncio.create_task(self.try_login(username, password)))

    async def try_login(self, username, password):
        try:
            with open(os.path.join(os.getcwd(), CONFIG_FILE)) as f:
                js = json.load(f)
                id_ = js['user_id']
        except:
            id_ = 0
        success = await self.ws_manager.connect_ws(id_, username=username, password=password)
        if success:
            logging.info("---准备启动主窗口---")
            await asyncio.sleep(0.1)
            self.open_main_window()
        else:
            QMessageBox.warning(self, "登录失败", "用户名或密码错误或连接失败。")

    def open_main_window(self):
        self.main_window = GridLayoutWindow(self.ws_manager)
        self.main_window.show()
        # QTimer.singleShot(0, lambda: asyncio.create_task(self.ws_manager.refresh_message()))
        # self.ws_manager.refresh_message()
        self.close()  # 关闭登录窗口

    def config_empty(self, file_path):
        """检查.config文件是否为空（文件不存在、大小为0或仅包含空白字符）"""
        try:
            if not os.path.exists(file_path):
                print(f"错误：文件 '{file_path}' 不存在")
                return True
            if os.path.getsize(file_path) == 0:
                print(f"文件 '{file_path}' 是空文件（0字节）")
                return True
            with open(file_path, 'r', encoding='utf-8') as file:
                try:
                    self.msg = json.load(file)
                except json.JSONDecodeError as e:
                    print(f"文件 '{file_path}' 包含无效JSON: {e}")
                    return True
            return False
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


class GridLayoutWindow(CustomWindow):
    def __init__(self, web):
        super().__init__()
        self.bubbles = []
        self.setWindowTitle("聊天室")
        self.setGeometry(1100, 100, 900, 600)
        self.web = web

        # 初始化头像路径
        self.avatar_dir = os.path.join(os.getcwd(), "source")
        if not os.path.exists(self.avatar_dir):
            os.makedirs(self.avatar_dir)
        self.current_avatar = os.path.join(self.avatar_dir, WebsocketMG.global_state.username + ".png")
        if not os.path.exists(self.current_avatar):
            default_avatar = QPixmap(40, 40)
            default_avatar.fill(Qt.white)
            default_avatar.save(self.current_avatar)

        # 创建主容器
        main_container = QWidget()
        main_container.setStyleSheet("""
            QWidget {
                background-color: #f5f5f5;
            }
            QTextEdit {
                font-size: 16px;
                padding: 10px;
                border: 1px solid #cccccc;
                border-radius: 5px;
                background-color: white;
            }
            QPushButton {
                font-size: 16px;
                padding: 10px 20px;
                background-color: #07C160;
                color: white;
                border: none;
                border-radius: 5px;
            }
            QPushButton:hover {
                background-color: #e0e0e0;
                color: #333333;
            }
        """)

        main_grid = QGridLayout(main_container)
        main_grid.setSpacing(15)
        main_grid.setContentsMargins(20, 20, 20, 20)

        self.text = SendOnEnterTextEdit(send_callback=self.send_text)
        self.text.file_dropped.connect(self.send_file)
        self.text.setAlignment(Qt.AlignLeft)
        self.text.setStyleSheet("""
            QTextEdit {
                background-color: white;
                color: #333333;
                padding: 15px;
                border-radius: 8px;
                font-size: 16px;
            }
        """)
        self.text.setFixedHeight(int(self.height() * 0.15))
        main_grid.addWidget(self.text, 8, 0, 1, 4)

        self.button = QPushButton('发送')
        self.button.clicked.connect(self.send_text)
        self.button.setStyleSheet("""
            QPushButton {
                background-color: #07C160;
                color: white;
                border: none;
                border-radius: 5px;
                font-size: 16px;
                padding: 10px 20px;
            }
            QPushButton:hover {
                background-color: #e0e0e0;
                color: #333333;
            }
        """)
        self.button.setFixedHeight(45)
        self.button.setFixedWidth(100)
        main_grid.addWidget(self.button, 9, 3, Qt.AlignRight)

        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setStyleSheet("""
            QScrollArea {
                border: none;
                background-color: transparent;
            }
            QScrollBar:vertical {
                border: none;
                background: #f0f0f0;
                width: 10px;
                margin: 0px;
            }
            QScrollBar::handle:vertical {
                background: #c0c0c0;
                min-height: 20px;
                border-radius: 5px;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0px;
            }
        """)
        
        self.chat_area_widget = QWidget()
        self.chat_area_layout = QVBoxLayout(self.chat_area_widget)
        self.chat_area_layout.setSizeConstraint(QLayout.SetMinAndMaxSize)
        self.chat_area_layout.addStretch()
        self.scroll_area.setWidget(self.chat_area_widget)
        main_grid.addWidget(self.scroll_area, 0, 0, 7, 4)

        for i in range(7):
            main_grid.setRowStretch(i, 1)
        main_grid.setRowStretch(8, 0)
        main_grid.setRowStretch(9, 0)
        self.scroll_area.setMinimumHeight(200)

        self.main_layout.addWidget(main_container)

        if web:
            asyncio.create_task(self.listen_messages())

    def send_text(self):
        text = self.text.toPlainText().strip()
        if text:
            self.add_message(text, "text", name=WebsocketMG.global_state.username, is_sender=True)
            # 使用 QTimer 来延迟执行异步操作
            QTimer.singleShot(0, lambda: asyncio.create_task(self.web.send_message(text)))
        self.text.clear()

    def send_file(self, file_path):
        mime, _ = mimetypes.guess_type(file_path)
        is_image = mime and mime.startswith("image")

        if is_image:
            self.add_message(file_path, "image", name=WebsocketMG.global_state.username, is_sender=True)
            QTimer.singleShot(0, lambda: asyncio.create_task(self.web.send_image(file_path)))
        else:
            self.add_message(file_path, "file", name=WebsocketMG.global_state.username, is_sender=True)
            QTimer.singleShot(0, lambda: asyncio.create_task(self.web.send_file(file_path)))

    def add_message(self, content, msg_type="text", time=0, name="", is_sender=True):
        if name == 0:
            name = "server"

        bubble = MessageBubble(content, msg_type=msg_type, is_sender=is_sender)
        self.bubbles.append(bubble)
        bubble.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Minimum)

        container = QWidget()
        container.setProperty("is_sender", is_sender)
        container.setProperty("user_name", name)  # 设置user_id属性
        logging.info(f"设置container属性: is_sender={is_sender}, user_name={name}")  # 调试信息
        container_layout = QHBoxLayout(container)
        container.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.setSpacing(10)

        # 头像
        avatar_label = QLabel()
        try:
            avatar_path = self.current_avatar if is_sender else os.path.join(os.getcwd(), "source", name + '.png')
            if not os.path.exists(avatar_path):
                avatar_path = os.path.join(os.getcwd(), "source", "img.png")
            pixmap = QPixmap(avatar_path)
            if not pixmap.isNull():
                avatar_label.setPixmap(pixmap.scaled(40, 40, Qt.KeepAspectRatio, Qt.SmoothTransformation))
            else:
                logging.error(f"无法加载头像: {avatar_path}")
                return
        except Exception as e:
            logging.error(f"设置头像时出错: {e}")
            return

        avatar_label.setStyleSheet("""
                    QLabel {
                        border-radius: 20px;
                        background-color: #ffffff;
                        padding: 2px;
                    }
                """)
        avatar_label.setProperty("is_avatar", True)
        avatar_label.setProperty("user_name", name)
        logging.info(f"设置avatar_label属性: is_avatar=True, user_name={name}")

        if is_sender:
            avatar_label.mousePressEvent = self.change_avatar
            avatar_label.setCursor(Qt.PointingHandCursor)
            avatar_label.setToolTip("点击更换头像")

        # 用户名
        name_label = QLabel(name)
        name_label.setStyleSheet("""
                    QLabel {
                        color: #1a1a1a;
                        font-size: 17px;
                        font-weight: bold;
                        padding: 2px 0;
                    }
                """)
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

    def change_avatar(self, event):
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "选择头像",
            "",
            "图片文件 (*.png *.jpg *.jpeg *.bmp *.gif)"
        )

        if file_path:
            try:
                # 生成新的头像文件名
                new_avatar_path = os.path.join(self.avatar_dir,
                                               f"{WebsocketMG.global_state.username}.png")

                # 复制并保存新头像
                shutil.copy2(file_path, new_avatar_path)
                self.current_avatar = new_avatar_path
                print(self.current_avatar)
                # 更新所有消息中的头像
                self.update_avatar({WebsocketMG.global_state.username: self.current_avatar})

                QMessageBox.information(self, "成功", "头像已更新！")
                QTimer.singleShot(0, lambda: asyncio.create_task(self.web.send_image(self.current_avatar, 10)))
            except Exception as e:
                QMessageBox.warning(self, "错误", f"更新头像时出错：{str(e)}")
                # 如果出错，恢复默认头像
                self.current_avatar = os.path.join(os.getcwd(), "source/img.png")

    def update_avatar(self, user_avatar_map: dict):
        """
        更新头像（可针对不同用户）
        参数：user_avatar_map: dict，格式为 {username: avatar_path}
        """
        logging.info(f"开始更新头像，头像映射: {user_avatar_map}")

        if not user_avatar_map:
            logging.warning("头像映射为空")
            return

        for i in range(self.chat_area_layout.count() - 1):
            try:
                container = self.chat_area_layout.itemAt(i).widget()
                if not container:
                    continue

                is_sender = container.property("is_sender")
                name = container.property("user_name")
                logging.info(f"消息 {i}: is_sender={is_sender}, user_name={name}")

                if name not in user_avatar_map:
                    continue

                for child in container.findChildren(QLabel):
                    if child.property("is_avatar"):
                        try:
                            if is_sender:
                                avatar_path = self.current_avatar
                                logging.info(f"更新发送者头像: {avatar_path}")
                            else:
                                avatar_path = user_avatar_map.get(name)
                                if not avatar_path:
                                    avatar_path = os.path.join(os.getcwd(), "source", "img.png")
                                logging.info(f"更新接收者头像: user_name={name}, path={avatar_path}")

                            if os.path.exists(avatar_path):
                                pixmap = QPixmap(avatar_path)
                                if not pixmap.isNull():
                                    child.setPixmap(pixmap.scaled(40, 40, Qt.KeepAspectRatio, Qt.SmoothTransformation))
                                    logging.info(f"成功更新头像: {avatar_path}")
                                else:
                                    logging.error(f"无法加载头像图片: {avatar_path}")
                            else:
                                logging.error(f"头像文件不存在: {avatar_path}")
                        except Exception as e:
                            logging.error(f"更新头像时出错: {e}")
            except Exception as e:
                logging.error(f"处理消息 {i} 时出错: {e}")
                continue

    def resizeEvent(self, event):
        super().resizeEvent(event)
        max_bubble_width = int(self.width() * 0.6)
        for bubble in self.bubbles:
            bubble.adjust_bubble_width(max_bubble_width)

    async def listen_messages(self):
        syn_flag = 0
        while True:
            try:
                if not self.web.is_connected:
                    await asyncio.sleep(1)
                    continue

                mess = await self.web.message_queue.get()
                logging.info(f"前端消息队列输出：{mess}")
                data = json.loads(mess)
                msg = data['message']
                name = data['name']
                flag = data['flag']
                time = data['timestamp']
                userid = data['id']
                if WebsocketMG.global_state.user_id == data['id'] and syn_flag:
                    continue
                is_sender = WebsocketMG.global_state.user_id == data['id']
                # 对离线消息同步过程中需要把自身信息进行识别
                # if flag == 7:
                #     syn_flag = 1
                #     continue
                # if flag == 0:
                #     self.add_message(msg, "text", name=name, time=time, is_sender= WebsocketMG.global_state.user_id == data['id'])
                # elif flag == 8 and os.path.exists(msg):
                #     self.add_message(msg, "image", name=name, time=time, is_sender= WebsocketMG.global_state.user_id == data['id'])
                # elif flag == 9:
                #     self.add_message(msg, "text", name=name, time=time, is_sender= WebsocketMG.global_state.user_id == data['id'])
                # elif flag == 10:
                #     pass
                #     file_path = msg
                #     new_name = name + '.png'
                #     shutil.copy2(file_path, new_name)
                #     self.updata_avatar(new_name)

                if flag == 7:
                    syn_flag = 1
                    continue
                if flag == 0:
                    self.add_message(msg, "text", name=name, time=time, is_sender=is_sender)
                elif flag == 8 and os.path.exists(msg):
                    self.add_message(msg, "image", name=name, time=time, is_sender=is_sender)
                elif flag == 9:
                    self.add_message(msg, "text", name=name, time=time, is_sender=is_sender)
                elif flag == 10:
                    file_path = msg
                    new_name = name + '.png'
                    target_path = os.path.join(os.getcwd(), "source", new_name)
                    logging.info(f"源文件路径为：{file_path}")
                    logging.info(f"目标文件路径为：{target_path}")

                    # 检查源文件和目标文件是否相同
                    if os.path.normpath(file_path) != os.path.normpath(target_path):
                        shutil.copy2(file_path, target_path)
                        self.update_avatar({name: target_path})
                    else:
                        logging.info("源文件和目标文件相同，跳过复制")
                        self.update_avatar({name: file_path})

            except Exception as e:
                print(f"Error processing message: {e}")
            await asyncio.sleep(0.1)  # 添加小延迟，避免过度占用CPU

    def closeEvent(self, event):
        super().closeEvent(event)


if __name__ == '__main__':
    try:
        app = QApplication(sys.argv)
        loop = qasync.QEventLoop(app)
        asyncio.set_event_loop(loop)

        window = LoginWindow()
        window.show()

        with loop:
            loop.run_forever()
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)
