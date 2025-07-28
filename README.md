# ADS-B Plane Tracker

This is my plane tracker I made with a Raspberry Pi 3 and an ADS-B antenna, it catches position and flight data broadcasted from planes, displays the planes on a radar display 
in their live position and uploads all of the received data to my Firebase DB. The plane data is then periodically pulled by my Kotlin mobile app and it notifies the user if there is any planes near them.


![pi](https://github.com/user-attachments/assets/eb424e8b-ef99-47bc-b1db-cc31004c61ce) ![tracker](https://github.com/user-attachments/assets/bfd21ef6-ab31-4d25-a3c9-39923469451d)


# How it works

The ADS-B antenna catches signals broadcasted from commercial, private and sometime smilitary planes, the data from each plane is then decoded to get the plane's flight data and 
position data. Using Python the plane is then displayed on the radar screen by converting latitude and longitude into X and Y pixel values. The data is then sent to Firebase 
which groups planes in different collections based on the date and time they were spotted. 

Every minute the Kotlin app pulls data only from the most recent Firebase collection 
and compares each plane's coordinates to the user's phone coordinates. If they are within 10Km and the plane was at those coordinates less than a minute ago that means the plane 
is near the user and gets added to a list of all the planes that are near the user. Once all the planes have been evaluated a notification gets sent with all the planes near 
the user. it shows the total stats and the amount of diffferent planes spotted using a pie chart, the CPU temp and RAM usage of the Raspberry Pi, a run switch letting me turn the
tracker on and off and a date selector which can be used to view stats from different dates by pressing the `Refresh` after selecting the desired date. 
