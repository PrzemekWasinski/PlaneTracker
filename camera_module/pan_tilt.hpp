#pragma once
#include <iostream>
#include <fstream>
#include <cmath>
#include <pigpio.h>
#include <unistd.h>

//constants
const int STEP_PINS[4] = {17, 18, 27, 22};
const int SERVO_PIN = 12;
const int STEPS_PER_REV = 540; //270 steps = 180 deg -> 540 steps/360 deg
const int STEP_DELAY_MS = 4;
const std::string STATE_FILE = "motor_state.txt";
const bool INVERT_STEPPER = false;

class PanTilt {
private:
    //28BYJ-48 stepper motor halfstep sequence
    int seq[8][4] = {
        {1,0,0,0}, {1,1,0,0}, {0,1,0,0}, {0,1,1,0},
        {0,0,1,0}, {0,0,1,1}, {0,0,0,1}, {1,0,0,1}
    };

    void normalizePan() {
        while(currentPan < 0) currentPan += 360.0;
        while(currentPan >= 360.0) currentPan -= 360.0;
    }

public:
    double currentPan = 0.0;
    double currentTilt = 90.0;

    PanTilt() {}

    void init() {
        //setup pins
        for(int i = 0; i < 4; i++) {
            gpioSetMode(STEP_PINS[i], PI_OUTPUT);
        }
        gpioSetMode(SERVO_PIN, PI_OUTPUT);
    }

    void cleanup() {
        for(int p = 0; p < 4; p++) {
            gpioWrite(STEP_PINS[p], 0);
        }
    }

    void loadState() {
        std::ifstream in(STATE_FILE);
        if(in >> currentPan >> currentTilt) {
            std::cout << "Loaded: Pan=" << currentPan << "°, Tilt=" << currentTilt << "°\n";
        } else {
            std::cout << "No save file found defaults = (Pan=0, Tilt=90).\n";
            currentPan = 0.0;
            currentTilt = 90.0;
        }
    }

    void saveState() {
        std::ofstream out(STATE_FILE);
        if(out << currentPan << " " << currentTilt) {
            std::cout << "Saved: Pan=" << currentPan << "°, Tilt=" << currentTilt << "°\n";
        } else {
            std::cerr << "Error saving state!\n";
        }
    }

    void stepMotor(int steps, bool clockwise) {
        int absSteps = abs(steps);
        
        if (INVERT_STEPPER) {
            clockwise = !clockwise;
        }
        
        for(int i = 0; i < absSteps; i++) {
            for(int s = 0; s < 8; s++) {
                int idx = clockwise ? s : (7 - s);
                for(int p = 0; p < 4; p++) {
                    gpioWrite(STEP_PINS[p], seq[idx][p]);
                }
                gpioDelay(STEP_DELAY_MS * 1000);
            }
        }
        cleanup(); 
    }

    //move relative steps and update internal angle
    void moveStepperSteps(int steps) {
        if (steps == 0) return;
        bool clockwise = steps > 0;
        stepMotor(abs(steps), clockwise);
        
        double angleChange = (double)steps / STEPS_PER_REV * 360.0;
        currentPan += angleChange;
        normalizePan();
    }

    void panToAngle(double targetAngle) {
        while(targetAngle < 0) targetAngle += 360;
        while(targetAngle >= 360) targetAngle -= 360;
        
        normalizePan();
        
        //calculate shortest path
        double diff = targetAngle - currentPan;
        if(diff > 180) diff -= 360;
        if(diff < -180) diff += 360;
        
        //convert angle to steps
        int steps = (int)((diff / 360.0) * STEPS_PER_REV);
        
        if(steps != 0) {
            std::cout << "Pan: " << currentPan << "° -> " << targetAngle 
                      << "° (" << diff << "°, " << steps << " steps)\n";
            stepMotor(abs(steps), steps > 0); //steps > 0 is clockwise
            currentPan = targetAngle;
        }
    }

    void setServo(double angle) {
        if(angle < 0) angle = 0;
        if(angle > 180) angle = 180;
        
        int pulse = 500 + (int)((angle / 180.0) * 2000);
        gpioServo(SERVO_PIN, pulse);
        currentTilt = angle;
        
        std::cout << "Servo: " << angle << "° (Pulse: " << pulse << ")\n";
    }
};
