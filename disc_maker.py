#!/usr/bin/env python3
"""
disc_maker.py - Automates VCD/SVCD disc image creation from video files.
"""

import argparse
import json
import logging
import os
import sys
from pathlib import Path


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

def load_config(config_path):
    """Load JSON config file."""
    config_path = Path(config_path)
    if not config_path.exists():
        print(f"ERROR: Config file not found: {config_path}")
        sys.exit(1)
    with open(config_path) as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

def setup_logging(log_level, output_dir, disc_name):
    """Set up logging to console and file."""
    numeric_level = getattr(logging, log_level.upper(), logging.INFO)
    log_path = Path(output_dir) / f"{disc_name}.log"

    handlers = [
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(log_path)
    ]

    logging.basicConfig(
        level=numeric_level,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=handlers
    )
    return logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

def parse_args():
    parser = argparse.ArgumentParser(
        description="Create VCD/SVCD disc images from video files.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s --format vcd --input ~/Videos/Parker_Lewis/ --name Parker_Lewis
  %(prog)s --format svcd --input movie.mkv --name My_Movie --scene-detect
  %(prog)s --format vcd --input ep1.mp4 ep2.mp4 ep3.mp4 --name Show --dry-run
  %(prog)s --format svcd --input movie.mkv --name Movie --disc-size 80min
        """
    )

    parser.add_argument(
        "--format",
        required=True,
        help="Output format — must match a key in disc_maker_config.json formats section"
    )

    parser.add_argument(
        "--input",
        nargs="+",
        required=True,
        help="Input file(s) or a single directory containing video files"
    )

    parser.add_argument(
        "--output",
        default=None,
        help="Output directory (default: current directory)"
    )

    parser.add_argument(
        "--name",
        required=True,
        help="Base name for output files e.g. Parker_Lewis"
    )

    parser.add_argument(
        "--disc-size",
        choices=["74min", "80min"],
        default=None,
        help="Target CD-R size (default: from config)"
    )

    parser.add_argument(
        "--scene-detect",
        action="store_true",
        default=False,
        help="Use PySceneDetect to find clean split points near disc boundaries"
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Calculate and display disc layout without encoding anything"
    )

    parser.add_argument(
        "--keep-temp",
        action="store_true",
        default=False,
        help="Keep intermediate encode files after disc image is built"
    )

    parser.add_argument(
        "--force",
        action="store_true",
        default=False,
        help="Re-encode even if intermediate files already exist"
    )

    parser.add_argument(
        "--no-split",
        action="store_true",
        default=False,
        help="Never split input files mid-file — always break at file boundaries"
    )

    parser.add_argument(
        "--split-threshold",
        type=float,
        default=None,
        help="Files longer than this many minutes are treated as movies and may be split (default: from config)"
    )

    parser.add_argument(
        "--balance-discs",
        action="store_true",
        default=False,
        help="Distribute content evenly across discs rather than packing each to capacity"
    )

    parser.add_argument(
        "--config",
        default=os.path.join(os.path.dirname(__file__), "disc_maker_config.json"),
        help="Path to config JSON file (default: disc_maker_config.json)"
    )

    return parser.parse_args()


# ---------------------------------------------------------------------------
# Input resolution
# ---------------------------------------------------------------------------

def resolve_inputs(input_args):
    """
    Accept either:
      - One or more explicit file paths
      - A single directory (scans for video files)
    Returns sorted list of Path objects.
    """
    video_extensions = {
        ".mp4", ".mkv", ".avi", ".mov", ".wmv",
        ".flv", ".m4v", ".mpg", ".mpeg", ".ts"
    }

    files = []

    if len(input_args) == 1 and Path(input_args[0]).is_dir():
        directory = Path(input_args[0])
        for f in sorted(directory.iterdir()):
            if f.suffix.lower() in video_extensions:
                files.append(f)
        if not files:
            print(f"ERROR: No video files found in {directory}")
            sys.exit(1)
    else:
        for arg in input_args:
            p = Path(arg)
            if not p.exists():
                print(f"ERROR: Input file not found: {p}")
                sys.exit(1)
            if not p.is_file():
                print(f"ERROR: Not a file: {p}")
                sys.exit(1)
            files.append(p)

    return files



# ---------------------------------------------------------------------------
# Probing
# ---------------------------------------------------------------------------

def probe_file(path, log):
    """
    Run ffprobe on a file and return a dict with:
      duration, width, height, fps, aspect_ratio,
      audio_channels, audio_codec, video_codec
    Returns None if file cannot be probed.
    """
    import subprocess
    import json as jsonlib

    cmd = [
        "ffprobe",
        "-v", "quiet",
        "-print_format", "json",
        "-show_streams",
        "-show_format",
        str(path)
    ]

    log.debug(f"Probing: {path}")

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30
        )
    except subprocess.TimeoutExpired:
        log.error(f"ffprobe timed out on {path}")
        return None
    except FileNotFoundError:
        log.error("ffprobe not found — is ffmpeg installed?")
        sys.exit(1)

    if result.returncode != 0:
        log.error(f"ffprobe failed on {path}: {result.stderr.strip()}")
        return None

    try:
        data = jsonlib.loads(result.stdout)
    except jsonlib.JSONDecodeError:
        log.error(f"ffprobe returned invalid JSON for {path}")
        return None

    video_stream = None
    audio_stream = None

    for stream in data.get("streams", []):
        if stream.get("codec_type") == "video" and video_stream is None:
            video_stream = stream
        if stream.get("codec_type") == "audio" and audio_stream is None:
            audio_stream = stream

    if video_stream is None:
        log.error(f"No video stream found in {path}")
        return None

    # Parse framerate
    fps = 29.97
    r_frame_rate = video_stream.get("r_frame_rate", "30/1")
    try:
        num, den = r_frame_rate.split("/")
        fps = round(float(num) / float(den), 3)
    except (ValueError, ZeroDivisionError):
        log.warning(f"Could not parse framerate {r_frame_rate}, assuming 29.97")

    # Parse duration — prefer format duration over stream duration
    duration = 0.0
    try:
        duration = float(data.get("format", {}).get("duration", 0))
        if duration == 0:
            duration = float(video_stream.get("duration", 0))
    except (ValueError, TypeError):
        log.warning(f"Could not parse duration for {path}")

    width  = int(video_stream.get("width",  0))
    height = int(video_stream.get("height", 0))
    aspect_ratio = round(width / height, 3) if height > 0 else 0.0

    audio_channels = 0
    audio_codec    = "none"
    audio_sample_rate = 48000

    if audio_stream:
        audio_channels    = int(audio_stream.get("channels", 0))
        audio_codec       = audio_stream.get("codec_name", "unknown")
        audio_sample_rate = int(audio_stream.get("sample_rate", 48000))

    info = {
        "path":              str(path),
        "duration":          duration,
        "duration_str":      f"{int(duration//3600):02d}:{int((duration%3600)//60):02d}:{int(duration%60):02d}",
        "width":             width,
        "height":            height,
        "aspect_ratio":      aspect_ratio,
        "fps":               fps,
        "video_codec":       video_stream.get("codec_name", "unknown"),
        "audio_channels":    audio_channels,
        "audio_codec":       audio_codec,
        "audio_sample_rate": audio_sample_rate,
    }

    return info


def probe_all(input_files, log):
    """Probe all input files. Exit if any file fails."""
    results = []
    total_duration = 0.0
    failed = False

    for f in input_files:
        info = probe_file(f, log)
        if info is None:
            log.error(f"Failed to probe {f} — aborting.")
            failed = True
            continue
        results.append(info)
        total_duration += info["duration"]
        log.info(
            f"  {Path(f).name}: "
            f"{info['duration_str']} | "
            f"{info['width']}x{info['height']} | "
            f"{info['fps']} fps | "
            f"{info['video_codec']} | "
            f"audio: {info['audio_codec']} {info['audio_channels']}ch"
        )

    if failed:
        sys.exit(1)

    log.info(
        f"Total duration: "
        f"{int(total_duration//3600):02d}:"
        f"{int((total_duration%3600)//60):02d}:"
        f"{int(total_duration%60):02d}"
    )

    return results, total_duration


# ---------------------------------------------------------------------------
# Disc layout calculation
# ---------------------------------------------------------------------------

def calculate_disc_layout(probed_files, total_duration, fmt_config,
                          disc_size, safety_margin, no_split,
                          split_threshold_seconds, log,
                          balance_discs=False):
    """
    Calculate how many discs are needed and what goes on each one.

    Each disc is a list of segments. A segment is either:
      - A full file:    {file, start, end, duration, is_split: False}
      - A partial file: {file, start, end, duration, is_split: True}

    no_split: if True, never cut a file mid-file regardless of duration.
    split_threshold_seconds: files shorter than this are always kept whole
      even if no_split is False. Files longer than this may be split.
    balance_discs: if True, distribute content evenly across the minimum
      number of discs rather than packing each disc to capacity.

    Returns a list of discs, each disc being a list of segments.
    """

    capacity_key = f"capacity_bytes_{disc_size}"
    capacity_bytes = fmt_config[capacity_key]
    effective_bytes = int(capacity_bytes * safety_margin)

    # Estimate bytes per second from format bitrates
    video_bps = fmt_config["video_bitrate"] * 1000 / 8
    audio_bps = fmt_config["audio_bitrate"] * 1000 / 8
    bytes_per_second = video_bps + audio_bps

    # Filesystem overhead estimate: ~10MB per disc
    fs_overhead = 10 * 1024 * 1024
    usable_bytes = effective_bytes - fs_overhead
    capacity_seconds = usable_bytes / bytes_per_second

    log.info(f"Disc capacity: {disc_size}")
    log.info(f"Usable capacity: {usable_bytes / (1024*1024):.1f} MB / {capacity_seconds/60:.1f} minutes per disc")

    # If balancing, calculate minimum disc count and divide evenly
    if balance_discs:
        import math
        min_discs = math.ceil(total_duration / capacity_seconds)
        if min_discs > 1:
            balanced_capacity = total_duration / min_discs
            # Add a small buffer so rounding doesn't push us over
            capacity_seconds = balanced_capacity + 1.0
            log.info(
                f"Balance mode: distributing {total_duration/60:.1f} min "
                f"evenly across {min_discs} discs "
                f"(~{balanced_capacity/60:.1f} min each)"
            )
        else:
            log.info("Balance mode: content fits on one disc — no balancing needed")

    discs = []
    current_disc = []
    current_disc_seconds = 0.0

    for file_info in probed_files:
        file_duration = file_info["duration"]
        file_path     = file_info["path"]
        fname         = Path(file_path).name

        # Determine if this file should be kept whole
        is_episode = no_split or (file_duration <= split_threshold_seconds)

        if is_episode:
            # --- Atomic file: never split mid-file ---
            if file_duration > capacity_seconds:
                # File is longer than an entire disc — warn and force-split anyway
                log.warning(
                    f"  {fname} ({file_duration/60:.1f} min) exceeds disc capacity "
                    f"({capacity_seconds/60:.1f} min) and must be split despite --no-split"
                )
                is_episode = False  # fall through to split logic below

            else:
                disc_remaining = capacity_seconds - current_disc_seconds
                if file_duration > disc_remaining:
                    # Doesn't fit on current disc — start a new one
                    if current_disc:
                        log.info(
                            f"  {fname} doesn't fit on current disc "
                            f"({disc_remaining/60:.1f} min remaining) — starting new disc"
                        )
                        discs.append(current_disc)
                        current_disc = []
                        current_disc_seconds = 0.0

                # Place whole file on current disc
                segment = {
                    "file":     file_path,
                    "start":    0.0,
                    "end":      file_duration,
                    "duration": file_duration,
                    "is_split": False
                }
                current_disc.append(segment)
                current_disc_seconds += file_duration
                continue  # next file

        if not is_episode:
            # --- Splittable file: take as much as fits per disc ---
            file_remaining = file_duration
            file_start     = 0.0

            while file_remaining > 0:
                disc_remaining = capacity_seconds - current_disc_seconds

                if disc_remaining <= 0:
                    discs.append(current_disc)
                    current_disc = []
                    current_disc_seconds = 0.0
                    disc_remaining = capacity_seconds

                if file_remaining <= disc_remaining:
                    segment = {
                        "file":     file_path,
                        "start":    file_start,
                        "end":      file_start + file_remaining,
                        "duration": file_remaining,
                        "is_split": file_start > 0.0
                    }
                    current_disc.append(segment)
                    current_disc_seconds += file_remaining
                    file_remaining = 0.0
                else:
                    take = disc_remaining
                    segment = {
                        "file":     file_path,
                        "start":    file_start,
                        "end":      file_start + take,
                        "duration": take,
                        "is_split": True
                    }
                    current_disc.append(segment)
                    current_disc_seconds += take
                    file_start     += take
                    file_remaining -= take

                    discs.append(current_disc)
                    current_disc = []
                    current_disc_seconds = 0.0

    # Add final disc if it has content
    if current_disc:
        discs.append(current_disc)

    return discs, capacity_seconds


def format_layout(discs, disc_name, log):
    """Log the disc layout in a human-readable format."""
    log.info(f"--- Disc Layout: {len(discs)} disc(s) needed ---")
    for i, disc in enumerate(discs, 1):
        disc_duration = sum(s["duration"] for s in disc)
        label = f"{disc_name}_{i:02d}"
        log.info(f"  Disc {i}: {label}  ({disc_duration/60:.1f} min total)")
        for seg in disc:
            fname = Path(seg["file"]).name
            start_str = f"{int(seg['start']//60):02d}:{int(seg['start']%60):02d}"
            end_str   = f"{int(seg['end']//60):02d}:{int(seg['end']%60):02d}"
            split_tag = " [SPLIT]" if seg["is_split"] else ""
            log.info(f"    {fname}  {start_str} -> {end_str}  ({seg['duration']/60:.1f} min){split_tag}")


# ---------------------------------------------------------------------------
# Encoding
# ---------------------------------------------------------------------------

def get_resolution(file_info, fmt_config, widescreen_threshold, log):
    """
    Determine output resolution based on source aspect ratio.
    Returns (width, height) tuple.
    """
    aspect = file_info["aspect_ratio"]
    if aspect > widescreen_threshold:
        w, h = fmt_config["resolution_widescreen"]
        log.info(f"  Source aspect {aspect:.2f} > {widescreen_threshold} — using widescreen {w}x{h}")
    else:
        w, h = fmt_config["resolution_standard"]
        log.info(f"  Source aspect {aspect:.2f} <= {widescreen_threshold} — using standard {w}x{h}")
    return w, h


def get_audio_filter(audio_channels, log):
    """
    Return appropriate ffmpeg audio filter string based on channel count.
    Stereo and mono: pass through with resample only.
    Surround (3+): fold down to stereo preserving center channel dialogue.
    """
    if audio_channels > 2:
        log.info(f"  Audio: {audio_channels}ch surround — applying dialogue-preserving fold to stereo")
        return "pan=stereo|FL=FC+0.30*FL+0.30*BL|FR=FC+0.30*FR+0.30*BR"
    else:
        log.info(f"  Audio: {audio_channels}ch — passing through to stereo")
        return None


def needs_fps_conversion(fps, log):
    """
    Return True if source framerate needs conversion to 29.97.
    Treat 29.97 (and 30000/1001) as already correct.
    """
    target = 29.97
    if abs(fps - target) < 0.01:
        log.info(f"  Framerate: {fps} fps — no conversion needed")
        return False
    else:
        log.info(f"  Framerate: {fps} fps — will convert to 29.97")
        return True


def build_video_cmd(segment, file_info, fmt_config, out_path,
                    width, height, convert_fps, log):
    """Build ffmpeg command for video elementary stream encode."""
    cmd = ["ffmpeg", "-y"]

    # Input with time range
    cmd += ["-i", segment["file"]]
    cmd += ["-ss", str(segment["start"])]
    cmd += ["-to", str(segment["end"])]

    # Video filter chain
    vf_parts = [
        f"scale={width}:{height}:force_original_aspect_ratio=decrease",
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2",
        "format=yuv420p"
    ]
    cmd += ["-vf", ",".join(vf_parts)]

    # Video codec settings
    cmd += ["-c:v",      fmt_config["video_codec"]]
    cmd += ["-b:v",      f"{fmt_config['video_bitrate']}k"]
    cmd += ["-maxrate",  f"{fmt_config['max_bitrate']}k"]
    cmd += ["-bufsize",  f"{fmt_config['bufsize']}k"]
    cmd += ["-g",        str(fmt_config["gop_size"])]

    if convert_fps:
        cmd += ["-r", "29.97"]

    cmd += ["-an"]
    cmd += [str(out_path)]

    return cmd


def build_audio_cmd(segment, file_info, fmt_config, out_path, audio_filter, log):
    """Build ffmpeg command for audio elementary stream encode."""
    cmd = ["ffmpeg", "-y"]

    cmd += ["-i", segment["file"]]
    cmd += ["-ss", str(segment["start"])]
    cmd += ["-to", str(segment["end"])]

    cmd += ["-vn"]

    if audio_filter:
        cmd += ["-af", audio_filter]

    cmd += ["-c:a", "mp2"]
    cmd += ["-b:a", f"{fmt_config['audio_bitrate']}k"]
    cmd += ["-ar",  "44100"]
    cmd += ["-ac",  "2"]
    cmd += [str(out_path)]

    return cmd


def build_mplex_cmd(video_path, audio_path, out_path, fmt_config):
    """Build mplex command to mux elementary streams."""
    return [
        "mplex",
        "-f", str(fmt_config["mplex_format"]),
        "-o", str(out_path),
        str(video_path),
        str(audio_path)
    ]


def parse_ffmpeg_time(line):
    """Extract time= value from ffmpeg stderr progress line. Returns seconds or None."""
    import re
    match = re.search(r'time=(\d+):(\d+):(\d+\.\d+)', line)
    if match:
        h, m, s = int(match.group(1)), int(match.group(2)), float(match.group(3))
        return h * 3600 + m * 60 + s
    return None


def run_cmd(cmd, log, label, duration_seconds=None):
    """
    Run a subprocess command.
    If duration_seconds is provided and the command is ffmpeg,
    displays a live progress line showing percentage and ETA.
    Returns True on success, False on failure.
    """
    import subprocess
    import sys
    import time

    log.info(f"  Running: {label}")
    log.debug(f"  CMD: {' '.join(cmd)}")

    is_ffmpeg = cmd[0] == "ffmpeg"
    show_progress = is_ffmpeg and duration_seconds and duration_seconds > 0

    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1
        )
    except FileNotFoundError as e:
        log.error(f"  Command not found: {cmd[0]} — {e}")
        return False

    stderr_lines = []
    start_time = time.time()
    last_print = 0

    while True:
        line = proc.stderr.readline()
        if not line and proc.poll() is not None:
            break
        if line:
            stderr_lines.append(line)
            if show_progress:
                current_time = parse_ffmpeg_time(line)
                if current_time is not None:
                    now = time.time()
                    if now - last_print >= 2.0:
                        pct = min(100.0, current_time / duration_seconds * 100)
                        elapsed = now - start_time
                        if pct > 0:
                            eta = elapsed / (pct / 100) - elapsed
                            eta_str = f"ETA {int(eta//60):02d}:{int(eta%60):02d}"
                        else:
                            eta_str = "ETA --:--"
                        bar_width = 30
                        filled = int(bar_width * pct / 100)
                        bar = "#" * filled + "-" * (bar_width - filled)
                        sys.stdout.write(
                            f"\r    [{bar}] {pct:5.1f}%  {eta_str}  "
                            f"{current_time/60:.1f}/{duration_seconds/60:.1f}m  "
                        )
                        sys.stdout.flush()
                        last_print = now

    if show_progress:
        sys.stdout.write(f"\r    [{"#" * 30}] 100.0%  done{" " * 20}\n")
        sys.stdout.flush()

    proc.wait()

    if proc.returncode != 0:
        stderr_tail = "".join(stderr_lines[-20:])
        log.error(f"  {label} failed (exit {proc.returncode})")
        log.error(f"  STDERR: {stderr_tail[-2000:]}")
        return False

    log.debug(f"  {label} completed successfully")
    return True


def encode_segment(seg_index, segment, file_info, fmt_config,
                   temp_dir, disc_name, disc_index,
                   widescreen_threshold, force, log):
    """
    Encode one segment (video + audio elementary streams, then mux).
    Returns path to muxed .mpg file, or None on failure.

    seg_index: 0-based index of this segment within the disc
    disc_index: 1-based disc number
    """
    seg_label  = f"{disc_name}_d{disc_index:02d}_s{seg_index+1:02d}"
    video_path = temp_dir / f"{seg_label}_video.m1v" if fmt_config["video_codec"] == "mpeg1video"                  else temp_dir / f"{seg_label}_video.m2v"
    audio_path = temp_dir / f"{seg_label}_audio.mpa"
    muxed_path = temp_dir / f"{seg_label}.mpg"

    fname = Path(segment["file"]).name
    log.info(f"  Segment {seg_index+1}: {fname} "
             f"{segment['start']/60:.1f}m -> {segment['end']/60:.1f}m")

    # Detect source properties
    width, height   = get_resolution(file_info, fmt_config, widescreen_threshold, log)
    audio_filter    = get_audio_filter(file_info["audio_channels"], log)
    convert_fps     = needs_fps_conversion(file_info["fps"], log)

    # --- Video encode ---
    if force or not video_path.exists():
        cmd = build_video_cmd(
            segment, file_info, fmt_config,
            video_path, width, height, convert_fps, log
        )
        ok = run_cmd(cmd, log, f"ffmpeg video encode {seg_label}",
                     duration_seconds=segment["duration"])
        if not ok:
            return None
    else:
        log.info(f"  Video file exists, skipping encode (use --force to re-encode)")

    # --- Audio encode ---
    if force or not audio_path.exists():
        cmd = build_audio_cmd(
            segment, file_info, fmt_config,
            audio_path, audio_filter, log
        )
        ok = run_cmd(cmd, log, f"ffmpeg audio encode {seg_label}")
        if not ok:
            return None
    else:
        log.info(f"  Audio file exists, skipping encode (use --force to re-encode)")

    # --- Mux ---
    if force or not muxed_path.exists():
        cmd = build_mplex_cmd(video_path, audio_path, muxed_path, fmt_config)
        ok = run_cmd(cmd, log, f"mplex mux {seg_label}")
        if not ok:
            return None
    else:
        log.info(f"  Muxed file exists, skipping mux (use --force to re-encode)")

    return muxed_path


def encode_disc(disc_index, disc_segments, probed_files, fmt_config,
                temp_dir, disc_name, widescreen_threshold, force, log):
    """
    Encode all segments for one disc.
    Returns list of muxed .mpg paths in order, or None on failure.
    """
    log.info(f"--- Encoding disc {disc_index} ---")
    muxed_paths = []

    # Build a lookup from file path to probe info
    probe_lookup = {info["path"]: info for info in probed_files}

    for seg_index, segment in enumerate(disc_segments):
        file_info = probe_lookup.get(segment["file"])
        if file_info is None:
            log.error(f"No probe info found for {segment['file']}")
            return None

        muxed = encode_segment(
            seg_index, segment, file_info, fmt_config,
            temp_dir, disc_name, disc_index,
            widescreen_threshold, force, log
        )
        if muxed is None:
            log.error(f"Encoding failed for segment {seg_index+1} on disc {disc_index}")
            return None

        muxed_paths.append(muxed)

    return muxed_paths


def encode_all_discs(discs, probed_files, fmt_config, temp_dir,
                     disc_name, widescreen_threshold, force, log):
    """
    Encode all discs. Returns list of lists of muxed paths.
    Outer list = discs, inner list = segments per disc.
    """
    all_muxed = []

    for disc_index, disc_segments in enumerate(discs, 1):
        muxed_paths = encode_disc(
            disc_index, disc_segments, probed_files, fmt_config,
            temp_dir, disc_name, widescreen_threshold, force, log
        )
        if muxed_paths is None:
            log.error(f"Disc {disc_index} encoding failed — aborting.")
            sys.exit(1)
        all_muxed.append(muxed_paths)
        log.info(f"Disc {disc_index} encoding complete: {len(muxed_paths)} segment(s)")

    return all_muxed



# ---------------------------------------------------------------------------
# Scene detection for clean split points
# ---------------------------------------------------------------------------

def find_clean_split(file_path, target_seconds, window_seconds, log):
    """
    Use PySceneDetect to find the nearest scene change to target_seconds
    within a window of +/- window_seconds.

    Returns the best split point in seconds, or target_seconds if no
    scene change found or PySceneDetect is unavailable.
    """
    try:
        from scenedetect import open_video, SceneManager
        from scenedetect.detectors import ContentDetector
    except ImportError:
        log.warning("PySceneDetect not installed — using hard time cut")
        return target_seconds

    start = max(0.0, target_seconds - window_seconds)
    duration = window_seconds * 2

    log.info(
        f"  Scene detect: scanning {start/60:.1f}m to "
        f"{(start+duration)/60:.1f}m for split near {target_seconds/60:.1f}m"
    )

    try:
        from scenedetect import FrameTimecode
        video    = open_video(file_path)
        fps      = video.frame_rate
        start_tc = FrameTimecode(start,           fps)
        end_tc   = FrameTimecode(start + duration, fps)
        video.seek(start_tc)
        scene_manager = SceneManager()
        scene_manager.add_detector(ContentDetector(threshold=27.0))
        scene_manager.detect_scenes(video=video, end_time=end_tc)
        scene_list = scene_manager.get_scene_list()
    except Exception as e:
        log.warning(f"  Scene detect failed: {e} — using hard time cut")
        return target_seconds

    if not scene_list:
        log.info(f"  No scene changes found in window — using hard time cut at {target_seconds/60:.1f}m")
        return target_seconds

    # Convert scene start times to seconds and find closest to target
    candidates = []
    for scene_start, scene_end in scene_list:
        t = scene_start.get_seconds()
        candidates.append(t)

    best = min(candidates, key=lambda t: abs(t - target_seconds))
    delta = best - target_seconds

    log.info(
        f"  Best scene cut: {best/60:.1f}m "
        f"({delta:+.1f}s from target {target_seconds/60:.1f}m)"
    )
    return best


def apply_scene_detection(discs, file_path, window_seconds, log):
    """
    For each disc boundary where file_path is split across discs,
    find a clean scene cut near the split point and adjust the
    segment end/start times on both sides of the boundary.

    Works by finding all disc-boundary split points directly rather
    than trying to infer them from segment properties.

    Returns updated discs list.
    """
    import copy
    discs = copy.deepcopy(discs)

    # Build a list of boundary split points to adjust.
    # A boundary exists between disc[i] and disc[i+1] when:
    #   - the last segment of disc[i] involves file_path and ends mid-file
    #   - the first segment of disc[i+1] continues the same file
    boundaries = []

    for disc_idx in range(len(discs) - 1):
        current_disc = discs[disc_idx]
        next_disc    = discs[disc_idx + 1]

        # Find the last segment of this disc that belongs to file_path
        last_seg_idx = None
        for seg_idx, seg in enumerate(current_disc):
            if seg["file"] == file_path:
                last_seg_idx = seg_idx

        if last_seg_idx is None:
            continue

        last_seg = current_disc[last_seg_idx]

        # Check the next disc starts with a continuation of file_path
        first_next_seg_idx = None
        for seg_idx, seg in enumerate(next_disc):
            if seg["file"] == file_path and seg["start"] > 0:
                first_next_seg_idx = seg_idx
                break

        if first_next_seg_idx is None:
            continue

        # This is a real disc boundary split
        boundaries.append({
            "disc_idx":           disc_idx,
            "last_seg_idx":       last_seg_idx,
            "next_disc_idx":      disc_idx + 1,
            "first_next_seg_idx": first_next_seg_idx,
            "target":             last_seg["end"]
        })

    if not boundaries:
        log.info("  No disc boundary splits found for this file")
        return discs

    log.info(f"  Found {len(boundaries)} disc boundary split(s) to adjust")

    for b in boundaries:
        target    = b["target"]
        disc_idx  = b["disc_idx"]
        seg_idx   = b["last_seg_idx"]
        next_didx = b["next_disc_idx"]
        next_sidx = b["first_next_seg_idx"]

        clean_cut = find_clean_split(file_path, target, window_seconds, log)

        if abs(clean_cut - target) > 1.0:
            log.info(
                f"  Adjusting disc {disc_idx+1} -> disc {next_didx+1} "
                f"split: {target/60:.1f}m -> {clean_cut/60:.1f}m"
            )
        else:
            log.info(
                f"  Disc {disc_idx+1} -> disc {next_didx+1} split "
                f"at {target/60:.1f}m — no better cut found nearby"
            )

        # Update the end of the last segment on the current disc
        discs[disc_idx][seg_idx]["end"]      = clean_cut
        discs[disc_idx][seg_idx]["duration"] = (
            clean_cut - discs[disc_idx][seg_idx]["start"]
        )

        # Update the start of the continuation segment on the next disc
        discs[next_didx][next_sidx]["start"]    = clean_cut
        discs[next_didx][next_sidx]["duration"] = (
            discs[next_didx][next_sidx]["end"] - clean_cut
        )

    return discs


def write_xml(disc_index, disc_count, muxed_paths, fmt_config,
              disc_name, xml_path, log):
    """
    Write vcdxbuild XML for one disc.
    disc_index: 1-based
    disc_count: total number of discs in the set
    muxed_paths: list of .mpg file paths for this disc, in order
    """
    vc  = fmt_config["vcdimager_class"]
    ver = fmt_config["vcdimager_version"]

    # Sanitize album ID — max 16 chars, uppercase, alphanumeric + underscore
    album_id = disc_name.upper()[:16].replace("-", "_").replace(" ", "_")
    volume_id = f"{album_id}_D{disc_index:02d}"[:32]

    lines = []
    lines.append('<?xml version="1.0"?>')
    lines.append('<!DOCTYPE videocd PUBLIC "-//GNU//DTD VideoCD//EN"')
    lines.append('  "http://www.gnu.org/software/vcdimager/videocd.dtd">')
    lines.append(f'<videocd xmlns="http://www.gnu.org/software/vcdimager/1.0/"')
    lines.append(f'         class="{vc}" version="{ver}">')
    lines.append('')
    lines.append('  <info>')
    lines.append(f'    <album-id>{album_id}</album-id>')
    lines.append(f'    <volume-count>{disc_count}</volume-count>')
    lines.append(f'    <volume-number>{disc_index}</volume-number>')
    lines.append('    <restriction>0</restriction>')
    lines.append('  </info>')
    lines.append('')
    lines.append('  <pvd>')
    lines.append(f'    <volume-id>{volume_id}</volume-id>')
    lines.append('  </pvd>')
    lines.append('')
    lines.append('  <sequence-items>')

    for i, mpg in enumerate(muxed_paths):
        seq_id = f"seg{i+1:02d}"
        lines.append(f'    <sequence-item src="{mpg}" id="{seq_id}"/>')

    lines.append('  </sequence-items>')
    lines.append('')
    lines.append('  <pbc>')
    lines.append(f'    <playlist id="main">')

    for i in range(len(muxed_paths)):
        seq_id = f"seg{i+1:02d}"
        lines.append(f'      <play-item ref="{seq_id}"/>')

    lines.append('    </playlist>')
    lines.append('  </pbc>')
    lines.append('')
    lines.append('</videocd>')

    xml_content = "\n".join(lines) + "\n"

    with open(xml_path, "w") as f:
        f.write(xml_content)

    log.info(f"  XML written: {xml_path}")
    log.debug(xml_content)


def build_disc_image(disc_index, disc_count, muxed_paths, fmt_config,
                     disc_name, output_dir, temp_dir, log):
    """
    Write XML and run vcdxbuild to produce BIN/CUE for one disc.
    Returns (bin_path, cue_path) on success, None on failure.
    """
    import subprocess

    label    = f"{disc_name}_{disc_index:02d}"
    xml_path = temp_dir / f"{label}.xml"
    bin_path = output_dir / f"{label}.bin"
    cue_path = output_dir / f"{label}.cue"

    log.info(f"--- Building disc image: {label} ---")

    # Write XML
    write_xml(disc_index, disc_count, muxed_paths, fmt_config,
              disc_name, xml_path, log)

    # Run vcdxbuild
    cmd = [
        "vcdxbuild",
        "--bin-file", str(bin_path),
        "--cue-file", str(cue_path),
        "--progress",
        str(xml_path)
    ]

    log.info(f"  Running vcdxbuild...")
    log.debug(f"  CMD: {' '.join(cmd)}")

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=str(temp_dir)
        )
    except FileNotFoundError:
        log.error("vcdxbuild not found — is vcdimager installed?")
        return None

    # vcdxbuild writes progress to stderr
    for line in result.stderr.splitlines():
        line = line.strip()
        if line:
            if "WARN" in line:
                log.warning(f"  vcdxbuild: {line}")
            elif "ERROR" in line or "error" in line.lower():
                log.error(f"  vcdxbuild: {line}")
            else:
                log.debug(f"  vcdxbuild: {line}")

    if result.returncode != 0:
        log.error(f"  vcdxbuild failed (exit {result.returncode})")
        return None

    if not bin_path.exists():
        log.error(f"  vcdxbuild completed but {bin_path} not found")
        return None

    bin_size = bin_path.stat().st_size
    bin_mb   = bin_size / (1024 * 1024)
    log.info(f"  {label}.bin: {bin_mb:.1f} MB")
    log.info(f"  {label}.cue: written")

    # Disc size warnings
    limit_74 = 681574400  # 74-min CD-R in bytes
    limit_80 = 734003200  # 80-min CD-R in bytes

    if bin_size > limit_80:
        log.warning(
            f"  *** DISC TOO LARGE FOR PHYSICAL MEDIA ***"
        )
        log.warning(
            f"  {bin_mb:.1f} MB exceeds 80-min CD-R limit "
            f"({limit_80/(1024*1024):.0f} MB)"
        )
        log.warning(
            f"  This image can be used as a file but cannot be burned to CD-R"
        )
    elif bin_size > limit_74:
        log.warning(
            f"  Disc exceeds 74-min CD-R ({limit_74/(1024*1024):.0f} MB) "
            f"— use 80-min CD-R to burn"
        )
    else:
        log.info(
            f"  Fits on 74-min CD-R "
            f"({bin_mb:.1f} / {limit_74/(1024*1024):.0f} MB, "
            f"{bin_size/limit_74*100:.1f}% used)"
        )

    return bin_path, cue_path


def build_all_images(all_muxed, fmt_config, disc_name,
                     output_dir, temp_dir, log):
    """
    Build disc images for all discs.
    Returns list of (bin_path, cue_path) tuples.
    """
    disc_count = len(all_muxed)
    results = []

    for disc_index, muxed_paths in enumerate(all_muxed, 1):
        result = build_disc_image(
            disc_index, disc_count, muxed_paths, fmt_config,
            disc_name, output_dir, temp_dir, log
        )
        if result is None:
            log.error(f"Disc image build failed for disc {disc_index} — aborting.")
            sys.exit(1)
        results.append(result)
        log.info(f"Disc {disc_index} image complete.")

    return results


# ---------------------------------------------------------------------------
# Filename parsing for human-readable manifest entries
# ---------------------------------------------------------------------------

def parse_filename(filepath):
    """
    Extract a human-readable title from a video filename.

    Handles common naming conventions:
      - S01E01 style: returns "S01E01 - Title"
      - Year detection: returns "Title (Year)"
      - Dot/underscore separated: converts to Title Case
      - Falls back to cleaned filename stem if nothing matches
    """
    import re
    stem = Path(filepath).stem

    # Replace dots and underscores with spaces
    cleaned = re.sub(r'[._]', ' ', stem)

    # Check for SxxExx pattern (TV episode)
    ep_match = re.search(r'(s\d{1,2}e\d{1,2}(?:e\d{1,2})?)', cleaned, re.IGNORECASE)
    if ep_match:
        ep_code = ep_match.group(1).upper()
        after_ep = cleaned[ep_match.end():].strip()
        after_ep = re.sub(
            r'\b(720p|1080p|2160p|4k|bluray|blu ray|webrip|'
            r'web dl|hdtv|dvdrip|xvid|x264|x265|hevc|aac|'
            r'ac3|dts|repack|proper|extended|directors cut).*',
            '', after_ep, flags=re.IGNORECASE).strip()
        if after_ep:
            title = re.sub(r'\s+', ' ', after_ep).strip().title()
            return f"{ep_code} - {title}"
        return ep_code

    # Check for bare episode number: ep01, episode01, e01
    bare_ep = re.search(r'\b(?:ep(?:isode)?\s*)(\d{1,3})\b', cleaned, re.IGNORECASE)
    if bare_ep:
        return f"Episode {int(bare_ep.group(1)):02d}"

    # Strip quality/source/codec tags from the end
    noise_pattern = (
        r'\b(720p|1080p|2160p|4k|bluray|blu ray|webrip|web dl|'
        r'hdtv|dvdrip|xvid|divx|x264|x265|hevc|aac|ac3|dts|'
        r'repack|proper|extended|theatrical|directors cut|'
        r'unrated|retail|readnfo|nfofix|internal).*'
    )
    cleaned = re.sub(noise_pattern, '', cleaned, flags=re.IGNORECASE).strip()

    # Check for year pattern
    year_match = re.search(r'\b(19|20)\d{2}\b', cleaned)
    if year_match:
        year = year_match.group(0)
        before_year = cleaned[:year_match.start()].strip()
        if before_year:
            title = re.sub(r'\s+', ' ', before_year).strip().title()
            return f"{title} ({year})"

    # Fall back to cleaned title-cased stem
    result = re.sub(r'\s+', ' ', cleaned).strip().title()
    return result if result else Path(filepath).stem


def write_manifest(discs, all_muxed, disc_name, output_dir,
                   args_format, disc_size, log):
    """
    Write a human-readable manifest of what is on each disc.
    """
    import datetime
    manifest_path = output_dir / f"{disc_name}_manifest.txt"

    lines = []
    lines.append(f"disc_maker manifest")
    lines.append(f"Generated: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"Name:      {disc_name}")
    lines.append(f"Format:    {args_format.upper()}")
    lines.append(f"Disc size: {disc_size}")
    lines.append(f"Discs:     {len(discs)}")
    lines.append("")

    for i, (disc_segments, muxed_paths) in enumerate(zip(discs, all_muxed), 1):
        label = f"{disc_name}_{i:02d}"
        disc_duration = sum(s["duration"] for s in disc_segments)
        lines.append(f"--- Disc {i}: {label}.bin ---")
        lines.append(f"Total duration: {int(disc_duration//60):02d}:{int(disc_duration%60):02d}")
        lines.append("Contents:")
        for seg in disc_segments:
            display   = parse_filename(seg["file"])
            start_str = f"{int(seg['start']//60):02d}:{int(seg['start']%60):02d}"
            end_str   = f"{int(seg['end']//60):02d}:{int(seg['end']%60):02d}"
            split_tag = " [split]" if seg["is_split"] else ""
            lines.append(f"  {display}  {start_str} -> {end_str}{split_tag}")
        lines.append("Encoded segments:")
        for mp in muxed_paths:
            lines.append(f"  {Path(mp).name}")
        lines.append("")

    with open(manifest_path, "w") as f:
        f.write("\n".join(lines))

    log.info(f"Manifest written: {manifest_path}")

# ---------------------------------------------------------------------------
# Main entry point (skeleton)
# ---------------------------------------------------------------------------

def main():
    args = parse_args()
    config = load_config(args.config)

    # Resolve output directory
    output_dir = Path(args.output) if args.output else Path.cwd()
    output_dir.mkdir(parents=True, exist_ok=True)

    # Set up logging
    log = setup_logging(
        config.get("log_level", "info"),
        output_dir,
        args.name
    )

    # Validate format against config
    available_formats = list(config.get("formats", {}).keys())
    if args.format not in available_formats:
        print(f"ERROR: Unknown format '{args.format}'")
        print(f"Available formats: {', '.join(available_formats)}")
        sys.exit(1)

    log.info("disc_maker starting")
    log.info(f"Format: {args.format.upper()}")
    log.info(f"Name:   {args.name}")
    log.info(f"Output: {output_dir}")

    # Resolve disc size
    disc_size = args.disc_size or config.get("disc_size", "74min")
    log.info(f"Disc size target: {disc_size}")

    # Resolve inputs
    input_files = resolve_inputs(args.input)
    log.info(f"Found {len(input_files)} input file(s):")
    for f in input_files:
        log.info(f"  {f}")

    if args.dry_run:
        log.info("DRY RUN mode — no encoding will be performed")

    log.info("Argument parsing and input resolution complete.")
    log.info("Probing input files...")
    probed_files, total_duration = probe_all(input_files, log)
    log.info("Probe complete.")

    # Load format config
    fmt_config   = config["formats"][args.format]
    disc_size    = args.disc_size or config.get("disc_size", "74min")
    safety_margin = config.get("safety_margin", 0.95)

    # Calculate disc layout
    log.info("Calculating disc layout...")
    split_threshold_seconds = (
        (args.split_threshold or config.get("split_threshold_minutes", 60)) * 60
    )
    no_split = args.no_split or config.get("no_split_default", False)

    if no_split:
        log.info("Mode: episode mode — files will not be split mid-file")
    else:
        log.info(
            f"Mode: auto — files under {split_threshold_seconds/60:.0f} min "
            f"kept whole, longer files may be split"
        )

    balance_discs = getattr(args, 'balance_discs', False) or config.get("balance_discs_default", False)

    if balance_discs:
        log.info("Balance mode enabled — content will be distributed evenly across discs")

    discs, capacity_seconds = calculate_disc_layout(
        probed_files, total_duration,
        fmt_config, disc_size, safety_margin,
        no_split, split_threshold_seconds, log,
        balance_discs=balance_discs
    )
    format_layout(discs, args.name, log)

    # Set up temp directory
    temp_dir = Path(config.get("temp_dir", "/tmp/disc_maker")) / args.name
    temp_dir.mkdir(parents=True, exist_ok=True)
    log.info(f"Temp directory: {temp_dir}")

    # Check disk space — rough estimate: total_duration * bytes_per_second * 3
    # (source + video elementary + audio elementary + muxed = ~3x encoded size)
    fmt_config      = config["formats"][args.format]
    video_bps       = fmt_config["video_bitrate"] * 1000 / 8
    audio_bps       = fmt_config["audio_bitrate"] * 1000 / 8
    bytes_per_sec   = video_bps + audio_bps
    estimated_bytes = int(total_duration * bytes_per_sec * 3)
    import shutil
    free_bytes = shutil.disk_usage(temp_dir).free
    log.info(f"Estimated temp space needed: {estimated_bytes / (1024**3):.1f} GB")
    log.info(f"Free space on temp volume:   {free_bytes / (1024**3):.1f} GB")
    if estimated_bytes > free_bytes:
        log.error("Insufficient disk space — aborting.")
        log.error(f"Need ~{estimated_bytes/(1024**3):.1f} GB, have {free_bytes/(1024**3):.1f} GB free")
        sys.exit(1)

    widescreen_threshold = config.get("widescreen_threshold", 1.5)

    # Apply scene detection to split points if requested
    if args.scene_detect:
        log.info("Scene detection enabled — finding clean split points...")
        window_seconds = config.get("scene_search_window_seconds", 180)

        # Find files that actually get split across discs
        split_files = set()
        for disc in discs:
            for seg in disc:
                if seg["is_split"]:
                    split_files.add(seg["file"])

        if not split_files:
            log.info("No split points in this job — scene detection not needed")
        else:
            for split_file in split_files:
                log.info(f"  Finding clean cuts in: {Path(split_file).name}")
                discs = apply_scene_detection(
                    discs, split_file, window_seconds, log
                )
            log.info("Scene detection complete. Updated disc layout:")
            format_layout(discs, args.name, log)
    else:
        if any(seg["is_split"] for disc in discs for seg in disc):
            log.info("Tip: use --scene-detect for cleaner split points on this job")

    if args.dry_run:
        log.info("Dry run complete. No files were encoded.")
        sys.exit(0)

    # Encode all discs
    log.info("Starting encode...")
    all_muxed = encode_all_discs(
        discs, probed_files, fmt_config, temp_dir,
        args.name, widescreen_threshold, args.force, log
    )

    log.info("All encoding complete.")

    # Build disc images
    log.info("Building disc images...")
    all_images = build_all_images(
        all_muxed, fmt_config, args.name,
        output_dir, temp_dir, log
    )

    # Write manifest
    write_manifest(
        discs, all_muxed, args.name,
        output_dir, args.format, disc_size, log
    )

    # Clean up temp files unless --keep-temp
    keep_temp = args.keep_temp or config.get("keep_temp", False)
    if not keep_temp:
        log.info("Cleaning up temp files...")
        import shutil as _shutil
        _shutil.rmtree(temp_dir, ignore_errors=True)
        log.info("Temp files removed.")
    else:
        log.info(f"Temp files kept at: {temp_dir}")

    # Final summary
    log.info("=== disc_maker complete ===")
    for bin_path, cue_path in all_images:
        size_mb = Path(bin_path).stat().st_size / (1024*1024)
        log.info(f"  {Path(bin_path).name}  ({size_mb:.1f} MB)")
    log.info(f"Manifest: {output_dir}/{args.name}_manifest.txt")


if __name__ == "__main__":
    main()
