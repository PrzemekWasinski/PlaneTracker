# ADS-B Plane Tracker

This is my plane tracker I made with a Raspberry Pi 3 and an ADS-B antenna, it catches position and flight data broadcasted from planes, displays the planes on a radar display 
in their live position and uploads all of the received data to my Firebase DB. The plane data is then periodically pulled by my Kotlin mobile app and it notifies the user if there is any planes near them.

# How it works

The ADS-B antenna catches signals broadcasted from commercial, private and sometime smilitary planes, the data from each plane is then decoded to get the plane's flight data and 
position data. Using Python the plane is then displayed on the radar screen by converting latitude and longitude into X and Y pixel values. The data is then sent to Firebase 
which groups planes in different collections based on the date and time they were spotted. 

Every minute the Kotlin app pulls data only from the most recent Firebase collection 
and compares each plane's coordinates to the user's phone coordinates. If they are within 10Km and the plane was at those coordinates less than a minute ago that means the plane 
is near the user and gets added to a list of all the planes that are near the user. Once all the planes have been evaluated a notification gets sent with all the planes near 
the user

# Current Setup
![pi](https://github.com/user-attachments/assets/135cd4fe-5195-4ed9-b3ac-d7d491639194)

Here is the Raspberry Pi connected to a display, the display has a radar GUI which is used to display the live positions of planes being picked up by the receiver. the display also contains a pop up menu which contains the performance stats of the Raspberry Pi, logs of planes being picked up and control buttons such as zoom in/out, pause and an off
button

# Mobile App
![Screenshot_20250624_212920_ADSB Plane Tracker(1)](https://github.com/user-attachments/assets/af2a83c0-3a1b-4710-bcf4-dca561aa646d)

This is the mobile app made in Kotlin, it shows the total stats and the amount of diffferent planes spotted using a pie chart, the CPU temp and RAM usage of the Raspberry Pi, a run switch letting me turn the Pi on and off and a date selector which can be used to view stats from different dates by pressing the `Refresh` after selecting the desired date.
