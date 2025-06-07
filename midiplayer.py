#!/usr/bin/env python3
"""
midiplayer.py

A simple audio player for Raspberry Pi Zero 2 W + Pirate Audio Line-Out:
- Browse MIDI/MP3 files via ST7789 display and 4 GPIO buttons
- Global track-to-channel mapping (16 tracks → 16 channels) through Setup menu
- Direct MIDI playback using mido (routes tracks to configured channels)
- MP3 playback via mpg123

Hardware:
- Pirate Audio Line-Out (I²S DAC, ST7789 240×240 display, buttons on BCM 5,6,16,24)
"""

import os
import sys
import json
import threading
import time
import math
import subprocess

from gpiozero import Button                     # Handles GPIO button input
from PIL import Image, ImageDraw, ImageFont      # Drawing on ST7789 display
import mido                                     # MIDI interface library
import st7789                                   # ST7789 display driver

# CONFIGURATION
MIDI_DIR   = "/home/pi/Music/MIDI"              # Directory for .mid files
AUDIO_DIR  = "/home/pi/Music/MP3"               # Directory for .mp3 files
MIDI_EXT   = ".mid"
AUDIO_EXT  = ".mp3"
MAP_FILE   = "/home/pi/track_map.json"          # File to persist track-channel mapping

# GPIO BCM pin assignments for buttons
BTN_SELECT = 5    # Confirm / Enter
BTN_RESET  = 6    # Reset / Return to main menu
BTN_DOWN   = 24   # Increase index or value
BTN_UP     = 16   # Decrease index or value

# RGB color definitions
COLOR_BG       = (0, 0, 0)     # Background: black
COLOR_TEXT     = (0, 255, 0)   # Text: green
COLOR_HIGHL    = (0, 255, 0)   # Highlight row background: green
COLOR_HIGHL_TX = (0, 0, 0)     # Highlight text: black
COLOR_SETUP_BG = (255, 0, 0)   # Setup menu background: red
COLOR_ANIM     = (255, 255, 255) # Animation color: white

# Display font settings
FONT_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
FONT_SIZE = 20

# Application modes and parameters
MODE_LIST   = ["MIDI FILE", "AUDIO FILE", "SETUP"]
NUM_TRACKS  = 16    # Number of tracks for setup
NUM_OUT     = 16    # Number of MIDI output channels

# GLOBAL STATE VARIABLES
operation_mode    = "main screen"  # Current UI mode
selected_index    = 0               # Currently selected index/menu item
files, paths      = [], []          # Lists of filenames and full paths
audio_proc        = None           # subprocess for mpg123 playback

# Setup mode state
in_edit           = False           # Are we editing a mapping?
track_map         = {}              # Dictionary mapping track index → MIDI channel

# Playback control variables
stop_flag         = threading.Event()  # Signal to stop the MIDI playback thread
midi_thread       = None               # MIDI playback thread
playback_active   = False              # Is playback currently active?
playback_start    = 0.0                # Timestamp when playback started
playback_duration = 0.0                # Calculated duration of the MIDI file
playback_events   = []                 # Sorted list of MIDI events to play
midi_outputs      = []                 # Opened MIDI output ports

# Main screen animation parameters
anim_x      = 0       # X position of the moving ball
anim_r      = 5       # Ball radius in pixels
anim_speed  = 200     # Pixels per second for horizontal movement
bounce_amp  = 10      # Amplitude in pixels for vertical sine motion

# ----- Persistent Mapping Load/Save -----
def load_mapping():
    """Load track_map from JSON file, or initialize defaults."""
    global track_map
    if os.path.exists(MAP_FILE):
        try:
            with open(MAP_FILE) as f:
                data = json.load(f)
                track_map = {int(k): int(v) for k, v in data.items()}
        except:
            track_map = {i: i for i in range(NUM_TRACKS)}
    else:
        track_map = {i: i for i in range(NUM_TRACKS)}


def save_mapping():
    """Save current track_map to JSON file."""
    try:
        with open(MAP_FILE, 'w') as f:
            json.dump(track_map, f)
    except Exception as e:
        print(f">>> [WARN] Unable to save mapping: {e}")

# ----- MIDI Output Management -----
def open_all_midi_outputs():
    """Open all valid MIDI output ports (excluding 'Midi Through')."""
    global midi_outputs
    names = mido.get_output_names()
    valid = [n for n in names if "MIDI" in n and not n.startswith("Midi Through")]
    midi_outputs = []
    for name in valid:
        try:
            midi_outputs.append(mido.open_output(name))
        except:
            pass


def close_all_midi_outputs():
    """Close all open MIDI output ports."""
    global midi_outputs
    for out in midi_outputs:
        try: out.close()
        except: pass
    midi_outputs = []

# ----- MIDI Playback Thread -----
def _midi_playback_worker(tpq):
    """Worker thread that sends MIDI events at the correct timing."""
    global playback_active
    prev_tick = 0
    for abs_tick, track_idx, msg in playback_events:
        if stop_flag.is_set():
            break
        delta = abs_tick - prev_tick
        # Convert delta ticks to seconds (assuming 500000 microseconds per beat)
        time.sleep(mido.tick2second(delta, tpq, 500000))
        if not msg.is_meta:
            # Map track index to output channel
            ch = track_map.get(track_idx, track_idx) % NUM_OUT
            out_msg = msg.copy(channel=ch)
            # Send message to each open port
            for port in midi_outputs:
                port.send(out_msg)
        prev_tick = abs_tick
    close_all_midi_outputs()
    playback_active = False

# ----- Trigger MIDI Playback -----
def play_midi_file(path):
    """Prepare MIDI events and start playback thread."""
    global midi_thread, stop_flag, playback_events, playback_start, playback_duration, playback_active
    # Signal the old thread to stop and wait for it
    stop_flag.set()
    if midi_thread:
        midi_thread.join()
    # Reset flag and build events list
    stop_flag.clear()
    mid = mido.MidiFile(path)
    tpq = mid.ticks_per_beat
    events = []
    for track_idx, track in enumerate(mid.tracks):
        abs_tick = 0
        for msg in track:
            abs_tick += msg.time
            if not msg.is_meta:
                events.append((abs_tick, track_idx, msg))
    events.sort(key=lambda x: x[0])
    playback_events = events
    # Compute duration in seconds
    max_tick = events[-1][0] if events else 0
    playback_duration = mido.tick2second(max_tick, tpq, 500000)
    playback_start = time.perf_counter()
    # Open outputs and launch worker thread
    open_all_midi_outputs()
    playback_active = True
    midi_thread = threading.Thread(target=_midi_playback_worker, args=(tpq,), daemon=True)
    midi_thread.start()

# ----- Trigger MP3 Playback -----
def stop_all_playback():
    """Stop both MIDI thread and MP3 subprocess."""
    global audio_proc, playback_active, stop_flag, midi_thread
    stop_flag.set()
    if midi_thread:
        midi_thread.join()
    close_all_midi_outputs()
    playback_active = False
    # Terminate mp3 process if running
    if audio_proc:
        try: audio_proc.terminate()
        except: pass
        audio_proc = None


def play_audio_file(path):
    """Play an MP3 file via mpg123 and store process for stopping."""
    global audio_proc
    stop_all_playback()
    audio_proc = subprocess.Popen([
        "mpg123","-q",path
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

# ----- File Scanning -----
def scan_files():
    """Populate files and paths lists for current mode."""
    global files, paths
    files, paths = [], []
    base, ext = (MIDI_DIR, MIDI_EXT) if operation_mode == "MIDI FILE" else (AUDIO_DIR, AUDIO_EXT)
    for dp, _, fnames in os.walk(base):
        for f in fnames:
            if f.lower().endswith(ext):
                files.append(f)
                paths.append(os.path.join(dp, f))
    if not files:
        files = ["<Empty>"]
        paths = [""]

# ----- GPIO Button Callback -----
def handle_button(btn):
    """Handle navigation, setup edits, and playback triggers."""
    global selected_index, operation_mode, in_edit
    pin = btn.pin.number
    if operation_mode == "SETUP":
        if in_edit:
            if pin == BTN_UP:
                track_map[selected_index] = max(0, track_map[selected_index] - 1)
            elif pin == BTN_DOWN:
                track_map[selected_index] = min(NUM_OUT - 1, track_map[selected_index] + 1)
            elif pin == BTN_SELECT:
                in_edit = False
                save_mapping()
        else:
            if pin == BTN_UP:
                selected_index = (selected_index - 1) % NUM_TRACKS
            elif pin == BTN_DOWN:
                selected_index = (selected_index + 1) % NUM_TRACKS
            elif pin == BTN_SELECT:
                in_edit = True
            elif pin == BTN_RESET:
                operation_mode = "main screen"
                selected_index = 0
    else:
        if pin == BTN_UP:
            selected_index = max(selected_index - 1, 0)
        elif pin == BTN_DOWN:
            limit = len(files) if operation_mode != "main screen" else len(MODE_LIST)
            selected_index = min(selected_index + 1, limit - 1)
        elif pin == BTN_RESET:
            stop_all_playback()
            operation_mode = "main screen"
            selected_index = 0
            scan_files()
        elif pin == BTN_SELECT:
            if operation_mode == "main screen":
                sel = MODE_LIST[selected_index]
                if sel == "SETUP":
                    operation_mode = "SETUP"
                    selected_index = 0
                else:
                    operation_mode = sel
                    selected_index = 0
                    scan_files()
            elif operation_mode == "MIDI FILE":
                if paths[selected_index]:
                    play_midi_file(paths[selected_index])
            elif operation_mode == "AUDIO FILE":
                if paths[selected_index]:
                    play_audio_file(paths[selected_index])

# ----- Display & Button Initialization -----
def init_display():
    """Initialize and return the ST7789 display object."""
    disp = st7789.ST7789(
        height=240, rotation=90, port=0,
        cs=st7789.BG_SPI_CS_FRONT, dc=9, backlight=13,
        spi_speed_hz=80_000_000, offset_left=0, offset_top=0
    )
    disp.begin()
    return disp


def init_buttons():
    """Attach the handle_button callback to each GPIO button."""
    for b in (BTN_SELECT, BTN_RESET, BTN_DOWN, BTN_UP):
        Button(b).when_pressed = handle_button

# ----- Main UI Loop -----
def main():
    load_mapping()
    scan_files()
    disp = init_display()
    init_buttons()
    font = ImageFont.truetype(FONT_PATH, FONT_SIZE) if os.path.exists(FONT_PATH) else ImageFont.load_default()
    W, H = disp.width, disp.height
    lh = FONT_SIZE + 8
    maxl = H // lh
    global anim_x
    last_time = time.time()

    while True:
        now = time.time()
        dt = now - last_time
        last_time = now
        if operation_mode == "main screen":
            anim_x = (anim_x + anim_speed * dt) % W

        img = Image.new("RGB", (W, H), COLOR_BG)
        draw = ImageDraw.Draw(img)

        if operation_mode == "main screen":
            items = MODE_LIST
        elif operation_mode == "SETUP":
            items = [f"TRK {i+1} -> OUT {track_map[i]+1}" for i in range(NUM_TRACKS)]
        else:
            items = files

        off = 0 if len(items) <= maxl else max(0, selected_index - maxl + 1)
        for idx, text in enumerate(items[off:off+maxl]):
            y = idx * lh
            sel = (off + idx == selected_index)
            bg = COLOR_SETUP_BG if operation_mode == "SETUP" else COLOR_HIGHL
            if sel:
                draw.rectangle([(0, y), (W, y + lh)], fill=bg)
            if operation_mode == "SETUP":
                pre, _, outstr = text.partition('->')
                pre = pre.strip() + ' -> '
                outstr = outstr.strip()
            else:
                pre = text
                outstr = ''
            x = 10
            draw.text((x, y + 4), pre, font=font, fill=COLOR_TEXT if not sel else COLOR_HIGHL_TX)
            x += draw.textbbox((0, 0), pre, font)[2]
            if operation_mode == "SETUP" and sel and in_edit:
                color = COLOR_TEXT if int(time.time() * 2) % 2 == 0 else COLOR_BG
            else:
                color = COLOR_TEXT if not sel else COLOR_HIGHL_TX
            draw.text((x, y + 4), outstr, font=font, fill=color)

        if playback_active and playback_duration > 0:
            elapsed = time.perf_counter() - playback_start
            frac = min(max(elapsed / playback_duration, 0), 1)
            draw.rectangle([(0, H - 5), (int(frac * W), H)], fill=COLOR_HIGHL)

        if operation_mode == "main screen":
            anim_y = (H - 10) + bounce_amp * math.sin(2 * math.pi * anim_x / W)
            draw.ellipse([(anim_x - anim_r, anim_y - anim_r), (anim_x + anim_r, anim_y + anim_r)], fill=COLOR_ANIM)

        disp.display(img)
        time.sleep(0.05)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        stop_all_playback()
        sys.exit(0)
