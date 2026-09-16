"""CD 实时播放引擎:后台线程读扇区 -> PortAudio(RawOutputStream) 输出。"""
from __future__ import annotations

import queue
import threading
import time
from array import array

from PySide6.QtCore import QObject, Signal

from ..cdrom.base import DiscError, DiscSource, TrackInfo

try:
    import sounddevice as _sd
    SD_AVAILABLE = True
except Exception:
    _sd = None
    SD_AVAILABLE = False

SECTOR_BYTES = 2352
CHUNK_SECTORS = 32            # 每次读 32 扇区 ≈ 0.43 秒
QUEUE_ITEMS = 8               # 读线程与音频回调之间的缓冲

STATE_PLAYING, STATE_PAUSED, STATE_STOPPED = "playing", "paused", "stopped"


class CDPlayer(QObject):
    positionChanged = Signal(int, float)   # (音轨号, 已播秒数)
    stateChanged = Signal(str)
    trackFinished = Signal(int)
    errorOccurred = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self._stream = None
        self._reader: threading.Thread | None = None
        self._q: queue.Queue = queue.Queue(maxsize=QUEUE_ITEMS)
        self._buf = bytearray()
        self._buf_lba = 0.0            # 下一个待播放字节对应的 LBA
        self._start_lba = 0
        self._lock = threading.Lock()
        self._stop_evt = threading.Event()
        self._pause_evt = threading.Event()
        self._sentinel = object()
        self._volume = 0.85
        self._track_no = 0
        self._track_title = ""
        self._state = STATE_STOPPED
        self._last_emit = 0.0
        self._ended_reported = False

    # ---------------- 属性 ----------------
    @staticmethod
    def is_supported() -> bool:
        return SD_AVAILABLE

    @property
    def state(self) -> str:
        return self._state

    @property
    def current_track(self) -> int:
        return self._track_no

    @property
    def track_title(self) -> str:
        return self._track_title

    def set_volume(self, v: float) -> None:
        self._volume = max(0.0, min(1.0, v))

    # ---------------- 控制 ----------------
    def play(self, drive: DiscSource, track: TrackInfo, title: str = "") -> None:
        self.stop()
        if not SD_AVAILABLE:
            self.errorOccurred.emit("当前环境没有可用的音频输出组件")
            return
        self._track_no = track.number
        self._track_title = title or track.title or f"第 {track.number} 轨"
        self._start_lba = track.start_lba
        self._buf = bytearray()
        self._buf_lba = float(track.start_lba)
        self._ended_reported = False
        self._start_reader(drive, track.start_lba, track.end_lba)
        self._open_stream()
        self._set_state(STATE_PLAYING)

    def pause(self) -> None:
        if self._state != STATE_PLAYING:
            return
        self._pause_evt.set()
        if self._stream:
            try:
                self._stream.stop()
            except Exception:
                pass
        self._set_state(STATE_PAUSED)

    def resume(self) -> None:
        if self._state != STATE_PAUSED:
            return
        self._pause_evt.clear()
        if self._stream:
            try:
                self._stream.start()
            except Exception:
                pass
        self._set_state(STATE_PLAYING)

    def toggle(self) -> None:
        if self._state == STATE_PLAYING:
            self.pause()
        elif self._state == STATE_PAUSED:
            self.resume()

    def stop(self) -> None:
        self._stop_evt.set()
        self._pause_evt.clear()
        if self._reader and self._reader.is_alive():
            self._reader.join(timeout=1.5)
        self._reader = None
        self._close_stream()
        with self._lock:
            self._buf = bytearray()
            self._drain_queue()
        self._set_state(STATE_STOPPED)

    def seek(self, seconds: float, drive: DiscSource, track: TrackInfo) -> None:
        """在当前播放的轨内跳转(播放或暂停状态下有效)。"""
        if self._state not in (STATE_PLAYING, STATE_PAUSED) or self._track_no != track.number:
            return
        target = track.start_lba + max(0, int(seconds * 75))
        target = min(target, max(track.start_lba, track.end_lba - 1))
        self._stop_evt.set()
        if self._reader and self._reader.is_alive():
            self._reader.join(timeout=1.5)
        with self._lock:
            self._buf = bytearray()
            self._drain_queue()
        self._buf_lba = float(target)
        self._ended_reported = False
        self._start_reader(drive, target, track.end_lba)
        # _start_reader 会创建全新(未设置)的 stop/pause 事件;
        # 若此前处于暂停,保持暂停语义(流仍是停止的,恢复时再 start)
        if self._state == STATE_PLAYING and self._stream:
            try:
                self._stream.start()
            except Exception:
                pass

    # ---------------- 内部 ----------------
    def _drain_queue(self) -> None:
        try:
            while True:
                self._q.get_nowait()
        except queue.Empty:
            pass

    def _start_reader(self, drive: DiscSource, start: int, end: int) -> None:
        self._stop_evt = threading.Event()
        self._pause_evt = threading.Event()
        stop_evt, pause_evt = self._stop_evt, self._pause_evt

        def reader() -> None:
            pos = start
            while not stop_evt.is_set():
                pause_evt.wait()
                if stop_evt.is_set():
                    break
                n = min(CHUNK_SECTORS, end - pos)
                if n <= 0:
                    self._offer(self._sentinel)
                    break
                try:
                    data = drive.read_sectors(pos, n)
                except DiscError as e:
                    self.errorOccurred.emit(f"读取光盘失败:{e}")
                    self._offer(self._sentinel)
                    break
                if not self._offer((pos, data)):
                    break
                pos += n

        self._reader = threading.Thread(target=reader, name="cd-reader", daemon=True)
        self._reader.start()

    def _offer(self, item) -> bool:
        """向队列投放,最多等待 2 秒;停止时放弃。"""
        deadline = time.monotonic() + 2.0
        while not self._stop_evt.is_set():
            try:
                self._q.put(item, timeout=0.1)
                return True
            except queue.Full:
                if time.monotonic() > deadline:
                    return False
        return False

    def _open_stream(self) -> None:
        self._close_stream()
        try:
            self._stream = _sd.RawOutputStream(
                samplerate=44100, channels=2, dtype="int16",
                callback=self._on_audio, blocksize=0)
            self._stream.start()
        except Exception as e:
            self._stream = None
            self.errorOccurred.emit(f"无法打开音频输出:{e}")

    def _close_stream(self) -> None:
        if self._stream is not None:
            try:
                self._stream.close()
            except Exception:
                pass
            self._stream = None

    def _set_state(self, s: str) -> None:
        if s != self._state:
            self._state = s
            self.stateChanged.emit(s)

    # ---------------- 音频回调(PortAudio 线程) ----------------
    def _on_audio(self, out_data, frames: int, _time, _status):
        need = frames * 4                     # int16 立体声 = 每帧 4 字节
        ended = False
        with self._lock:
            while len(self._buf) < need and not ended:
                try:
                    item = self._q.get_nowait()
                except queue.Empty:
                    break
                if item is self._sentinel:
                    ended = True
                    break
                lba, data = item
                if not self._buf:
                    self._buf_lba = float(lba)
                self._buf += data
            have = min(need, len(self._buf))
            seg = bytes(self._buf[:have])
            del self._buf[:have]
            if have:
                self._buf_lba += have / SECTOR_BYTES
            pos = max(0.0, (self._buf_lba - self._start_lba) / 75.0)
            finish = ended and have == 0 and not self._ended_reported
            if finish:
                self._ended_reported = True

        self._fill(out_data, seg, self._volume)
        now = time.monotonic()
        if now - self._last_emit > 0.25:
            self._last_emit = now
            self.positionChanged.emit(self._track_no, pos)
        if finish:
            self.trackFinished.emit(self._track_no)
            return _sd.CallbackStop
        return None

    @staticmethod
    def _fill(out_data, pcm: bytes, vol: float) -> None:
        target = len(out_data)
        if len(pcm) < target:
            pcm += b"\x00" * (target - len(pcm))
        if vol >= 0.999:
            out_data[:] = pcm
            return
        a = array("h", pcm)
        v = int(vol * 32768)
        for i in range(len(a)):
            a[i] = (a[i] * v) >> 15
        out_data[:] = a.tobytes()
