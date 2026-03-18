#!/usr/bin/env python3
"""
burnwright_gui.py - Graphical front end for disc_maker.py

Requires PySide6 or PySide2:
  pip install PySide6 --break-system-packages
"""

import sys
import os
import threading
import logging
import queue
from pathlib import Path

# ---------------------------------------------------------------------------
# PySide6 / PySide2 compatibility shim
# ---------------------------------------------------------------------------

try:
    from PySide6.QtWidgets import (
        QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
        QGridLayout, QLabel, QLineEdit, QPushButton, QRadioButton,
        QButtonGroup, QCheckBox, QFileDialog, QListWidget, QListWidgetItem,
        QTextEdit, QProgressBar, QGroupBox, QSizePolicy, QSplitter,
        QAbstractItemView, QFrame
    )
    from PySide6.QtCore import Qt, QThread, Signal, QObject
    from PySide6.QtGui import QFont, QColor, QTextCursor, QPalette
    PYSIDE_VERSION = 6
except ImportError:
    try:
        from PySide2.QtWidgets import (
            QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
            QGridLayout, QLabel, QLineEdit, QPushButton, QRadioButton,
            QButtonGroup, QCheckBox, QFileDialog, QListWidget, QListWidgetItem,
            QTextEdit, QProgressBar, QGroupBox, QSizePolicy, QSplitter,
            QAbstractItemView, QFrame
        )
        from PySide2.QtCore import Qt, QThread, Signal, QObject
        from PySide2.QtGui import QFont, QColor, QTextCursor, QPalette
        PYSIDE_VERSION = 2
    except ImportError:
        print("ERROR: PySide6 or PySide2 is required.")
        print("Install with: pip install PySide6 --break-system-packages")
        sys.exit(1)

# ---------------------------------------------------------------------------
# Import disc_maker pipeline functions
# ---------------------------------------------------------------------------

# Add the directory containing disc_maker.py to the path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    import disc_maker as dm
except ImportError:
    print("ERROR: disc_maker.py not found in the same directory as burnwright_gui.py")
    sys.exit(1)


# ---------------------------------------------------------------------------
# Worker thread — runs the encode pipeline without blocking the UI
# ---------------------------------------------------------------------------

class EncodeWorker(QObject):
    """
    Runs the disc_maker pipeline in a background thread.
    Emits signals to update the GUI.
    """

    log_message    = Signal(str, str)   # (level, message)
    step_progress  = Signal(float)      # 0.0 - 100.0
    step_label     = Signal(str)        # current step description
    overall_progress = Signal(float)    # 0.0 - 100.0
    overall_label  = Signal(str)        # overall status
    finished       = Signal(bool, str)  # (success, final_message)

    def __init__(self, args_dict, config):
        super().__init__()
        self._args_dict = args_dict
        self._config    = config
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        """Execute the full pipeline. Called from QThread."""
        try:
            self._execute()
        except Exception as e:
            self.log_message.emit("ERROR", f"Unexpected error: {e}")
            self.finished.emit(False, str(e))

    def _emit_log(self, level, msg):
        if not self._cancelled:
            self.log_message.emit(level, msg)

    def _execute(self):
        config  = self._config
        ad      = self._args_dict

        fmt_name    = ad["format"]
        disc_name   = ad["name"]
        input_files = ad["input_files"]
        output_dir  = Path(ad["output_dir"])
        disc_size   = ad["disc_size"]
        no_split    = ad["no_split"]
        scene_detect = ad["scene_detect"]
        force       = ad["force"]
        keep_temp   = ad["keep_temp"]
        dry_run     = ad["dry_run"]

        output_dir.mkdir(parents=True, exist_ok=True)

        # Set up a logging handler that emits to the GUI
        log = self._make_logger(output_dir, disc_name)

        total_steps = 6  # probe, layout, scene_detect, encode, build, done
        step = 0

        def advance(label):
            nonlocal step
            step += 1
            pct = step / total_steps * 100
            self.overall_progress.emit(pct)
            self.overall_label.emit(label)
            self.step_progress.emit(0.0)
            self.step_label.emit(label)

        # --- Step 1: Probe ---
        advance("Probing input files...")
        log.info(f"disc_maker starting")
        log.info(f"Format: {fmt_name.upper()}")
        log.info(f"Name:   {disc_name}")
        log.info(f"Output: {output_dir}")

        probed_files, total_duration = dm.probe_all(input_files, log)

        if self._cancelled:
            self.finished.emit(False, "Cancelled")
            return

        # --- Step 2: Layout ---
        advance("Calculating disc layout...")
        fmt_config   = config["formats"][fmt_name]
        safety_margin = config.get("safety_margin", 0.95)
        split_threshold_seconds = config.get("split_threshold_minutes", 60) * 60

        discs, capacity_seconds = dm.calculate_disc_layout(
            probed_files, total_duration,
            fmt_config, disc_size, safety_margin,
            no_split, split_threshold_seconds, log
        )
        dm.format_layout(discs, disc_name, log)

        # Disk space check
        import shutil
        temp_dir = Path(config.get("temp_dir", "/tmp/disc_maker")) / disc_name
        temp_dir.mkdir(parents=True, exist_ok=True)

        video_bps = fmt_config["video_bitrate"] * 1000 / 8
        audio_bps = fmt_config["audio_bitrate"] * 1000 / 8
        estimated_bytes = int(total_duration * (video_bps + audio_bps) * 3)
        free_bytes = shutil.disk_usage(temp_dir).free

        if estimated_bytes > free_bytes:
            msg = (f"Insufficient disk space — need "
                   f"~{estimated_bytes/(1024**3):.1f} GB, "
                   f"have {free_bytes/(1024**3):.1f} GB free")
            log.error(msg)
            self.finished.emit(False, msg)
            return

        # --- Step 3: Scene detection ---
        if scene_detect:
            advance("Scene detection...")
            window_seconds = config.get("scene_search_window_seconds", 180)
            split_files = set()
            for disc in discs:
                for seg in disc:
                    if seg["is_split"]:
                        split_files.add(seg["file"])

            for split_file in split_files:
                if self._cancelled:
                    self.finished.emit(False, "Cancelled")
                    return
                log.info(f"Finding clean cuts in: {Path(split_file).name}")
                discs = dm.apply_scene_detection(
                    discs, split_file, window_seconds, log
                )
            dm.format_layout(discs, disc_name, log)
        else:
            step += 1  # skip scene detect step in count

        if dry_run:
            self.finished.emit(True, "Dry run complete — no files encoded")
            return

        if self._cancelled:
            self.finished.emit(False, "Cancelled")
            return

        # --- Step 4: Encode ---
        widescreen_threshold = config.get("widescreen_threshold", 1.5)
        total_discs = len(discs)

        for disc_idx, disc_segments in enumerate(discs, 1):
            if self._cancelled:
                self.finished.emit(False, "Cancelled")
                return

            advance(f"Encoding disc {disc_idx} of {total_discs}...")
            self.overall_progress.emit((3 + disc_idx) / (total_steps + total_discs - 1) * 100)

            probe_lookup = {info["path"]: info for info in probed_files}
            muxed_paths = []

            for seg_idx, segment in enumerate(disc_segments):
                if self._cancelled:
                    self.finished.emit(False, "Cancelled")
                    return

                file_info = probe_lookup.get(segment["file"])
                if file_info is None:
                    log.error(f"No probe info for {segment['file']}")
                    self.finished.emit(False, "Encode error")
                    return

                seg_label = f"{disc_name}_d{disc_idx:02d}_s{seg_idx+1:02d}"
                ext = ".m1v" if fmt_config["video_codec"] == "mpeg1video" else ".m2v"
                video_path = temp_dir / f"{seg_label}_video{ext}"
                audio_path = temp_dir / f"{seg_label}_audio.mpa"
                muxed_path = temp_dir / f"{seg_label}.mpg"

                w, h = dm.get_resolution(file_info, fmt_config, widescreen_threshold, log)
                audio_filter = dm.get_audio_filter(file_info["audio_channels"], log)
                convert_fps  = dm.needs_fps_conversion(file_info["fps"], log)

                seg_duration = segment["duration"]
                seg_label_display = (
                    f"Disc {disc_idx}/{total_discs} — "
                    f"Segment {seg_idx+1}/{len(disc_segments)} — Video"
                )
                self.step_label.emit(seg_label_display)

                # Patch run_cmd to emit progress signals to GUI
                original_run_cmd = dm.run_cmd

                def gui_run_cmd(cmd, log, label, duration_seconds=None):
                    import subprocess, time, re
                    log.info(f"  Running: {label}")

                    is_ffmpeg = cmd[0] == "ffmpeg"
                    show_progress = is_ffmpeg and duration_seconds and duration_seconds > 0

                    try:
                        proc = subprocess.Popen(
                            cmd,
                            stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE,
                            text=True, bufsize=1
                        )
                    except FileNotFoundError as e:
                        log.error(f"  Command not found: {cmd[0]} — {e}")
                        return False

                    stderr_lines = []
                    while True:
                        line = proc.stderr.readline()
                        if not line and proc.poll() is not None:
                            break
                        if line:
                            stderr_lines.append(line)
                            if show_progress:
                                match = re.search(
                                    r'time=(\d+):(\d+):(\d+\.\d+)', line)
                                if match:
                                    h2 = int(match.group(1))
                                    m2 = int(match.group(2))
                                    s2 = float(match.group(3))
                                    current = h2*3600 + m2*60 + s2
                                    pct = min(100.0, current / duration_seconds * 100)
                                    self.step_progress.emit(pct)

                        if self._cancelled:
                            proc.terminate()
                            return False

                    proc.wait()
                    if show_progress:
                        self.step_progress.emit(100.0)

                    if proc.returncode != 0:
                        stderr_tail = "".join(stderr_lines[-20:])
                        log.error(f"  {label} failed (exit {proc.returncode})")
                        log.error(f"  STDERR: {stderr_tail[-2000:]}")
                        return False
                    return True

                dm.run_cmd = gui_run_cmd

                # Video
                self.step_label.emit(
                    f"Disc {disc_idx}/{total_discs} — Seg {seg_idx+1} — Video encode")
                if force or not video_path.exists():
                    cmd = dm.build_video_cmd(
                        segment, file_info, fmt_config,
                        video_path, w, h, convert_fps, log
                    )
                    if not gui_run_cmd(cmd, log,
                                       f"ffmpeg video encode {seg_label}",
                                       duration_seconds=seg_duration):
                        dm.run_cmd = original_run_cmd
                        self.finished.emit(False, "Video encode failed")
                        return

                # Audio
                self.step_label.emit(
                    f"Disc {disc_idx}/{total_discs} — Seg {seg_idx+1} — Audio encode")
                self.step_progress.emit(0.0)
                if force or not audio_path.exists():
                    cmd = dm.build_audio_cmd(
                        segment, file_info, fmt_config,
                        audio_path, audio_filter, log
                    )
                    if not gui_run_cmd(cmd, log,
                                       f"ffmpeg audio encode {seg_label}"):
                        dm.run_cmd = original_run_cmd
                        self.finished.emit(False, "Audio encode failed")
                        return

                # Mux
                self.step_label.emit(
                    f"Disc {disc_idx}/{total_discs} — Seg {seg_idx+1} — Muxing")
                self.step_progress.emit(50.0)
                if force or not muxed_path.exists():
                    cmd = dm.build_mplex_cmd(
                        video_path, audio_path, muxed_path, fmt_config)
                    if not gui_run_cmd(cmd, log,
                                       f"mplex mux {seg_label}"):
                        dm.run_cmd = original_run_cmd
                        self.finished.emit(False, "Mux failed")
                        return

                self.step_progress.emit(100.0)
                muxed_paths.append(muxed_path)
                dm.run_cmd = original_run_cmd

            # --- Step 5: Build disc image ---
            self.step_label.emit(f"Building disc image {disc_idx} of {total_discs}...")
            self.step_progress.emit(0.0)

            result = dm.build_disc_image(
                disc_idx, total_discs, muxed_paths, fmt_config,
                disc_name, output_dir, temp_dir, log
            )
            if result is None:
                self.finished.emit(False, f"Disc image build failed for disc {disc_idx}")
                return

            self.step_progress.emit(100.0)

        # --- Step 6: Manifest and cleanup ---
        advance("Writing manifest...")

        # Rebuild all_muxed for manifest (paths already computed above)
        # Simple approach: write manifest from disc layout
        import datetime
        manifest_path = output_dir / f"{disc_name}_manifest.txt"
        lines = [
            "disc_maker manifest",
            f"Generated: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"Name:      {disc_name}",
            f"Format:    {fmt_name.upper()}",
            f"Disc size: {disc_size}",
            f"Discs:     {len(discs)}",
            ""
        ]
        for i, disc_segments in enumerate(discs, 1):
            label = f"{disc_name}_{i:02d}"
            disc_duration = sum(s["duration"] for s in disc_segments)
            lines.append(f"--- Disc {i}: {label}.bin ---")
            lines.append(
                f"Total duration: "
                f"{int(disc_duration//60):02d}:{int(disc_duration%60):02d}"
            )
            lines.append("Contents:")
            for seg in disc_segments:
                fname     = Path(seg["file"]).name
                start_str = f"{int(seg['start']//60):02d}:{int(seg['start']%60):02d}"
                end_str   = f"{int(seg['end']//60):02d}:{int(seg['end']%60):02d}"
                split_tag = " [split]" if seg["is_split"] else ""
                lines.append(f"  {fname}  {start_str} -> {end_str}{split_tag}")
            lines.append("")

        with open(manifest_path, "w") as f:
            f.write("\n".join(lines))
        log.info(f"Manifest written: {manifest_path}")

        if not keep_temp:
            import shutil as _shutil
            _shutil.rmtree(temp_dir, ignore_errors=True)
            log.info("Temp files removed.")

        self.overall_progress.emit(100.0)
        self.overall_label.emit("Complete")
        self.step_progress.emit(100.0)
        self.step_label.emit("Done")

        disc_count = len(discs)
        self.finished.emit(
            True,
            f"Done. {disc_count} disc image{'s' if disc_count != 1 else ''} "
            f"written to {output_dir}"
        )

    def _make_logger(self, output_dir, disc_name):
        """Create a logger that emits to both the GUI and a log file."""
        log_path = Path(output_dir) / f"{disc_name}.log"
        logger   = logging.getLogger(f"burnwright.{disc_name}")
        logger.setLevel(logging.DEBUG)
        logger.handlers.clear()

        # File handler
        fh = logging.FileHandler(log_path)
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(logging.Formatter(
            "%(asctime)s [%(levelname)s] %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S"
        ))
        logger.addHandler(fh)

        # GUI signal handler
        worker = self

        class GUIHandler(logging.Handler):
            def emit(self, record):
                worker.log_message.emit(
                    record.levelname,
                    self.format(record)
                )

        gh = GUIHandler()
        gh.setLevel(logging.INFO)
        gh.setFormatter(logging.Formatter(
            "%(asctime)s [%(levelname)s] %(message)s",
            datefmt="%H:%M:%S"
        ))
        logger.addHandler(gh)

        return logger


# ---------------------------------------------------------------------------
# Main window
# ---------------------------------------------------------------------------

class BurnwrightWindow(QMainWindow):

    def __init__(self):
        super().__init__()
        self.setWindowTitle("burnwright")
        self.setMinimumWidth(720)
        self.setMinimumHeight(680)

        self._worker  = None
        self._thread  = None
        self._config  = self._load_config()

        central = QWidget()
        self.setCentralWidget(central)
        root_layout = QVBoxLayout(central)
        root_layout.setSpacing(10)
        root_layout.setContentsMargins(16, 16, 16, 16)

        # Title
        title = QLabel("burnwright")
        title_font = QFont()
        title_font.setPointSize(18)
        title_font.setBold(True)
        title.setFont(title_font)
        root_layout.addWidget(title)

        tagline = QLabel("Your media. Your discs. Your call.")
        tagline_font = QFont()
        tagline_font.setItalic(True)
        tagline.setFont(tagline_font)
        root_layout.addWidget(tagline)

        # Divider
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setFrameShadow(QFrame.Sunken)
        root_layout.addWidget(line)

        # Options grid
        options_group = QGroupBox("Job settings")
        grid = QGridLayout(options_group)
        grid.setSpacing(8)
        row = 0

        # Format
        grid.addWidget(QLabel("Format:"), row, 0)
        fmt_widget = QWidget()
        fmt_layout = QHBoxLayout(fmt_widget)
        fmt_layout.setContentsMargins(0, 0, 0, 0)
        self._fmt_vcd  = QRadioButton("VCD")
        self._fmt_svcd = QRadioButton("SVCD")
        self._fmt_vcd.setChecked(True)
        self._fmt_group = QButtonGroup()
        self._fmt_group.addButton(self._fmt_vcd,  1)
        self._fmt_group.addButton(self._fmt_svcd, 2)
        fmt_layout.addWidget(self._fmt_vcd)
        fmt_layout.addWidget(self._fmt_svcd)
        fmt_layout.addStretch()
        grid.addWidget(fmt_widget, row, 1)
        row += 1

        # Name
        grid.addWidget(QLabel("Name:"), row, 0)
        self._name_edit = QLineEdit()
        self._name_edit.setPlaceholderText("e.g. Parker_Lewis or My_Movie")
        grid.addWidget(self._name_edit, row, 1)
        row += 1

        # Input files
        grid.addWidget(QLabel("Input:"), row, 0)
        input_widget = QWidget()
        input_layout = QVBoxLayout(input_widget)
        input_layout.setContentsMargins(0, 0, 0, 0)
        input_layout.setSpacing(4)

        input_btn_row = QWidget()
        input_btn_layout = QHBoxLayout(input_btn_row)
        input_btn_layout.setContentsMargins(0, 0, 0, 0)
        self._add_files_btn   = QPushButton("Add files...")
        self._add_folder_btn  = QPushButton("Add folder...")
        self._remove_file_btn = QPushButton("Remove selected")
        input_btn_layout.addWidget(self._add_files_btn)
        input_btn_layout.addWidget(self._add_folder_btn)
        input_btn_layout.addWidget(self._remove_file_btn)
        input_btn_layout.addStretch()

        self._file_list = QListWidget()
        self._file_list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self._file_list.setMaximumHeight(100)

        input_layout.addWidget(input_btn_row)
        input_layout.addWidget(self._file_list)
        grid.addWidget(input_widget, row, 1)
        row += 1

        # Output directory
        grid.addWidget(QLabel("Output:"), row, 0)
        output_widget = QWidget()
        output_layout = QHBoxLayout(output_widget)
        output_layout.setContentsMargins(0, 0, 0, 0)
        self._output_edit = QLineEdit()
        self._output_edit.setPlaceholderText("Output directory for BIN/CUE files")
        self._output_browse_btn = QPushButton("Browse...")
        output_layout.addWidget(self._output_edit)
        output_layout.addWidget(self._output_browse_btn)
        grid.addWidget(output_widget, row, 1)
        row += 1

        # Disc size
        grid.addWidget(QLabel("Disc size:"), row, 0)
        size_widget = QWidget()
        size_layout = QHBoxLayout(size_widget)
        size_layout.setContentsMargins(0, 0, 0, 0)
        self._size_74 = QRadioButton("74 min  (standard CD-R)")
        self._size_80 = QRadioButton("80 min  (overburn CD-R)")
        self._size_74.setChecked(True)
        self._size_group = QButtonGroup()
        self._size_group.addButton(self._size_74, 1)
        self._size_group.addButton(self._size_80, 2)
        size_layout.addWidget(self._size_74)
        size_layout.addWidget(self._size_80)
        size_layout.addStretch()
        grid.addWidget(size_widget, row, 1)
        row += 1

        # Checkboxes
        grid.addWidget(QLabel("Options:"), row, 0)
        opts_widget = QWidget()
        opts_layout = QHBoxLayout(opts_widget)
        opts_layout.setContentsMargins(0, 0, 0, 0)
        self._cb_scene   = QCheckBox("Scene detect")
        self._cb_nosplit = QCheckBox("Episode mode (no split)")
        self._cb_dryrun  = QCheckBox("Dry run (preview only)")
        self._cb_force   = QCheckBox("Force re-encode")
        self._cb_keep    = QCheckBox("Keep temp files")
        for cb in (self._cb_scene, self._cb_nosplit, self._cb_dryrun,
                   self._cb_force, self._cb_keep):
            opts_layout.addWidget(cb)
        opts_layout.addStretch()
        grid.addWidget(opts_widget, row, 1)
        row += 1

        root_layout.addWidget(options_group)

        # Progress
        progress_group = QGroupBox("Progress")
        progress_layout = QVBoxLayout(progress_group)

        step_label_row = QHBoxLayout()
        self._step_label = QLabel("Ready")
        step_label_row.addWidget(self._step_label)
        step_label_row.addStretch()
        progress_layout.addLayout(step_label_row)

        self._step_bar = QProgressBar()
        self._step_bar.setRange(0, 1000)
        self._step_bar.setValue(0)
        self._step_bar.setFormat("Current step: %p%")
        progress_layout.addWidget(self._step_bar)

        overall_label_row = QHBoxLayout()
        self._overall_label = QLabel("Waiting")
        overall_label_row.addWidget(self._overall_label)
        overall_label_row.addStretch()
        progress_layout.addLayout(overall_label_row)

        self._overall_bar = QProgressBar()
        self._overall_bar.setRange(0, 1000)
        self._overall_bar.setValue(0)
        self._overall_bar.setFormat("Overall: %p%")
        progress_layout.addWidget(self._overall_bar)

        root_layout.addWidget(progress_group)

        # Log area
        log_group = QGroupBox("Log")
        log_layout = QVBoxLayout(log_group)
        self._log_area = QTextEdit()
        self._log_area.setReadOnly(True)
        self._log_area.setFont(QFont("Monospace", 9))
        self._log_area.setMinimumHeight(180)
        log_layout.addWidget(self._log_area)
        root_layout.addWidget(log_group)

        # Buttons
        btn_row = QHBoxLayout()
        self._run_btn    = QPushButton("Let's go")
        self._cancel_btn = QPushButton("Changed my mind")
        self._cancel_btn.setEnabled(False)

        self._run_btn.setMinimumHeight(36)
        self._cancel_btn.setMinimumHeight(36)

        run_font = QFont()
        run_font.setBold(True)
        self._run_btn.setFont(run_font)

        btn_row.addStretch()
        btn_row.addWidget(self._run_btn)
        btn_row.addWidget(self._cancel_btn)
        root_layout.addLayout(btn_row)

        # Connect signals
        self._add_files_btn.clicked.connect(self._add_files)
        self._add_folder_btn.clicked.connect(self._add_folder)
        self._remove_file_btn.clicked.connect(self._remove_files)
        self._output_browse_btn.clicked.connect(self._browse_output)
        self._run_btn.clicked.connect(self._run)
        self._cancel_btn.clicked.connect(self._cancel)

    # -----------------------------------------------------------------------
    # Config
    # -----------------------------------------------------------------------

    def _load_config(self):
        config_path = Path(__file__).parent / "disc_maker_config.json"
        if config_path.exists():
            import json
            with open(config_path) as f:
                return json.load(f)
        # Minimal fallback
        return {
            "formats": {
                "vcd":  {"capacity_seconds": 4440, "capacity_bytes_74min": 681574400,
                         "capacity_bytes_80min": 734003200, "video_bitrate": 1150,
                         "max_bitrate": 1150, "audio_bitrate": 224, "bufsize": 40,
                         "gop_size": 18, "framerate": "29.97",
                         "resolution_standard": [352, 240],
                         "resolution_widescreen": [352, 240],
                         "video_codec": "mpeg1video", "mplex_format": 1,
                         "vcdimager_class": "vcd", "vcdimager_version": "2.0"},
                "svcd": {"capacity_seconds": 2700, "capacity_bytes_74min": 681574400,
                         "capacity_bytes_80min": 734003200, "video_bitrate": 2000,
                         "max_bitrate": 2600, "audio_bitrate": 224, "bufsize": 224,
                         "gop_size": 15, "framerate": "29.97",
                         "resolution_standard": [480, 480],
                         "resolution_widescreen": [480, 272],
                         "video_codec": "mpeg2video", "mplex_format": 4,
                         "vcdimager_class": "svcd", "vcdimager_version": "1.0"}
            },
            "safety_margin": 0.95,
            "disc_size": "74min",
            "scene_search_window_seconds": 180,
            "widescreen_threshold": 1.5,
            "split_threshold_minutes": 60,
            "temp_dir": "/tmp/disc_maker",
            "keep_temp": False,
            "log_level": "info"
        }

    # -----------------------------------------------------------------------
    # File/folder management
    # -----------------------------------------------------------------------

    def _add_files(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Select video files", str(Path.home()),
            "Video files (*.mp4 *.mkv *.avi *.mov *.wmv *.flv *.m4v *.mpg *.mpeg *.ts)"
            ";;All files (*)"
        )
        for p in paths:
            if not self._file_already_added(p):
                self._file_list.addItem(QListWidgetItem(p))

    def _add_folder(self):
        folder = QFileDialog.getExistingDirectory(
            self, "Select folder containing video files", str(Path.home()))
        if folder:
            video_exts = {".mp4", ".mkv", ".avi", ".mov", ".wmv",
                          ".flv", ".m4v", ".mpg", ".mpeg", ".ts"}
            for f in sorted(Path(folder).iterdir()):
                if f.suffix.lower() in video_exts:
                    if not self._file_already_added(str(f)):
                        self._file_list.addItem(QListWidgetItem(str(f)))

    def _remove_files(self):
        for item in self._file_list.selectedItems():
            self._file_list.takeItem(self._file_list.row(item))

    def _file_already_added(self, path):
        for i in range(self._file_list.count()):
            if self._file_list.item(i).text() == path:
                return True
        return False

    def _browse_output(self):
        folder = QFileDialog.getExistingDirectory(
            self, "Select output directory", str(Path.home()))
        if folder:
            self._output_edit.setText(folder)

    # -----------------------------------------------------------------------
    # Run / cancel
    # -----------------------------------------------------------------------

    def _run(self):
        # Validate
        if not self._name_edit.text().strip():
            self._append_log("ERROR", "Please enter a name for this job.")
            return
        if self._file_list.count() == 0:
            self._append_log("ERROR", "Please add at least one input file.")
            return
        if not self._output_edit.text().strip():
            self._append_log("ERROR", "Please select an output directory.")
            return

        fmt      = "vcd" if self._fmt_vcd.isChecked() else "svcd"
        name     = self._name_edit.text().strip().replace(" ", "_")
        inputs   = [self._file_list.item(i).text()
                    for i in range(self._file_list.count())]
        output   = self._output_edit.text().strip()
        size     = "74min" if self._size_74.isChecked() else "80min"

        args_dict = {
            "format":       fmt,
            "name":         name,
            "input_files":  inputs,
            "output_dir":   output,
            "disc_size":    size,
            "no_split":     self._cb_nosplit.isChecked(),
            "scene_detect": self._cb_scene.isChecked(),
            "dry_run":      self._cb_dryrun.isChecked(),
            "force":        self._cb_force.isChecked(),
            "keep_temp":    self._cb_keep.isChecked(),
        }

        self._log_area.clear()
        self._step_bar.setValue(0)
        self._overall_bar.setValue(0)
        self._step_label.setText("Starting...")
        self._overall_label.setText("Starting...")
        self._run_btn.setEnabled(False)
        self._cancel_btn.setEnabled(True)

        self._worker = EncodeWorker(args_dict, self._config)
        self._thread = QThread()
        self._worker.moveToThread(self._thread)

        self._thread.started.connect(self._worker.run)
        self._worker.log_message.connect(self._append_log)
        self._worker.step_progress.connect(
            lambda v: self._step_bar.setValue(int(v * 10)))
        self._worker.step_label.connect(self._step_label.setText)
        self._worker.overall_progress.connect(
            lambda v: self._overall_bar.setValue(int(v * 10)))
        self._worker.overall_label.connect(self._overall_label.setText)
        self._worker.finished.connect(self._job_finished)

        self._thread.start()

    def _cancel(self):
        if self._worker:
            self._worker.cancel()
            self._cancel_btn.setEnabled(False)
            self._append_log("INFO", "Cancellation requested — stopping after current step...")

    def _job_finished(self, success, message):
        self._run_btn.setEnabled(True)
        self._cancel_btn.setEnabled(False)
        if success:
            self._overall_label.setText("Complete")
            self._step_label.setText("Done")
            self._overall_bar.setValue(1000)
            self._step_bar.setValue(1000)
            self._append_log("INFO", f"=== {message} ===")
        else:
            self._overall_label.setText("Failed or cancelled")
            self._append_log("ERROR", f"Job ended: {message}")

        if self._thread:
            self._thread.quit()
            self._thread.wait()

    # -----------------------------------------------------------------------
    # Log display
    # -----------------------------------------------------------------------

    def _append_log(self, level, message):
        level_colors = {
            "DEBUG":   "#888888",
            "INFO":    "#dddddd",
            "WARNING": "#ffaa00",
            "ERROR":   "#ff5555",
        }
        color = level_colors.get(level, "#dddddd")
        html = (f'<span style="color:{color}; font-family:monospace; '
                f'font-size:9pt;">{message}</span><br>')
        self._log_area.moveCursor(QTextCursor.End)
        self._log_area.insertHtml(html)
        self._log_area.moveCursor(QTextCursor.End)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    app = QApplication(sys.argv)
    app.setApplicationName("burnwright")

    window = BurnwrightWindow()
    window.show()
    sys.exit(app.exec() if PYSIDE_VERSION == 6 else app.exec_())


if __name__ == "__main__":
    main()
