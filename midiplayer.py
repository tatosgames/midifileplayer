#!/usr/bin/env python3
"""
midiplayer.py

Un semplice player per Raspberry Pi Zero 2W + Pirate Audio Line-Out:
- Naviga file MIDI e file MP3 con quattro pulsanti
- Riproduce MIDI via midish (inoltra ogni traccia al canale corrispondente)
- Riproduce MP3 via mpg123 attraverso il DAC I²S del Pirate Audio Hat
- Mostra il nome dei file sul display ST7789 da 240×240
"""

import os
import subprocess
import threading
import time

from gpiozero import Button
from PIL import Image, ImageDraw, ImageFont
import mido
from ST7789 import ST7789

# —————————————— CONFIGURAZIONE ——————————————

# Percorsi alle cartelle contenenti i file
MIDI_DIR  = os.path.expanduser("~/Music/MIDI")
AUDIO_DIR = os.path.expanduser("~/Music/MP3")

# Estensioni dei file
MIDI_EXT  = ".mid"
AUDIO_EXT = ".mp3"

# Porta di output MIDI su USB (modificare se diverso)
# Nota: prima di eseguire venga collegato un dispositivo MIDI USB, altrimenti l’array è vuoto.
OUTPUT_PORTS = mido.get_output_names()
MIDI_OUT = OUTPUT_PORTS[-1] if OUTPUT_PORTS else None

# GPIO dei pulsanti (BCM)
BUTTON_UP     = Button(5)   # Scorri in alto
BUTTON_RESET  = Button(6)   # Torna al menu principale e ferma riproduzione
BUTTON_DOWN   = Button(16)  # Scorri in basso
BUTTON_SELECT = Button(24)  # Seleziona / avvia playback

# Display ST7789 240×240 (collegamento Pirate Audio Line-Out)
disp = ST7789(
    height=240,
    width=240,
    rotation=90,
    port=0,
    cs=ST7789.BG_SPI_CS_FRONT,
    dc=9,
    backlight=13,
    spi_speed_hz=80_000_000,
    offset_left=0,
    offset_top=0,
)

# Font per il testo sul display
FONT = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 20)

# Intervallo di refresh del display (secondi)
REFRESH_INTERVAL = 0.1

# —————————————— VARIABILI GLOBALI ——————————————

midi_process  = None   # Subprocess che esegue `midish`
audio_process = None   # Subprocess che esegue `mpg123`

operation_mode  = "main screen"
previous_mode   = None
file_paths      = []   # Percorsi completi dei file nella cartella corrente
file_names      = []   # Nomi da mostrare a schermo (senza estensione)
selected_index  = 0

# Modalità possibili nel menu principale
MAIN_MODES = ["MIDI FILE", "AUDIO FILE"]

# —————————————— FUNZIONI DI PLAYBACK ——————————————

def stop_all_playback():
    """Termina qualunque processo di riproduzione in corso."""
    global midi_process, audio_process

    if midi_process:
        try:
            midi_process.stdin.write("quit\n")
            midi_process.stdin.flush()
            midi_process.wait()
        except Exception:
            pass
        midi_process = None

    if audio_process:
        try:
            audio_process.terminate()
            audio_process.wait()
        except Exception:
            pass
        audio_process = None

def play_midi(path):
    """
    Avvia `midish`, crea un client 0 puntato sul dispositivo MIDI USB,
    quindi invia ogni messaggio del file MIDI sulla porta corretta.
    """
    global midi_process
    stop_all_playback()

    if not MIDI_OUT:
        print("Nessuna porta MIDI USB rilevata.")
        return

    # Avvia midish
    midi_process = subprocess.Popen(
        ["midish"],
        stdin=subprocess.PIPE,
        text=True
    )
    # Crea client 0 → porta USB
    midi_process.stdin.write(f'dnew 0 "{MIDI_OUT}" wo\n')
    midi_process.stdin.flush()

    # Carica e riproduci il file MIDI
    mid = mido.MidiFile(path)
    for msg in mid.play():
        if not msg.is_meta:
            status = msg.bytes()[0]
            data1  = msg.bytes()[1] if len(msg.bytes()) > 1 else 0
            data2  = msg.bytes()[2] if len(msg.bytes()) > 2 else 0
            midi_process.stdin.write(f"ev {status} {data1} {data2}\n")
            midi_process.stdin.flush()

    # Al termine, chiudi midish
    midi_process.stdin.write("quit\n")
    midi_process.stdin.flush()
    midi_process.wait()
    midi_process = None

def play_audio(path):
    """
    Avvia mpg123 in modalità quiet per riprodurre il file MP3
    tramite il DAC I²S del Pirate Audio Hat.
    """
    global audio_process
    stop_all_playback()

    audio_process = subprocess.Popen(
        ["mpg123", "-q", path]
    )

# —————————————— NAVIGAZIONE FILE ——————————————

def scan_files_for_mode(mode):
    """
    Popola `file_paths` e `file_names` in base alla modalità:
    - "MIDI FILE": cerca files .mid in MIDI_DIR
    - "AUDIO FILE": cerca files .mp3 in AUDIO_DIR
    """
    global file_paths, file_names, selected_index

    file_paths = []
    file_names = []
    selected_index = 0

    if mode == "MIDI FILE":
        base_dir = MIDI_DIR
        ext = MIDI_EXT
    elif mode == "AUDIO FILE":
        base_dir = AUDIO_DIR
        ext = AUDIO_EXT
    else:
        return

    if not os.path.isdir(base_dir):
        os.makedirs(base_dir, exist_ok=True)

    for root, _, files in os.walk(base_dir):
        for f in sorted(files):
            if f.lower().endswith(ext):
                full = os.path.join(root, f)
                file_paths.append(full)
                file_names.append(os.path.splitext(f)[0])

    if not file_paths:
        file_names = ["<no files>"]

# —————————————— GESTIONE PULSANTI ——————————————

def handle_button_up():
    """Scorri verso l’alto nella lista."""
    global selected_index
    if operation_mode in MAIN_MODES and file_names:
        selected_index = max(selected_index - 1, 0)

def handle_button_down():
    """Scorri verso il basso nella lista."""
    global selected_index
    if operation_mode in MAIN_MODES and file_names:
        selected_index = min(selected_index + 1, len(file_names) - 1)

def handle_button_reset():
    """
    Ripristina la modalità principale, ferma riproduzione e torna al menu principale.
    """
    global operation_mode, previous_mode, file_names, file_paths, selected_index
    stop_all_playback()
    previous_mode = operation_mode
    operation_mode = "main screen"
    file_paths = []
    file_names = []
    selected_index = 0

def handle_button_select():
    """
    Al click di SELECT:
    - Se in "main screen", passa a "MIDI FILE" o "AUDIO FILE" in base a selected_index
    - Se in "MIDI FILE", avvia play_midi()
    - Se in "AUDIO FILE", avvia play_audio()
    """
    global operation_mode, previous_mode

    if operation_mode == "main screen":
        # Seleziona la sottocategoria in base all’indice
        operation_mode = MAIN_MODES[selected_index % len(MAIN_MODES)]
        scan_files_for_mode(operation_mode)
    elif operation_mode == "MIDI FILE":
        if file_paths:
            play_midi(file_paths[selected_index])
    elif operation_mode == "AUDIO FILE":
        if file_paths:
            play_audio(file_paths[selected_index])

# Associa le callback ai pulsanti
BUTTON_UP.when_pressed     = handle_button_up
BUTTON_DOWN.when_pressed   = handle_button_down
BUTTON_RESET.when_pressed  = handle_button_reset
BUTTON_SELECT.when_pressed = handle_button_select

# —————————————— RENDERING DISPLAY ——————————————

def render_display():
    """
    Aggiorna il display ST7789 disegnando:
    - Il menu principale con "MIDI FILE" e "AUDIO FILE"
    - Oppure la lista dei file (MIDI o MP3) con evidenziato selected_index
    """
    img = Image.new("RGB", (disp.width, disp.height), color=(0, 0, 0))
    draw = ImageDraw.Draw(img)

    if operation_mode == "main screen":
        options = ["MIDI FILE", "AUDIO FILE"]
        for i, text in enumerate(options):
            y = 60 + i * 40
            if i == selected_index:
                # Rettangolo bianco con testo nero
                draw.rectangle([20, y - 5, 220, y + 25], fill=(255, 255, 255))
                draw.text((30, y), text, font=FONT, fill=(0, 0, 0))
            else:
                draw.text((30, y), text, font=FONT, fill=(255, 255, 255))
    else:
        # Mostra la lista dei file in file_names
        max_lines = 5  # quante righe visuali tenere
        start_index = max(0, selected_index - 2)
        for i in range(start_index, min(start_index + max_lines, len(file_names))):
            y = 20 + (i - start_index) * 40
            if i == selected_index:
                draw.rectangle([10, y - 5, 230, y + 25], fill=(255, 255, 255))
                draw.text((20, y), file_names[i], font=FONT, fill=(0, 0, 0))
            else:
                draw.text((20, y), file_names[i], font=FONT, fill=(255, 255, 255))

    disp.display(img)

# Thread di rendering costante
def display_thread():
    while True:
        render_display()
        time.sleep(REFRESH_INTERVAL)

# —————————————— PROGRAMMA PRINCIPALE ——————————————

if __name__ == "__main__":
    # Inizializza display
    disp.begin()

    # Se non c’è alcuna porta MIDI, mostra un messaggio su console
    if MIDI_OUT is None:
        print("Attenzione: nessun dispositivo MIDI USB rilevato.")
    else:
        print(f"Output MIDI selezionato: {MIDI_OUT}")

    # Avvia il thread di rendering del display
    t = threading.Thread(target=display_thread, daemon=True)
    t.start()

    # Loop principale: mantiene attivo il programma
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        stop_all_playback()
        disp.clear()  # spegne il display
        print("\nUscita programmata.")

