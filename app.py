"""CDA2MP3 Studio 启动器(PyInstaller 入口)。"""
import sys

from cda2mp3.app import main

if __name__ == "__main__":
    sys.exit(main())
