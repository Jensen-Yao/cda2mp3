"""MP3 编码(LAME)与 ID3 标签写入。"""
from __future__ import annotations

import os
from pathlib import Path


def sanitize_filename(name: str) -> str:
    """去掉 Windows 文件名非法字符。"""
    for ch in '<>:"/\\|?*':
        name = name.replace(ch, " ")
    name = "".join(c for c in name if ord(c) >= 32)
    name = name.strip().strip(".").strip()
    return name or "未命名"


class Mp3Encoder:
    """流式 PCM(16bit 交错立体声) -> MP3。"""

    def __init__(self, path: str | os.PathLike, bitrate_kbps: int = 320,
                 sample_rate: int = 44100, channels: int = 2):
        try:
            import lameenc
        except ImportError as e:  # pragma: no cover
            raise RuntimeError("缺少 lameenc 组件,请重新安装本软件") from e
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._enc = lameenc.Encoder()
        self._enc.set_bit_rate(int(bitrate_kbps))
        self._enc.set_in_sample_rate(sample_rate)
        self._enc.set_channels(channels)
        self._enc.set_quality(2)  # 2=高,接近最慢但质量最好
        self._closed = False
        self._wrote_any = False
        self._f = open(self._path, "wb")

    def write(self, pcm: bytes) -> None:
        if pcm and not self._closed:
            self._f.write(self._enc.encode(pcm))
            self._wrote_any = True

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            try:
                if self._wrote_any:
                    self._f.write(self._enc.flush())
            finally:
                self._f.close()

    def __enter__(self) -> "Mp3Encoder":
        return self

    def __exit__(self, *exc) -> None:
        self.close()


_COVER_MIME = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
               ".bmp": "image/bmp", ".webp": "image/webp"}


def write_id3_tags(path: str | os.PathLike, *, title: str = "", artist: str = "",
                   album: str = "", track: int = 0, track_total: int = 0,
                   year: str = "", genre: str = "", cover_image: str | None = None) -> None:
    """为 MP3 写入 ID3v2.3 标签(Windows 资源管理器兼容性最好)。"""
    from mutagen.id3 import (APIC, ID3, ID3NoHeaderError, TALB, TCON, TDRC,
                             TIT2, TPE1, TRCK)

    try:
        tags = ID3(str(path))
    except ID3NoHeaderError:
        tags = ID3()
    if title:
        tags.add(TIT2(encoding=3, text=title))
    if artist:
        tags.add(TPE1(encoding=3, text=artist))
    if album:
        tags.add(TALB(encoding=3, text=album))
    if track:
        text = f"{track}/{track_total}" if track_total else f"{track}"
        tags.add(TRCK(encoding=3, text=text))
    if year:
        tags.add(TDRC(encoding=3, text=year))
    if genre:
        tags.add(TCON(encoding=3, text=genre))
    if cover_image and os.path.isfile(cover_image):
        ext = os.path.splitext(cover_image)[1].lower()
        mime = _COVER_MIME.get(ext)
        if mime:
            with open(cover_image, "rb") as f:
                tags.add(APIC(encoding=3, mime=mime, type=3, desc="Cover", data=f.read()))
    tags.save(str(path), v2_version=3)
