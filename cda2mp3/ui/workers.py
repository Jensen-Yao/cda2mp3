"""后台工作线程:批量抓轨编码。"""
from __future__ import annotations

import os
import time

from PySide6.QtCore import QThread, Signal

from ..audio.encoder import Mp3Encoder, sanitize_filename, write_id3_tags
from ..cdrom.base import DiscSource, TrackInfo

READ_CHUNK = 128        # 每轮读 128 扇区 ≈ 1.7 秒音频(约 300KB)


class RipWorker(QThread):
    trackStart = Signal(int)
    trackProgress = Signal(int, int)      # (轨道序号, 0-100)
    trackDone = Signal(int, str)          # (轨道序号, 输出路径)
    trackError = Signal(int, str)
    finishedAll = Signal(int, int, str)   # (成功数, 失败数, 输出目录)
    logLine = Signal(str)

    def __init__(self, drive: DiscSource, jobs: list[dict], out_dir: str, *,
                 bitrate: int, template: str, write_tags: bool,
                 album: str = "", artist: str = "", year: str = "", genre: str = "",
                 cover_image: str | None = None, track_total: int = 0):
        super().__init__()
        self._drive = drive
        self._jobs = jobs              # [{"track": TrackInfo, "title": str}]
        self._out_dir = out_dir
        self._bitrate = bitrate
        self._template = template
        self._write_tags = write_tags
        self._album = album
        self._artist = artist
        self._year = year
        self._genre = genre
        self._cover = cover_image
        self._track_total = track_total
        self._stop = False

    def stop(self) -> None:
        self._stop = True

    # ---------------- 主流程 ----------------
    def run(self) -> None:
        ok = fail = 0
        for idx, job in enumerate(self._jobs):
            if self._stop:
                break
            track: TrackInfo = job["track"]
            title = job.get("title") or f"Track {track.number:02d}"
            try:
                self.trackStart.emit(idx)
                path = self._rip_one(idx, track, title)
                ok += 1
                self.trackDone.emit(idx, path)
                self.logLine.emit(f"✓ {os.path.basename(path)}")
            except Exception as e:  # noqa: BLE001 —— 单轨失败不影响其余轨道
                fail += 1
                self.trackError.emit(idx, str(e))
                self.logLine.emit(f"✗ 第 {track.number} 轨失败:{e}")
        self.finishedAll.emit(ok, fail, self._out_dir)

    def _render_filename(self, track: TrackInfo, title: str) -> str:
        name = self._template.format(
            track=track.number,
            title=title,
            artist=self._artist or "未知艺术家",
            album=self._album or "未知专辑",
        )
        return sanitize_filename(name) + ".mp3"

    def _rip_one(self, idx: int, track: TrackInfo, title: str) -> str:
        os.makedirs(self._out_dir, exist_ok=True)
        out_path = os.path.join(self._out_dir, self._render_filename(track, title))
        total = track.length_lba
        started = time.monotonic()
        with Mp3Encoder(out_path, bitrate_kbps=self._bitrate) as enc:
            pos = track.start_lba
            end = track.end_lba
            while pos < end:
                if self._stop:
                    raise InterruptedError("已取消")
                n = min(READ_CHUNK, end - pos)
                data = self._drive.read_sectors(pos, n)
                enc.write(data)
                pos += n
                self.trackProgress.emit(idx, int((pos - track.start_lba) * 100 / max(1, total)))
        if self._write_tags:
            try:
                write_id3_tags(
                    out_path, title=title,
                    artist=track.artist or self._artist,
                    album=self._album,
                    track=track.number, track_total=self._track_total,
                    year=self._year, genre=self._genre,
                    cover_image=self._cover)
            except Exception as e:  # 标签失败不算抓轨失败
                self.logLine.emit(f"! 第 {track.number} 轨标签写入失败:{e}")
        secs = time.monotonic() - started
        speed = (total / 75.0) / secs if secs > 0 else 0
        self.logLine.emit(f"  用时 {secs:.1f}s(约 {speed:.1f}x 实时速度)")
        return out_path
