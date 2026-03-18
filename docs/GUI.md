# burnwright GUI

`burnwright_gui.py` is the graphical front end for burnwright. It provides the same functionality as the command-line tool in a single-window desktop interface, with live progress bars and a scrolling log area.

## Requirements

PySide6 (preferred) or PySide2:

```bash
pip install PySide6 --break-system-packages
```

Or if PySide6 is unavailable on your system:

```bash
pip install PySide2 --break-system-packages
```

The GUI auto-detects which version is installed and adjusts accordingly.

## Running the GUI

```bash
python3 burnwright_gui.py
```

`burnwright_gui.py` must be in the same directory as `disc_maker.py` and `disc_maker_config.json`.

---

## Interface

![burnwright GUI screenshot](screenshot.png)

### Job settings

**Format** — Choose VCD or SVCD. VCD gives approximately 61–74 minutes per disc at lower quality. SVCD gives approximately 35–45 minutes per disc at significantly higher quality. See README for guidance on which to use.

**Name** — The base name for all output files. Used as the disc label and the prefix for BIN/CUE filenames. Spaces are replaced with underscores. Parentheses and other characters are handled correctly — `The_Core_(2003)` works as expected.

**Input** — Add one or more video files using **Add files...**, or add an entire folder of episodes using **Add folder...**. Files are processed in the order they appear in the list. Use **Remove selected** to remove entries. Accepted formats include MP4, MKV, AVI, MOV, WMV, FLV, M4V, MPG, MPEG, and TS.

**Output** — The directory where BIN/CUE disc images, the manifest, and the log file will be written. Use **Browse...** to select a folder, or type a path directly. The directory will be created if it does not exist.

**Disc size** — Target physical media size. Use 74 min for standard CD-R (650 MB). Use 80 min for overburn CD-R (700 MB). This affects how much content is packed onto each disc and whether burnwright warns you about overflow.

### Options

| Option | Description |
|---|---|
| **Scene detect** | Use PySceneDetect to find clean scene-change split points near disc boundaries. Adds 1–2 minutes per split point but produces noticeably better breaks in movies. Recommended for any multi-disc movie. |
| **Episode mode (no split)** | Never cut a source file mid-file. Each input file is placed whole on a disc. If it does not fit on the current disc, it starts a new one. Use this for TV episodes. |
| **Dry run (preview only)** | Calculate and display the disc layout, including scene-detected split points, without encoding anything. Use this to verify the plan before committing to a long encode. |
| **Force re-encode** | Re-encode all segments even if intermediate files already exist in the temp directory. Normally burnwright resumes from existing files. |
| **Keep temp files** | Do not delete intermediate `.m1v`, `.m2v`, `.mpa`, and `.mpg` files after the disc images are built. Useful for debugging or if you want to reuse encoded segments. |

### Progress

Two progress bars show during an active job:

- **Current step** — progress within the current ffmpeg video encode, updated every 2 seconds with percentage complete
- **Overall** — progress across all steps in the job (probe, layout, scene detection, each disc encode, image building, manifest)

The step label above each bar describes what is currently happening.

### Log

The scrolling log area shows timestamped output from every step of the pipeline — the same information written to the log file. Color coding:

- **Light grey** — normal info messages
- **Amber** — warnings (non-fatal, job continues)
- **Red** — errors (job will stop)

The log auto-scrolls to the latest entry during a job.

### Buttons

**Let's go** — Start the job. Disabled during an active encode.

**Changed my mind** — Cancel the current job. The job stops after the current subprocess finishes — it will not cut off mid-frame. Disabled when no job is running.

---

## Output files

For each job, burnwright writes to the output directory:

| File | Description |
|---|---|
| `Name_01.bin` | Raw disc image, track 1 |
| `Name_01.cue` | Cue sheet for disc 1 |
| `Name_02.bin` / `Name_02.cue` | Disc 2 (if needed) |
| `Name_manifest.txt` | Plain text listing of what is on each disc |
| `Name.log` | Full timestamped log of the job |

Disc images are in BIN/CUE format compatible with CDEmu (virtual drive), K3b, Brasero, cdrdao, and most other CD burning applications.

---

## Workflow example — TV episodes

1. Set **Format** to VCD
2. Enter the show name in **Name** (e.g. `Parker_Lewis_S01`)
3. Click **Add folder...** and select the folder containing your episode files
4. Set **Output** to your discs folder
5. Check **Episode mode (no split)** so episodes are never cut mid-file
6. Check **Dry run** first to verify the disc layout
7. Hit **Let's go** — review the layout in the log
8. If it looks right, uncheck **Dry run** and hit **Let's go** again

## Workflow example — Movie

1. Set **Format** to SVCD
2. Enter the movie name in **Name** (e.g. `The_Core_(2003)`)
3. Click **Add files...** and select the MKV or MP4
4. Set **Output** to your discs folder
5. Check **Scene detect** for clean split points
6. Check **Dry run** first
7. Hit **Let's go** — review the split points in the log
8. Uncheck **Dry run** and run the full encode

---

## Tested on

- Linux Mint 22 (Ubuntu Noble base)
- Python 3.12.3
- PySide2 5.15.13
- PySide6 6.x (compatible)
