"""CD 数据模型与统一的光盘数据源抽象。"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

SECTOR_SIZE = 2352        # CD 音频一个扇区的原始 PCM 字节数(588 帧 × 4 字节)
FRAMES_PER_SECOND = 75    # 1 秒 = 75 个扇区


def lba_to_msf(lba: int) -> tuple[int, int, int]:
    """LBA -> (分, 秒, 帧)。LBA 0 对应 MSF 00:02:00。"""
    v = max(0, lba) + 150
    return v // (60 * 75), (v // 75) % 60, v % 75


def msf_to_lba(m: int, s: int, f: int) -> int:
    return (m * 60 + s) * 75 + f - 150


def format_duration(seconds: float) -> str:
    seconds = int(round(seconds))
    return f"{seconds // 60}:{seconds % 60:02d}"


class DiscError(Exception):
    """光盘操作通用错误。"""


class DiscReadError(DiscError):
    """读取扇区失败。"""


@dataclass
class TrackInfo:
    number: int              # 1 起始的音轨号
    start_lba: int           # 起始扇区
    length_lba: int          # 长度(扇区数)
    is_audio: bool = True
    title: str = ""
    artist: str = ""

    @property
    def duration_seconds(self) -> float:
        return self.length_lba / FRAMES_PER_SECOND

    @property
    def end_lba(self) -> int:
        return self.start_lba + self.length_lba


@dataclass
class DiscTOC:
    tracks: list[TrackInfo] = field(default_factory=list)
    leadout_lba: int = 0
    album: str = ""
    artist: str = ""
    genre: str = ""

    @property
    def audio_tracks(self) -> list[TrackInfo]:
        return [t for t in self.tracks if t.is_audio]

    @property
    def total_seconds(self) -> float:
        return sum(t.duration_seconds for t in self.audio_tracks)


class DiscSource(ABC):
    """统一接口的“光盘”:物理光驱(SPTI)或镜像文件。"""

    name: str = "DISC"
    is_virtual: bool = False
    verify_reads: bool = False

    @abstractmethod
    def get_toc(self) -> DiscTOC:
        """读取音轨表(含 CD-Text,尽力而为)。"""

    @abstractmethod
    def read_sectors(self, lba: int, count: int) -> bytes:
        """读取 count 个 2352 字节原始音频扇区。"""

    def media_present(self) -> bool:
        return True

    def close(self) -> None:
        pass
