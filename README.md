# ADS-B Plane Tracker

This is my plane tracker I made with a Raspberry Pi 4 and a Radio Antenna, it catches flight data broadcasted from planes and uses this data to populate the radar display,
the flight data is also uploaded to Firebase for my Kotlin app to use.

# Current setup:

![20251127_111136(1)](https://github.com/user-attachments/assets/98fc99f8-623c-4a89-9fcd-6529e1f90010)

# How it works

![antennafull(3)](https://github.com/user-attachments/assets/5c6f30fe-3fa2-4a16-ac0f-e1837f251cfc)

The Radio antenna catches ADS-B signals broadcasted from commercial, private and sometimes military planes, the data from each plane is then decoded to get the plane's flight data and 
position data. Using Python the plane is then displayed on the radar screen by converting latitude and longitude into X and Y pixel values and the data is then uploaded to a Firebase DB.

Currently the max range I've gotten is about 150 Km meaning with a slightly bigger antenna mounted higher I would be able to track planes flying in France and Belgium.

# Tech Stack
    Language: Python
    Radar GUI: Pygame
    Database: Firebase
    Hardware: Raspberry Pi 4b, NESDR Mini USB ADS-B receiver + Antenna
    
