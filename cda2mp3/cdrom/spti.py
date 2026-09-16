"""Windows SPTI(SCSI Pass-Through Interface)直读音频 CD,零第三方 DLL 依赖。

通过 DeviceIoControl(IOCTL_SCSI_PASS_THROUGH_DIRECT) 向光驱发送 SCSI CDB:
  - READ TOC (0x43, format 0)     -> 音轨表(起始扇区/是否音轨)
  - READ TOC/PMA/ATIP (0x43, format 5) -> CD-Text(专辑/艺术家/曲目名,尽力而为)
  - READ CD  (0xBE, main channel) -> 2352 字节原始音频扇区(无损抓轨的基础)
"""
from __future__ import annotations

import ctypes
import threading
from ctypes import wintypes

from .base import (
    DiscError,
    DiscReadError,
    DiscSource,
    DiscTOC,
    TrackInfo,
    msf_to_lba,
)

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
kernel32.CreateFileW.restype = wintypes.HANDLE
kernel32.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                 wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
kernel32.DeviceIoControl.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPVOID,
                                     wintypes.DWORD, wintypes.LPVOID, wintypes.DWORD,
                                     wintypes.LPDWORD, wintypes.LPVOID]
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]

IOCTL_SCSI_PASS_THROUGH_DIRECT = 0x0004D014
IOCTL_STORAGE_CHECK_VERIFY = 0x0002D480
IOCTL_CDROM_RAW_READ = 0x0002403E          # cdrom.sys 原生 CDDA 原始读取
TRACK_MODE_CDDA = 2
SCSI_IOCTL_DATA_IN = 1
SENSE_LEN = 32
SENSE_OFF = 64
DATA_OFF = 128
MAX_SECTORS_PER_READ = 64          # 单次 SPTI 传输上限,兼容性最好
READ_TOC_TIMEOUT = 10

GENERIC_READ = 0x80000000
GENERIC_WRITE = 0x40000000
FILE_SHARE_READ = 0x1
FILE_SHARE_WRITE = 0x2
OPEN_EXISTING = 3
DRIVE_TYPE_CDROM = 5


class RAW_READ_INFO(ctypes.Structure):
    _fields_ = [
        ("DiskOffset", ctypes.c_longlong),    # 字节偏移(LBA × 2048)
        ("SectorCount", ctypes.c_ulong),
        ("TrackMode", ctypes.c_ulong),        # CDDA = 2
    ]


class SCSI_PASS_THROUGH_DIRECT(ctypes.Structure):
    _fields_ = [
        ("Length", ctypes.c_ushort),
        ("ScsiStatus", ctypes.c_ubyte),
        ("PathId", ctypes.c_ubyte),
        ("TargetId", ctypes.c_ubyte),
        ("Lun", ctypes.c_ubyte),
        ("CdbLength", ctypes.c_ubyte),
        ("SenseInfoLength", ctypes.c_ubyte),
        ("DataIn", ctypes.c_ubyte),
        ("DataTransferLength", ctypes.c_ulong),
        ("TimeOutValue", ctypes.c_ulong),
        ("DataBuffer", ctypes.c_void_p),
        ("SenseInfoOffset", ctypes.c_ulong),
        ("Cdb", ctypes.c_ubyte * 16),
    ]


def list_cd_drives() -> list[str]:
    """枚举系统中的光驱盘符,如 ["D", "E"]。"""
    n = kernel32.GetLogicalDriveStringsW(0, None)
    buf = ctypes.create_unicode_buffer(n + 2)
    kernel32.GetLogicalDriveStringsW(n + 1, buf)
    drives: list[str] = []
    for part in ctypes.wstring_at(buf, n + 1).split("\x00"):
        if part and kernel32.GetDriveTypeW(ctypes.c_wchar_p(part)) == DRIVE_TYPE_CDROM:
            drives.append(part[0])
    return drives


class DiscTransferTooBig(DiscReadError):
    """单次 SCSI 传输超过适配器/桥接芯片上限(WinError 87),需减小块重试。"""


_CDTEXT_TYPES = {0x80: "title", 0x81: "performer", 0x82: "songwriter",
                 0x83: "composer", 0x84: "arranger", 0x85: "message",
                 0x87: "genre", 0x8E: "upc"}


def _decode_cdtext(raw: bytes) -> str:
    for enc in ("utf-8", "gbk", "cp1252"):
        try:
            return raw.decode(enc).strip("\x00 \t").strip()
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-16-be", "replace").replace("\x00", "").strip()


class SptiDrive(DiscSource):
    """一台物理光驱。read_sectors 读出的是原始 2352B/扇区 PCM(16bit/44.1kHz/立体声)。"""

    def __init__(self, letter: str, *, verify: bool = False, timeout: int = 10):
        self.letter = letter.upper().rstrip(":")[:1]
        self.name = f"{self.letter}: 光驱"
        self.verify_reads = verify
        self._timeout = timeout
        self.max_transfer_sectors = MAX_SECTORS_PER_READ   # 会被自适应下调
        self._lock = threading.Lock()
        self._handle: int | None = None
        self._open()
        # 部分 USB 桥接芯片不支持 SCSI 直通抓轨(READ CD 0xBE)但支持系统原生
        # IOCTL_CDROM_RAW_READ,启动时探测一次自动选择后端
        self._use_raw = not self._probe_spti_read()
        if self._use_raw:
            self.max_transfer_sectors = 64   # cdrom.sys 原始读取可自动分片

    def _probe_spti_read(self) -> bool:
        old = self._timeout
        self._timeout = 6
        try:
            self._read_cd(0, 1)
            return True
        except DiscError:
            return False
        finally:
            self._timeout = old

    # ---------- 句柄 ----------
    def _open(self) -> None:
        path = f"\\\\.\\{self.letter}:"
        h = kernel32.CreateFileW(path, GENERIC_READ | GENERIC_WRITE,
                                 FILE_SHARE_READ | FILE_SHARE_WRITE, None,
                                 OPEN_EXISTING, 0, None)
        if not h or h == wintypes.HANDLE(-1).value:
            h = kernel32.CreateFileW(path, GENERIC_READ,
                                     FILE_SHARE_READ | FILE_SHARE_WRITE, None,
                                     OPEN_EXISTING, 0, None)
        if not h or h == wintypes.HANDLE(-1).value:
            raise DiscError(f"无法打开光驱 {self.letter}:(WinError {ctypes.get_last_error()})")
        self._handle = h

    def _reopen(self) -> None:
        self._close_handle()
        self._open()

    def _close_handle(self) -> None:
        if self._handle:
            kernel32.CloseHandle(self._handle)
            self._handle = None

    def close(self) -> None:
        with self._lock:
            self._close_handle()

    # ---------- SCSI 底层 ----------
    def _scsi(self, cdb: bytes, data_len: int) -> tuple[bytes, bytes]:
        with self._lock:
            if not self._handle:
                raise DiscError("光驱尚未打开")
            total = DATA_OFF + max(data_len, 1) + 16
            buf = ctypes.create_string_buffer(total)
            sptd = SCSI_PASS_THROUGH_DIRECT.from_buffer(buf)
            sptd.Length = ctypes.sizeof(SCSI_PASS_THROUGH_DIRECT)
            sptd.CdbLength = len(cdb)
            sptd.SenseInfoLength = SENSE_LEN
            sptd.DataIn = SCSI_IOCTL_DATA_IN
            sptd.DataTransferLength = data_len
            sptd.TimeOutValue = self._timeout
            sptd.DataBuffer = ctypes.addressof(buf) + DATA_OFF
            sptd.SenseInfoOffset = SENSE_OFF
            for i, b in enumerate(cdb[:16]):
                sptd.Cdb[i] = b
            returned = wintypes.DWORD(0)
            ok = kernel32.DeviceIoControl(self._handle, IOCTL_SCSI_PASS_THROUGH_DIRECT,
                                          buf, total, buf, total,
                                          ctypes.byref(returned), None)
            sense = bytes(buf[SENSE_OFF:SENSE_OFF + SENSE_LEN])
            n = sptd.DataTransferLength if ok else 0
            data = bytes(buf[DATA_OFF:DATA_OFF + n])
            if not ok:
                err = ctypes.get_last_error()
                key = sense[2] if len(sense) > 2 else -1
                if err == 87:   # ERROR_INVALID_PARAMETER: 多为传输长度超桥接上限
                    raise DiscTransferTooBig("SCSI 传输长度超限(WinError 87)")
                if key == 0x02:  # NOT READY
                    raise DiscError("光驱未就绪(没有放入光盘?)")
                raise DiscReadError(f"SCSI 命令失败(WinError {err}, sense=0x{key:02x})")
            return data, sense

    # ---------- 对外能力 ----------
    def media_present(self) -> bool:
        ok = kernel32.DeviceIoControl(self._handle, IOCTL_STORAGE_CHECK_VERIFY,
                                      None, 0, None, 0,
                                      ctypes.byref(wintypes.DWORD(0)), None)
        if ok:
            return True
        # 部分 USB 桥接芯片对 CHECK_VERIFY 误报“无介质”,用真实 READ TOC 复核
        try:
            self._toc_raw()
            return True
        except DiscError:
            return False

    def _toc_raw(self) -> bytes:
        cdb = bytearray(12)
        cdb[0] = 0x43          # READ TOC
        cdb[1] = 0x02          # MSF 格式
        cdb[7], cdb[8] = 0x08, 0x04   # 分配长度 2052
        data, _ = self._scsi(bytes(cdb), 2052)
        if len(data) < 4:
            raise DiscError("读取音轨表失败")
        return data

    def set_speed(self, kb_per_sec: int) -> bool:
        """SET CD-ROM SPEED (0xBB) 限速,温和读盘。best-effort,失败返回 False。"""
        try:
            cdb = bytearray(12)
            cdb[0] = 0xBB
            v = max(176, int(kb_per_sec))          # 176 kB/s ≈ 1x
            cdb[2], cdb[3] = (v >> 8) & 0xFF, v & 0xFF
            self._scsi(bytes(cdb), 16)
            return True
        except DiscError:
            return False

    def get_toc(self) -> DiscTOC:
        if not self.media_present():
            raise DiscError(f"光驱 {self.letter}: 中没有光盘,请放入 CD 后重试")
        toc = self._read_toc()
        try:
            self._apply_cdtext(toc)
        except DiscError:
            pass  # CD-Text 属于尽力而为
        return toc

    def _read_toc(self) -> DiscTOC:
        data = self._toc_raw()
        first, last = data[2], data[3]
        if not (1 <= first <= last <= 99):
            raise DiscError("音轨表异常,这可能不是音频 CD")
        tracks: list[TrackInfo] = []
        leadout = 0
        # 条目数 = 轨数 + 1(最后一条是 lead-out,轨号 0xAA)
        for k in range(last - first + 2):
            e = data[4 + k * 8: 4 + k * 8 + 8]
            if len(e) < 8:
                break
            ctrl, tno = e[1], e[2]
            m, s, f = e[5], e[6], e[7]
            lba = msf_to_lba(m, s, f)
            if tno == 0xAA:            # lead-out
                leadout = lba
                continue
            if not (1 <= tno <= 99):
                continue
            tracks.append(TrackInfo(number=tno, start_lba=lba, length_lba=0,
                                    is_audio=(ctrl & 0x04) == 0))
        if not tracks:
            raise DiscError("没有发现音轨")
        for i, t in enumerate(tracks):
            nxt = tracks[i + 1].start_lba if i + 1 < len(tracks) else leadout
            t.length_lba = max(0, nxt - t.start_lba)
        audio = [t for t in tracks if t.is_audio]
        if not audio:
            raise DiscError("这不是音乐 CD(没有音频轨)")
        return DiscTOC(tracks=tracks, leadout_lba=leadout or audio[-1].end_lba)

    def _apply_cdtext(self, toc: DiscTOC) -> None:
        cdb = bytearray(12)
        cdb[0] = 0x43          # READ TOC/PMA/ATIP
        cdb[7], cdb[8] = 0x40, 0x00   # 分配长度 16KB
        cdb[9] = 0x05          # format 5 = CD-Text
        data, _ = self._scsi(bytes(cdb), 0x4000)
        if len(data) <= 4:
            return
        packs: dict[tuple[int, int], dict[int, bytes]] = {}
        off = 4
        while off + 18 <= len(data):
            pack = data[off:off + 18]
            off += 18
            ptype = pack[0]
            if ptype not in _CDTEXT_TYPES:
                continue
            tno = pack[1] & 0x7F
            seq = pack[2]
            packs.setdefault((ptype, tno), {})[seq] = pack[4:16]
        by_track: dict[int, dict[str, str]] = {}
        for (ptype, tno), seqs in packs.items():
            blob = b"".join(seqs[k] for k in sorted(seqs))
            for field in blob.split(b"\x00"):
                text = _decode_cdtext(field)
                if text:
                    by_track.setdefault(tno, {})[_CDTEXT_TYPES[ptype]] = text
        disc = by_track.get(0, {})
        toc.album = disc.get("title", "")
        toc.artist = disc.get("performer", "")
        toc.genre = disc.get("genre", "")
        for t in toc.tracks:
            info = by_track.get(t.number, {})
            t.title = info.get("title", "")
            t.artist = info.get("performer", "") or toc.artist

    MIN_TRANSFER_SECTORS = 4

    def read_sectors(self, lba: int, count: int) -> bytes:
        out = bytearray()
        pos, remaining = lba, count
        while remaining > 0:
            n = min(self.max_transfer_sectors, remaining)
            try:
                out += self._read_raw(pos, n)
            except DiscTransferTooBig:
                if self.max_transfer_sectors <= self.MIN_TRANSFER_SECTORS:
                    raise DiscReadError(
                        f"读取 LBA {lba} 失败:传输参数被系统拒绝(即使最小块)")
                self.max_transfer_sectors = self.max_transfer_sectors // 2
                continue
            pos += n
            remaining -= n
        return bytes(out)

    def _read_raw(self, lba: int, n: int, attempts: int = 3) -> bytes:
        last_err: Exception | None = None
        for _ in range(attempts):
            try:
                if self._use_raw:
                    data = self._raw_read_os(lba, n)
                else:
                    data = self._read_cd(lba, n)
                if self.verify_reads:
                    if self._use_raw:
                        data2 = self._raw_read_os(lba, n)
                    else:
                        data2 = self._read_cd(lba, n)
                    if data2 != data:
                        raise DiscReadError("两次读取不一致,盘面可能存在划痕")
                return data
            except DiscTransferTooBig:
                raise                       # 由 read_sectors 调整块大小
            except DiscError as e:
                last_err = e
                try:
                    self._reopen()
                except DiscError:
                    pass
        raise last_err or DiscReadError("读取失败")

    def _raw_read_os(self, lba: int, n: int) -> bytes:
        """系统原生原始读取(IOCTL_CDROM_RAW_READ, CDDA 模式)。"""
        info = RAW_READ_INFO()
        info.DiskOffset = lba * 2048
        info.SectorCount = n
        info.TrackMode = TRACK_MODE_CDDA
        buf = ctypes.create_string_buffer(n * 2352)
        ret = wintypes.DWORD(0)
        ok = kernel32.DeviceIoControl(self._handle, IOCTL_CDROM_RAW_READ,
                                      ctypes.byref(info), ctypes.sizeof(info),
                                      buf, n * 2352, ctypes.byref(ret), None)
        if not ok:
            err = ctypes.get_last_error()
            if err == 87:
                raise DiscTransferTooBig("原始读取长度超限(WinError 87)")
            raise DiscReadError(f"系统原始读取失败(WinError {err})")
        if ret.value < n * 2352:
            raise DiscReadError(f"原始读取不完整(LBA {lba})")
        return buf.raw[:ret.value]

    def _read_cd(self, lba: int, n: int) -> bytes:
        cdb = bytearray(12)
        cdb[0] = 0xBE                                # READ CD
        cdb[2:6] = lba.to_bytes(4, "big")            # 起始 LBA
        cdb[6], cdb[7] = (n >> 8) & 0xFF, n & 0xFF   # 扇区数
        cdb[9] = 0x10                                # 主通道 = 音频 2352B
        data, _ = self._scsi(bytes(cdb), n * 2352)
        if len(data) < n * 2352:
            raise DiscReadError(f"扇区读取不完整(LBA {lba})")
        return data

    def __del__(self):
        try:
            self._close_handle()
        except Exception:
            pass
