import os
import hashlib
import tempfile
import requests
from PyQt5.QtCore import QObject, QUrl, QThread, pyqtSignal
from PyQt5.QtMultimedia import QMediaPlayer, QMediaContent
from PyQt5.QtWidgets import QMessageBox
from PyQt5.QtGui import QDesktopServices


class DownloadWorker(QThread):
    finished = pyqtSignal(str)  # Emit local file path khi xong
    error = pyqtSignal(str, bool)  # Emit error message và is_file_not_found flag

    def __init__(self, audio_url, cache_dir):
        super().__init__()
        self.audio_url = audio_url
        self.cache_dir = cache_dir

    def run(self):
        try:
            # Tạo cache key từ URL
            url_hash = hashlib.md5(self.audio_url.encode()).hexdigest()
            cache_file = os.path.join(self.cache_dir, f"voice_{url_hash}.wav")
            
            # Kiểm tra cache
            if os.path.exists(cache_file):
                self.finished.emit(cache_file)
                return
            
            # Download file
            response = requests.get(self.audio_url, timeout=30, stream=True)
            
            if response.status_code == 404:
                self.error.emit("File đã bị xóa hoặc không tồn tại trên server", True)
                return
            
            response.raise_for_status()
            
            # Lưu vào cache
            os.makedirs(self.cache_dir, exist_ok=True)
            with open(cache_file, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
            
            self.finished.emit(cache_file)
        except requests.exceptions.HTTPError as e:
            # Kiểm tra nếu là lỗi 404
            if hasattr(e.response, 'status_code') and e.response.status_code == 404:
                self.error.emit("File đã bị xóa hoặc không tồn tại trên server", True)
            else:
                self.error.emit(f"Không thể tải file: {str(e)}", False)
        except Exception as e:
            self.error.emit(f"Không thể tải file: {str(e)}", False)


class VoicePlayer(QObject):

    def __init__(self, parent=None):
        super().__init__(parent)
        self._parent = parent
        self._player = QMediaPlayer()
        self._current_widget = None
        self._current_url = None
        self._current_local_file = None
        self._download_worker = None
        
        # Tạo cache directory
        self._cache_dir = os.path.join(tempfile.gettempdir(), "ltm_ck_voice_cache")
        os.makedirs(self._cache_dir, exist_ok=True)

        self._player.positionChanged.connect(self._on_position_changed)
        self._player.durationChanged.connect(self._on_duration_changed)
        self._player.stateChanged.connect(self._on_state_changed)
        self._player.error.connect(self._on_player_error)

    def toggle_play_pause(self, audio_url, widget, btn_play_pause):
        try:
            if self._current_url and self._current_url != audio_url:
                self._reset_widget(self._current_widget)
                self._player.stop()
                self._current_local_file = None

            if (
                self._player.state() == QMediaPlayer.PlayingState
                and self._current_url == audio_url
            ):
                self._player.pause()
                btn_play_pause.setText("▶")
                return

            if (
                self._player.state() == QMediaPlayer.PausedState
                and self._current_url == audio_url
            ):
                self._player.play()
                btn_play_pause.setText("⏸")
                return

            # Start new playback
            self._current_url = audio_url
            self._current_widget = widget
            media_content = QMediaContent(QUrl(audio_url))
            self._player.setMedia(media_content)
            self._player.play()
            btn_play_pause.setText("⏸")

        except Exception as exc:
            # Nếu có lỗi ngay từ đầu, thử download
            self._download_and_play(audio_url, widget, btn_play_pause)

    def seek(self, widget, position):
        """Seek to position for active widget."""
        if widget is not None and widget == self._current_widget:
            self._player.setPosition(position)

    def stop(self):
        """Stop playback and reset widget state."""
        self._player.stop()
        self._reset_widget(self._current_widget)
        self._current_widget = None
        self._current_url = None
        self._current_local_file = None
        
        # Hủy download worker nếu đang chạy
        if self._download_worker and self._download_worker.isRunning():
            self._download_worker.terminate()
            self._download_worker.wait()
            self._download_worker = None

    def _on_position_changed(self, position):
        widget = self._current_widget
        if not widget:
            return
        slider = widget.property('progress_slider')
        time_label = widget.property('time_label')

        if slider:
            slider.blockSignals(True)
            slider.setValue(position)
            slider.blockSignals(False)

        if time_label:
            duration = self._player.duration()
            time_label.setText(f"{self._format_time(position)} / {self._format_time(duration)}")

    def _on_duration_changed(self, duration):
        widget = self._current_widget
        if not widget:
            return
        slider = widget.property('progress_slider')
        time_label = widget.property('time_label')

        if slider:
            slider.setRange(0, duration if duration > 0 else 0)

        if time_label and duration > 0:
            time_label.setText(f"00:00 / {self._format_time(duration)}")

    def _on_state_changed(self, state):
        widget = self._current_widget
        if not widget:
            return

        btn_play_pause = widget.property('btn_play_pause')
        slider = widget.property('progress_slider')
        time_label = widget.property('time_label')

        if state == QMediaPlayer.PlayingState:
            if btn_play_pause:
                btn_play_pause.setText("⏸")
        elif state == QMediaPlayer.PausedState:
            if btn_play_pause:
                btn_play_pause.setText("▶")
        elif state == QMediaPlayer.StoppedState:
            if btn_play_pause:
                btn_play_pause.setText("▶")
            if slider:
                slider.blockSignals(True)
                slider.setValue(0)
                slider.blockSignals(False)
            if time_label:
                duration = self._player.duration()
                time_label.setText(f"00:00 / {self._format_time(duration)}")

    def _reset_widget(self, widget):
        if not widget:
            return
        btn_play_pause = widget.property('btn_play_pause')
        slider = widget.property('progress_slider')
        time_label = widget.property('time_label')

        if btn_play_pause:
            btn_play_pause.setText("▶")
        if slider:
            slider.blockSignals(True)
            slider.setValue(0)
            slider.blockSignals(False)
        if time_label:
            duration = self._player.duration()
            time_label.setText(f"00:00 / {self._format_time(duration)}")

    def _on_player_error(self, error):
        """Xử lý lỗi từ QMediaPlayer."""
        # Lấy error string từ player
        error_string = self._player.errorString()
        error_msg = error_string if error_string else f"Media player error code: {error}"
        print(f"[VoicePlayer] Error: {error_msg} (code: {error})")
        
        # Nếu đang phát từ URL và gặp lỗi, thử download về local
        if self._current_url and not self._current_local_file:
            widget = self._current_widget
            if widget:
                btn_play_pause = widget.property('btn_play_pause')
                if btn_play_pause:
                    btn_play_pause.setText("⏳")
                    btn_play_pause.setEnabled(False)
                
                # Download và phát từ local
                self._download_and_play(self._current_url, widget, btn_play_pause)
        else:
            # Nếu đã phát từ local mà vẫn lỗi (codec không hỗ trợ)
            widget = self._current_widget
            if widget:
                btn_play_pause = widget.property('btn_play_pause')
                if btn_play_pause:
                    btn_play_pause.setText("▶")
                    btn_play_pause.setEnabled(True)
            
            # Hiển thị thông báo và cho phép mở bằng ứng dụng khác
            if self._parent:
                from PyQt5.QtWidgets import QMessageBox
                reply = QMessageBox.question(
                    self._parent,
                    "Không thể phát audio",
                    f"Trình phát media không hỗ trợ định dạng này.\n\n"
                    f"Lỗi: {error_msg}\n\n"
                    f"Bạn có muốn mở file bằng ứng dụng mặc định không?",
                    QMessageBox.Yes | QMessageBox.No,
                    QMessageBox.Yes
                )
                
                if reply == QMessageBox.Yes:
                    # Mở file bằng ứng dụng mặc định
                    if self._current_local_file and os.path.exists(self._current_local_file):
                        try:
                            QDesktopServices.openUrl(QUrl.fromLocalFile(self._current_local_file))
                        except Exception as e:
                            print(f"[VoicePlayer] Error opening file: {e}")
                    elif self._current_url:
                        try:
                            QDesktopServices.openUrl(QUrl(self._current_url))
                        except Exception as e:
                            print(f"[VoicePlayer] Error opening URL: {e}")
            
            self._reset_widget(self._current_widget)

    def _download_and_play(self, audio_url, widget, btn_play_pause):
        if self._download_worker and self._download_worker.isRunning():
            return

        self._download_worker = DownloadWorker(audio_url, self._cache_dir)
        self._download_worker.finished.connect(
            lambda local_file: self._play_from_local_file(local_file, widget, btn_play_pause)
        )
        self._download_worker.error.connect(
            lambda error_msg, is_file_not_found: self._on_download_error(error_msg, is_file_not_found, widget, btn_play_pause)
        )
        self._download_worker.start()

    def _play_from_local_file(self, local_file, widget, btn_play_pause):
        try:
            self._current_local_file = local_file
            media_content = QMediaContent(QUrl.fromLocalFile(local_file))
            self._player.setMedia(media_content)
            self._player.play()
            if btn_play_pause:
                btn_play_pause.setText("⏸")
                btn_play_pause.setEnabled(True)
        except Exception as e:
            print(f"[VoicePlayer] Error playing local file: {e}")
            if btn_play_pause:
                btn_play_pause.setText("▶")
                btn_play_pause.setEnabled(True)
            # Nếu không phát được, cho phép mở bằng ứng dụng khác
            if self._parent:
                from PyQt5.QtWidgets import QMessageBox
                reply = QMessageBox.question(
                    self._parent,
                    "Không thể phát audio",
                    f"Không thể phát file audio.\n\n"
                    f"Lỗi: {str(e)}\n\n"
                    f"Bạn có muốn mở file bằng ứng dụng mặc định không?",
                    QMessageBox.Yes | QMessageBox.No,
                    QMessageBox.Yes
                )
                
                if reply == QMessageBox.Yes and os.path.exists(local_file):
                    try:
                        QDesktopServices.openUrl(QUrl.fromLocalFile(local_file))
                    except Exception as ex:
                        print(f"[VoicePlayer] Error opening file: {ex}")

    def _on_download_error(self, error_msg, is_file_not_found, widget, btn_play_pause):
        """Xử lý lỗi khi download."""
        print(f"[VoicePlayer] Download error: {error_msg} (file_not_found: {is_file_not_found})")
        
        # Nếu file không tồn tại, xóa widget khỏi UI
        if is_file_not_found and widget:
            # Lấy callback xóa widget từ property
            remove_widget_cb = widget.property('remove_widget_cb')
            if remove_widget_cb:
                try:
                    remove_widget_cb()
                    print(f"[VoicePlayer] Đã xóa widget voice message vì file không tồn tại")
                    return
                except Exception as e:
                    print(f"[VoicePlayer] Lỗi khi xóa widget: {e}")
        
        # Cập nhật widget để hiển thị trạng thái lỗi (nếu không xóa được)
        if widget:
            time_label = widget.property('time_label')
            if time_label:
                if is_file_not_found:
                    time_label.setText("⚠️ File đã bị xóa")
                    time_label.setStyleSheet("color: #f44336; font-weight: bold;")
                else:
                    time_label.setText("⚠️ Lỗi tải file")
                    time_label.setStyleSheet("color: #ff9800; font-weight: bold;")
            
            # Disable nút play nếu file không tồn tại
            if btn_play_pause:
                if is_file_not_found:
                    btn_play_pause.setText("❌")
                    btn_play_pause.setEnabled(False)
                    btn_play_pause.setToolTip("File đã bị xóa hoặc không tồn tại")
                    btn_play_pause.setStyleSheet("""
                        QPushButton {
                            background-color: #f44336;
                            color: white;
                            border: none;
                            border-radius: 18px;
                            font-size: 14px;
                            font-weight: bold;
                        }
                    """)
                else:
                    btn_play_pause.setText("▶")
                    btn_play_pause.setEnabled(True)
            
            # Đánh dấu widget là có lỗi
            widget.setProperty('file_not_found', is_file_not_found)
            widget.setProperty('has_error', True)
        
        # Hiển thị thông báo cho người dùng (chỉ khi không xóa được widget)
        if self._parent and not is_file_not_found:
            QMessageBox.warning(
                self._parent, 
                "Lỗi tải file", 
                f"{error_msg}\n\nThử mở trong trình duyệt?"
            )
            # Thử mở trong trình duyệt (chỉ khi không phải lỗi 404)
            try:
                if self._current_url:
                    QDesktopServices.openUrl(QUrl(self._current_url))
            except Exception:
                pass

    @staticmethod
    def _format_time(milliseconds):
        if milliseconds < 0:
            return "00:00"
        total_seconds = milliseconds // 1000
        minutes = total_seconds // 60
        seconds = total_seconds % 60
        return f"{minutes:02d}:{seconds:02d}"


