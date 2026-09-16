"""CDA2MP3 Studio 主窗口。"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QIcon, QKeySequence, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QCheckBox, QComboBox, QFileDialog,
    QFrame, QGridLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
    QMainWindow, QMessageBox, QPlainTextEdit, QProgressBar, QPushButton,
    QSlider, QStackedWidget, QTableWidget, QTableWidgetItem, QVBoxLayout,
    QWidget,
)

from .. import APP_NAME, __version__
from ..audio.encoder import sanitize_filename
from ..audio.player import STATE_PAUSED, STATE_PLAYING, CDPlayer
from ..cdrom import (
    DiscError,
    DiscTOC,
    ImageDisc,
    SptiDrive,
    TrackInfo,
    format_duration,
    guess_album_info,
    list_cd_drives,
    open_image,
    parse_cda_paths,
)
from ..config import load_config, save_config
from ..paths import resource_path
from .theme import QSS
from .workers import RipWorker

MUSIC_DIR = Path.home() / "Music"


def _col(parent):
    w = QWidget(parent)
    v = QVBoxLayout(w)
    v.setContentsMargins(0, 0, 0, 0)
    v.setSpacing(0)
    return w, v


class MainWindow(QMainWindow):
    def __init__(self, image_path: str | None = None, drive_letter: str | None = None):
        super().__init__()
        self.cfg = load_config()
        self.drive: SptiDrive | ImageDisc | None = None
        self.toc: DiscTOC | None = None
        self.cda_entries = None          # 通过 .cda 导入的清单
        self._titles: dict[int, str] = {}   # 轨号 -> 标题
        self._loading = False
        self._seeking = False
        self._playing_track: TrackInfo | None = None
        self.worker: RipWorker | None = None
        self.player = CDPlayer()

        self.setWindowTitle(f"{APP_NAME} v{__version__}")
        self.setWindowIcon(QIcon(resource_path("assets/icon.ico")))
        self.resize(1200, 780)
        self.setMinimumSize(1040, 680)
        self.setAcceptDrops(True)

        self._build_ui()
        self._connect_player()
        self._load_settings_into_ui()

        # 光驱自动检测轮询
        self._poll = QTimer(self)
        self._poll.timeout.connect(self._poll_drives)
        self._poll.start(2000)

        QTimer.singleShot(60, lambda: self._startup(image_path, drive_letter))
        QShortcut(QKeySequence(Qt.Key_Space), self, self._toggle_play_shortcut)

    # ==================================================================
    # UI 构建
    # ==================================================================
    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ---------- 顶栏 ----------
        header = QFrame(objectName="HeaderBar")
        header.setFixedHeight(58)
        hv = QHBoxLayout(header)
        hv.setContentsMargins(18, 0, 18, 0)
        logo = QLabel()
        logo.setPixmap(QPixmap(resource_path("assets/icon.png")).scaled(
            34, 34, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        title_box = QVBoxLayout()
        title_box.setSpacing(0)
        t1 = QLabel(APP_NAME, objectName="AppTitle")
        t2 = QLabel("CD 无损抓轨 → MP3  ·  CD 播放器  ·  .cda 识别", objectName="AppSubtitle")
        title_box.addWidget(t1)
        title_box.addWidget(t2)
        hv.addWidget(logo)
        hv.addSpacing(10)
        hv.addLayout(title_box)
        hv.addStretch(1)
        self.drive_combo = QComboBox()
        self.drive_combo.setMinimumWidth(150)
        refresh_btn = QPushButton("⟳ 检测")
        refresh_btn.clicked.connect(self.refresh_drives)
        hv.addWidget(QLabel("光驱:"))
        hv.addWidget(self.drive_combo)
        hv.addSpacing(8)
        hv.addWidget(refresh_btn)
        root.addWidget(header)

        # ---------- 主体 ----------
        body = QHBoxLayout()
        body.setContentsMargins(16, 14, 16, 12)
        body.setSpacing(14)
        root.addLayout(body, 1)

        # 左侧:栈(空状态 / 光盘视图) + 播放条
        left = QVBoxLayout()
        left.setSpacing(12)
        body.addLayout(left, 1)

        self.stack = QStackedWidget()
        self.stack.addWidget(self._build_empty_page())
        self.stack.addWidget(self._build_disc_page())
        left.addWidget(self.stack, 1)
        left.addWidget(self._build_player_bar())

        # 右侧:信息 + 转换设置
        body.addWidget(self._build_right_panel())

        self.statusBar().showMessage("就绪 —— 将 CD 插入光驱,或拖入 .cda / CUE / WAV 文件")

    def _build_empty_page(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setAlignment(Qt.AlignCenter)
        card = QFrame(objectName="EmptyCard")
        card.setFixedWidth(640)
        cv = QVBoxLayout(card)
        cv.setContentsMargins(40, 34, 40, 30)
        cv.setSpacing(12)
        icon = QLabel("💿", objectName="EmptyIcon")
        icon.setAlignment(Qt.AlignCenter)
        self.empty_title = QLabel("未检测到音乐 CD", objectName="EmptyTitle")
        self.empty_title.setAlignment(Qt.AlignCenter)
        self.empty_text = QLabel(
            "在光驱中放入音频 CD 后会自动识别。\n\n"
            "为什么 .cda 文件无法直接转换?.cda 只是 Windows 生成的 44 字节音轨索引,\n"
            "不含任何音频数据;真正的声音保存在 CD 盘片上,必须通过光驱读取。\n"
            "没有光驱?一个 USB 外置光驱即可(约 50–100 元),也可以直接打开 CUE/WAV 镜像。",
            objectName="EmptyText")
        self.empty_text.setAlignment(Qt.AlignCenter)
        self.empty_text.setWordWrap(True)
        btns = QHBoxLayout()
        btns.addStretch(1)
        b1 = QPushButton("导入 .cda 文件")
        b1.clicked.connect(self.import_cda)
        b2 = QPushButton("打开镜像 (CUE/WAV)")
        b2.clicked.connect(self.open_image_dialog)
        b3 = QPushButton("重新检测")
        b3.clicked.connect(self.refresh_drives)
        for b in (b1, b2, b3):
            btns.addWidget(b)
        btns.addStretch(1)
        cv.addWidget(icon)
        cv.addWidget(self.empty_title)
        cv.addSpacing(4)
        cv.addWidget(self.empty_text)
        cv.addSpacing(8)
        cv.addLayout(btns)
        v.addWidget(card)
        return w

    def _build_disc_page(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(10)

        # 专辑信息条
        info = QFrame(objectName="Card")
        iv = QHBoxLayout(info)
        iv.setContentsMargins(16, 12, 16, 12)
        self.disc_icon = QLabel("💿")
        self.disc_icon.setStyleSheet("font-size:30px")
        self.album_label = QLabel("未知专辑")
        self.album_label.setStyleSheet("font-size:16px;font-weight:700;color:#fff;background:transparent")
        self.disc_meta = QLabel("")
        self.disc_meta.setStyleSheet("color:#8b93a7;background:transparent")
        iv.addWidget(self.disc_icon)
        iv.addSpacing(6)
        info_v = QVBoxLayout()
        info_v.setSpacing(2)
        info_v.addWidget(self.album_label)
        info_v.addWidget(self.disc_meta)
        iv.addLayout(info_v)
        iv.addStretch(1)
        self.check_all_btn = QPushButton("全选")
        self.check_all_btn.setCheckable(True)
        self.check_all_btn.setChecked(True)
        self.check_all_btn.toggled.connect(self._toggle_all)
        iv.addWidget(self.check_all_btn)
        v.addWidget(info)

        # 音轨表
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["", "轨号", "标题", "时长", "状态"])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionMode(QAbstractItemView.NoSelection)
        self.table.setEditTriggers(QAbstractItemView.DoubleClicked)
        self.table.setShowGrid(False)
        self.table.setAlternatingRowColors(True)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(2, QHeaderView.Stretch)
        for col, wpx in ((0, 36), (1, 56), (3, 90), (4, 230)):
            self.table.setColumnWidth(col, wpx)
        self.table.itemChanged.connect(self._on_item_changed)
        self.table.doubleClicked.connect(self._on_table_double)
        v.addWidget(self.table, 1)
        return w

    def _build_player_bar(self) -> QFrame:
        bar = QFrame(objectName="Card")
        bar.setFixedHeight(74)
        hv = QHBoxLayout(bar)
        hv.setContentsMargins(16, 8, 16, 8)
        hv.setSpacing(10)

        self.now_label = QLabel("未在播放")
        self.now_label.setStyleSheet("font-weight:700;color:#fff;font-size:14px")
        self.now_label.setFixedWidth(190)
        self.now_time = QLabel("00:00 / 00:00")
        self.now_time.setStyleSheet("color:#8b93a7;font-family:Consolas,monospace")

        self.btn_prev = QPushButton("⏮", objectName="TransportButton")
        self.btn_play = QPushButton("▶", objectName="PlayButton")
        self.btn_play.setFixedSize(46, 46)
        self.btn_next = QPushButton("⏭", objectName="TransportButton")
        self.btn_stop = QPushButton("⏹", objectName="TransportButton")
        for b in (self.btn_prev, self.btn_next, self.btn_stop):
            b.setFixedSize(38, 38)

        self.seek = QSlider(Qt.Horizontal)
        self.seek.setRange(0, 1000)
        self.seek.sliderPressed.connect(lambda: setattr(self, "_seeking", True))
        self.seek.sliderReleased.connect(self._on_seek_released)

        self.vol_label = QLabel("🔊")
        self.volume = QSlider(Qt.Horizontal)
        self.volume.setFixedWidth(110)
        self.volume.setRange(0, 100)
        self.volume.setValue(int(self.cfg.get("volume", 0.85) * 100))
        self.volume.valueChanged.connect(lambda v: self.player.set_volume(v / 100))

        hv.addWidget(self.btn_prev)
        hv.addWidget(self.btn_play)
        hv.addWidget(self.btn_next)
        hv.addWidget(self.btn_stop)
        hv.addSpacing(6)
        now_v = QVBoxLayout()
        now_v.setSpacing(2)
        now_v.addWidget(self.now_label)
        now_v.addWidget(self.now_time)
        hv.addLayout(now_v)
        hv.addSpacing(10)
        hv.addWidget(self.seek, 1)
        hv.addSpacing(10)
        hv.addWidget(self.vol_label)
        hv.addWidget(self.volume)

        self.btn_prev.clicked.connect(lambda: self._skip(-1))
        self.btn_next.clicked.connect(lambda: self._skip(1))
        self.btn_play.clicked.connect(self._toggle_play)
        self.btn_stop.clicked.connect(self._stop_playback)
        self._set_player_enabled(False)
        return bar

    def _build_right_panel(self) -> QFrame:
        panel = QFrame(objectName="Card")
        panel.setFixedWidth(330)
        v = QVBoxLayout(panel)
        v.setContentsMargins(18, 16, 18, 16)
        v.setSpacing(10)

        cap = QLabel("专辑元数据(CD-Text 自动填充,可修改)", objectName="CardTitle")
        v.addWidget(cap)
        grid = QGridLayout()
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(8)
        self.ed_album = QLineEdit()
        self.ed_artist = QLineEdit()
        self.ed_year = QLineEdit()
        self.ed_year.setPlaceholderText("如 2024")
        self.ed_genre = QLineEdit()
        self.ed_genre.setPlaceholderText("如 Pop")
        grid.addWidget(QLabel("专辑"), 0, 0)
        grid.addWidget(self.ed_album, 0, 1)
        grid.addWidget(QLabel("艺术家"), 1, 0)
        grid.addWidget(self.ed_artist, 1, 1)
        row = QGridLayout()
        row.addWidget(QLabel("年份"), 0, 0)
        row.addWidget(self.ed_year, 0, 1)
        row.addWidget(QLabel("流派"), 0, 2)
        row.addWidget(self.ed_genre, 0, 3)
        grid.addLayout(row, 2, 0, 1, 2)
        v.addLayout(grid)

        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("color:#262c3d")
        v.addWidget(sep)

        cap2 = QLabel("转换设置", objectName="CardTitle")
        v.addWidget(cap2)
        v.addWidget(QLabel("输出目录"))
        out_row = QHBoxLayout()
        self.ed_out = QLineEdit(self.cfg.get("out_dir", ""))
        self.ed_out.setPlaceholderText(str(MUSIC_DIR))
        browse = QPushButton("…")
        browse.setFixedWidth(36)
        browse.clicked.connect(self._choose_out_dir)
        out_row.addWidget(self.ed_out)
        out_row.addWidget(browse)
        v.addLayout(out_row)

        q_row = QHBoxLayout()
        q_row.addWidget(QLabel("音质"))
        self.bitrate = QComboBox()
        for kb, desc in ((320, "320 kbps · 极致 (推荐)"), (256, "256 kbps · 高"),
                         (192, "192 kbps · 标准"), (128, "128 kbps · 节省空间")):
            self.bitrate.addItem(f"{kb} kbps —— {desc}", kb)
        self.bitrate.setCurrentIndex(0)
        q_row.addWidget(self.bitrate, 1)
        v.addLayout(q_row)

        v.addWidget(QLabel("文件名模板"))
        self.ed_template = QLineEdit(self.cfg.get("template", "{track:02d}. {title}"))
        v.addWidget(self.ed_template)

        self.chk_tags = QCheckBox("写入 ID3 标签(标题/艺术家/专辑)")
        self.chk_tags.setChecked(bool(self.cfg.get("write_tags", True)))
        self.chk_verify = QCheckBox("安全模式(每段读两遍校验,更慢更稳)")
        self.chk_verify.setChecked(bool(self.cfg.get("verify", False)))
        v.addWidget(self.chk_tags)
        v.addWidget(self.chk_verify)

        cover_row = QHBoxLayout()
        self.cover_path: str | None = None
        self.btn_cover = QPushButton("选择封面图片…")
        self.btn_cover.clicked.connect(self._choose_cover)
        self.btn_cover_clear = QPushButton("清除")
        self.btn_cover_clear.setFixedWidth(52)
        self.btn_cover_clear.setVisible(False)
        self.btn_cover_clear.clicked.connect(self._clear_cover)
        cover_row.addWidget(self.btn_cover)
        cover_row.addWidget(self.btn_cover_clear)
        v.addLayout(cover_row)

        v.addSpacing(4)
        self.btn_rip = QPushButton("▶  开始转换所选音轨", objectName="AccentButton")
        self.btn_rip.clicked.connect(self.start_rip)
        v.addWidget(self.btn_rip)

        self.progress = QProgressBar()
        self.progress.setValue(0)
        self.progress.setFormat("%p%")
        v.addWidget(self.progress)

        cancel_row = QHBoxLayout()
        self.btn_cancel = QPushButton("取消转换")
        self.btn_cancel.setVisible(False)
        self.btn_cancel.clicked.connect(self._cancel_rip)
        self.btn_open_dir = QPushButton("打开输出文件夹")
        self.btn_open_dir.setVisible(False)
        self.btn_open_dir.clicked.connect(self._open_out_dir)
        cancel_row.addWidget(self.btn_cancel)
        cancel_row.addWidget(self.btn_open_dir)
        v.addLayout(cancel_row)

        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setPlaceholderText("转换日志…")
        v.addWidget(self.log, 1)
        return panel

    # ==================================================================
    # 光盘加载
    # ==================================================================
    def _startup(self, image_path: str | None, drive_letter: str | None) -> None:
        self.refresh_drives()
        if image_path:
            self._load_image(image_path)
        elif drive_letter:
            self._load_physical_drive(drive_letter)
        else:
            self._poll_drives(force=True)

    def refresh_drives(self) -> None:
        cur = self.drive_combo.currentData()
        self.drive_combo.blockSignals(True)
        self.drive_combo.clear()
        letters = list_cd_drives()
        if letters:
            for L in letters:
                self.drive_combo.addItem(f"光驱 {L}:", L)
            if cur in letters:
                self.drive_combo.setCurrentIndex(letters.index(cur))
        else:
            self.drive_combo.addItem("未检测到光驱", None)
        self.drive_combo.blockSignals(False)

    def _load_physical_drive(self, letter: str) -> None:
        try:
            drv = SptiDrive(letter, verify=self.chk_verify.isChecked())
        except DiscError as e:
            self.statusBar().showMessage(str(e), 5000)
            return
        try:
            toc = drv.get_toc()
        except DiscError as e:
            drv.close()
            self._show_empty(str(e))
            return
        self._cleanup_drive()
        self.drive = drv
        self.cda_entries = None
        self.toc = toc
        self._apply_toc_to_ui(source="disc")
        self.statusBar().showMessage(f"已加载光驱 {letter}: 共 {len(toc.audio_tracks)} 条音频轨", 6000)

    def _load_image(self, path: str) -> None:
        try:
            img = open_image(path)
            toc = img.get_toc()
        except DiscError as e:
            QMessageBox.warning(self, "无法打开镜像", str(e))
            return
        self.player.stop()
        self._cleanup_drive()
        self.drive = img
        self.cda_entries = None
        self.toc = toc
        self._apply_toc_to_ui(source="image")
        self.statusBar().showMessage(f"已加载镜像:{os.path.basename(path)}", 6000)

    def _apply_toc_to_ui(self, source: str) -> None:
        toc = self.toc
        self._loading = True
        try:
            self.stack.setCurrentIndex(1)
            album = toc.album or "未知专辑"
            artist = toc.artist or "未知艺术家"
            if self.cda_entries:
                ga, gb = guess_album_info(self.cda_entries)
                if ga:
                    artist, album = ga, (gb or album)
            self.album_label.setText(album)
            k = len(toc.audio_tracks)
            total = format_duration(toc.total_seconds)
            src = {"disc": "CD 光盘", "image": "镜像"}.get(source, source)
            self.disc_meta.setText(f"{artist} · {k} 轨 · 总时长 {total} · 来源:{src}")
            self.ed_album.setText(toc.album or (album if album != "未知专辑" else ""))
            self.ed_artist.setText(toc.artist or (artist if artist != "未知艺术家" else ""))

            audio = {t.number for t in toc.audio_tracks}
            self.table.setRowCount(len(toc.tracks))
            self._titles = {}
            for r, t in enumerate(toc.tracks):
                cb = QTableWidgetItem()
                cb.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
                cb.setCheckState(Qt.Checked if t.is_audio else Qt.Unchecked)
                self.table.setItem(r, 0, cb)
                no = QTableWidgetItem(f"{t.number:02d}")
                no.setFlags(Qt.ItemIsEnabled)
                no.setTextAlignment(Qt.AlignCenter)
                self.table.setItem(r, 1, no)
                title = t.title or f"Track {t.number:02d}"
                self._titles[t.number] = title
                ti = QTableWidgetItem(title)
                ti.setFlags((Qt.ItemIsEnabled | Qt.ItemIsEditable) if t.is_audio else Qt.ItemIsEnabled)
                if not t.is_audio:
                    ti.setText("(数据轨)")
                self.table.setItem(r, 2, ti)
                du = QTableWidgetItem(format_duration(t.duration_seconds) if t.is_audio else "—")
                du.setFlags(Qt.ItemIsEnabled)
                du.setTextAlignment(Qt.AlignCenter)
                self.table.setItem(r, 3, du)
                st = QTableWidgetItem("等待转换" if t.is_audio else "")
                st.setFlags(Qt.ItemIsEnabled)
                self.table.setItem(r, 4, st)
        finally:
            self._loading = False
        self._set_player_enabled(True)
        self.btn_rip.setEnabled(True)
        # 默认输出目录
        if not self.ed_out.text().strip():
            album_dir = sanitize_filename(self.ed_album.text() or "CD_RIP")
            self.ed_out.setText(str(MUSIC_DIR / album_dir))

    def _show_empty(self, msg: str = "") -> None:
        self.stack.setCurrentIndex(0)
        letters = list_cd_drives()
        if msg:
            self.empty_title.setText("无法读取音频 CD")
            self.empty_text.setText(msg + "\n\n放入音频 CD 后点击“重新检测”。")
        elif letters:
            self.empty_title.setText(f"光驱 {letters[0]}: 已就绪,等待放入音频 CD")
        else:
            self.empty_title.setText("未检测到光驱")
        self._set_player_enabled(False)
        self.btn_rip.setEnabled(False)

    def _cleanup_drive(self) -> None:
        self.player.stop()
        self._playing_track = None
        if self.drive:
            self.drive.close()
            self.drive = None
        self.toc = None

    def _poll_drives(self, force: bool = False) -> None:
        if self.worker is not None:
            return
        if isinstance(self.drive, SptiDrive):
            if not self.drive.media_present():
                name = self.drive.letter
                self._cleanup_drive()
                self._show_empty()
                self.statusBar().showMessage(f"光驱 {name}: 中的光盘已取出", 5000)
            return
        # 空闲状态:发现插入的音乐 CD 就自动加载
        try:
            letters = list_cd_drives()
        except Exception:
            return
        for L in letters:
            try:
                drv = SptiDrive(L)
            except DiscError:
                continue
            try:
                if not drv.media_present():
                    drv.close()
                    continue
                toc = drv.get_toc()
            except DiscError:
                drv.close()
                continue
            # 有音频 CD → 自动加载(drv 所有权移交)
            self._cleanup_drive()
            self.drive = drv
            self.toc = toc
            self.cda_entries = None
            self._apply_toc_to_ui(source="disc")
            self.statusBar().showMessage(f"检测到音频 CD(光驱 {L}:),已自动加载", 6000)
            return

    # ==================================================================
    # 导入入口
    # ==================================================================
    def import_cda(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(self, "选择 .cda 文件(可直接选文件夹中的全部)",
                                                "", "CDA 音轨索引 (*.cda)")
        if not paths:
            return
        self._import_cda_paths(paths)

    def _import_cda_paths(self, paths: list[str]) -> None:
        try:
            entries = parse_cda_paths(paths)
        except DiscError as e:
            QMessageBox.warning(self, "导入失败", str(e))
            return
        ga, gb = guess_album_info(entries)
        self.cda_entries = entries
        # 构造伪 TOC 展示
        tracks = [TrackInfo(number=e.track_number, start_lba=e.start_lba,
                            length_lba=e.length_lba if e.valid else 0)
                  for e in entries]
        self.player.stop()
        self._cleanup_drive()
        self.toc = DiscTOC(tracks=tracks, leadout_lba=0, album=gb or "从 .cda 导入",
                           artist=ga)
        self.stack.setCurrentIndex(1)
        self._apply_toc_to_ui(source="cda")
        self.btn_rip.setEnabled(False)
        self.btn_rip.setToolTip("请放入与这些音轨对应的原版 CD,识别后会自动启用转换")
        self.statusBar().showMessage(
            f"已从 .cda 导入 {len(entries)} 条音轨清单 —— "
            f"放入原版 CD 后本软件会自动识别并衔接,然后即可一键转换", 8000)

    def open_image_dialog(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "打开光盘镜像", "",
                                              "光盘镜像 (*.cue *.wav *.bin);;所有文件 (*)")
        if path:
            self._load_image(path)

    # ==================================================================
    # 播放
    # ==================================================================
    def _connect_player(self) -> None:
        self.player.positionChanged.connect(self._on_position)
        self.player.stateChanged.connect(self._on_state)
        self.player.trackFinished.connect(self._on_track_finished)
        self.player.errorOccurred.connect(lambda m: self.statusBar().showMessage(m, 6000))

    def _audio_rows(self) -> list[int]:
        out = []
        for r in range(self.table.rowCount()):
            if self.table.item(r, 0) and self.table.item(r, 0).checkState() == Qt.Checked:
                out.append(r)
        return out

    def _track_at_row(self, r: int) -> TrackInfo | None:
        if self.toc is None or not (0 <= r < len(self.toc.tracks)):
            return None
        return self.toc.tracks[r]

    def play_row(self, r: int) -> None:
        if self.drive is None or self.toc is None:
            return
        t = self._track_at_row(r)
        if not t or not t.is_audio or t.length_lba <= 0:
            return
        title = self._titles.get(t.number) or t.title or f"Track {t.number:02d}"
        self._playing_track = t
        self.player.play(self.drive, t, title)
        self.now_label.setText(f"{t.number:02d} · {title}")
        dur = max(1, int(t.duration_seconds * 10))
        self.seek.setRange(0, dur)
        self._update_row_states()

    def _toggle_play(self) -> None:
        if self.player.state == STATE_PLAYING:
            self.player.pause()
        elif self.player.state == STATE_PAUSED:
            self.player.resume()
        elif self._playing_track is None:
            rows = self._audio_rows()
            if rows:
                self.play_row(rows[0])

    def _toggle_play_shortcut(self) -> None:
        if self.player.state in (STATE_PLAYING, STATE_PAUSED):
            self._toggle_play()

    def _stop_playback(self) -> None:
        self.player.stop()
        self._playing_track = None
        self.now_label.setText("未在播放")
        self.now_time.setText("00:00 / 00:00")
        self.seek.setValue(0)
        self._update_row_states()

    def _skip(self, step: int) -> None:
        rows = [r for r in range(self.table.rowCount())
                if self._track_at_row(r) and self._track_at_row(r).is_audio]
        if not rows:
            return
        cur = self.table.currentRow()
        if self._playing_track:
            for r in rows:
                if self._track_at_row(r) is self._playing_track:
                    cur = r
                    break
        idx = rows.index(cur) if cur in rows else -1
        nxt = rows[(idx + step) % len(rows)]
        self.play_row(nxt)
        self.table.setCurrentCell(nxt, 2)

    def _on_table_double(self, index) -> None:
        if index.column() == 2:
            self.play_row(index.row())

    def _on_seek_released(self) -> None:
        self._seeking = False
        if self._playing_track and self.drive:
            self.player.seek(self.seek.value() / 10.0, self.drive, self._playing_track)

    def _on_position(self, track_no: int, seconds: float) -> None:
        if self._seeking or self._playing_track is None:
            return
        self.now_time.setText(f"{format_duration(seconds)} / "
                              f"{format_duration(self._playing_track.duration_seconds)}")
        self.seek.setValue(min(self.seek.maximum(), int(seconds * 10)))

    def _on_state(self, s: str) -> None:
        self.btn_play.setText("⏸" if s == STATE_PLAYING else "▶")

    def _on_track_finished(self, track_no: int) -> None:
        if self._playing_track and self._playing_track.number == track_no:
            self._skip(1)

    def _set_player_enabled(self, on: bool) -> None:
        for b in (self.btn_prev, self.btn_play, self.btn_next, self.btn_stop):
            b.setEnabled(on)
        self.seek.setEnabled(on)

    def _update_row_states(self) -> None:
        for r in range(self.table.rowCount()):
            t = self._track_at_row(r)
            st = self.table.item(r, 4)
            if not t or not st:
                continue
            if self._playing_track and t is self._playing_track and self.player.state == STATE_PLAYING:
                st.setText("♪ 正在播放")
            elif st.text() not in ("完成 ✓", "抓取中…", "失败 ✗"):
                st.setText("等待转换" if t.is_audio else "")

    # ==================================================================
    # 表格事件
    # ==================================================================
    def _on_item_changed(self, item: QTableWidgetItem) -> None:
        if self._loading or self.toc is None:
            return
        r = item.row()
        if r >= len(self.toc.tracks):
            return
        t = self.toc.tracks[r]
        if item.column() == 2:
            self._titles[t.number] = item.text().strip()

    def _toggle_all(self, checked: bool) -> None:
        self._loading = True
        for r in range(self.table.rowCount()):
            it = self.table.item(r, 0)
            if it and it.flags() & Qt.ItemIsUserCheckable and self._track_at_row(r).is_audio:
                it.setCheckState(Qt.Checked if checked else Qt.Unchecked)
        self._loading = False
        self.check_all_btn.setText("全选" if not checked else "全不选")

    # ==================================================================
    # 转换
    # ==================================================================
    def _choose_out_dir(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "选择输出目录", self.ed_out.text() or str(MUSIC_DIR))
        if d:
            self.ed_out.setText(d)

    def _choose_cover(self) -> None:
        f, _ = QFileDialog.getOpenFileName(self, "选择封面图片", "",
                                           "图片 (*.jpg *.jpeg *.png *.bmp *.webp)")
        if f:
            self.cover_path = f
            self.btn_cover.setText("封面:" + os.path.basename(f))
            self.btn_cover_clear.setVisible(True)

    def _clear_cover(self) -> None:
        self.cover_path = None
        self.btn_cover.setText("选择封面图片…")
        self.btn_cover_clear.setVisible(False)

    def start_rip(self) -> None:
        if self.drive is None or self.toc is None:
            return
        jobs = []
        for r in range(self.table.rowCount()):
            it = self.table.item(r, 0)
            t = self._track_at_row(r)
            if it and t and t.is_audio and it.checkState() == Qt.Checked:
                jobs.append({"track": t, "title": self._titles.get(t.number) or t.title or ""})
        if not jobs:
            QMessageBox.information(self, APP_NAME, "请先勾选要转换的音轨")
            return
        out_dir = self.ed_out.text().strip() or str(MUSIC_DIR / "CD_RIP")
        bitrate = self.bitrate.currentData()
        self._set_rip_busy(True)
        self.progress.setValue(0)
        self.progress.setMaximum(len(jobs) * 100)
        self.log.appendPlainText(f"—— 开始转换 {len(jobs)} 轨 → MP3 {bitrate}kbps ——")
        self.worker = RipWorker(
            self.drive, jobs, out_dir,
            bitrate=bitrate,
            template=self.ed_template.text() or "{track:02d}. {title}",
            write_tags=self.chk_tags.isChecked(),
            album=self.ed_album.text().strip(),
            artist=self.ed_artist.text().strip(),
            year=self.ed_year.text().strip(),
            genre=self.ed_genre.text().strip(),
            cover_image=self.cover_path,
            track_total=len(self.toc.audio_tracks))
        self.worker.trackStart.connect(lambda i: self._set_row_status(i, "抓取中…"))
        self.worker.trackProgress.connect(self._on_rip_progress)
        self.worker.trackDone.connect(lambda i, p: self._set_row_status(i, "完成 ✓"))
        self.worker.trackError.connect(lambda i, m: self._set_row_status(i, "失败 ✗"))
        self.worker.logLine.connect(lambda m: self.log.appendPlainText(m))
        self.worker.finishedAll.connect(self._on_rip_finished)
        self.worker.start()

    def _set_row_status(self, idx: int, text: str) -> None:
        for r in range(self.table.rowCount()):
            t = self._track_at_row(r)
            if t and t.number == self.worker._jobs[idx]["track"].number:
                self.table.item(r, 4).setText(text)
                break

    def _on_rip_progress(self, idx: int, pct: int) -> None:
        if self.worker:
            done_before = sum(1 for j in self.worker._jobs[:idx]) * 100
            self.progress.setValue(done_before + pct)

    def _cancel_rip(self) -> None:
        if self.worker:
            self.worker.stop()
            self.btn_cancel.setEnabled(False)

    def _on_rip_finished(self, ok: int, fail: int, out_dir: str) -> None:
        self.worker = None
        self._set_rip_busy(False)
        self.progress.setValue(self.progress.maximum())
        msg = f"转换完成:成功 {ok} 轨" + (f",失败 {fail} 轨" if fail else "")
        self.log.appendPlainText(f"—— {msg} ——")
        self.statusBar().showMessage(msg + f" · 输出目录:{out_dir}", 10000)
        if ok and not fail:
            QMessageBox.information(self, APP_NAME, f"{msg}\n输出目录:{out_dir}")
        elif fail:
            QMessageBox.warning(self, APP_NAME, f"{msg}\n详见日志;若是划痕盘可开启“安全模式”重试")

    def _set_rip_busy(self, busy: bool) -> None:
        self.btn_rip.setEnabled(not busy)
        self.btn_cancel.setVisible(busy)
        self.btn_cancel.setEnabled(True)
        self.btn_open_dir.setVisible(not busy and False)
        self.chk_verify.setEnabled(not busy)
        self.drive_combo.setEnabled(not busy)

    def _open_out_dir(self) -> None:
        d = self.ed_out.text().strip()
        if d and os.path.isdir(d):
            os.startfile(d)  # noqa: S606

    # ==================================================================
    # 拖放 / 关闭
    # ==================================================================
    def dragEnterEvent(self, e) -> None:
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e) -> None:
        paths = [u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()]
        if not paths:
            return
        exts = {os.path.splitext(p)[1].lower() for p in paths}
        if ".cue" in exts or ".wav" in exts or ".bin" in exts:
            img = next(p for p in paths if os.path.splitext(p)[1].lower() in (".cue", ".wav", ".bin"))
            self._load_image(img)
        elif ".cda" in exts or all(os.path.isdir(p) for p in paths):
            self._import_cda_paths(paths)

    def closeEvent(self, e) -> None:
        if self.worker is not None:
            ret = QMessageBox.question(self, APP_NAME, "正在转换,确定退出吗?",
                                       QMessageBox.Yes | QMessageBox.No)
            if ret != QMessageBox.Yes:
                e.ignore()
                return
            self.worker.stop()
            self.worker.wait(3000)
        self.player.stop()
        self.cfg.update({
            "out_dir": self.ed_out.text().strip(),
            "bitrate": self.bitrate.currentData(),
            "template": self.ed_template.text(),
            "verify": self.chk_verify.isChecked(),
            "write_tags": self.chk_tags.isChecked(),
            "volume": self.volume.value() / 100,
            "last_drive": self.drive_combo.currentData() or "",
        })
        save_config(self.cfg)
        self._cleanup_drive()
        super().closeEvent(e)

    def _load_settings_into_ui(self) -> None:
        self.player.set_volume(self.volume.value() / 100)


def run_gui(image_path: str | None = None, drive_letter: str | None = None) -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setStyleSheet(QSS)
    win = MainWindow(image_path=image_path, drive_letter=drive_letter)
    win.show()
    return app.exec()
