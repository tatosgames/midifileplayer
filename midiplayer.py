#!/usr/bin/env python3
import sys
import time
import os
import fluidsynth

from gpiozero import Button, DigitalOutputDevice
from PIL import Image, ImageDraw, ImageFont

import st7789
        
MESSAGE = ""
#
# enter directory this script will scan in the line below
#
directory = '/home/pi' 
file_extension = '.mid'

button1=Button(5)
button2=Button(6)
button3=Button(16)
button4=Button(24)

pathes=[]
files=[]
selectedindex=0
    
def handle_button(bt):
    global selectedindex
    global files
    global pathes
    if str(bt.pin)=="GPIO16":
        selectedindex-=1
    if str(bt.pin)=="GPIO24":
        selectedindex+=1
    if selectedindex<0:
        selectedindex=0
    if selectedindex>len(files)-1:
        selectedindex=len(files)-1
    if str(bt.pin)=="GPIO5":
        fs = fluidsynth.Synth()
        fs.start(driver="alsa")
        sfid=fs.sfload("/usr/share/sounds/sf2/General_MIDI_64_1.6.sf2")
        fs.play_midi_file(pathes[selectedindex])
        input("Press Enter to stop playback...")
        fs.play_midi_stop()
        fs.delete()

for dirpath, dirnames, filenames in os.walk(directory):
    for filename in filenames:
        if filename.endswith(file_extension):
            pathes.append(dirpath+"/"+filename)
            files.append(filename.replace(".mid","").replace("_"," "))

button1.when_pressed = handle_button
button2.when_pressed = handle_button
button3.when_pressed = handle_button
button4.when_pressed = handle_button

try:
    display_type = sys.argv[2]
except IndexError:
    display_type = "square"


# Create ST7789 LCD display class.

if display_type in ("square", "rect", "round"):
    disp = st7789.ST7789(
        height=135 if display_type == "rect" else 240,
        rotation=0 if display_type == "rect" else 90,
        port=0,
        cs=st7789.BG_SPI_CS_FRONT,  # BG_SPI_CS_BACK or BG_SPI_CS_FRONT
        dc=9,
        backlight=19,  # 18 for back BG slot, 19 for front BG slot.
        spi_speed_hz=80 * 1000 * 1000,
        offset_left=0 if display_type == "square" else 40,
        offset_top=53 if display_type == "rect" else 0,
    )

elif display_type == "dhmini":
    disp = st7789.ST7789(
        height=240,
        width=320,
        rotation=180,
        port=0,
        cs=1,
        dc=9,
        backlight=13,
        spi_speed_hz=60 * 1000 * 1000,
        offset_left=0,
        offset_top=0,
    )

else:
    print("Invalid display type!")

os.system(f'amixer cset numid=1 50%')
fs = fluidsynth.Synth()
fs.start(driver="alsa")
sfid=fs.sfload("/usr/share/sounds/sf2/General_MIDI_64_1.6.sf2")
fs.play_midi_file(pathes[selectedindex])
input("Press Enter to stop playback...")
fs.play_midi_stop()
fs.delete()

# Initialize display.
disp.begin()

WIDTH = disp.width
HEIGHT = disp.height


img = Image.new("RGB", (WIDTH, HEIGHT), color=(0, 0, 0))

draw = ImageDraw.Draw(img)

font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 20)

size_x, size_y = draw.textsize(MESSAGE, font)


while True:
    time.sleep(0.1)
    draw.rectangle((0, 0, disp.width, disp.height), (0, 0, 0))
    for i, line in enumerate(files): # Highlight the specific line by inverting its colors 
        if i == selectedindex: 
            draw.rectangle([10, 10 + (i * 30), 230, 40 + (i * 30)], fill=(255, 255, 255)) 
            draw.text((10, 10 + (i * 30)), line, font=font, fill=(0, 0, 0)) 
        else:
            draw.text((10, 10 + (i * 30)), line, font=font, fill=(255, 255, 255))
    disp.display(img)
