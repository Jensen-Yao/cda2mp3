"""程序入口:GUI / 命令行抓轨。

用法:
  cda2mp3                          打开图形界面
  cda2mp3 --image album.cue        打开镜像(虚拟光盘)
  cda2mp3 --drive D                指定光驱盘符
  cda2mp3 --rip --out DIR          命令行抓取全部音频轨为 MP3 后退出
  cda2mp3 --list-drives            列出光驱
"""
from __future__ import annotations

import argparse
import os
import sys

from . import APP_NAME, __version__
from .audio.encoder import Mp3Encoder, sanitize_filename, write_id3_tags
from .cdrom import ImageDisc, SptiDrive, format_duration, list_cd_drives, open_image
from .config import load_config


def _pick_tracks(toc, spec: str | None):
    tracks = toc.audio_tracks
    if not spec:
        return tracks
    want: set[int] = set()
    for part in spec.split(","):
        part = part.strip()
        if "-" in part:
            a, b = part.split("-", 1)
            want.update(range(int(a), int(b) + 1))
        elif part:
            want.add(int(part))
    return [t for t in tracks if t.number in want]


def cli_rip(args) -> int:
    cfg = load_config()
    if args.image:
        drive = open_image(args.image)
    else:
        letters = [args.drive] if args.drive else list_cd_drives()
        if not letters:
            print("未检测到光驱;也可用 --image 指定 CUE/WAV 镜像")
            return 2
        letter = letters[0]
        drive = SptiDrive(letter, verify=args.verify or cfg.get("verify", False))
        print(f"使用光驱 {letter}:")
        if getattr(args, "speed", 0):
            speed_ok = drive.set_speed(int(args.speed * 176))   # 1x ≈ 176 kB/s
            print(f"限速 {args.speed:g}x:{'成功' if speed_ok else '驱动器未响应(按默认速度)'}")
    try:
        toc = drive.get_toc()
    except Exception as e:
        print(f"读取失败:{e}")
        return 1
    tracks = _pick_tracks(toc, args.tracks)
    if not tracks:
        print("没有可转换的音频轨")
        return 1
    album = args.album or toc.album or "未知专辑"
    out_dir = args.out or os.path.join(os.getcwd(), album.replace('/', '_'))
    os.makedirs(out_dir, exist_ok=True)
    total_secs = sum(t.duration_seconds for t in tracks)
    print(f"专辑:{album} | {len(tracks)} 轨 | 约 {format_duration(total_secs)}")
    print(f"输出:{out_dir} | {args.bitrate} kbps\n")
    ok = fail = 0
    for t in tracks:
        # 无 CD-Text 时,标题回退为 “专辑名 + 轨号”,文件名回退为 “轨号. 专辑名”
        title = t.title or (f"{album} {t.number:02d}" if album else f"Track {t.number:02d}")
        try:
            name = args.template.format(track=t.number, title=title,
                                        artist=toc.artist or args.artist_default or "",
                                        album=album)
        except (KeyError, IndexError):
            name = f"{t.number:02d}. {title}"
        name = sanitize_filename(name) + ".mp3"
        path = os.path.join(out_dir, name)
        print(f"[{t.number:02d}] {title}({format_duration(t.duration_seconds)}) ...",
              end="", flush=True)
        try:
            import time
            t0 = time.monotonic()
            with Mp3Encoder(path, bitrate_kbps=args.bitrate) as enc:
                pos, end = t.start_lba, t.end_lba
                while pos < end:
                    n = min(128, end - pos)
                    enc.write(drive.read_sectors(pos, n))
                    pos += n
            if not args.no_tags:
                write_id3_tags(path, title=title, artist=t.artist or toc.artist,
                               album=album, track=t.number, track_total=len(tracks),
                               year=args.year or "", genre=toc.genre)
            ok += 1
            print(f" 完成({time.monotonic() - t0:.1f}s)")
        except KeyboardInterrupt:
            print(" 已取消")
            return 130
        except Exception as e:
            fail += 1
            print(f" 失败:{e}")
    print(f"\n完成:成功 {ok},失败 {fail} → {out_dir}")
    return 0 if fail == 0 else 1


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="cda2mp3",
                                description=f"{APP_NAME} —— CD 抓轨转 MP3 + CD 播放器")
    p.add_argument("--image", help="打开镜像文件(CUE/WAV/BIN)作为虚拟光盘")
    p.add_argument("--drive", help="指定光驱盘符,如 D")
    p.add_argument("--list-drives", action="store_true", help="列出光驱后退出")
    p.add_argument("--rip", action="store_true", help="命令行模式:抓取音频轨为 MP3 后退出")
    p.add_argument("--out", help="输出目录(--rip)")
    p.add_argument("--bitrate", type=int, default=320, help="MP3 码率(默认 320)")
    p.add_argument("--tracks", help="音轨选择,如 1,3-5(--rip)")
    p.add_argument("--album", help="专辑名(--rip)")
    p.add_argument("--year", default="", help="年份(--rip)")
    p.add_argument("--verify", action="store_true", help="安全模式:双读校验(--rip)")
    p.add_argument("--speed", type=float, default=0, help="限制光驱速度(倍速,如 8;0=默认),温和读盘")
    p.add_argument("--template", default="{track:02d}. {title}",
                   help="文件名模板,可用 {track} {title} {artist} {album}")
    p.add_argument("--artist-default", default="", help="CD 无元数据时的默认艺术家")
    p.add_argument("--no-tags", action="store_true", help="不写 ID3 标签(--rip)")
    p.add_argument("--version", action="version", version=f"{APP_NAME} v{__version__}")
    args = p.parse_args(argv)

    if args.list_drives:
        letters = list_cd_drives()
        print("\n".join(letters) if letters else "(未检测到光驱)")
        return 0
    if args.rip:
        return cli_rip(args)
    from .ui.main_window import run_gui
    return run_gui(image_path=args.image, drive_letter=args.drive)


if __name__ == "__main__":
    sys.exit(main())
