#!/bin/bash

#Simple Bash script to automatically switch to the right directory and start the plane tracker program

cd ~/PlaneTracker && source venv/bin/activate && python3 ./plane_tracker.py
