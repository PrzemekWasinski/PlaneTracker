# Plane Tracker

This is my plane tracker project which uses a raspberry pi 3 and an ADS-B receiver to catch plane signals containing their location and flight data. This information
is then uploaded to Firebase and retrieved by a Kotlin app running on my phone which sends periodic notifications about which planes are near my coordinates and lets
me see how the raspberry pi is running.

# Current Setup
![20250327_221017(1)](https://github.com/user-attachments/assets/880dfb90-bb74-4b0d-a955-8516e61e497f)

Here is the Raspberry Pi connected to a screen which displays the device stats and the plane data it receives.

# Mobile App
![Screenshot_20250327_221935_ADSB Plane Tracker(1)](https://github.com/user-attachments/assets/5d865781-7706-4403-b1e7-e1fd96a8d875)

This is the mobile app showing today's planes and the stats of the raspberry pi, the run switch lets me remotely stop and start the script.
