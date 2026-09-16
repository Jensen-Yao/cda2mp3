"""从镜像文件(WAV/BIN + CUE)构建的“虚拟光盘”。

用途:
  1. 无光驱环境下完整体验/演示 抓轨+播放 流程;
  2. 直接处理整轨 WAV/BIN 镜像(+CUE 分轨),把镜像里的音轨转成 MP3。
"""
from __future__ import annotations

import os
import re
import struct
from pathlib import Path

from .base import (
    DiscError,
    DiscSource,
    DiscTOC,
    TrackInfo,
    format_duration,
)


def _scan_wav(f) -> tuple[int, int]:
    """返回 (PCM 数据偏移, PCM 字节数),要求 44.1kHz/16bit/立体声。"""
    f.seek(0)
    head = f.read(12)
    if len(head) < 12 or head[:4] != b"RIFF" or head[8:12] != b"WAVE":
        raise DiscError("不是有效的 WAV 文件")
    fmt = None
    off = 12
    data_off = data_size = -1
    while True:
        f.seek(off)
        hdr = f.read(8)
        if len(hdr) < 8:
            break
        cid, size = hdr[:4], struct.unpack("<I", hdr[4:8])[0]
        if cid == b"fmt ":
            fmt = f.read(size)[:16]
        elif cid == b"data":
            data_off = off + 8
            data_size = size
            break
        off += 8 + size + (size & 1)
    if fmt is None or data_off < 0:
        raise DiscError("WAV 缺少 fmt/data 块")
    tag, ch, rate, _brate, _align, bits = struct.unpack("<HHIIHH", fmt)
    if tag != 1 or bits != 16:
        raise DiscError("仅支持 16bit PCM WAV")
    if rate != 44100 or ch != 2:
        raise DiscError("CD 音频必须是 44100Hz 立体声")
    if data_size < 0:
        f.seek(0, 2)
        data_size = f.tell() - data_off
    return data_off, data_size


class ImageDisc(DiscSource):
    """WAV/BIN(+可选 CUE)虚拟光盘。LBA 0 = 音频数据第 0 字节。"""

    def __init__(self, audio_path: str | os.PathLike, cue_path: str | os.PathLike | None = None):
        self.audio_path = Path(audio_path)
        self.cue_path = Path(cue_path) if cue_path else None
        ext = self.audio_path.suffix.lower()
        if ext == ".wav":
            with open(self.audio_path, "rb") as f:
                self._data_off, pcm_size = _scan_wav(f)
        elif ext in (".bin", ".img", ".raw"):
            self._data_off = 0
            pcm_size = self.audio_path.stat().st_size
        else:
            raise DiscError("不支持的镜像格式(请使用 WAV/BIN)")
        self.total_sectors = pcm_size // 2352
        if self.total_sectors < 75:
            raise DiscError("音频太短,不足 1 秒")

        album = artist = ""
        starts: list[tuple[int, int]] = []      # (track#, start_lba)
        titles: dict[int, str] = {}
        if self.cue_path:
            starts, album, artist, audio_ref, titles = self._parse_cue()
            if audio_ref and (self.audio_path.stem.lower() != Path(audio_ref).stem.lower()):
                # CUE 指定了别的文件则跟随
                candidate = self.cue_path.parent / audio_ref
                if candidate.is_file():
                    self.audio_path = candidate
                    with open(self.audio_path, "rb") as f:
                        self._data_off, pcm_size = _scan_wav(f)
                    self.total_sectors = pcm_size // 2352
        else:
            starts = [(1, 0)]

        if not starts:
            raise DiscError("CUE 中没有解析到音轨")
        tracks: list[TrackInfo] = []
        for i, (tno, start) in enumerate(starts):
            nxt = starts[i + 1][1] if i + 1 < len(starts) else self.total_sectors
            length = max(0, min(nxt, self.total_sectors) - start)
            if length <= 0:
                continue
            tracks.append(TrackInfo(number=tno, start_lba=start, length_lba=length,
                                    title=titles.get(tno, "")))
        self.name = self.audio_path.stem
        self._toc = DiscTOC(tracks=tracks,
                            leadout_lba=self.total_sectors,
                            album=album or self.audio_path.stem,
                            artist=artist)
        self._file = open(self.audio_path, "rb")

    # ---------- CUE ----------
    def _parse_cue(self):
        starts, album, artist = [], "", ""
        titles: dict[int, str] = {}
        audio_ref = ""
        cur_track = 0
        text = self.cue_path.read_bytes().decode("utf-8", "replace")
        if text.startswith("\ufeff"):
            text = text[1:]
        for line in text.splitlines():
            line = line.strip()
            if line.upper().startswith("FILE"):
                m = re.match(r'FILE\s+"([^"]+)"', line, re.I)
                if m and not audio_ref:
                    audio_ref = m.group(1)
            elif line.upper().startswith("TRACK"):
                m = re.match(r"TRACK\s+(\d+)\s+(\w+)", line, re.I)
                if m:
                    cur_track = int(m.group(1))
                    starts.append((cur_track, -1))
            elif line.upper().startswith("TITLE") and cur_track:
                titles[cur_track] = line.split("TITLE", 1)[1].strip().strip('"')
            elif line.upper().startswith("INDEX 01"):
                m = re.match(r"INDEX\s+01\s+(\d+):(\d+):(\d+)", line, re.I)
                if m and starts:
                    mm, ss, ff = map(int, m.groups())
                    if starts[-1][1] < 0:
                        starts[-1] = (starts[-1][0], (mm * 60 + ss) * 75 + ff)
            elif line.upper().startswith("REM TITLE"):
                album = line.split("REM TITLE", 1)[1].strip().strip('"')
            elif line.upper().startswith("REM PERFORMER"):
                artist = line.split("REM PERFORMER", 1)[1].strip().strip('"')
            elif line.upper().startswith("PERFORMER") and not artist:
                artist = line.split("PERFORMER", 1)[1].strip().strip('"')
            elif line.upper().startswith("TITLE") and not album:
                album = line.split("TITLE", 1)[1].strip().strip('"')
        starts = [(t, s) for t, s in starts if s >= 0]
        return starts, album, artist, audio_ref, titles

    # ---------- DiscSource ----------
    def get_toc(self) -> DiscTOC:
        return self._toc

    def read_sectors(self, lba: int, count: int) -> bytes:
        if lba < 0 or count < 0 or lba + count > self.total_sectors:
            raise DiscError(f"读取范围越界(LBA {lba}+{count})")
        self._file.seek(self._data_off + lba * 2352)
        data = self._file.read(count * 2352)
        if len(data) < count * 2352:
            raise DiscError("镜像数据不完整")
        return data

    def close(self) -> None:
        if self._file and not self._file.closed:
            self._file.close()


def _cue_audio_ref(cue_path: Path) -> str:
    """读取 CUE 里第一条 FILE 引用的音频文件名。"""
    try:
        text = cue_path.read_bytes().decode("utf-8", "replace")
    except OSError:
        return ""
    for line in text.splitlines():
        m = re.match(r'\s*FILE\s+"([^"]+)"', line.strip(), re.I)
        if m:
            return m.group(1)
    return ""


def open_image(path: str | os.PathLike) -> ImageDisc:
    """智能打开镜像:给 .cue 自动找音频;给 .wav/.bin 自动找同名 .cue。"""
    p = Path(path)
    if p.suffix.lower() == ".cue":
        ref = _cue_audio_ref(p)
        audio = p.parent / ref if ref else p.with_suffix(".wav")
        return ImageDisc(audio, p)
    cue = p.with_suffix(".cue")
    if cue.is_file():
        return ImageDisc(p, cue)
    return ImageDisc(p, None)
