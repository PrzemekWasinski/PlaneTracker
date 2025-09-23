# ADS-B Plane Tracker

This is my plane tracker I made with a Raspberry Pi 3 and a Radio Antenna, it catches position and flight data broadcasted from planes and displays the planes on a radar display 
in their live position. The Kotlin mobile app alerts the user if there are any planes nearby and shows live statistics.

# Current setup and Mobile App:

![pi](https://github.com/user-attachments/assets/eb424e8b-ef99-47bc-b1db-cc31004c61ce) ![tracker](https://github.com/user-attachments/assets/bfd21ef6-ab31-4d25-a3c9-39923469451d)


# How it works

![antennafull(3)](https://github.com/user-attachments/assets/5c6f30fe-3fa2-4a16-ac0f-e1837f251cfc)

# ADS-B Plane Tracker:

The Radio antenna catches ADS-B signals broadcasted from commercial, private and sometimes military planes, the data from each plane is then decoded to get the plane's flight data and 
position data. Using Python the plane is then displayed on the radar screen by converting latitude and longitude into X and Y pixel values and the data is then uploaded to a Firebase DB.

# Mobile app:

Every minute the Kotlin app pulls all the recent plane data
and compares each plane's coordinates to the user's phone coordinates, it then sends a notification with all the nearby planes. The mobile app also shows today's statistics, the amount of different planes spotted displayed in a pie chart, the Raspberry Pi's CPU temp and RAM usage, a switch letting me remotely turn the Raspberry Pi plane
tracker on and off and a date selector which can be used to view stats from different dates by pressing the `Refresh` after selecting the desired date. 

# Tech Stack
    Mobile App: Kotlin
    Plane Tracker: Python
    Radar GUI: Pygame
    Database: Firebase
    Hardware: Raspberry Pi 4b, NESDR Mini USB ADS-B receiver + Antenna
    