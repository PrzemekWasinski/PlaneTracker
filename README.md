# ADS-B Plane Tracker

This is my plane tracker I made with a Raspberry Pi 4 and a Radio Antenna, it catches flight data broadcasted from planes and uses this data to populate the radar display,
the flight data is also uploaded to Firebase for my Kotlin app to use.

![planes](https://github.com/user-attachments/assets/8f3b0528-d802-44fc-aa27-f57cd7dce782)

# GUI
<img width="691" height="415" alt="menu" src="https://github.com/user-attachments/assets/0b9e0b60-83fb-40f2-8fbe-53f0b625d2b4" />

This is the radar GUI showing planes in their live position, nearby airports and rings showing different distances, the arrow on the right side of the screen opens a menu
that can be used to zoom in and out, pause and unpause the plane tracker, see logs, see the Raspberry Pi's system performance, time and amount of planes being tracked.


# How it works

![antennafull(3)](https://github.com/user-attachments/assets/5c6f30fe-3fa2-4a16-ac0f-e1837f251cfc)

The Radio antenna catches ADS-B signals broadcasted from commercial, private and sometimes military planes, the data from each plane is then decoded to get the plane's flight data and 
position data. Using Python the plane is then displayed on the radar screen by converting latitude and longitude into X and Y pixel values and the data is then uploaded to a Firebase DB.

Currently the max range I've gotten is about 150 Km meaning with a slightly bigger antenna mounted higher I would be able to track planes flying in France and Belgium.

# Tech Stack
    Language: Python & C++
    Radar GUI: Pygame
    Database: Firebase
    Hardware: Raspberry Pi 4b, NESDR Mini USB ADS-B receiver + Antenna
    
