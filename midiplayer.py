#!/usr/bin/env python3
#
# let's import some libraries
#
import sys,git,threading,time,os,fluidsynth,mido,st7789
from gpiozero import Button, DigitalOutputDevice
from PIL import Image, ImageDraw, ImageFont
#
# the onscreen text gets stored in here
#
MESSAGE = ""
#
# specifiy the home directory here
#
directory = '/home/pi' 
file_extension = '.mid'
soundfontname="/usr/share/sounds/sf2/General_MIDI_64_1.6.sf2"
#
# these are the GPIO pins listening to the four buttons
#
button1=Button(5)
button2=Button(6)
button3=Button(16)
button4=Button(24)
#
# link to our fluidsynth instance
#
fs = fluidsynth.Synth()
fs.start(driver="alsa")
sfid=fs.sfload(soundfontname)
#
# holds the filenames, the pathes they're found in and the number of the currently selected midifile
#
pathes=["MIDI KEYBOARD","SOUND FONT","MIDI FILE"]
files=["MIDI KEYBOARD","SOUND FONT","MIDI FILE"]
selectedindex=0
#
# Define the path to your repository (assuming script is inside it)
#
repo_path = os.path.dirname(os.path.abspath(__file__))
#
# the display is always "square" on the Pimoroni boards
#
display_type = "square"
#
# get the first midi keyboard
#
input_ports = mido.get_input_names()
midi_input = input_ports[-1]
print(f"Using MIDI input: {midi_input}")
#
# operation modes
#
operation_mode="main screen"
previous_operation_mode="main_screen"
#
# this part checks for updates
#
def check_for_updates(repo_path):
    try:
        repo = git.Repo(repo_path)
        origin = repo.remotes.origin

        # Fetch latest changes from the remote
        origin.fetch()

        # Compare local HEAD with remote HEAD
        local_commit = repo.head.object.hexsha
        remote_commit = origin.refs[repo.active_branch.name].object.hexsha

        if local_commit != remote_commit:
            print("New updates detected! Pulling latest changes...")
            origin.pull()
            return True  # Indicate update was applied

        print("No updates found. Running the script as usual.")
        return False
    except Exception as e:
        print("Error checking for updates:", e)
        return False
#
# select first preset
#
def select_first_preset(synth, sfid):
    # Get the first available preset in the SoundFont
    for bank in range(128):  # MIDI supports 128 banks
        for preset in range(128):  # Each bank has 128 presets
            if synth.program_select(0, sfid, bank, preset):
                print(f"Selected Bank {bank}, Preset {preset}")
                return
    raise ValueError("No presets found in the SoundFont")
#
# listen to buttons
#
def init_buttons():
    button1.when_pressed = handle_button
    button2.when_pressed = handle_button
    button3.when_pressed = handle_button
    button4.when_pressed = handle_button
#
# listen to midi events
#
def midi_listener():
    global midi_input,fs
    with mido.open_input(midi_input) as inport:
        for msg in inport:
            if msg.type == 'note_on':
                fs.noteon(0, msg.note, msg.velocity)
            elif msg.type == 'note_off':
                fs.noteoff(0,msg.note)
            elif msg.type == 'control_change':
                fs.cc(0, msg.control, msg.value)
            elif msg.type == 'program_change':
                fs.program_change(0, msg.program)
            elif msg.type == 'pitchwheel':
                fs.pitch_bend(0, msg.pitch)
#
# reset the synth
#
def resetsynth():
    global selectedindex,files,pathes,fs,operation_mode,previous_operation_mode,midi_input,soundfontname
    operation_mode="main screen"
    pathes=["MIDI KEYBOARD","SOUND FONT","MIDI FILE"]
    files=["MIDI KEYBOARD","SOUND FONT","MIDI FILE"]
    selectedindex=0
    fs.delete()
    fs=fluidsynth.Synth()
    fs.start(driver="alsa")
    sfid=fs.sfload(soundfontname)
#
# if a button was pressed:
#
def handle_button(bt):
    global selectedindex,files,pathes,fs,operation_mode,previous_operation_mode,midi_input,soundfontname
    if str(bt.pin)=="GPIO16":
        selectedindex-=1
    if str(bt.pin)=="GPIO24":
        selectedindex+=1
    if selectedindex<0:
        selectedindex=0
    if selectedindex>len(files)-1:
        selectedindex=len(files)-1
    if str(bt.pin)=="GPIO6":
        resetsynth()
    if str(bt.pin)=="GPIO5":
        if operation_mode=="main screen":
            pathes=["MIDI KEYBOARD","SOUND FONT","MIDI FILE"]
            files=["MIDI KEYBOARD","SOUND FONT","MIDI FILE"]
            operation_mode=pathes[selectedindex]
        if operation_mode=="MIDI KEYBOARD":
            pathes=[]
            files=[]
            input_ports = mido.get_input_names()
            for port in input_ports:
                pathes.append(port)
                files.append(port)
            if(previous_operation_mode==operation_mode):
                sfid=fs.sfload(soundfontname)
                #fs.program_select(0, sfid, 0, 0)
                try:
                    select_first_preset(fs, sfid)
                except ValueError as e:
                    print(e)
                fs.set_reverb(0.9,0.5,0.8,0.7)
            previous_operation_mode=operation_mode
        if operation_mode=="SOUND FONT":
            #
            # scan the above specified directory and read all midifiles into the pathes and files arrays
            #
            pathes=[]
            files=[]
            target_directory=os.readlink(directory+"/sf2")
            for dirpath, dirnames, filenames in os.walk(target_directory):
                for filename in filenames:
                    if filename.endswith(".sf2"):
                        pathes.append(dirpath+"/"+filename)
                        files.append(filename.replace(".sf2","").replace("_"," "))
            if(previous_operation_mode==operation_mode):
                soundfontname=pathes[selectedindex];
                resetsynth()
            previous_operation_mode=operation_mode
        if operation_mode=="MIDI FILE":
            #
            # scan the above specified directory and read all midifiles into the pathes and files arrays
            #
            pathes=[]
            files=[]
            for dirpath, dirnames, filenames in os.walk(directory+"/midifiles"):
                for filename in filenames:
                    if filename.endswith(file_extension):
                        pathes.append(dirpath+"/"+filename)
                        files.append(filename.replace(".mid","").replace("_"," "))
            if(previous_operation_mode==operation_mode):
                operation_mode=="main screen"
                #
                # a not very elegant way of stopping midi file playback
                #
                fs.delete()
                fs=fluidsynth.Synth()
                fs.start(driver="alsa")
                sfid=fs.sfload(soundfontname)
                fs.play_midi_file(pathes[selectedindex])
            previous_operation_mode=operation_mode
#
# Check for updates and restart if necessary
#
if check_for_updates(repo_path):
    print("Restarting script to apply updates...")
    os.execv(sys.executable, ['python'] + sys.argv)
#
# attach the above given "handle_button" function to the four buttons
#
gpio_thread = threading.Thread(target=init_buttons)
gpio_thread.start()
#
# start listening to midi
#
midi_thread = threading.Thread(target=midi_listener)
midi_thread.start()
#
# Create ST7789 LCD display class.
#
if display_type in ("square", "rect", "round"):
    disp = st7789.ST7789(
        height=135 if display_type == "rect" else 240,
        rotation=0 if display_type == "rect" else 90,
        port=0,
        cs=st7789.BG_SPI_CS_FRONT,  # BG_SPI_CS_BACK or BG_SPI_CS_FRONT
        dc=9,
        backlight=13,  # 18 for back BG slot, 19 for front BG slot.
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
        if i>=selectedindex-6:
            xi=i
            if selectedindex>6:
                xi=i-(selectedindex-6)
            if i == selectedindex: 
                draw.rectangle([10, 10 + (xi * 30), 230, 40 + (xi * 30)], fill=(255, 255, 255)) 
                draw.text((10, 10 + (xi * 30)), line, font=font, fill=(0, 0, 0)) 
            else:
                draw.text((10, 10 + (xi * 30)), line, font=font, fill=(255, 255, 255))
    disp.display(img)
