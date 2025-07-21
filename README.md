# Plane Tracker

This is my plane tracker I made with a Raspberry Pi 3 and an ADS-B antenna, it catches position and flight data broadcasted from planes, displays the planes on a radar display 
in their live position and uploads all of the received data to my Firebase DB.

The plane data is also periodically pulled by my Kotlin mobile app which compares all the recent plane's coordinates to my phone's current coordinates and if a plane is 
nearby and was picked up by the antenna recently the app will send a notification displaying which plane's are nearby.

# How it works

As I mentioned earlier the project uses an antenna that picks up ADS-B (Automatic Dependent Surveillance-Broadcast) signals these are broadcasted from every commercial, private 
and some military aircraft. The signals that are picked up by the antenna are then decoded by the raspberry pi which give us the plane's hex code, longitude, latitude, altitude
and some other info. Using Python the data gets uploaded to Firebase and the planes are displayed on the radar in their live position by converting coordinates into pixel x and y 
values.

# Current Setup
![pi](https://github.com/user-attachments/assets/135cd4fe-5195-4ed9-b3ac-d7d491639194)

Here is the Raspberry Pi connected to a display, the display has a radar GUI which is used to display th elive positions of planes being picked up by the receiver. the display also contains a pop up menu which contains the performance stats of the Raspberry Pi, logs of planes being picked up and controls such as zoom in/out, pause and stop the tracker.

# Mobile App
![Screenshot_20250624_212920_ADSB Plane Tracker(1)](https://github.com/user-attachments/assets/af2a83c0-3a1b-4710-bcf4-dca561aa646d)

This is the mobile app made in Kotlin, it shows the total stats and the amount of diffferent planes spotted using a pie chart, the CPU temp and RAM usage of the Raspberry Pi, a run switch letting me turn the Pi on and off and a date selector which can be used to view stats from different dates by pressing the `Refresh` after selecting the desired date.
