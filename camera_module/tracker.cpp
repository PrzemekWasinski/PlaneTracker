#include <iostream>
#include <fstream> 
#include <string> 
#include <cmath>
#include <pigpio.h>
#include "pan_tilt.hpp"

#define DEG2RAD (M_PI / 180.0)
#define RAD2DEG (180.0 / M_PI)

double myLat, myLon, myAlt;
double tgtLat, tgtLon, tgtAlt;
bool defaultMode = false;

PanTilt pt;

//load config
void loadConfig() {
    std::string configPath = "config.yaml";
    std::ifstream file(configPath);
    
    // If not found in current dir, try ../config/
    if (!file.good()) {
        file.close();
        configPath = "../config/config.yaml";
        file.open(configPath);
    }
    
    if (!file.good()) {
        std::cerr << "Error: Could not find config.yaml in ./ or ../config/\n";
        return;
    }
    
    std::cout << "Loading config from: " << configPath << "\n";
    std::string line;
    while (std::getline(file, line)) {
        if (line.empty() || line[0] == '#') continue;
        size_t colon = line.find(':');
        if (colon == std::string::npos) continue;
        
        std::string key = line.substr(0, colon);
        std::string valStr = line.substr(colon + 1);
        
        // Trim whitespace from key and value
        key.erase(0, key.find_first_not_of(" \t\n\r\f\v"));
        key.erase(key.find_last_not_of(" \t\n\r\f\v") + 1);
        valStr.erase(0, valStr.find_first_not_of(" \t\n\r\f\v"));
        valStr.erase(valStr.find_last_not_of(" \t\n\r\f\v") + 1);

        double val = 0.0;
        try { val = std::stod(valStr); } catch(...) {} // Simple parse
        
        if (key == "myLat") myLat = val;
        else if (key == "myLon") myLon = val;
        else if (key == "myAlt") myAlt = val;
        else if (key == "tgtLat") tgtLat = val;
        else if (key == "tgtLon") tgtLon = val;
        else if (key == "tgtAlt") tgtAlt = val;
        else if (key == "defaultMode") defaultMode = (valStr.find("true") != std::string::npos);
    }
    std::cout << "Loaded Config:\n";
    std::cout << "  My Pos: " << myLat << ", " << myLon << ", " << myAlt << "m\n";
    std::cout << "  Target: " << tgtLat << ", " << tgtLon << ", " << tgtAlt << "m\n";
}

// Calculate bearing (azimuth) from my position to target
double calculateBearing(double lat1, double lon1, double lat2, double lon2) {
    double dLon = (lon2 - lon1) * DEG2RAD;
    double y = sin(dLon) * cos(lat2 * DEG2RAD);
    double x = cos(lat1 * DEG2RAD) * sin(lat2 * DEG2RAD) -
               sin(lat1 * DEG2RAD) * cos(lat2 * DEG2RAD) * cos(dLon);
    double bearing = atan2(y, x) * RAD2DEG;
    
    // Normalize to 0-360
    bearing = fmod(bearing + 360.0, 360.0);
    return bearing;
}

// Calculate distance and relative bearing for servo
void calculateAngles(double &stepperAngle, double &servoAngle, bool &inRange) {
    // Calculate bearing (azimuth) to target
    double azimuth = calculateBearing(myLat, myLon, tgtLat, tgtLon);
    
    // Calculate horizontal distance using Haversine formula
    double dLat = (tgtLat - myLat) * DEG2RAD;
    double dLon = (tgtLon - myLon) * DEG2RAD;
    double a = sin(dLat/2) * sin(dLat/2) +
               cos(myLat * DEG2RAD) * cos(tgtLat * DEG2RAD) *
               sin(dLon/2) * sin(dLon/2);
    double c = 2 * atan2(sqrt(a), sqrt(1-a));
    double horizontalDist = 6371000 * c;  // Earth radius in meters
    
    // Calculate elevation angle
    double heightDiff = tgtAlt - myAlt;
    double elevationAngle = atan2(heightDiff, horizontalDist) * RAD2DEG;
    
    std::cout << "\nTarget Analysis:\n";
    std::cout << "  Azimuth: " << azimuth << "° (North=0, East=90, South=180, West=270)\n";
    std::cout << "  Distance: " << horizontalDist << " m\n";
    std::cout << "  Elevation: " << elevationAngle << "° (0=Horizon, 90=Zenith)\n";
    
    //Stepper = Pan (Azimuth)
    //Servo = Tilt (Elevation)
    
    //set Stepper to Azimuth
    stepperAngle = azimuth;
    
    //set Servo to Elevation
    if (elevationAngle < -90) elevationAngle = -90;
    if (elevationAngle > 90) elevationAngle = 90;
    
    servoAngle = 180.0 - elevationAngle; 
    
    //safety clamp for servo
    if (servoAngle < 0) servoAngle = 0;
    if (servoAngle > 180) servoAngle = 180;
    
    inRange = true;
    
    std::cout << "  Stepper Target (Azimuth): " << stepperAngle << "°\n";
    std::cout << "  Servo Target (Angle): " << servoAngle << "° (180=Flat, 90=Up)\n";
}

void prepareForTracking() {
    std::cout << "\n=== INITIALIZATION ===\n";
    std::cout << "Loading saved state (Stepper should be at North/0°)...\n";
    
    std::cout << "\nSetting Servo to default default (Horizon/Flat)...\n";
    pt.setServo(180.0);
    
    std::cout << "\nReady to track\n";
}

void trackTarget() {
    double stepperAngle, servoAngle;
    bool inRange;
    
    calculateAngles(stepperAngle, servoAngle, inRange);
    
    std::cout << "\n=== TRACKING TARGET ===\n";
    
    if(inRange) {
        pt.panToAngle(stepperAngle);
        pt.setServo(servoAngle);
        std::cout << "Tracking complete - pointing at target\n";
        pt.saveState();
    } else {
        std::cout << "Target outside servo range!\n";
    }
}

int main() {
    if(gpioInitialise() < 0) {
        std::cerr << "pigpio initialization failed\n";
        return 1;
    }
    
    loadConfig(); //load coordinates from file
    
    pt.init();
    
    //load state
    pt.loadState();
    
    std::cout << "Pan-Tilt Aircraft Tracker\n";
    std::cout << "========================\n";
    std::cout << "Servo Configuration:\n";
    std::cout << "  180° = Horizon (Flat)\n";
    std::cout << "  90°  = Up (Zenith)\n\n";
    
    //prepare set servo to horizon assume stepper is North
    prepareForTracking();
    
    gpioDelay(2000000);  //2 seconds
    
    //Track target if not in default mode
    if(!defaultMode) {
        trackTarget();
        gpioDelay(5000000);  //Hold position for 5 seconds
    } else {
        std::cout << "\nDefault mode active staying at default position\n";
        gpioDelay(5000000);
    }
    
    // Removed auto-return. We leave it at target position and save state.
    std::cout << "\nStopping at target position run calibrate -> r to reset.\n";
    
    pt.cleanup();
    pt.saveState(); // Save final state
    
    gpioTerminate();
    return 0;
}