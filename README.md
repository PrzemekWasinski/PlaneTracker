# ADS-B Plane Tracker

This is my ADS-B Aircraft Tracker. It works by picking up signals from aircraft and showing their positions on a radar-style display.

Aircraft in flight continuously broadcast information about themselves, including their location. These radio signals use a technology called ADS-B. My system receives these radio signals using a 1090 MHz radio antenna. The signals are then processed by a software called Dump1090, which decodes the radio messages and converts the data into JSON format that can be used by 'plane_tracker.pu`. Once the aircraft’s latitude and longitude are decoded, the system converts these coordinates into X and Y pixel positions. This allows each aircraft to be displayed accurately on the radar screen in its live position.

# Demo Video

https://github.com/user-attachments/assets/47664e26-9741-456e-98a1-10eecfc91036

# GUI

<img width="1600" height="900" alt="gui" src="https://github.com/user-attachments/assets/451635a0-fd22-4958-afec-cd45e10c19d7" />

This is the GUI, it displays aircraft in their live position which get updated everytime a new ADS-B signal is received for that aircraft, after the aircraft is updated the old position is saved on the radar display creating a historical trajectory over time. A mouse can be used to select different aircraft to view their stats such as their altitude, airline, aircraft type and more, if an aircraft is not selected by the user the program will 
display the stats of the nearest aircraft.

The GUI also includes statistics from the past 24 hours, information about the currently slected aircrfat, logs, system performance, a polar plot to inspect the radio coverage, altitude / distance filters and a toolbar.

# How it works

<img width="4032" height="3024" alt="20260414_161829" src="https://github.com/user-attachments/assets/7f2f82dd-a575-4e07-bcab-c253a1889c4c" />

<img width="4032" height="3024" alt="20260416_201814" src="https://github.com/user-attachments/assets/a198839a-fb1a-482e-b815-5f78d26b1f78" />

The radio antenna receives ADS-B signals on 1090 MHz, which is the standard frequency used by aircraft for these broadcasts. While Dump1090 runs in the background, it tunes a device called an RTL-SDR to this frequency.

An RTL-SDR (Realtek Software Defined Radio) is a low-cost USB device that can receive radio signals and pass them to a computer for processing. In this system, it captures the ADS-B signals and allows them to be converted into digital data.

After the signals are decoded, all further processing is handled by `plane_tracker.py`. Currently, the system has a maximum observed range of about 150 nautical miles, which allows me to track aircraft over countries such as France and Belgium while operating from England.

# Plane Cam

<img width="4032" height="3024" alt="20260405_104031" src="https://github.com/user-attachments/assets/1543526a-0ff3-4f91-9622-76ae15331a22" />

This system works with [PlaneCam](https://github.com/PrzemekWasinski/PlaneCam) to optically track the aircraft that are picked up by the radio antenna. This is doen by converting an aircraft's latitude and longitude into servo motor angles, taking an image when the servo motors are locked onto the aircraft and sending it back over the local network.

# Tech Stack
    Language: Python
    Radar GUI: Pygame
    Hardware: Raspberry Pi 4b, RTL-SDR BLOG V4 & 60cm 1090MHz radio antenna
    
