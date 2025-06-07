#!/usr/bin/env python3
"""
midiplayer.py

Player per Raspberry Pi Zero 2 W + Pirate Audio Line-Out:
- Navigazione file MIDI/MP3 via display ST7789 e 4 pulsanti GPIO
- Mapping globale 16 tracce→16 canali via menu Setup
- Playback MIDI diretto con mido (routing tracce→canali configurati)
- Playback MP3 con mpg123

Hardware:
- Pirate Audio Line-Out (DAC I²S, display ST7789 240×240, pulsanti BCM 5,6,16,24)
"""

import os
import sys
import threading
import time
import subprocess

from gpiozero import Button
from PIL import Image, ImageDraw, ImageFont
import mido
import st7789

# CONFIG
MIDI_DIR   = "/home/pi/Music/MIDI"
AUDIO_DIR  = "/home/pi/Music/MP3"
MIDI_EXT   = ".mid"
AUDIO_EXT  = ".mp3"

BTN_SELECT = 5
BTN_RESET  = 6
BTN_DOWN   = 24  # increase index
BTN_UP     = 16  # decrease index

COLOR_BG       = (0, 0, 0)
COLOR_TEXT     = (0, 255, 0)
COLOR_HIGHL    = (0, 255, 0)
COLOR_HIGHL_TX = (0, 0, 0)
COLOR_SETUP_BG = (255, 0, 0)

FONT_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
FONT_SIZE = 20

MODE_LIST = ["MIDI FILE", "AUDIO FILE", "SETUP"]
NUM_TRACKS = 16
NUM_OUT    = 16

# GLOBAL STATE
operation_mode    = "main screen"
selected_index    = 0
files, paths      = [], []
audio_proc        = None

# Setup state
in_setup         = False
in_edit          = False
track_map        = {i: i for i in range(NUM_TRACKS)}  # default 0->0,1->1,...

# Playback control
stop_flag         = threading.Event()
midi_thread       = None
playback_active   = False
playback_start    = 0.0
playback_duration = 0.0
playback_events   = []

midi_outputs = []

# MIDI outputs
def open_all_midi_outputs():
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
    global midi_outputs
    for out in midi_outputs:
        try: out.close()
        except: pass
    midi_outputs = []

# Playback worker
def _midi_playback_worker(tpq):
    global playback_active
    prev = 0
    for abs_tick, tidx, msg in playback_events:
        if stop_flag.is_set(): break
        delta = abs_tick - prev
        time.sleep(mido.tick2second(delta, tpq, 500000))
        if not msg.is_meta:
            ch = track_map.get(tidx, tidx) % 16
            out = msg.copy(channel=ch)
            for o in midi_outputs: o.send(out)
        prev = abs_tick
    close_all_midi_outputs()
    playback_active = False

# Play MIDI
def play_midi_file(path):
    global midi_thread, stop_flag, playback_events, playback_start, playback_duration, playback_active
    stop_flag.set()
    if midi_thread: midi_thread.join()
    stop_flag.clear()
    mid = mido.MidiFile(path)
    tpq = mid.ticks_per_beat
    evts = []
    for tidx, tr in enumerate(mid.tracks):
        abs_tick = 0
        for msg in tr:
            abs_tick += msg.time
            if not msg.is_meta:
                evts.append((abs_tick, tidx, msg))
    evts.sort(key=lambda x: x[0])
    playback_events = evts
    max_tick = evts[-1][0] if evts else 0
    playback_duration = mido.tick2second(max_tick, tpq, 500000)
    playback_start = time.perf_counter()
    open_all_midi_outputs()
    playback_active = True
    midi_thread = threading.Thread(target=_midi_playback_worker, args=(tpq,), daemon=True)
    midi_thread.start()

# MP3
def stop_all_playback():
    global audio_proc, playback_active
    stop_flag.set()
    if midi_thread: midi_thread.join()
    close_all_midi_outputs()
    playback_active = False
    if audio_proc:
        try: audio_proc.terminate()
        except: pass
        audio_proc = None


def play_audio_file(path):
    stop_all_playback()
    subprocess.Popen(["mpg123","-q",path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

# File scan
def scan_files():
    global files, paths
    files, paths = [], []
    base, ext = (MIDI_DIR, MIDI_EXT) if operation_mode=="MIDI FILE" else (AUDIO_DIR, AUDIO_EXT)
    for dp,_,fn in os.walk(base):
        for f in fn:
            if f.lower().endswith(ext):
                files.append(f); paths.append(os.path.join(dp,f))
    if not files:
        files = ["<Empty>"]
        paths = [""]

# Buttons
def handle_button(btn):
    global selected_index, operation_mode, in_setup, in_edit
    pin = btn.pin.number
    if operation_mode == "SETUP":
        if in_edit:
            if pin == BTN_UP: track_map[selected_index] = min(track_map[selected_index]+1, NUM_OUT-1)
            elif pin == BTN_DOWN: track_map[selected_index] = max(track_map[selected_index]-1, 0)
            elif pin == BTN_SELECT: in_edit = False
        else:
            if pin == BTN_UP: selected_index = (selected_index-1) % NUM_TRACKS
            elif pin == BTN_DOWN: selected_index = (selected_index+1) % NUM_TRACKS
            elif pin == BTN_SELECT: in_edit = True
            elif pin == BTN_RESET:
                in_setup = False; operation_mode = "main screen"; selected_index = 0
    else:
        if pin == BTN_UP: selected_index = max(selected_index-1, 0)
        elif pin == BTN_DOWN: selected_index = min(selected_index+1, len(files if operation_mode!="main screen" else MODE_LIST)-1)
        elif pin == BTN_RESET:
            stop_all_playback(); operation_mode="main screen"; selected_index=0; scan_files()
        elif pin == BTN_SELECT:
            sel = MODE_LIST[selected_index] if operation_mode=="main screen" else operation_mode
            if operation_mode=="main screen":
                if sel=="SETUP":
                    operation_mode = "SETUP"; in_setup = True; selected_index=0
                else:
                    operation_mode = sel; selected_index=0; scan_files()
            elif operation_mode=="MIDI FILE":
                if paths[selected_index]: play_midi_file(paths[selected_index])
            elif operation_mode=="AUDIO FILE":
                if paths[selected_index]: play_audio_file(paths[selected_index])

# Display
def init_display():
    d = st7789.ST7789(
        height=240, rotation=90, port=0,
        cs=st7789.BG_SPI_CS_FRONT, dc=9, backlight=13,
        spi_speed_hz=80_000_000, offset_left=0, offset_top=0
    )
    d.begin(); return d

def init_buttons():
    for b in (BTN_SELECT, BTN_RESET, BTN_DOWN, BTN_UP): Button(b).when_pressed = handle_button

# Main
def main():
    disp = init_display(); init_buttons()
    font = ImageFont.truetype(FONT_PATH, FONT_SIZE) if os.path.exists(FONT_PATH) else ImageFont.load_default()
    W,H = disp.width, disp.height; lh = FONT_SIZE+8; maxl = H//lh; scroll=50
    scan_files()
    while True:
        img = Image.new("RGB", (W,H), COLOR_BG); draw = ImageDraw.Draw(img)
        if operation_mode=="main screen":
            items = MODE_LIST
        elif operation_mode=="SETUP":
            items = [f"TRK {i+1} -> OUT {track_map[i]+1}" for i in range(NUM_TRACKS)]
        else:
            items = files
        off = 0 if len(items)<=maxl else max(0, selected_index-maxl+1)
        for idx, text in enumerate(items[off:off+maxl]):
            y = idx*lh; sel = (off+idx==selected_index)
            bg = COLOR_SETUP_BG if operation_mode=="SETUP" else COLOR_HIGHL
            if sel: draw.rectangle([(0,y),(W,y+lh)], fill=bg)
            x0=10; tw,_ = draw.textbbox((0,0),text,font)[2:]
            if sel and tw>W-20:
                t=time.time(); offx=int((t*scroll)%(tw+20)); x=x0-offx
                draw.text((x,y+4), text, font=font, fill=COLOR_HIGHL_TX)
                draw.text((x+tw+20,y+4), text, font=font, fill=COLOR_HIGHL_TX)
            else:
                col=COLOR_HIGHL_TX if sel else COLOR_TEXT
                draw.text((x0,y+4), text, font=font, fill=col)
        if playback_active and playback_duration>0:
            e=time.perf_counter()-playback_start; f=min(max(e/playback_duration,0),1)
            draw.rectangle([(0,H-5),(int(f*W),H)], fill=COLOR_HIGHL)
        disp.display(img); time.sleep(0.05)

if __name__=="__main__":
    try: main()
    except KeyboardInterrupt:
        stop_all_playback(); sys.exit(0)
