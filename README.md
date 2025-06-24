# Plane Tracker

This is my plane tracker project which uses a raspberry pi 3 and an ADS-B receiver to catch plane signals containing their location and flight data. This information
is then uploaded to Firebase and retrieved by a Kotlin app running on my phone which sends periodic notifications about which planes are near my coordinates and lets
me see how the raspberry pi is running.

# Current Setup
![pi](https://github.com/user-attachments/assets/135cd4fe-5195-4ed9-b3ac-d7d491639194)

Here is the Raspberry Pi connected to a screen which displays the device stats and the plane data it receives.

# Mobile App
![Screenshot_20250624_212920_ADSB Plane Tracker(1)](https://github.com/user-attachments/assets/af2a83c0-3a1b-4710-bcf4-dca561aa646d)

This is the mobile app made in Kotlin, it shows the total stats and the amount of diffferent planes spotted using a pie chart, the CPU temp and RAM usage of the Raspberry Pi, a run switch letting me turn the Pi on and off and a date selector which can be used to view stats from different dates by pressing the `Refresh` after selecting the desired date.
