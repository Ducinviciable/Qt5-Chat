import os
import tempfile
import threading
import time
import wave

try:
    import pyaudio
    PYAUDIO_AVAILABLE = True
except ImportError:
    PYAUDIO_AVAILABLE = False

"""Handle audio recording using PyAudio."""
class AudioRecorder:


    def __init__(self, filename=None):
        if not PYAUDIO_AVAILABLE:
            raise RuntimeError("PyAudio not available. Please install with: pip install pyaudio")

        self.filename = filename
        self.chunk = 1024
        self.format = pyaudio.paInt16
        self.channels = 1
        self.rate = 44100
        self.is_recording = False
        self.frames = []
        self.p = None
        self.stream = None
        self._record_thread = None

    def _init_pyaudio(self):
        if self.p is None:
            self.p = pyaudio.PyAudio()

    def start_recording(self):
        if not PYAUDIO_AVAILABLE:
            raise RuntimeError("PyAudio not available")

        if self.is_recording:
            return

        self._init_pyaudio()
        self.is_recording = True
        self.frames = []

        try:
            self.stream = self.p.open(
                format=self.format,
                channels=self.channels,
                rate=self.rate,
                input=True,
                frames_per_buffer=self.chunk,
            )
            self._record_thread = threading.Thread(target=self._record_loop, daemon=True)
            self._record_thread.start()
        except Exception as exc:
            self.is_recording = False
            raise RuntimeError(f"Failed to start recording: {exc}") from exc

    def _record_loop(self):
        while self.is_recording:
            try:
                if self.stream is None:
                    break
                data = self.stream.read(self.chunk, exception_on_overflow=False)
                self.frames.append(data)
            except Exception:
                break

    def stop_recording(self):
        if not self.is_recording:
            return None

        self.is_recording = False

        if self._record_thread and self._record_thread.is_alive():
            self._record_thread.join(timeout=1.0)

        try:
            if self.stream is not None:
                self.stream.stop_stream()
                self.stream.close()
                self.stream = None
        except Exception:
            pass

        min_frames = int(0.5 * self.rate / self.chunk)
        if len(self.frames) < min_frames:
            return None

        if not self.filename:
            temp_dir = tempfile.gettempdir()
            self.filename = os.path.join(temp_dir, f"voice_{int(time.time() * 1000)}.wav")

        try:
            with wave.open(self.filename, "wb") as wf:
                wf.setnchannels(self.channels)
                wf.setsampwidth(self.p.get_sample_size(self.format))
                wf.setframerate(self.rate)
                wf.writeframes(b"".join(self.frames))
            return self.filename
        except Exception:
            return None

    def cleanup(self):
        try:
            if self.stream is not None:
                self.stream.stop_stream()
                self.stream.close()
                self.stream = None
        except Exception:
            pass

        try:
            if self.p is not None:
                self.p.terminate()
                self.p = None
        except Exception:
            pass


