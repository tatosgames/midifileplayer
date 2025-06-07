# midifileplayer

**midifileplayer** is a lightweight Python application for Raspberry Pi Zero 2 W (or Pi 3/4) with the Pirate Audio Line-Out HAT. It lets you:

* Browse and select local **MIDI** and **MP3** files via a 240×240 ST7789 display and 4 GPIO buttons (BCM 5=SELECT, 6=RESET, 24=DOWN, 16=UP).
* Configure a **global track-to-MIDI‑channel mapping** for up to 16 tracks via a **Setup** menu.
* Playback MIDI on all connected USB‑MIDI outputs (e.g. hardware synths) with your custom channel mapping.
* Playback MP3 files through the Pirate Audio HAT using `mpg123`.

---

## Features

1. **Global Track Mapping**: assign any of 16 logical MIDI tracks to any of 16 output channels.
2. **Menu System**: intuitive browse, play, and setup screens on the Pi display.
3. **Python + Mido**: direct ALSA MIDI via \[python-rtmidi]/Mido—no `midish` overhead.
4. **MP3 Playback**: uses `mpg123` for simple, low-latency MP3 output.

---

## Hardware

* **Raspberry Pi Zero 2 W**, Pi 3, or Pi 4 (32‑bit OS)
* **Pirate Audio Line-Out** HAT (PCM5100A DAC + ST7789 display)
* **USB‑MIDI** device(s) (e.g. DirtyWave M8) connected to Pi USB port(s)
* 4 buttons wired to BCM 5 (SELECT), 6 (RESET), 24 (DOWN), 16 (UP)

---

## Installation

### 1. Prepare OS

1. Flash a **32‑bit Raspberry Pi OS Lite** (Bullseye or Bookworm) to your SD card.
2. Enable **SSH** and configure Wi‑Fi if needed.
3. Boot Pi, SSH in as `pi`:

   ```bash
   sudo apt update && sudo apt upgrade -y
   sudo raspi-config            # enable SPI, I²C if not already
   ```

### 2. Install system packages

```bash
sudo apt install -y \
  python3 python3-pip python3-pil python3-numpy \
  python3-gpiozero python3-spidev \
  libopenblas-dev \
  mpg123 \
  git build-essential libasound2-dev libffi-dev python3-rpi.gpio python3-mido python3-rtmidi
```

### 3. Install Python libraries

```bash
pip3 install \
  pillow mido python-rtmidi st7789 \
  --break-system-packages
```

### 4. Clone this repository

```bash
cd ~
git clone https://github.com/yourusername/midifileplayer.git
cd midifileplayer
chmod +x midiplayer.py
```

### 5. Create music folders

```bash
mkdir -p ~/Music/MIDI ~/Music/MP3
# Copy your .mid into ~/Music/MIDI and .mp3 into ~/Music/MP3
```

### 6. Optional: Autostart on boot

Edit the `pi` user’s crontab:

```bash
crontab -e
```

Add this line at the end:

```cron
@reboot /usr/bin/python3 /home/pi/midifileplayer/midiplayer.py > /home/pi/midiplayer.log 2>&1
```

Save and exit. The script will launch automatically on reboot, logging to `~/midiplayer.log`.

---

## Usage

1. **Browse**: UP/DOWN to move, SELECT to enter.
2. **Play MIDI**: select **MIDI FILE**, choose a `.mid`, it will start playback on all USB‑MIDI outputs with your mapping.
3. **Play MP3**: select **AUDIO FILE**, choose an `.mp3`, it will play via the Pirate Audio HAT.
4. **Setup**: select **SETUP** to configure track → MIDI channel mapping:

   * UP/DOWN to select track (1–16)
   * SELECT to enter *edit* (highlight blinks)
   * UP/DOWN to change output channel (1–16)
   * SELECT to save mapping
   * RESET to exit Setup and return to main menu

During playback, a **progress bar** appears at the bottom.

---

## Troubleshooting

* **No MIDI devices found?** Connect your USB‑MIDI device, ensure it appears in:

  ```bash
  python3 - <<EOF
  import mido; print(mido.get_output_names())
  EOF
  ```
* **Display not working?** Verify ST7789 wiring, SPI enabled:

  ```bash
  python3 - <<EOF
  from PIL import Image; import st7789
  disp = st7789.ST7789(...); disp.begin(); disp.display(Image.new('RGB',(240,240),(255,0,0)))
  EOF
  ```
* **Button input issues?** Check wiring to BCM 5,6,24,16 and pull‑down/up resistors.

---

## License

MIT License 
