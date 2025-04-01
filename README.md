# midifileplayer
Plays back midi files on a Raspberry PI


How to install/use

Install 32 bit os lite, bookworm or bullseye

ssh to raspberrypi

sudo apt update

sudo apt upgrade

sudo apt install fluidsynth

sudo raspi-config  - turn on spi and i2c

sudo nano /boot/firmware/config.txt, add


dtoverlay=hifiberry-dac

gpio=25=op,dh

sudo apt-get install python3-rpi.gpio python3-spidev python3-pip python3-pil python3-numpy

sudo pip3 install pidi-display-st7789 --break-system-packages

sudo pip3 install pyfluidsynth --break-system-packages

sudo python3 -m pip install mido --break-system-packages

sudo apt install git

git clone  https://github.com/pimoroni/st7789-python

cd st7789-python/examples/

sudo apt install libopenblas-dev

python3 scrolling-text.py


-> this works!


sudo nano /etc/security/limits.conf

@audio - rtprio 90 

@audio - memlock unlimited

sudo reboot


cd /usr/share/sounds/sf2

sudo wget http://ntonyx.com/soft/32MbGMStereo.sf2

sudo wget https://musical-artifacts.com/artifacts/923/General_MIDI_64_1.6.sf2


there's an SD card image for RasPi Zero 2 here:  https://1drv.ms/u/s!Au06jbGd_8NctIMgqsqv9tbYcJHwTQ?e=V0flcq


(Download any MIDI file)


fluidsynth -a alsa -n -i /usr/share/sounds/sf2/FluidR3_GM.sf2 midifile.mid


IF YOU GET AN ERROR SAYING "THE DEFAULT AUDIO DEVICE IS USED BY ANOTHER APPLICATION", try these steps:

When installing fluidsynth, it will be installed as a service (for whatever reason) - please do the following:

sudo systemctl disable fluidsynth.service

if that does not help, try


sudo mv /usr/lib/systemd/user/fluidsynth.service /usr/lib/systemd/user/fluidsynth.service_nonono


Then reboot.

If that doesn't help, try editing the /boot/firmware/config.txt file in your boot folder and change this line:


#Enable audio (loads snd_bcm2835)

dtparam=audio=off    # (was on)
