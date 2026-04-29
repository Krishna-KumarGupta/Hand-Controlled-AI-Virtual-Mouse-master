import json
import math
import time

import cv2  # pip install opencv-python
import mediapipe as mp  # pip install mediapipe
import pyautogui  # pip install PyautoGUI


def clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def dist(a, b) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def load_config(path: str) -> dict:
    defaults = {
        "camera_index": 0,
        "smoothening": 8,
        "cursor_frame_margin_px": 80,
        "pinch_threshold_px": 38,
        "pinch_release_threshold_px": 52,
        "click_cooldown_s": 0.35,
        # Left-click responsiveness:
        # - quick pinch (< drag_hold_s) => left click
        # - hold pinch (>= drag_hold_s) => drag until release
        "drag_hold_s": 0.12,
        "scroll_speed": 40,
        # For continuous scrolling while holding a posture.
        # Lower = more frequent scroll events (smoother / faster).
        "continuous_scroll_interval_s": 0.03,
        # Allow some landmark flicker without stopping scroll immediately.
        "continuous_scroll_latch_s": 0.18,
        "pause_toggle_hold_s": 0.8,
        "level_control_smoothening": 0.25,
        # Per-pixel adjustment when using hand up/down motion in VOLUME/BRIGHTNESS mode (when not pinching).
        "level_scroll_step": 0.004,
        # Disable if pause toggles accidentally on your camera/lighting.
        "pause_enabled": True,
        "pause_requires_pinch": True,
        "pause_toggle_cooldown_s": 1.2,
        "scroll_deadzone_px": 6,
        "show_hud": True,
    }
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return {**defaults, **data}
    except Exception:
        pass
    return defaults


def fingers_up(lm, handedness: str = "Right") -> dict:
    # For index/middle/ring/pinky: tip.y < pip.y means finger is up (image origin at top-left).
    # Thumb needs handedness to interpret x-direction correctly in mirrored camera view.
    thumb_up = (lm[4].x > lm[3].x) if handedness.lower().startswith("right") else (lm[4].x < lm[3].x)
    return {
        "thumb": thumb_up,
        "index": lm[8].y < lm[6].y,
        "middle": lm[12].y < lm[10].y,
        "ring": lm[16].y < lm[14].y,
        "pinky": lm[20].y < lm[18].y,
    }


def to_px(lm_point, frame_w: int, frame_h: int) -> tuple[int, int]:
    return int(lm_point.x * frame_w), int(lm_point.y * frame_h)


def draw_hud(frame, lines):
    y = 28
    for line in lines:
        cv2.putText(
            frame,
            line,
            (12, y),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.65,
            (30, 220, 30),
            2,
            cv2.LINE_AA,
        )
        y += 26


def try_init_volume_controller():
    try:
        from ctypes import cast, POINTER  # type: ignore

        import comtypes  # type: ignore
        from comtypes import CLSCTX_ALL  # type: ignore
        from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume  # type: ignore
        from pycaw.utils import AudioDeviceState  # type: ignore

        # Ensure COM is initialized on this thread (common cause of pycaw failures).
        try:
            comtypes.CoInitialize()
        except Exception:
            # CoInitialize may raise if already initialized; safe to ignore.
            pass

        # Some systems report a "default speakers" endpoint that is NotPresent.
        # Prefer an Active render endpoint if available.
        try:
            dev = AudioUtilities.GetSpeakers()
            if getattr(dev, "state", None) != AudioDeviceState.Active:
                raise RuntimeError(f"Default speakers not active: {getattr(dev, 'state', None)}")
            endpoint = dev.EndpointVolume
            return endpoint, None
        except Exception:
            pass

        active = [d for d in AudioUtilities.GetAllDevices() if getattr(d, "state", None) == AudioDeviceState.Active]
        if not active:
            return None, "No active audio render devices found"
        dev = active[0]
        endpoint = dev.EndpointVolume
        # Validate by calling a harmless getter (forces COM interface to be usable).
        try:
            endpoint.GetMasterVolumeLevelScalar()
        except Exception:
            # If this active device can't be controlled, fall back to the next one.
            for dev in active[1:]:
                try:
                    endpoint = dev.EndpointVolume
                    endpoint.GetMasterVolumeLevelScalar()
                    break
                except Exception:
                    continue
            else:
                return None, "Active devices found but none were controllable"

        return cast(endpoint, POINTER(IAudioEndpointVolume)), None
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"


def set_master_volume(endpoint, value_0_to_1: float):
    if endpoint is None:
        return False, "No audio endpoint"
    try:
        endpoint.SetMasterVolumeLevelScalar(float(clamp(value_0_to_1, 0.0, 1.0)), None)
        return True, None
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


def try_set_brightness(value_0_to_1: float):
    try:
        import screen_brightness_control as sbc  # type: ignore

        sbc.set_brightness(int(round(clamp(value_0_to_1, 0.0, 1.0) * 100)))
        return True
    except Exception:
        return False


def main():
    cfg = load_config("virtual_mouse_config.json")

    pyautogui.FAILSAFE = True
    pyautogui.PAUSE = 0

    screen_w, screen_h = pyautogui.size()

    cam_index = int(cfg["camera_index"])
    cap = None
    # Windows camera backends can be flaky; try a couple of reliable fallbacks.
    for backend in (None, getattr(cv2, "CAP_DSHOW", None), getattr(cv2, "CAP_MSMF", None)):
        try:
            cap = cv2.VideoCapture(cam_index) if backend is None else cv2.VideoCapture(cam_index, backend)
            if cap is not None and cap.isOpened():
                break
        except Exception:
            cap = None
    if cap is None or not cap.isOpened():
        raise RuntimeError(
            f"Could not open camera index {cam_index}. "
            "Try changing 'camera_index' in virtual_mouse_config.json (0/1/2) or close apps using the webcam."
        )

    hands = mp.solutions.hands.Hands(
        model_complexity=1,
        max_num_hands=1,
        min_detection_confidence=0.6,
        min_tracking_confidence=0.6,
    )
    drawing = mp.solutions.drawing_utils

    smooth = float(cfg["smoothening"])
    margin = int(cfg["cursor_frame_margin_px"])
    pinch_th = float(cfg["pinch_threshold_px"])
    pinch_rel = float(cfg["pinch_release_threshold_px"])
    click_cd = float(cfg["click_cooldown_s"])
    drag_hold_s = float(cfg.get("drag_hold_s", 0.12))
    scroll_speed = int(cfg["scroll_speed"])
    cont_scroll_interval = float(cfg.get("continuous_scroll_interval_s", 0.03))
    cont_scroll_latch = float(cfg.get("continuous_scroll_latch_s", 0.18))
    pause_hold = float(cfg["pause_toggle_hold_s"])
    level_smooth = float(cfg["level_control_smoothening"])
    pause_enabled = bool(cfg.get("pause_enabled", True))
    pause_requires_pinch = bool(cfg["pause_requires_pinch"])
    pause_cooldown = float(cfg["pause_toggle_cooldown_s"])
    scroll_deadzone = int(cfg["scroll_deadzone_px"])
    show_hud = bool(cfg["show_hud"])
    level_scroll_step = float(cfg.get("level_scroll_step", 0.004))

    plocx = plocy = 0.0
    clocx = clocy = 0.0

    last_click_t = 0.0
    dragging = False
    pinch_down_t = None  # type: float | None
    paused = False
    pause_candidate_t = None
    last_pause_toggle_t = 0.0
    volume_endpoint, volume_err = try_init_volume_controller()
    volume_level = None  # type: float | None
    brightness_level = None  # type: float | None
    prev_scroll_y = None  # type: int | None
    prev_level_y = None  # type: int | None
    last_cont_scroll_t = 0.0
    cont_scroll_dir = 0  # 1 = up, -1 = down
    cont_scroll_until_t = 0.0

    prev_time = time.time()
    fps = 0.0
    started = False

    while True:
        ok, frame = cap.read()
        if not ok:
            if not started:
                raise RuntimeError(
                    "Camera opened, but no frames could be read. "
                    "On Windows this is often a webcam permission / driver / backend issue. "
                    "Try another camera_index (0/1/2), close Teams/Zoom/Browser, and retry."
                )
            break
        started = True

        frame = cv2.flip(frame, 1)
        fh, fw, _ = frame.shape

        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        out = hands.process(rgb)

        now = time.time()
        dt = max(1e-6, now - prev_time)
        prev_time = now
        fps = 0.9 * fps + 0.1 * (1.0 / dt)

        mode = "NO HAND"

        if out.multi_hand_landmarks:
            hand = out.multi_hand_landmarks[0]
            drawing.draw_landmarks(frame, hand, mp.solutions.hands.HAND_CONNECTIONS)
            lm = hand.landmark

            handedness = "Right"
            try:
                if out.multi_handedness:
                    handedness = out.multi_handedness[0].classification[0].label
            except Exception:
                handedness = "Right"

            p_wrist = to_px(lm[0], fw, fh)
            p_index = to_px(lm[8], fw, fh)
            p_thumb = to_px(lm[4], fw, fh)
            p_middle = to_px(lm[12], fw, fh)
            p_ring = to_px(lm[16], fw, fh)

            up = fingers_up(lm, handedness)
            fist = (not up["index"]) and (not up["middle"]) and (not up["ring"]) and (not up["pinky"])
            three_up = up["index"] and up["middle"] and up["ring"] and (not up["pinky"])
            four_up = up["index"] and up["middle"] and up["ring"] and up["pinky"]

            # Pinch detection (thumb-index)
            pinch = dist(p_thumb, p_index)

            # Pause toggle: hold a fist for a short time.
            # Optional extra safety: require thumb-index pinch while making a fist,
            # which prevents accidental pauses when finger detection flickers.
            if pause_enabled:
                pause_armed = fist and ((not pause_requires_pinch) or (pinch <= pinch_th))
                if pause_armed and (now - last_pause_toggle_t) >= pause_cooldown:
                    if pause_candidate_t is None:
                        pause_candidate_t = now
                    elif now - pause_candidate_t >= pause_hold:
                        paused = not paused
                        pause_candidate_t = None
                        last_pause_toggle_t = now
                else:
                    pause_candidate_t = None
            else:
                pause_candidate_t = None

            if paused:
                mode = "PAUSED (hold fist to toggle)"
                prev_scroll_y = None
                prev_level_y = None
            else:
                # Volume control: 3 fingers up (index+middle+ring), pinky down; pinch distance controls level
                if three_up:
                    mode = "VOLUME"
                    # If user is pinching, use pinch distance. Otherwise, allow "scroll" (vertical motion) to adjust.
                    if pinch <= pinch_rel:
                        v = (pinch - pinch_th) / max(1.0, (pinch_rel - pinch_th))
                        v = clamp(v, 0.0, 1.0)
                        volume_level = v if volume_level is None else (1 - level_smooth) * volume_level + level_smooth * v
                        prev_level_y = None
                    else:
                        y = p_middle[1]
                        if prev_level_y is None:
                            prev_level_y = y
                        else:
                            dy = y - prev_level_y
                            if abs(dy) >= scroll_deadzone:
                                # Image coords: y increases downward. Move hand down => decrease.
                                base = 0.5 if volume_level is None else float(volume_level)
                                volume_level = clamp(base + (-dy) * level_scroll_step, 0.0, 1.0)
                                prev_level_y = y
                    ok_vol, set_err = set_master_volume(volume_endpoint, volume_level)
                    if not ok_vol:
                        # Show the real failure cause (packages may be installed but COM/audio endpoint can fail).
                        mode = f"VOLUME (error: {set_err or volume_err or 'unknown'})"
                    prev_scroll_y = None

                # Brightness control: 4 fingers up (index+middle+ring+pinky); pinch distance controls level
                elif four_up:
                    mode = "BRIGHTNESS"
                    if pinch <= pinch_rel:
                        b = (pinch - pinch_th) / max(1.0, (pinch_rel - pinch_th))
                        b = clamp(b, 0.0, 1.0)
                        brightness_level = b if brightness_level is None else (1 - level_smooth) * brightness_level + level_smooth * b
                        prev_level_y = None
                    else:
                        y = p_middle[1]
                        if prev_level_y is None:
                            prev_level_y = y
                        else:
                            dy = y - prev_level_y
                            if abs(dy) >= scroll_deadzone:
                                base = 0.5 if brightness_level is None else float(brightness_level)
                                brightness_level = clamp(base + (-dy) * level_scroll_step, 0.0, 1.0)
                                prev_level_y = y
                    ok_b = try_set_brightness(brightness_level)
                    if not ok_b:
                        mode = "BRIGHTNESS (install: screen_brightness_control)"
                    prev_scroll_y = None

                else:
                    prev_level_y = None

                # Cursor move: index finger up, middle down (reduces accidental moves while scrolling)
                if up["index"] and not up["middle"]:
                    x1, y1 = p_index
                    cv2.circle(frame, (x1, y1), 12, (0, 255, 255), -1)

                    # Limit motion to a smaller ROI for stability
                    x1 = clamp(x1, margin, fw - margin)
                    y1 = clamp(y1, margin, fh - margin)

                    sx = (x1 - margin) / max(1, (fw - 2 * margin))
                    sy = (y1 - margin) / max(1, (fh - 2 * margin))

                    tx = sx * screen_w
                    ty = sy * screen_h

                    clocx = plocx + (tx - plocx) / smooth
                    clocy = plocy + (ty - plocy) / smooth
                    pyautogui.moveTo(clocx, clocy)
                    plocx, plocy = clocx, clocy
                    mode = "MOVE"
                    prev_scroll_y = None
                    prev_level_y = None

                # Scroll: index + middle up; scroll by vertical hand motion (robust for up/down)
                # Continuous scroll (infinite while holding gesture):
                # - 2 fingers up (index+middle up, ring+pinky down) => scroll up
                # - thumb only (thumb up, index+middle+ring+pinky down) => scroll down
                scroll_up_posture = up["index"] and up["middle"] and (not up["ring"]) and (not up["pinky"])
                scroll_down_posture = (
                    up["thumb"]
                    and (not up["index"])
                    and (not up["middle"])
                    and (not up["ring"])
                    and (not up["pinky"])
                )

                if scroll_up_posture:
                    cont_scroll_dir = 1
                    cont_scroll_until_t = now + max(0.0, cont_scroll_latch)
                elif scroll_down_posture:
                    cont_scroll_dir = -1
                    cont_scroll_until_t = now + max(0.0, cont_scroll_latch)
                elif now >= cont_scroll_until_t:
                    cont_scroll_dir = 0

                if cont_scroll_dir != 0:
                    if now - last_cont_scroll_t >= max(0.005, cont_scroll_interval):
                        pyautogui.scroll(cont_scroll_dir * scroll_speed)
                        last_cont_scroll_t = now
                    mode = "SCROLL (HOLD)"
                    prev_level_y = None
                    prev_scroll_y = None
                else:
                    prev_scroll_y = None

                # Left click / drag: pinch with index only (middle down)
                if up["index"] and not up["middle"]:
                    # Pinch state machine:
                    # - pinch start => start timer
                    # - release before drag_hold_s => left click
                    # - hold for drag_hold_s => start drag (mouseDown), release ends drag
                    if pinch <= pinch_th:
                        if pinch_down_t is None:
                            pinch_down_t = now
                        # Start dragging only after the hold threshold.
                        if (not dragging) and (pinch_down_t is not None) and ((now - pinch_down_t) >= drag_hold_s):
                            pyautogui.mouseDown()
                            dragging = True
                            mode = "DRAG"
                    elif pinch >= pinch_rel:
                        # Release
                        if dragging:
                            pyautogui.mouseUp()
                            dragging = False
                        else:
                            if pinch_down_t is not None and (now - last_click_t) >= click_cd:
                                # Quick pinch => left click
                                pyautogui.click(button="left")
                                last_click_t = now
                                mode = "LEFT CLICK"
                        pinch_down_t = None
                else:
                    # If the "index only" posture is lost, reset pinch timer.
                    pinch_down_t = None

                # Right click: pinch thumb-index while middle finger is up (intentional)
                if up["index"] and up["middle"] and pinch <= pinch_th and (now - last_click_t) >= click_cd:
                    pyautogui.click(button="right")
                    last_click_t = now
                    mode = "RIGHT CLICK"

                # If we started a drag but user changes modes, release safely
                if dragging and not up["index"]:
                    pyautogui.mouseUp()
                    dragging = False
                    pinch_down_t = None

        if show_hud:
            hud = [
                f"Mode: {mode}",
                f"FPS: {fps:.1f}",
                "Keys: q=quit",
            ]
            draw_hud(frame, hud)

        cv2.imshow("Virtual Mouse", frame)
        key = cv2.waitKey(1) & 0xFF
        if key == ord("q"):
            break

    if dragging:
        pyautogui.mouseUp()
    cap.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
    
