# Plane Tracker

This is my plane tracker project which uses a Raspberry Pi 3 and an ADS-B receiver to catch plane signals containing their location and flight data. Plane information
is then uploaded to Firebase and retrieved by a Kotlin app running on my phone which sends notifications about which planes are near my coordinates and lets
me see how the Raspberry Pi is running.

# Current Setup
![Screenshot_20250430_205831_Gallery(1)](https://github.com/user-attachments/assets/e4e8e073-d43b-44eb-b008-1ece09313d53)

Here is the Raspberry Pi connected to a screen with a radar GUI which displays the device stats and the plane data it receives plotting the planes on the map according to their real time position.

# Mobile App
![Screenshot_20250327_221935_ADSB Plane Tracker(1)](https://github.com/user-attachments/assets/5d865781-7706-4403-b1e7-e1fd96a8d875)

This is the mobile app showing today's planes and the stats of the raspberry pi, the run switch lets me remotely stop and start the script and the calendar lets me see planes from the past.
