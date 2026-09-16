"""生成应用图标(光盘 → MP3)。运行: python assets/make_icon.py"""
from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

SIZE = 1024
OUT = Path(__file__).parent


def rounded_bg() -> Image.Image:
    img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    # 深蓝紫渐变背景
    top = (24, 26, 44)
    bottom = (43, 32, 74)
    px = img.load()
    mask = Image.new("L", (SIZE, SIZE), 0)
    md = ImageDraw.Draw(mask)
    md.rounded_rectangle((0, 0, SIZE, SIZE), radius=220, fill=255)
    grad = Image.new("RGBA", (SIZE, SIZE))
    gp = grad.load()
    for y in range(SIZE):
        t = y / SIZE
        r = int(top[0] + (bottom[0] - top[0]) * t)
        g = int(top[1] + (bottom[1] - top[1]) * t)
        b = int(top[2] + (bottom[2] - top[2]) * t)
        for x in range(SIZE):
            gp[x, y] = (r, g, b, 255)
    img.paste(grad, (0, 0), mask)
    return img


def draw_disc(img: Image.Image) -> None:
    d = ImageDraw.Draw(img)
    cx, cy, r = 470, 460, 300
    # 彩虹外环
    colors = [(91, 124, 250), (124, 92, 255), (196, 92, 255), (255, 92, 160),
              (255, 146, 92), (250, 220, 92), (92, 220, 180)]
    for i in range(120):
        a0 = i * 3
        d.arc((cx - r - 26, cy - r - 26, cx + r + 26, cy + r + 26),
              a0, a0 + 4, fill=colors[(i // 6) % len(colors)], width=16)
    # 盘体
    d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=(232, 236, 244),
              outline=(203, 210, 224), width=3)
    d.ellipse((cx - r + 22, cy - r + 22, cx + r - 22, cy + r - 22),
              outline=(219, 224, 235), width=2)
    # 高光弧
    d.arc((cx - r + 40, cy - r + 40, cx + r - 40, cy + r - 40), 200, 250,
          fill=(255, 255, 255), width=30)
    d.arc((cx - r + 46, cy - r + 46, cx + r - 46, cy + r - 46), 20, 70,
          fill=(198, 206, 222), width=14)
    # 中孔
    d.ellipse((cx - 62, cy - 62, cx + 62, cy + 62), fill=(20, 22, 34))
    d.ellipse((cx - 40, cy - 40, cx + 40, cy + 40), fill=(33, 36, 52))


def draw_arrow_and_badge(img: Image.Image) -> None:
    d = ImageDraw.Draw(img)
    # 箭头:从光盘指向右下角徽标
    pts = [(660, 640), (740, 720)]
    d.line(pts, fill=(124, 92, 255), width=30)
    d.polygon([(770, 750), (700, 742), (748, 694)], fill=(124, 92, 255))
    # MP3 徽标
    bx, by, br = 790, 790, 190
    d.ellipse((bx - br - 14, by - br - 14, bx + br + 14, by + br + 14),
              fill=(18, 20, 30))
    d.ellipse((bx - br, by - br, bx + br, by + br), fill=(34, 197, 94))
    d.ellipse((bx - br + 18, by - br + 18, bx + br - 18, by + br - 18),
              outline=(255, 255, 255), width=6)
    font = ImageFont.truetype("C:/Windows/Fonts/arialbd.ttf", 150)
    text = "MP3"
    bbox = d.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    d.text((bx - tw / 2 - bbox[0], by - th / 2 - bbox[1]), text,
           font=font, fill=(255, 255, 255))


def main() -> None:
    img = rounded_bg()
    draw_disc(img)
    draw_arrow_and_badge(img)
    img.save(OUT / "icon.png")
    img.save(OUT / "icon.ico", sizes=[(256, 256), (128, 128), (64, 64), (48, 48),
                                      (32, 32), (16, 16)])
    print("icon.png / icon.ico 已生成")


if __name__ == "__main__":
    main()
