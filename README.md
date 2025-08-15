# ADS-B Plane Tracker

This is my plane tracker I made with a Raspberry Pi 3 and a Radio Antenna, it catches position and flight data broadcasted from planes, displays the planes on a radar display 
in their live position. The plane data is then periodically pulled by my Kotlin mobile app and it notifies the user if there is any planes near them.

# Current setup and Mobile App:

![pi](https://github.com/user-attachments/assets/eb424e8b-ef99-47bc-b1db-cc31004c61ce) ![tracker](https://github.com/user-attachments/assets/bfd21ef6-ab31-4d25-a3c9-39923469451d)


# How it works

The Radio antenna catches ADS-B signals broadcasted from commercial, private and sometimes smilitary planes, the data from each plane is then decoded to get the plane's flight data and 
position data. Using Python the plane is then displayed on the radar screen by converting latitude and longitude into X and Y pixel values. The data is then sent and stored in a Firebase DB.

# Mobile app
Every minute the Kotlin app pulls all the recent plane data
and compares each plane's coordinates to the user's phone coordinates then sends a notification with all the nearby planes. The mobile app also shows the total stats and the amount of diffferent planes spotted in a pie chart, the Raspberry Pi's CPU temp and RAM usage, a switch letting me turn the
tracker on and off and a date selector which can be used to view stats from different dates by pressing the `Refresh` after selecting the desired date. 
