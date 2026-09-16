"""解析 .cda 文件。

.cda 是 Windows 为音频 CD 每一轨生成的 44 字节“快捷方式”(RIFF/CDDA fmt 块),
本身不含任何音频数据,只记录:轨号、起始扇区、长度。必须配合原版 CD + 光驱使用。
字段偏移已经过真实 CD 的 TOC 链条校验:0x16 轨号、0x1C 起始 LBA、0x20 长度。
"""
from __future__ import annotations

import glob
import os
import struct
from dataclasses import dataclass
from pathlib import Path

from .base import DiscError, format_duration

_CDA_MAX_SECTORS = 405_000  # 90 分钟 CD 的扇区上限,用于合法性判断


@dataclass
class CdaEntry:
    path: str
    track_number: int
    start_lba: int = 0
    length_lba: int = 0

    @property
    def valid(self) -> bool:
        return self.track_number > 0 and 0 <= self.start_lba < _CDA_MAX_SECTORS and 0 < self.length_lba < _CDA_MAX_SECTORS

    @property
    def duration_seconds(self) -> float:
        return self.length_lba / 75.0

    def duration_text(self) -> str:
        return format_duration(self.duration_seconds) if self.valid else "未知"


def parse_cda(path: str | os.PathLike) -> CdaEntry:
    p = Path(path)
    data = p.read_bytes()
    if len(data) < 44 or data[:4] != b"RIFF" or data[8:12] != b"CDDA":
        raise DiscError(f"{p.name} 不是有效的 CDA 文件")
    _version, track = struct.unpack_from("<HH", data, 20)
    start, length = struct.unpack_from("<II", data, 28)
    return CdaEntry(path=str(p), track_number=track, start_lba=start, length_lba=length)


def parse_cda_paths(paths: list[str | os.PathLike]) -> list[CdaEntry]:
    """解析一组 .cda(或包含 .cda 的目录),按轨号排序。"""
    files: list[str] = []
    for x in paths:
        if os.path.isdir(x):
            files += glob.glob(os.path.join(x, "*.cda"))
        elif str(x).lower().endswith(".cda"):
            files.append(str(x))
    entries: list[CdaEntry] = []
    for f in sorted(files):
        try:
            entries.append(parse_cda(f))
        except (DiscError, OSError):
            continue
    entries.sort(key=lambda e: e.track_number)
    if not entries:
        raise DiscError("所选位置没有可识别的 .cda 文件")
    return entries


def guess_album_info(entries: list[CdaEntry]) -> tuple[str, str]:
    """从 cda 所在文件夹名猜(艺术家, 专辑),如 “陈一豪-羞于启齿”。"""
    try:
        folder = Path(entries[0].path).parent.name
    except (IndexError, OSError):
        return "", ""
    if "-" in folder:
        artist, album = folder.split("-", 1)
        return artist.strip(), album.strip()
    return "", folder
