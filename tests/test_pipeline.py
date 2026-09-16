"""端到端流水线测试:虚拟光盘 → 抓轨 → MP3 → 标签校验。
运行: .venv/Scripts/python tests/test_pipeline.py
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cda2mp3.audio.encoder import Mp3Encoder, write_id3_tags
from cda2mp3.cdrom import open_image
from cda2mp3.demo_synth import gen_album


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="cda2mp3_test_"))
    wav, cue = tmp / "demo_album.wav", tmp / "demo_album.cue"
    print("1) 生成虚拟专辑…")
    gen_album(wav, cue)
    assert wav.exists() and cue.exists()

    print("2) 打开镜像读取 TOC…")
    disc = open_image(cue)
    toc = disc.get_toc()
    assert len(toc.tracks) == 4, f"应 4 轨,实际 {len(toc.tracks)}"
    assert toc.album == "星轨 · 演示专辑"
    assert all(t.length_lba > 0 for t in toc.tracks)
    for t in toc.tracks:
        print(f"   {t.number:02d} {t.title} {t.duration_seconds:.1f}s "
              f"({t.start_lba}+{t.length_lba})")

    print("3) 读取扇区…")
    data = disc.read_sectors(toc.tracks[0].start_lba, 75)
    assert len(data) == 75 * 2352, "1 秒音频应为 176400 字节"

    print("4) 抓第 1、3 轨转 MP3 (320kbps)…")
    out_dir = tmp / "out"
    out_dir.mkdir()
    outs = []
    for idx in (0, 2):
        t = toc.tracks[idx]
        path = out_dir / f"{t.number:02d}. {t.title}.mp3"
        with Mp3Encoder(path, bitrate_kbps=320) as enc:
            pos = t.start_lba
            while pos < t.end_lba:
                n = min(128, t.end_lba - pos)
                enc.write(disc.read_sectors(pos, n))
                pos += n
        write_id3_tags(path, title=t.title, artist="CDA2MP3 Studio",
                       album=toc.album, track=t.number, track_total=4,
                       year="2026", genre="Test")
        outs.append(path)

    print("5) 用 mutagen 校验产物…")
    from mutagen.mp3 import MP3
    for idx, path in zip((0, 2), outs):
        t = toc.tracks[idx]
        m = MP3(str(path))
        expect = t.duration_seconds
        assert abs(m.info.length - expect) < 0.6, \
            f"{path.name} 时长 {m.info.length:.2f}s ≠ 期望 {expect:.2f}s"
        assert 300000 <= m.info.bitrate <= 340000, f"码率异常:{m.info.bitrate}"
        tags = m.tags
        assert tags.get("TIT2").text[0] == t.title
        assert tags.get("TALB").text[0] == toc.album
        assert tags.get("TRCK").text[0] == f"{t.number}/4"
        print(f"   ✓ {path.name}: {m.info.length:.2f}s, {m.info.bitrate//1000}kbps, 标签 OK")

    print(f"\n全部通过 ✔  产物在 {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
