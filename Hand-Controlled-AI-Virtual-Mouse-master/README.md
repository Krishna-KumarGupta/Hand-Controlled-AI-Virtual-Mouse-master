# Hand-Controlled AI Virtual Mouse

Control your mouse using **hand gestures** in front of your webcam.

This project uses:
- **OpenCV** for camera frames
- **MediaPipe Hands** for 21-point hand landmarks
- **PyAutoGUI** to move the cursor, click, drag, and scroll
- Optional: **pycaw** for volume control (Windows)
- Optional: **screen_brightness_control** for brightness control (may not work on all devices)

---

## Gestures (cheat sheet)

### Mouse movement
- **Move cursor**: **Index finger up** AND **middle finger down**

### Click / drag
- **Left click**: in Move posture, do a **quick pinch** (Thumb + Index) and release
- **Drag**: in Move posture, **pinch and hold** (Thumb + Index) to drag; release to drop
- **Right click**: **Index + Middle up**, then **pinch** (Thumb + Index)

### Scrolling (continuous / “infinite” while you hold)
- **Scroll up continuously**: **Index + Middle up** (ring + pinky down)
- **Scroll down continuously**: **Thumb only** (thumb up, index/middle/ring/pinky down)

> Tip: if scroll stops due to brief tracking flicker, the code includes a small “latch” window
> so scrolling continues smoothly as long as you’re holding the gesture.

### Volume / brightness (optional)
- **Volume mode**: **Index + Middle + Ring up** (pinky down)
  - Pinch (Thumb + Index) to adjust
  - Or move hand up/down (when not pinching) to fine-adjust
- **Brightness mode**: **Index + Middle + Ring + Pinky up**
  - Pinch (Thumb + Index) to adjust
  - Or move hand up/down (when not pinching) to fine-adjust

### Pause / quit
- **Pause / resume** (optional): hold a **fist** for ~1 second (configurable)
- **Quit**: press **`q`** in the OpenCV window

---

## Requirements

- **Windows 10/11**
- **Python 3.10+** recommended
- A working **webcam**

The dependencies are listed in `requirements.txt`.

---

## Installation (step-by-step)

Open PowerShell in the project folder (the folder containing `mouse.py`).

### 1) Create and activate a virtual environment (recommended)

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
```

If PowerShell blocks activation, run this once (then try again):

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

### 2) Upgrade pip

```powershell
python -m pip install --upgrade pip
```

### 3) Install dependencies

```powershell
pip install -r requirements.txt
```

---

## Run

```powershell
python mouse.py
```

An OpenCV window named **Virtual Mouse** will open.

Safety notes:
- **PyAutoGUI failsafe is enabled**: move your mouse to the **top-left corner** to stop automation.
- To exit normally, press **`q`** in the camera window.

---

## Configuration

Edit `virtual_mouse_config.json` to tune the behavior.

Common settings:
- **`smoothening`**: higher = smoother cursor (less jitter), but more lag
- **`pinch_threshold_px` / `pinch_release_threshold_px`**: pinch sensitivity
- **`scroll_speed`**: how strong each scroll “tick” is
- **`continuous_scroll_interval_s`**: lower = more frequent scroll ticks (faster/smoother)
- **`continuous_scroll_latch_s`**: how long scrolling continues through brief landmark flicker

---

## Troubleshooting

### Camera opens but shows no frames / black screen
- Close apps that might be using the webcam (Teams/Zoom/browser)
- Try another camera index in `virtual_mouse_config.json`:
  - `"camera_index": 0` (try `1` or `2` if needed)

### Volume control doesn’t work
- Volume control uses `pycaw` (Windows-only) and may fail if no active audio endpoint is available.

### Brightness control doesn’t work
- Brightness control depends on your hardware/driver support; some laptops/monitors won’t allow software control.

---

## Project files

- `mouse.py`: main application
- `virtual_mouse_config.json`: tuning/config values
- `requirements.txt`: Python dependencies
