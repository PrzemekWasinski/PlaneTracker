# Plane Tracker

This is my plane tracker I made with a Raspberry Pi 3 and an ADS-B antenna, it catches position and flight data broadcasted from planes, displays the planes on a radar display 
in their live position and uploads all of the received data to my Firebase DB.

The plane data is also periodically pulled by my Kotlin mobile app which compares all the recent plane's coordinates to my phone's current coordinates and if a plane is 
nearby and was picked up by the antenna recently the app will send a notification displaying which plane's are nearby.

# How it works

As I mentioned earlier the project uses an antenna that picks up ADS-B (Automatic Dependent Surveillance-Broadcast) signals these are broadcasted from every commercial, private 
and some military aircraft. The signals that are picked up by the antenna are then decoded by the raspberry pi which give us the plane's hex code, longitude, latitude, altitude
and some other info. The data then gets uploaded to Firebase and the planes are displayed on the radar in their live position by converting coordinates into pixel x and y 
values.

Every few minutes the Kotlin app pulls all the plane data but only if its less than 10 minutes old, this is because pulling lots of data from 
Firebase can get expensive. How this is done is before the raspberry pi uploads a plane it checks when it was received if it was received at 9:56
it will round it to 9:50 and store all the planes in a collection called `9:50` so every 10 minute a new collection is made and the Kotlin app 
only pulls the most recent 10 minute collection of planes. The Kotlin app then goes through all this data and checks which planes have been
spotted within 2 minutes and if they have been spotted within 8KM of the user's phone coordinates if both of these conditions are true then the
plane gets added to a list and once all the planes have been iterated through the app will send a notification with all the planes that are near
the user.

# Current Setup
![pi](https://github.com/user-attachments/assets/135cd4fe-5195-4ed9-b3ac-d7d491639194)

Here is the Raspberry Pi connected to a display, the display has a radar GUI which is used to display th elive positions of planes being picked up by the receiver. the display also contains a pop up menu which contains the performance stats of the Raspberry Pi, logs of planes being picked up and controls such as zoom in/out, pause and stop the tracker.

# Mobile App
![Screenshot_20250624_212920_ADSB Plane Tracker(1)](https://github.com/user-attachments/assets/af2a83c0-3a1b-4710-bcf4-dca561aa646d)

This is the mobile app made in Kotlin, it shows the total stats and the amount of diffferent planes spotted using a pie chart, the CPU temp and RAM usage of the Raspberry Pi, a run switch letting me turn the Pi on and off and a date selector which can be used to view stats from different dates by pressing the `Refresh` after selecting the desired date.
