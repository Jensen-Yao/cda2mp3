"""启动 GUI 并截图(用于 README 宣传图)。
用法: python scripts/screenshot_demo.py [main|empty]
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PIL import ImageGrab
from PySide6.QtCore import QTimer
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QApplication, QMessageBox

from cda2mp3.ui.main_window import MainWindow
from cda2mp3.ui.theme import QSS

OUT = ROOT / "screenshots"
OUT.mkdir(exist_ok=True)

# 截图模式下不弹窗
QMessageBox.information = staticmethod(lambda *a, **k: None)
QMessageBox.warning = staticmethod(lambda *a, **k: None)

# 截图模式使用隔离配置,避免污染真实配置
import cda2mp3.ui.main_window as _mw

from cda2mp3.config import _DEFAULTS

_mw.load_config = lambda: dict(_DEFAULTS, out_dir=str(ROOT / "testdata" / "rip_out"))
_mw.save_config = lambda cfg: None


def grab(win, name: str) -> None:
    g = win.frameGeometry()
    f = QGuiApplication.primaryScreen().devicePixelRatio()
    box = (int(g.x() * f), int(g.y() * f),
           int((g.x() + g.width()) * f), int((g.y() + g.height()) * f))
    img = ImageGrab.grab(bbox=box)
    img.save(OUT / name)
    print("saved", OUT / name, img.size)


def main() -> None:
    mode = sys.argv[1] if len(sys.argv) > 1 else "main"
    app = QApplication.instance() or QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setStyleSheet(QSS)

    if mode == "empty":
        win = MainWindow()
        win.show()

        def shot() -> None:
            grab(win, "empty.png")
            app.quit()

        QTimer.singleShot(2600, shot)
    else:
        win = MainWindow(image_path=str(ROOT / "testdata" / "demo_album.cue"))
        win.show()

        def begin() -> None:
            if win.drive is None or win.toc is None:
                print("ERROR: 镜像未加载")
                app.quit()
                return
            real_read = win.drive.read_sectors

            def slow(lba, count):
                time.sleep(0.05)
                return real_read(lba, count)

            win.drive.read_sectors = slow
            win.start_rip()

        def shot_ripping() -> None:
            grab(win, "ripping.png")

        def shot_done() -> None:
            if win.worker:
                win.worker.stop()
                win.worker.wait(3000)
            win.player.stop()
            grab(win, "main.png")
            app.quit()

        QTimer.singleShot(1300, begin)
        QTimer.singleShot(2600, shot_ripping)
        QTimer.singleShot(8000, shot_done)

    app.exec()


if __name__ == "__main__":
    main()
