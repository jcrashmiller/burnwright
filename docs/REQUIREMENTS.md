# Requirements and dependencies

## System dependencies

These are Linux packages installed via apt. Run this single command to install everything burnwright needs:

```bash
sudo apt install -y \
  ffmpeg \
  vcdimager \
  cdrdao \
  wodim \
  genisoimage \
  mjpegtools \
  sox \
  imagemagick \
  vlc \
  bchunk \
  libmpeg2-4 \
  yasm \
  nasm
```

### What each package provides

| Package | Purpose |
|---|---|
| `ffmpeg` | Video and audio encoding — the core encode engine |
| `vcdimager` | VCD/SVCD disc image creation; provides `vcdxbuild`, `vcdxgen`, `vcdimager` |
| `cdrdao` | BIN/CUE disc image writing |
| `wodim` | CD burning (replaces `cdrtools` on Debian/Ubuntu) |
| `genisoimage` | ISO filesystem creation (replaces `mkisofs`) |
| `mjpegtools` | Provides `mplex` for muxing MPEG elementary streams to system stream |
| `sox` | Audio format conversion utilities |
| `imagemagick` | Image processing for menu graphics |
| `vlc` | Playback testing |
| `bchunk` | BIN/CUE to ISO conversion |
| `libmpeg2-4` | MPEG-2 decoding library |
| `yasm` / `nasm` | Assembler dependencies for codec optimization |

### Optional: CDEmu (virtual disc drive)

CDEmu lets you mount BIN/CUE disc images as virtual CD drives for testing without burning:

```bash
sudo add-apt-repository ppa:cdemu-team/ppa
sudo apt update
sudo apt install -y cdemu-client gcdemu vhba-dkms
```

After installing, load a disc image:

```bash
cdemu load 0 /path/to/disc.cue
```

---

## Python dependencies

burnwright requires **Python 3.8 or later**. Install Python packages with:

```bash
pip install scenedetect[opencv] --break-system-packages
```

### Optional: GUI dependencies

If you want to run the graphical interface (`burnwright_gui.py`), install PySide6:

```bash
pip install PySide6 --break-system-packages
```

Or if you are on an older system and PySide6 is unavailable:

```bash
pip install PySide2 --break-system-packages
```

### Full Python requirements list

```
scenedetect[opencv]>=0.6.0
PySide6>=6.0.0          # GUI only — optional
```

Save this as `requirements.txt` and install with:

```bash
pip install -r requirements.txt --break-system-packages
```

---

## Verifying your installation

Run this to confirm all critical tools are present:

```bash
which ffmpeg vcdxbuild vcdimager mplex bchunk cdrdao wodim genisoimage
```

All eight should return paths. If any are missing, install the corresponding package from the table above.

Check Python packages:

```bash
python3 -c "import scenedetect; print('scenedetect:', scenedetect.__version__)"
python3 -c "import PySide6; print('PySide6:', PySide6.__version__)"
```

---

## Tested on

- Linux Mint 22 (Ubuntu Noble / 24.04 base)
- Python 3.12.3
- ffmpeg 6.1.1
- vcdimager 2.0.1
- PySceneDetect 0.6.7.1

Other Debian/Ubuntu-based distributions should work without modification. RPM-based distributions (Fedora, openSUSE) will need equivalent packages via `dnf` or `zypper` — package names may differ slightly.
