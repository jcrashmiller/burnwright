# burnwright

**Convert your video files into VCD and SVCD disc images. Your media. Your discs. Your call.**

burnwright is a command-line tool (with an optional GUI) that takes MP4, MKV, AVI, and other common video formats and produces VCD 2.0 and SVCD disc images — BIN/CUE pairs ready to burn to CD-R. It handles everything: encoding to spec, splitting long content across multiple discs at clean scene boundaries, generating disc images, and telling you exactly what ended up on each disc.

It is named for three things simultaneously:

- **wright** — a craftsperson who makes something real with their hands (wheelwright, wainwright)
- **write** — because data is physically written to the disc, not streamed from a server
- **right** — because it is your right to preserve and use the media you own

---

## What it does

- Encodes any ffmpeg-readable source to VCD or SVCD spec automatically
- Detects aspect ratio and applies the correct resolution (standard or widescreen)
- Detects surround audio and folds it down to stereo preserving dialogue clarity
- Calculates how many discs are needed and plans the layout automatically
- Never splits a TV episode mid-file — each episode stays whole on a single disc
- Uses PySceneDetect to find clean scene-change split points for movies
- Produces BIN/CUE disc images ready for CDEmu, burning software, or archival
- Writes a disc manifest so you always know what is on each disc
- Warns you if a disc image would overflow a physical CD-R before you burn it
- Shows a live progress bar during encoding so you know what it is doing and when it will finish

---

## Philosophy

See [PHILOSOPHY.md](PHILOSOPHY.md) for the full statement. The short version:

burnwright is built on the belief that when you buy or create something, you own it — including the right to choose what format it lives in, what device plays it, and what happens to it when you are done. The tool's relationship with you ends the moment it hands you a disc image. After that, it is none of our business.

---

## Quick start

```bash
# Three TV episodes onto VCD discs
python3 disc_maker.py \
  --format vcd \
  --input ep01.avi ep02.avi ep03.avi \
  --name My_Show \
  --output ~/discs/My_Show

# A movie split across SVCD discs with clean scene cuts
python3 disc_maker.py \
  --format svcd \
  --input movie.mkv \
  --name My_Movie \
  --output ~/discs/My_Movie \
  --scene-detect

# Preview the disc layout without encoding anything
python3 disc_maker.py \
  --format svcd \
  --input movie.mkv \
  --name My_Movie \
  --dry-run
```

---

## Command reference

| Argument | Description |
|---|---|
| `--format` | `vcd` or `svcd` |
| `--input` | One or more video files, or a directory |
| `--output` | Output directory for BIN/CUE files and manifest |
| `--name` | Base name for output files and disc labels |
| `--disc-size` | `74min` (default) or `80min` |
| `--scene-detect` | Find clean scene-change split points for movies |
| `--no-split` | Never cut a file mid-file (episode mode) |
| `--split-threshold` | Files longer than this many minutes may be split (default: 60) |
| `--dry-run` | Show disc layout without encoding |
| `--keep-temp` | Keep intermediate encode files |
| `--force` | Re-encode even if intermediate files exist |
| `--config` | Path to config JSON (default: `disc_maker_config.json`) |

---

## Output

For each job, burnwright produces:

- `Name_01.bin` / `Name_01.cue` — disc image pairs, one per disc
- `Name_manifest.txt` — plain text listing of what is on each disc
- `Name.log` — full timestamped log of every step

---

## Configuration

Edit `disc_maker_config.json` to adjust format parameters, disc capacity targets, safety margins, scene detection window, and temp directory location. The config file is the authoritative source for all format-specific values — no magic numbers are hardcoded in the script.

---

## Project status

Working and tested on Linux Mint (Ubuntu Noble base). Core pipeline is complete. GUI in development.

See [ROADMAP.md](ROADMAP.md) for planned features.

---

## Part of the UserEnd suite

burnwright is one tool in a growing collection of Linux utilities built around the principle of digital self-sufficiency. Others include FolderFlow, EasyEXE, Peek-a-Boo, and the Linux Creative Suite AppPack installer. Each tool does one thing well and then gets out of your way.

https://github.com/jcrashmiller
