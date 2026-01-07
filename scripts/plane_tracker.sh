#Simple Bash script to automatically switch to the right directory and start the plane tracker program

#Double ../ because the plane tracker directory is behind the /home directory
#And this script is in /home/desktop
cd ../../plane_tracker 
source venv/bin/activate
python ./plane_tracker.py
