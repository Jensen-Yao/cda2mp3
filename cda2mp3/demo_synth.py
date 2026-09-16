"""生成演示用“虚拟 CD 专辑”(纯标准库合成,用于无光驱环境演示与自动化测试)。"""
from __future__ import annotations

import math
import wave
from array import array
from pathlib import Path

SR = 44100
BYTES_PER_FRAME = 4  # 16bit 立体声

# 五声音阶(半音),听感和谐
_PENTA = [0, 3, 5, 7, 10, 12, 15]
_PROGRESSION = [0, -4, -2, 3]  # 每小节根音偏移


def _tone(freq: float, dur: float, vol: float, decay: float = 3.0) -> array:
    n = int(dur * SR)
    out = array("h", bytes(2 * n))
    for i in range(n):
        t = i / SR
        env = min(1.0, t / 0.008) * math.exp(-decay * t)
        s = (math.sin(2 * math.pi * freq * t)
             + 0.30 * math.sin(4 * math.pi * freq * t)
             + 0.12 * math.sin(6 * math.pi * freq * t))
        out[i] = int(vol * env * s * 32767 * 0.6)
    return out


def _mix(dst: array, src: array, at: int) -> None:
    end = min(len(dst), at + len(src))
    for i in range(at, end):
        v = dst[i] + src[i - at]
        dst[i] = max(-32768, min(32767, v))


def gen_track(seconds: float, root: int, seed: int) -> bytes:
    """生成一段合成旋律,返回交错的 16bit 立体声 PCM 字节。"""
    import random
    rng = random.Random(seed)
    mono = array("h", bytes(2 * int(seconds * SR)))
    root_hz = 220.0 * (2 ** (root / 12.0))
    beat = 0.42
    t = 0.0
    bar = 0
    while t < seconds - 1.0:
        chord_root = root_hz * (2 ** (_PROGRESSION[bar % len(_PROGRESSION)] / 12.0))
        # 低音
        _mix(mono, _tone(chord_root / 2, beat * 0.95, 0.20, 1.5), int(t * SR))
        # 琶音旋律
        steps = rng.choice((2, 2, 4))
        for k in range(steps):
            if t + k * beat >= seconds:
                break
            deg = rng.choice(_PENTA)
            hz = chord_root * (2 ** (deg / 12.0)) * rng.choice((1, 2))
            _mix(mono, _tone(hz, beat * 0.9, 0.16, 4.0), int((t + k * beat) * SR))
        # 长音铺底
        if bar % 2 == 0:
            _mix(mono, _tone(chord_root, beat * 4, 0.07, 0.8), int(t * SR))
        t += beat * 4
        bar += 1
    # 立体声 + 首尾淡入淡出
    fade = int(0.8 * SR)
    total = int(seconds * SR)
    out = array("h", bytes(BYTES_PER_FRAME * total))
    for i in range(total):
        g = 1.0
        if i < fade:
            g = i / fade
        elif i > total - fade:
            g = max(0.0, (total - i) / fade)
        v = int(mono[i] * g)
        out[2 * i] = v
        out[2 * i + 1] = int(mono[max(0, i - rng.randint(0, 6))] * g)  # 轻微立体声展宽
    return out.tobytes()


DEFAULT_TRACKS = [
    ("星尘入场", 24.0, 0),
    ("慢板慢行", 20.0, -4),
    ("午夜环线", 27.0, -2),
    ("回声车站", 22.0, 3),
]


def gen_album(wav_path: str | Path, cue_path: str | Path,
              tracks: list[tuple[str, float, int]] | None = None) -> None:
    """生成整轨 WAV + 对应 CUE。"""
    tracks = tracks or DEFAULT_TRACKS
    pcm = bytearray()
    offsets: list[int] = []
    for _name, secs, root in tracks:
        offsets.append(len(pcm) // BYTES_PER_FRAME)
        pcm += gen_track(secs, root, seed=root + 7)
    with wave.open(str(wav_path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(bytes(pcm))
    lines = ['REM TITLE "星轨 · 演示专辑"', 'REM PERFORMER "CDA2MP3 Studio"',
             f'FILE "{Path(wav_path).name}" WAVE']
    pos = 0.0
    for i, (name, secs, _root) in enumerate(tracks, 1):
        m, s = int(pos // 60), int(pos % 60)
        lines.append(f"  TRACK {i:02d} AUDIO")
        lines.append(f'    TITLE "{name}"')
        lines.append(f"    INDEX 01 {m:02d}:{s:02d}:00")
        pos += secs
    Path(cue_path).write_text("\n".join(lines) + "\n", "utf-8")


if __name__ == "__main__":
    import sys
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "testdata")
    out.mkdir(exist_ok=True)
    gen_album(out / "demo_album.wav", out / "demo_album.cue")
    print("已生成:", out / "demo_album.wav", "和", out / "demo_album.cue")
