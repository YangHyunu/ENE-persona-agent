"""
clova_mcp_gui.py - PySide6 GUI for ENE Desktop Widget

Pure GUI layer:
- ChatWindow: 대화 UI + HITL 승인 다이얼로그 + 응답 파싱
- SetWindow: 캐릭터 설정
- ENE: 데스크탑 위젯 + 스프라이트 애니메이션

파이프라인/설정은 config.py, graph.py에서 import
"""

import sys
import os
import asyncio
import uuid
import re
import json
import platform
from datetime import datetime
from pathlib import Path
import pathlib

# Qt 플러그인 경로 설정
def setup_qt_plugin_path():
    try:
        import PySide6
        pyside_dir = os.path.dirname(PySide6.__file__)
        plugin_path = os.path.join(pyside_dir, "Qt", "plugins")
        platform_path = os.path.join(plugin_path, "platforms")
        if os.path.exists(platform_path):
            os.environ["QT_QPA_PLATFORM_PLUGIN_PATH"] = platform_path
            os.environ["QT_PLUGIN_PATH"] = plugin_path
    except ImportError:
        pass

setup_qt_plugin_path()

# Qt imports
from PySide6.QtWidgets import (QApplication, QWidget, QLabel, QMenu,
                               QVBoxLayout, QTextEdit, QLineEdit, QPushButton,
                               QComboBox, QMessageBox)
from PySide6.QtCore import Qt, QTimer, QPoint
from PySide6.QtGui import QPixmap

# qasync
import qasync
from qasync import QEventLoop, asyncSlot

# 상위 디렉토리 추가
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# LangGraph
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langchain_core.messages import HumanMessage, AIMessage, ToolMessage

# Local modules
from config import SENSITIVE_TOOL_NAMES, load_mcp_tools
from graph import create_agent_graph


# ============================================================
# Session Management
# ============================================================

def get_last_thread_id():
    if os.path.exists("last_session.txt"):
        with open("last_session.txt", "r") as f:
            return f.read().strip()
    return "mcp_default_session"


def save_last_thread_id(thread_id):
    with open("last_session.txt", "w") as f:
        f.write(thread_id)


# ============================================================
# ChatWindow - GUI for Clova Agent
# ============================================================

class ChatWindow(QWidget):
    def __init__(self, owner, graph, config, parent=None):
        super().__init__(parent)
        self.owner = owner
        self.graph = graph
        self.config = config

        self.current_response = ""
        self.current_response_html = ""
        self.is_processing = False

        self.user_profile = {
            "nickname": "",
            "relation_type": "단짝 비서 ENE (에네)",
            "first_meet_date": datetime.now().isoformat()
        }

        self.setWindowFlags(Qt.Window | Qt.WindowStaysOnTopHint)
        self.setWindowTitle("ENE와의 대화 (Clova Agent)")
        self.resize(400, 500)

        layout = QVBoxLayout(self)

        self.chat_history = QTextEdit()
        self.chat_history.setReadOnly(True)
        layout.addWidget(self.chat_history)

        self.input_field = QLineEdit()
        self.input_field.setPlaceholderText("메시지 입력 (명령어: /tools, /quit)")
        self.input_field.returnPressed.connect(self.on_send_clicked)
        layout.addWidget(self.input_field)

        self.send_btn = QPushButton("전송")
        self.send_btn.clicked.connect(self.on_send_clicked)
        layout.addWidget(self.send_btn)

        # SQLite에서 히스토리 로드
        asyncio.create_task(self.load_history_from_sqlite())

    async def load_history_from_sqlite(self):
        """SQLite에서 대화 히스토리 로드"""
        try:
            current = await self.graph.aget_state(self.config)
            if not current or not current.values:
                print("No previous session found")
                return

            messages = current.values.get("messages", [])

            if not messages:
                print("No messages in session")
                return

            html_content = ""
            for msg in messages:
                if isinstance(msg, HumanMessage):
                    content = msg.content
                    html_content += f"<b>나:</b> {content}<br>"
                elif isinstance(msg, AIMessage):
                    if not msg.tool_calls:
                        content = msg.content
                        try:
                            json_match = re.search(r'\{[^{}]*"답변"[^{}]*\}', content)
                            if json_match:
                                response_data = json.loads(json_match.group())
                                content = response_data.get("답변", content)
                        except:
                            pass

                        html_content += f"<span style='color: #0078d7;'><b>ENE:</b></span> {content}<br><br>"

            self.chat_history.setHtml(html_content)
            self.chat_history.verticalScrollBar().setValue(
                self.chat_history.verticalScrollBar().maximum()
            )
        except Exception as e:
            print(f"[ERROR] Failed to load history from SQLite: {e}")
            import traceback
            traceback.print_exc()

    def append_system_message(self, text):
        current_html = self.chat_history.toHtml()
        new_html = current_html + f"<span style='color: gray;'>[시스템] {text}</span><br><br>"
        self.chat_history.setHtml(new_html)
        self.chat_history.verticalScrollBar().setValue(
            self.chat_history.verticalScrollBar().maximum()
        )

    def on_send_clicked(self):
        if self.is_processing:
            return
        msg = self.input_field.text().strip()
        if not msg:
            return
        asyncio.create_task(self.send_message(msg))

    async def send_message(self, msg: str):
        if msg.startswith("/"):
            self.input_field.clear()
            await self.handle_command(msg)
            return

        current_html = self.chat_history.toHtml()
        user_html = f"<b>나:</b> {msg}<br>"
        ene_header = f"<span style='color: #0078d7;'><b>ENE:</b></span> "

        new_html = current_html + user_html + ene_header
        self.chat_history.setHtml(new_html)
        self.chat_history.verticalScrollBar().setValue(
            self.chat_history.verticalScrollBar().maximum()
        )

        self.input_field.clear()
        self.input_field.setEnabled(False)
        self.send_btn.setEnabled(False)
        self.is_processing = True

        self.current_response_html = new_html
        self.user_message = msg

        self.owner.start_emotion_animation("busy")

        try:
            result = await self.execute_graph_with_hitl(msg)
            await self.on_response_finished(result)
        except Exception as e:
            print(f"[ERROR] Graph execution failed: {e}")
            import traceback
            traceback.print_exc()
            self.on_error(str(e))

    async def handle_command(self, command: str):
        if command == "/quit":
            self.append_system_message("안녕히 가세요!")
            self.close()
            return

        if command == "/status":
            current = await self.graph.aget_state(self.config)
            current_vals = current.values if current.values else {}

            status_text = (
                f"Thread ID: {self.config['configurable']['thread_id']}\n"
                f"Profile: {current_vals.get('user_profile', self.user_profile)}\n"
                f"Intimacy: {current_vals.get('intimacy_level', 0)}\n"
                f"Emotion: {current_vals.get('current_emotion', 'N/A')}"
            )
            self.append_system_message(status_text)
            return

        if command == "/boost":
            current = await self.graph.aget_state(self.config)
            current_vals = current.values if current.values else {}
            level = current_vals.get("intimacy_level", 0)
            new_level = min(100, level + 10)

            await self.graph.aupdate_state(
                self.config,
                {"intimacy_level": new_level,}, as_node="sensitive_tools"
            )
            self.append_system_message(f"친밀도 증가: {level} -> {new_level}")
            return

        if command == "/reset":
            new_id = f"mcp_session_v3_{uuid.uuid4().hex[:8]}"
            self.config["configurable"]["thread_id"] = new_id
            save_last_thread_id(new_id)
            self.user_profile = {
                "nickname": "",
                "relation_type": "단짝 비서 ENE (에네)",
                "first_meet_date": datetime.now().isoformat()
            }

            self.chat_history.clear()

            self.append_system_message(f"새 세션 시작: {new_id}")
            return

        if command == "/tools":
            safe_tools, sensitive_tools = await load_mcp_tools()
            tools_text = (
                f"[Safe Tools]: {[t.name for t in safe_tools]}\n"
                f"[Sensitive Tools]: {[t.name for t in sensitive_tools]}"
            )
            self.append_system_message(tools_text)
            return

        self.append_system_message(f"알 수 없는 명령어: {command}")

    async def execute_graph_with_hitl(self, message: str) -> dict:
        """HITL 처리"""
        current = await self.graph.aget_state(self.config)
        current_vals = current.values if current.values else {}

        current_inputs = {
            "messages": [HumanMessage(content=message)],
            "user_id": "default",
            "intimacy_level": current_vals.get("intimacy_level", 0),
            "user_profile": current_vals.get("user_profile", self.user_profile),
            "current_emotion": current_vals.get("current_emotion", ""),
            "system_prompt": "",
            "retrieved_memories": [],
            "context_metadata": {}
        }

        while True:
            should_break_execution = False

            async for chunk in self.graph.astream(current_inputs, config=self.config, stream_mode="updates"):
                for node_name, output in chunk.items():
                    if node_name == "agent":
                        if "messages" in output and output["messages"]:
                            last_msg = output["messages"][-1]

                            if hasattr(last_msg, "tool_calls") and last_msg.tool_calls:
                                tool_names = [tc["name"] for tc in last_msg.tool_calls]

                                if any(name in SENSITIVE_TOOL_NAMES for name in tool_names):
                                    print("\n[HITL] Sensitive tool approval requested")

                                    approved = self.show_approval_dialog(last_msg.tool_calls)

                                    if not approved:
                                        print("[HITL] User rejected tool execution")
                                        rejection_msgs = [
                                            ToolMessage(
                                                tool_call_id=tc['id'],
                                                content="사용자가 이 작업을 거부했습니다. 다른 대안을 제시하거나 거부 사실을 알리세요."
                                            ) for tc in last_msg.tool_calls
                                        ]
                                        await self.graph.aupdate_state(
                                            self.config,
                                            {"messages": rejection_msgs},
                                            as_node="sensitive_tools"
                                        )
                                        current_inputs = None
                                        should_break_execution = True
                                        break
                                    else:
                                        print("[HITL] User approved tool execution")

            if should_break_execution:
                break

            current_state = await self.graph.aget_state(self.config)
            if not current_state.next:
                return current_state.values

            current_inputs = None

    def show_approval_dialog(self, tool_calls) -> bool:
        tool_info = "\n".join([
            f"  {tc['name']}\n   매개변수: {tc['args']}"
            for tc in tool_calls
        ])

        reply = QMessageBox.question(
            self,
            "민감한 도구 실행 승인",
            f"다음 도구 실행을 승인하시겠습니까?\n\n{tool_info}",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )

        return reply == QMessageBox.Yes

    async def on_response_finished(self, result: dict):
        """응답 처리 (콘솔 출력 포함)"""
        current = await self.graph.aget_state(self.config)
        current_vals = current.values if current.values else {}

        answer = ""
        if result and result.get("messages"):
            for msg in reversed(result["messages"]):
                if isinstance(msg, AIMessage) and msg.content:
                    try:
                        json_match = re.search(r'\{[^{}]*"답변"[^{}]*\}', msg.content)
                        if json_match:
                            response_data = json.loads(json_match.group())
                            answer = response_data.get("답변", msg.content)

                            # 호감도 변화
                            affinity_change = response_data.get("호감도변화", 0)
                            if affinity_change:
                                current_intimacy = current_vals.get("intimacy_level", 0)
                                new_intimacy = max(0, min(100, current_intimacy + affinity_change))
                                await self.graph.aupdate_state(
                                    self.config,
                                    {"intimacy_level": new_intimacy}
                                )
                                print(f"   친밀도: {current_intimacy} -> {new_intimacy}")

                            # 닉네임 변화
                            new_nickname = response_data.get("nickname", "")
                            current_profile = current_vals.get("user_profile", self.user_profile)
                            if new_nickname and new_nickname != current_profile.get("nickname", ""):
                                current_profile = {**current_profile, "nickname": new_nickname}
                                await self.graph.aupdate_state(
                                    self.config,
                                    {"user_profile": current_profile}
                                )
                                print(f"   닉네임 설정: '{new_nickname}'")

                            # 관계 타입 변화
                            new_relation = response_data.get("relation", "")
                            if new_relation and new_relation != current_profile.get("relation_type", ""):
                                current_profile = {**current_profile, "relation_type": new_relation}
                                await self.graph.aupdate_state(
                                    self.config,
                                    {"user_profile": current_profile}
                                )
                                print(f"   관계 타입: '{new_relation}'")

                            # 감정 상태
                            new_emotion = response_data.get("감정", "")
                            if new_emotion:
                                await self.graph.aupdate_state(
                                    self.config,
                                    {"current_emotion": new_emotion}
                                )
                                print(f"   감정: '{new_emotion}'")

                            print(answer)
                            detected_emotion = result.get("current_emotion", "basic")
                            self.owner.start_emotion_animation(detected_emotion)

                        else:
                            if not msg.tool_calls:
                                answer = msg.content
                                print(f"\nAI: {answer}")
                    except (json.JSONDecodeError, Exception) as e:
                        if not msg.tool_calls:
                            answer = msg.content
                            print(f"\nAI: {answer}")
                    break

        if not answer:
            answer = "(응답 없음)"

        # UI 업데이트
        escaped_answer = answer.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('\n', '<br>')
        self.current_response_html += escaped_answer + "<br><br>"
        self.chat_history.setHtml(self.current_response_html)
        self.chat_history.verticalScrollBar().setValue(
            self.chat_history.verticalScrollBar().maximum()
        )

        # 메타데이터 출력
        metadata = result.get("context_metadata", {})
        if metadata.get("memories_found", 0) > 0:
            print(f"   ({metadata['memories_found']}개의 관련 기억 활용됨)")

        emotion = result.get("current_emotion", "")
        if emotion:
            print(f"   [Analyzer] 현재 감정: {emotion}")

        # 입력 필드 재활성화
        self.input_field.setEnabled(True)
        self.send_btn.setEnabled(True)
        self.input_field.setFocus()
        self.is_processing = False

    def on_error(self, error_msg: str):
        print(f"[ERROR] {error_msg}")

        error_html = self.current_response_html + f"<span style='color: red;'>[오류: {error_msg}]</span><br><br>"
        self.chat_history.setHtml(error_html)

        self.input_field.setEnabled(True)
        self.send_btn.setEnabled(True)
        self.input_field.setFocus()
        self.is_processing = False

        self.owner.stop_animation()

    def closeEvent(self, event):
        self.owner.start_emotion_animation("basic")
        event.accept()


# ============================================================
# SetWindow - Settings UI
# ============================================================

class SetWindow(QWidget):
    def __init__(self, owner, parent=None):
        super().__init__(parent)
        self.owner = owner

        self.setWindowFlags(Qt.Window | Qt.WindowStaysOnTopHint)
        self.setWindowTitle("ENE 환경설정")
        self.resize(300, 150)

        layout = QVBoxLayout(self)

        char_label = QLabel("캐릭터 선택:")
        layout.addWidget(char_label)

        self.char_combo = QComboBox()
        self.char_combo.addItem("아야", "aya")
        self.char_combo.addItem("마리사", "marisa")
        self.char_combo.addItem("코이시", "koishi")
        self.char_combo.addItem("치르노", "cirno")

        current_index = self.char_combo.findData(self.owner.current_character)
        if current_index >= 0:
            self.char_combo.setCurrentIndex(current_index)

        layout.addWidget(self.char_combo)

        close_btn = QPushButton("설정 완료")
        close_btn.clicked.connect(self.apply_and_close)
        layout.addWidget(close_btn)

    def apply_and_close(self):
        selected_char = self.char_combo.currentData()

        if selected_char != self.owner.current_character:
            self.owner.current_character = selected_char
            self.owner.load_assets()
            self.owner.save_character_preference()

        self.close()


# ============================================================
# ENE - Main Desktop Widget
# ============================================================

class ENE(QWidget):
    def __init__(self, graph, config):
        super().__init__()
        self.graph = graph
        self.config = config

        self.init_window_settings()
        self.base_dir = pathlib.Path(__file__).parent.resolve()
        self.asset_path = Path("assets")
        self.current_character = "koishi"
        self.character_pref_file = Path("character_preference.txt")

        self.current_frame = 0
        self.repeat_count = 0
        self.is_dragging = False
        self.drag_position = QPoint()
        self.chat_window = None
        self.settings_window = None

        self.is_animating = False
        self.animation_timer = QTimer(self)
        self.animation_timer.timeout.connect(self.update_animation)

        self.img_label = QLabel(self)
        self.img_label.setAlignment(Qt.AlignCenter)
        self.frames = {"idle": None, "happy": [], "sad": [], "angry": [], "pouting": [], "love": [], "busy": [], "basic": []}

        self.load_character_preference()
        self.load_assets()
        self.init_position()

    def load_character_preference(self):
        if self.character_pref_file.exists():
            try:
                with open(self.character_pref_file, "r", encoding="utf-8") as f:
                    self.current_character = f.read().strip() or "koishi"
            except Exception as e:
                print(f"[ERROR] Failed to load character preference: {e}")
                self.current_character = "koishi"

    def save_character_preference(self):
        try:
            with open(self.character_pref_file, "w", encoding="utf-8") as f:
                f.write(self.current_character)
        except Exception as e:
            print(f"[ERROR] Failed to save character preference: {e}")

    def open_settings(self):
        if self.settings_window is None:
            self.settings_window = SetWindow(owner=self)
        else:
            self.settings_window.close()
            self.settings_window = SetWindow(owner=self)

        screen_geo = QApplication.primaryScreen().availableGeometry()
        center_point = screen_geo.center()

        self.settings_window.move(
            center_point.x() - self.settings_window.width() // 2,
            center_point.y() - self.settings_window.height() // 2
        )

        self.settings_window.show()
        self.settings_window.activateWindow()

    def init_window_settings(self):
        flags = Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
        if platform.system() == 'Darwin':
            flags |= Qt.NoDropShadowWindowHint
        self.setWindowFlags(flags)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setMouseTracking(True)
        self.setContentsMargins(0, 0, 0, 0)

    def load_assets(self):
        emo_list = ["happy", "sad", "angry", "pouting", "love", "busy", "basic"]
        try:
            self.frames = {"idle": None, "happy": [], "sad": [], "angry": [], "pouting": [], "love": [], "busy": [], "basic": []}

            idle_path = self.base_dir / self.asset_path / self.current_character / "basic" / "frame_000.png"
            if idle_path.exists():
                pix = QPixmap(str(idle_path))
                if not pix.isNull():
                    pix = pix.scaled(pix.width() // 2, pix.height() // 2,
                                     Qt.KeepAspectRatio, Qt.SmoothTransformation)
                    self.frames["idle"] = pix
                else:
                    raise FileNotFoundError(f"Failed to load idle: {idle_path}")
            else:
                raise FileNotFoundError(f"{idle_path} not found")

            for emo in emo_list:
                for i in range(16):
                    frame_path = self.base_dir / self.asset_path / self.current_character / emo / f"frame_{i:03d}.png"
                    if frame_path.exists():
                        pix = QPixmap(str(frame_path))
                        if not pix.isNull():
                            pix = pix.scaled(pix.width() // 2, pix.height() // 2,
                                             Qt.KeepAspectRatio, Qt.SmoothTransformation)
                            self.frames[emo].append(pix)

            if self.frames["idle"]:
                self.img_label.setPixmap(self.frames["idle"])
                pix_size = self.img_label.pixmap().size()
                self.resize(pix_size.width() + 30, pix_size.height() + 30)
                self.img_label.resize(self.size())

            print(f"[DEBUG] Assets loaded for {self.current_character}")
        except Exception as e:
            print(f"Error loading assets: {e}")
            self.img_label.setText("ENE Resource Error")

    def init_position(self):
        screen = QApplication.primaryScreen().availableGeometry()
        center_x = screen.width() // 2
        center_y = screen.height() - self.height() // 2 - 50
        self.move(center_x - self.width() // 2, center_y - self.height() // 2)

    def start_emotion_animation(self, emotion_text):
        self.repeat_count = 0
        try:
            target_emotion = emotion_text
            if target_emotion in self.frames and self.frames[target_emotion]:
                self.is_animating = True
                self.current_frame = 0
                self.current_emotion_target = target_emotion
                self.animation_timer.start(175)
        except:
            target_emotion = "basic"
            if target_emotion in self.frames and self.frames[target_emotion]:
                self.is_animating = True
                self.current_frame = 0
                self.current_emotion_target = target_emotion
                self.animation_timer.start(175)

    def update_animation(self):
        target = getattr(self, "current_emotion_target", "basic")
        frames = self.frames.get(target, [])

        if not frames:
            return

        self.current_frame = (self.current_frame + 1) % len(frames)
        self.img_label.setPixmap(frames[self.current_frame])
        next_frame = self.current_frame + 1

        if next_frame < len(frames):
            self.current_frame = next_frame
        else:
            if target == "busy" or target == "basic":
                self.current_frame = 0
            else:
                self.repeat_count += 1

                if self.repeat_count < 3:
                    self.current_frame = 0
                else:
                    self.start_emotion_animation("basic")

    def stop_animation(self):
        if self.is_animating:
            self.animation_timer.stop()
            self.is_animating = False
            self.current_frame = 0
            if self.frames["idle"]:
                self.img_label.setPixmap(self.frames["idle"])

    def open_chat_interface(self):
        if self.chat_window is None:
            self.chat_window = ChatWindow(owner=self, graph=self.graph, config=self.config)

        screen = QApplication.primaryScreen().availableGeometry()

        ene_center_x = self.pos().x() + self.width() // 2
        chat_x = ene_center_x - self.chat_window.width() // 2
        chat_y = self.pos().y() - self.chat_window.height() - 20

        if chat_x < screen.left():
            chat_x = screen.left()
        elif chat_x + self.chat_window.width() > screen.right():
            chat_x = screen.right() - self.chat_window.width()

        if chat_y < screen.top():
            chat_y = self.pos().y() + self.height() + 20
            if chat_y + self.chat_window.height() > screen.bottom():
                chat_y = screen.top()

        self.chat_window.move(chat_x, chat_y)
        self.chat_window.show()
        self.chat_window.activateWindow()
        self.chat_window.input_field.setFocus()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.is_dragging = True
            center = self.pos() + QPoint(self.width() // 2, self.height() // 2)
            self.drag_position = event.globalPosition().toPoint() - center
            event.accept()

    def mouseMoveEvent(self, event):
        if self.is_dragging and event.buttons() == Qt.LeftButton:
            center = event.globalPosition().toPoint() - self.drag_position
            self.move(center.x() - self.width() // 2, center.y() - self.height() // 2)
            event.accept()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.is_dragging = False
            event.accept()

    def contextMenuEvent(self, event):
        chat_visible = self.chat_window is not None and self.chat_window.isVisible()
        settings_visible = self.settings_window is not None and self.settings_window.isVisible()

        if chat_visible or settings_visible:
            return

        menu = QMenu(self)
        chat_act = menu.addAction("대화하기")
        set_act = menu.addAction("환경설정")
        quit_act = menu.addAction("ENE 보내주기 (종료)")

        action = menu.exec(event.globalPos())

        if action == chat_act:
            self.open_chat_interface()
        elif action == set_act:
            self.open_settings()
        elif action == quit_act:
            if self.chat_window:
                self.chat_window.close()
            if self.settings_window:
                self.settings_window.close()
            self.close()
            os._exit(0)


# ============================================================
# Main Entry Point
# ============================================================

async def async_main(app, loop):
    print("\n" + "=" * 60)
    print("  ENE Desktop with Clova MCP Agent v3")
    print("  PySide6 GUI + LangGraph + AsyncSqliteSaver")
    print("=" * 60 + "\n")

    try:
        import aiosqlite
        print("[Init] aiosqlite found")
    except ImportError:
        print("[ERROR] aiosqlite not found.")
        print("Please run: pip install aiosqlite")
        return

    async with AsyncSqliteSaver.from_conn_string("persona_mcp_v3.sqlite") as checkpointer:
        try:
            graph = await create_agent_graph(checkpointer)

            thread_id = get_last_thread_id()
            save_last_thread_id(thread_id)

            config = {
                "recursion_limit": 25,
                "configurable": {
                    "thread_id": thread_id
                }
            }

            print(f"[Init] Session thread ID: {thread_id}")
            print(f"[Init] Database: persona_mcp_v3.sqlite (shared with CLI)\n")

            ene = ENE(graph=graph, config=config)
            ene.show()

            while True:
                await asyncio.sleep(0.1)
                if not app.topLevelWidgets():
                    break

        except Exception as e:
            print(f"[ERROR] Failed to initialize: {e}")
            import traceback
            traceback.print_exc()


def main():
    app = QApplication.instance() or QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    app.setApplicationName("ENE Desktop with Clova Agent")

    loop = QEventLoop(app)
    asyncio.set_event_loop(loop)

    with loop:
        loop.run_until_complete(async_main(app, loop))


if __name__ == "__main__":
    main()
