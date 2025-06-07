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
import json
import threading
import time
import math
import subprocess

from gpiozero import Button              # per gestire i pulsanti GPIO
from PIL import Image, ImageDraw, ImageFont  # per disegnare sul display ST7789
import mido                              # per interfaccia MIDI
import st7789                            # driver per il display

# CONFIGURAZIONE FILE e pin
MIDI_DIR   = "/home/pi/Music/MIDI"
AUDIO_DIR  = "/home/pi/Music/MP3"
MIDI_EXT   = ".mid"
AUDIO_EXT  = ".mp3"
MAP_FILE   = "/home/pi/track_map.json"   # mapping persistenza

# Pin BCM per i pulsanti
BTN_SELECT = 5    # conferma / enter
BTN_RESET  = 6    # reset / menu principale
BTN_DOWN   = 24   # aumento indice o valore
BTN_UP     = 16   # diminuzione indice o valore

# Colori RGB
COLOR_BG       = (0, 0, 0)
COLOR_TEXT     = (0, 255, 0)
COLOR_HIGHL    = (0, 255, 0)
COLOR_HIGHL_TX = (0, 0, 0)
COLOR_SETUP_BG = (255, 0, 0)
COLOR_ANIM     = (255, 255, 255)  # colore animazione

# Font per display
FONT_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
FONT_SIZE = 20

# Modalità e parametri globali
MODE_LIST   = ["MIDI FILE", "AUDIO FILE", "SETUP"]
NUM_TRACKS  = 16    # 16 tracce per setup
NUM_OUT     = 16    # 16 canali MIDI configurabili

# STATO GLOBALE
operation_mode    = "main screen"  # schermata corrente
selected_index    = 0               # indice selezionato
files, paths      = [], []          # liste file e percorsi
audio_proc        = None           # processo mpg123

# Setup state
in_edit           = False           # flag per modalità modifica
track_map         = {}              # mappatura traccia→canale

# Playback control
stop_flag         = threading.Event()  # flag per interrompere thread MIDI
midi_thread       = None               # thread di playback MIDI
playback_active   = False              # playback in corso
playback_start    = 0.0                # timestamp di inizio
playback_duration = 0.0                # durata del MIDI
playback_events   = []                 # eventi pianificati
midi_outputs      = []                 # porte MIDI aperte

# Animazione main screen
anim_x      = 0         # posizione orizzontale
anim_r      = 5         # raggio
anim_speed  = 200       # velocità px/s (aumentata)
bounce_amp  = 10        # ampiezza movimento verticale

# ----- Persistenza mapping -----
def load_mapping():
    """
    Carica mapping da JSON o inizializza default.
    """
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
    """Salva mapping in JSON."""
    try:
        with open(MAP_FILE, 'w') as f:
            json.dump(track_map, f)
    except Exception as e:
        print(f">>> [WARN] Unable to save mapping: {e}")

# ----- Gestione porte MIDI -----
def open_all_midi_outputs():
    """Apre tutte le porte di output MIDI valide."""
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
    """Chiude tutte le porte MIDI aperte."""
    global midi_outputs
    for o in midi_outputs:
        try:
            o.close()
        except:
            pass
    midi_outputs = []

# ----- Thread per playback MIDI -----
def _midi_playback_worker(tpq):
    """Invia eventi MIDI sincronizzati in un thread separato."""
    global playback_active
    prev_tick = 0
    for abs_tick, tidx, msg in playback_events:
        if stop_flag.is_set():
            break
        delta = abs_tick - prev_tick
        time.sleep(mido.tick2second(delta, tpq, 500000))  # sleep basato su tick
        if not msg.is_meta:
            ch = track_map.get(tidx, tidx) % NUM_OUT
            out_msg = msg.copy(channel=ch)
            for o in midi_outputs:
                o.send(out_msg)
        prev_tick = abs_tick
    close_all_midi_outputs()
    playback_active = False

# ----- Funzione di playback MIDI -----
def play_midi_file(path):
    """Prepara e avvia playback MIDI per un file."""
    global midi_thread, stop_flag, playback_events, playback_start, playback_duration, playback_active
    stop_flag.set()  # segnala stop al thread corrente
    if midi_thread:
        midi_thread.join()
    stop_flag.clear()  # reset flag
    mid = mido.MidiFile(path)
    tpq = mid.ticks_per_beat
    events = []
    for tidx, tr in enumerate(mid.tracks):
        abs_tick = 0
        for msg in tr:
            abs_tick += msg.time
            if not msg.is_meta:
                events.append((abs_tick, tidx, msg))
    events.sort(key=lambda x: x[0])
    playback_events = events
    max_tick = events[-1][0] if events else 0
    playback_duration = mido.tick2second(max_tick, tpq, 500000)
    playback_start = time.perf_counter()
    open_all_midi_outputs()
    playback_active = True
    midi_thread = threading.Thread(target=_midi_playback_worker, args=(tpq,), daemon=True)
    midi_thread.start()

# ----- MP3 playback -----
def stop_all_playback():
    """Ferma sia il playback MIDI che quello MP3."""
    global audio_proc, playback_active, stop_flag
    stop_flag.set()
    if midi_thread:
        midi_thread.join()
    close_all_midi_outputs()
    playback_active = False
    if audio_proc:
        try:
            audio_proc.terminate()
        except:
            pass
        audio_proc = None


def play_audio_file(path):
    """Riproduce file MP3 tramite mpg123."""
    stop_all_playback()
    subprocess.Popen(["mpg123", "-q", path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

# ----- Navigazione file -----
def scan_files():
    """Popola files e paths per la modalità corrente."""
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

# ----- Callback pulsanti -----
def handle_button(btn):
    """Gestisce logica pulsanti: navigazione, setup, playback."""
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

# ----- Inizializzazione display e pulsanti -----
def init_display():
    """Inizializza e restituisce il display ST7789."""
    disp = st7789.ST7789(
        height=240, rotation=90, port=0,
        cs=st7789.BG_SPI_CS_FRONT, dc=9, backlight=13,
        spi_speed_hz=80_000_000, offset_left=0, offset_top=0
    )
    disp.begin()
    return disp


def init_buttons():
    """Associa handle_button a ciascun pulsante."""
    for b in (BTN_SELECT, BTN_RESET, BTN_DOWN, BTN_UP):
        Button(b).when_pressed = handle_button

# ----- Loop principale -----
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
        # aggiorna animazione solo in main screen
        if operation_mode == "main screen":
            anim_x = (anim_x + anim_speed * dt) % W

        img = Image.new("RGB", (W, H), COLOR_BG)
        draw = ImageDraw.Draw(img)

        # seleziona elenco da disegnare
        if operation_mode == "main screen":
            items = MODE_LIST
        elif operation_mode == "SETUP":
            items = [f"TRK {i+1} -> OUT {track_map[i]+1}" for i in range(NUM_TRACKS)]
        else:
            items = files

        off = 0 if len(items) <= maxl else max(0, selected_index - maxl + 1)
        # disegna righe menu
        for idx, text in enumerate(items[off:off+maxl]):
            y = idx * lh
            sel = (off + idx == selected_index)
            bg = COLOR_SETUP_BG if operation_mode == "SETUP" else COLOR_HIGHL
            if sel:
                draw.rectangle([(0, y), (W, y + lh)], fill=bg)
            # split per blinking in setup
            if operation_mode == "SETUP":
                pre, _, outstr = text.partition('->')
                pre = pre.strip() + ' -> '
                outstr = outstr.strip()
            else:
                pre = text
                outstr = ''
            x = 10
            draw.text((x, y+4), pre, font=font,
                      fill=COLOR_TEXT if not sel else COLOR_HIGHL_TX)
            x += draw.textbbox((0,0), pre, font)[2]
            # blink solo outstr quando in edit mode
            if operation_mode == "SETUP" and sel and in_edit:
                color = COLOR_TEXT if int(time.time()*2) % 2 == 0 else COLOR_BG
            else:
                color = COLOR_TEXT if not sel else COLOR_HIGHL_TX
            draw.text((x, y+4), outstr, font=font, fill=color)
        # disegna barra di progresso
        if playback_active and playback_duration > 0:
            elapsed = time.perf_counter() - playback_start
            frac = min(max(elapsed / playback_duration, 0), 1)
            draw.rectangle([(0, H-5), (int(frac * W), H)], fill=COLOR_HIGHL)
        # disegna animazione sfera con rimbalzo verticale
        if operation_mode == "main screen":
            anim_y = (H - 10) + bounce_amp * math.sin(2 * math.pi * anim_x / W)
            draw.ellipse([(anim_x-anim_r, anim_y-anim_r), (anim_x+anim_r, anim_y+anim_r)], fill=COLOR_ANIM)
        disp.display(img)
        time.sleep(0.05)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        stop_all_playback()
        sys.exit(0)
