#include <iostream>
#include <string>
#include "pan_tilt.hpp"

//clear input buffer
void clearInput() {
    std::cin.ignore(1000, '\n');
}

int main() {
    if(gpioInitialise() < 0) {
        std::cerr << "pigpio error\n";
        return 1;
    }

    PanTilt pt;
    pt.init();
    pt.loadState();

    bool running = true;
    char cmd;

    std::cout << "\nPan Tilt Calibration\n";

    while(running) {
        std::cout << "\n----------------------------\n";
        std::cout << "Current Angles:\n";
        std::cout << "  Azumith Motor Angle: " << pt.currentPan << "°\n";
        std::cout << "  Tilt Motor Angle:      " << pt.currentTilt << "°\n";
        std::cout << "----------------------------\n";
        std::cout << "Menu:\n";
        std::cout << "  s: Move Azumith (Steps)\n";
        std::cout << "  g: Go to Azumith Angle (degrees)\n";
        std::cout << "  v: Set Tilt (Angle)\n";
        std::cout << "  r: Reset Position\n";
        std::cout << "  z: Zero Stepper\n";
        std::cout << "  q: Save & Quit\n";
        std::cout << "> ";
        
        std::cin >> cmd;

        if (cmd == 's') {
            int steps;
            std::cout << "Enter number of steps: ";
            if(std::cin >> steps) {
                std::cout << "Moving " << steps << " steps...\n";
                pt.moveStepperSteps(steps);
            } else {
                std::cout << "Invalid input\n";
                // Reset cin error state
                std::cin.clear();
                clearInput();
            }
        }
        else if (cmd == 'g') {
            double target;
            std::cout << "Enter target Azumith angle (0-360): ";
            if(std::cin >> target) {
                std::cout << "Moving to " << target << "°...\n";
                pt.panToAngle(target);
            } else {
                std::cout << "Invalid input\n";
                std::cin.clear();
                clearInput();
            }
        }
        else if (cmd == 'r') {
            std::cout << "Returning to 0° (North)...\n";
            std::cout << "Current Pan: " << pt.currentPan << "°\n";
            pt.panToAngle(0.0);
            
            std::cout << "Resetting Servo to 180° (North Flat)...\n";
            pt.setServo(180.0);
            
            pt.saveState();
            std::cout << "Reset complete position saved as 0\n";
        } 
        else if (cmd == 'v') {
            double angle;
            std::cout << "Enter tilt angle (0-180): ";
            if(std::cin >> angle) {
                std::cout << "Setting servo to " << angle << "°...\n";
                pt.setServo(angle);
            } else {
                std::cout << "Invalid input\n";
                std::cin.clear();
                clearInput();
            }
        } 
        else if (cmd == 'z') {
            std::cout << "Zeroing stepper position...\n";
            std::cout << "Current physical position is now defined as 0° (North)\n";
            pt.currentPan = 0;
            pt.saveState();
        } 
        else if (cmd == 'q') {
            std::cout << "Saving state and exiting...\n";
            pt.saveState();
            running = false;
        } 
        else {
            std::cout << "Unknown command\n";
            clearInput();
        }
    }

    pt.cleanup();
    gpioTerminate();
    return 0;
}
