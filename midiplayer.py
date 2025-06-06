#!/usr/bin/env python3
"""
midiplayer.py

Un semplice player per Raspberry Pi Zero 2 W + Pirate Audio Line-Out:
- Navigazione e selezione di file MIDI e MP3 via display ST7789 e 4 pulsanti GPIO
- Playback MIDI puro via midish (canale per traccia)
- Playback MP3 via mpg123 sul Pirate Audio HAT

Hardware:
- Pirate Audio Line-Out (DAC PCM5100A, display ST7789 240×240, 4 pulsanti su BCM 5, 6, 16, 24)
- Pulsanti BCM 5=SELECT, 6=RESET, 16=DOWN, 24=UP

Librerie:
- ST7789 (display)
- gpiozero (pulsanti)
- mido (MIDI)
- mpg123 (riproduzione MP3)
- subprocess (midish & mpg123)
- PIL (render testo)
"""

import os
import sys
import subprocess
import threading
import time

from gpiozero import Button
from PIL import Image, ImageDraw, ImageFont
import mido
import st7789

# ------------------------------------------------------------
# CONFIGURAZIONE
# ------------------------------------------------------------
# Directory dei file
MIDI_DIR  = "/home/pi/Music/MIDI"    # cartella con file .mid
AUDIO_DIR = "/home/pi/Music/MP3"     # cartella con file .mp3

# Estensioni
MIDI_EXT  = ".mid"
AUDIO_EXT = ".mp3"

# Pulsanti GPIO (BCM)
BTN_SELECT = 5   # seleziona / invio
BTN_RESET  = 6   # reset / torna al menu principale / stop
BTN_DOWN   = 16  # scendi
BTN_UP     = 24  # sali

# Palette colori
COLOR_BG       = (0, 0, 0)        # sfondo nero
COLOR_TEXT     = (255, 255, 255)  # testo bianco
COLOR_HIGHL    = (255, 255, 255)  # sfondo riga evidenziata
COLOR_HIGHL_TX = (0, 0, 0)        # testo nero (riga evid.)

# Font per display (DejaVuSans-Bold, dimensione 20)
FONT_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
FONT_SIZE = 20

# ------------------------------------------------------------
# VARIABILI GLOBALI
# ------------------------------------------------------------
# Lista delle modalità principali
MODE_LIST = ["MIDI FILE", "AUDIO FILE"]

# Stato corrente
operation_mode   = "main screen"
selected_index   = 0
files, paths     = [], []
midi_out_port    = None

# Processi per playback
midish_proc = None
audio_proc  = None

# ------------------------------------------------------------
# FUNZIONI DI UTILITÀ PLAYBACK
# ------------------------------------------------------------
def stop_all_playback():
    """
    Chiude eventuali processi di playback MIDI (midish) o audio (mpg123).
    """
    global midish_proc, audio_proc

    # Stop MIDI
    if midish_proc:
        try:
            midish_proc.stdin.write("quit\n")
            midish_proc.stdin.flush()
            midish_proc.wait(timeout=2)
        except Exception:
            pass
        midish_proc = None

    # Stop audio MP3
    if audio_proc:
        try:
            audio_proc.terminate()
            audio_proc.wait(timeout=2)
        except Exception:
            pass
        audio_proc = None


def play_midi_with_midish(path):
    """
    Riproduce il file MIDI in 'path' instradando ciascun evento MIDI
    su midish, canale=track_index+1.
    """
    global midish_proc, midi_out_port

    stop_all_playback()

    # Avvia midish come subprocess
    midish_proc = subprocess.Popen(
        ["midish"],
        stdin=subprocess.PIPE,
        text=True,
        bufsize=0
    )

    # Crea un nuovo client 0 verso la porta USB MIDI rilevata
    midish_proc.stdin.write(f'dnew 0 "{midi_out_port}" wo\n')
    midish_proc.stdin.flush()

    # Leggi il file MIDI e invia messaggi
    mid = mido.MidiFile(path)
    for msg in mid.play():
        if msg.is_meta:
            continue

        # Status byte (nota ON, off, cc, ecc.) + canale
        status = msg.bytes()[0]
        data1  = msg.bytes()[1] if len(msg.bytes()) > 1 else 0
        data2  = msg.bytes()[2] if len(msg.bytes()) > 2 else 0

        # Invia “ev <status> <data1> <data2>”
        midish_proc.stdin.write(f"ev {status} {data1} {data2}\n")
        midish_proc.stdin.flush()

def play_audio_mp3(path):
    """
    Riproduce il file MP3 in 'path' usando mpg123 sul Pirate Audio HAT.
    """
    global audio_proc

    stop_all_playback()

    audio_proc = subprocess.Popen(
        ["mpg123", "-q", path],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )

# ------------------------------------------------------------
# FUNZIONI DI NAVIGAZIONE FILE
# ------------------------------------------------------------
def scan_files():
    """
    Popola 'paths' e 'files' in base alla modalità corrente.
    """
    global paths, files, operation_mode

    paths = []
    files = []

    if operation_mode == "MIDI FILE":
        for dp, dn, fn in os.walk(MIDI_DIR):
            for f in fn:
                if f.lower().endswith(MIDI_EXT):
                    paths.append(os.path.join(dp, f))
                    files.append(f)
    elif operation_mode == "AUDIO FILE":
        for dp, dn, fn in os.walk(AUDIO_DIR):
            for f in fn:
                if f.lower().endswith(AUDIO_EXT):
                    paths.append(os.path.join(dp, f))
                    files.append(f)

    # Se non ci sono file, mostra un placeholder
    if not files:
        files = ["<Nessun file trovato>"]
        paths = [""]

# ------------------------------------------------------------
# CALLBACK PULSANTI
# ------------------------------------------------------------
def handle_button(button):
    """
    Gestisce la pressione dei 4 pulsanti.
    BCM 5 (SELECT), 6 (RESET), 16 (DOWN), 24 (UP).
    """
    global selected_index, operation_mode, files, paths

    pin = button.pin.number

    # NAVIGAZIONE SU/GIÙ
    if pin == BTN_UP:
        if operation_mode in ("MIDI FILE", "AUDIO FILE"):
            selected_index = max(selected_index - 1, 0)
        elif operation_mode == "main screen":
            selected_index = max(selected_index - 1, 0)

    elif pin == BTN_DOWN:
        if operation_mode in ("MIDI FILE", "AUDIO FILE"):
            selected_index = min(selected_index + 1, len(files) - 1)
        elif operation_mode == "main screen":
            selected_index = min(selected_index + 1, len(MODE_LIST) - 1)

    # RESET: torna al menu principale e interrompe playback
    elif pin == BTN_RESET:
        stop_all_playback()
        operation_mode = "main screen"
        selected_index = 0
        files  = []
        paths  = []

    # SELECT: conferma selezione
    elif pin == BTN_SELECT:
        if operation_mode == "main screen":
            # Passa alla modalità scelta e popola lista file
            operation_mode = MODE_LIST[selected_index]
            selected_index = 0
            scan_files()

        elif operation_mode == "MIDI FILE":
            if paths[selected_index]:
                play_midi_with_midish(paths[selected_index])

        elif operation_mode == "AUDIO FILE":
            if paths[selected_index]:
                play_audio_mp3(paths[selected_index])

# ------------------------------------------------------------
# INIZIALIZZAZIONE DISPLAY ST7789
# ------------------------------------------------------------
def init_display():
    """
    Configura e restituisce l’istanza ST7789 per il display PIRATE.
    """
    disp = st7789.ST7789(
        height=240,
        rotation=90,
        port=0,
        cs=st7789.BG_SPI_CS_FRONT,
        dc=9,
        backlight=13,
        spi_speed_hz=80_000_000,
        offset_left=0,
        offset_top=0,
    )
    disp.begin()
    return disp

# ------------------------------------------------------------
# INIZIALIZZAZIONE PULSANTI
# ------------------------------------------------------------
def init_buttons():
    """
    Associa la callback handle_button a ciascun pulsante.
    """
    Button(BTN_SELECT).when_pressed = handle_button
    Button(BTN_RESET).when_pressed  = handle_button
    Button(BTN_DOWN).when_pressed   = handle_button
    Button(BTN_UP).when_pressed     = handle_button

# ------------------------------------------------------------
# MAIN: INIZIALIZZAZIONE E LOOP PRINCIPALE
# ------------------------------------------------------------
def main():
    global midi_out_port, operation_mode, selected_index

    # 1. Trova la porta di output MIDI USB (ultima rilevata)
    out_ports = mido.get_output_names()
    if out_ports:
        midi_out_port = out_ports[-1]
    else:
        print("Nessuna porta MIDI USB rilevata. Collega un device e riavvia.")
        sys.exit(1)

    # 2. Inizializza display e pulsanti
    disp = init_display()
    init_buttons()

    # 3. Carica font
    try:
        font = ImageFont.truetype(FONT_PATH, FONT_SIZE)
    except Exception:
        font = ImageFont.load_default()

    # 4. Variabili per il rendering
    WIDTH  = disp.width   # 240
    HEIGHT = disp.height  # 240
    line_height = FONT_SIZE + 8
    max_lines   = HEIGHT // line_height

    # 5. Ciclo principale di rendering
    while True:
        # Crea immagine nera di base
        img  = Image.new("RGB", (WIDTH, HEIGHT), color=COLOR_BG)
        draw = ImageDraw.Draw(img)

        # Determina lista da mostrare
        if operation_mode == "main screen":
            display_list = MODE_LIST
        else:
            display_list = files

        # Calcola offset per scroll se troppi elementi
        if len(display_list) <= max_lines:
            offset = 0
        else:
            # Scroll in modo che selected_index sia sempre visibile
            if selected_index < max_lines:
                offset = 0
            else:
                offset = selected_index - max_lines + 1

        # Disegna ciascuna riga
        for idx, entry in enumerate(display_list[offset: offset + max_lines]):
            y = idx * line_height
            # Evidenzia riga selezionata
            if (idx + offset) == selected_index:
                draw.rectangle([(0, y), (WIDTH, y + line_height)], fill=COLOR_HIGHL)
                draw.text((10, y + 4), entry, font=font, fill=COLOR_HIGHL_TX)
            else:
                draw.text((10, y + 4), entry, font=font, fill=COLOR_TEXT)

        # Mostra immagine sul display
        disp.display(img)

        # Breve pausa per ridurre l’uso CPU
        time.sleep(0.1)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        stop_all_playback()
        sys.exit(0)
