#include <iostream>
#include <fstream>
#include <string>
#include <cmath>
#include <pigpio.h>
#include <sys/socket.h>
#include <netinet/in.h>
#include <unistd.h>
#include <cstring>
#include <thread>
#include <atomic>

//SERVO PINS
const int PAN_PIN  = 18;
const int TILT_PIN = 19;

//SERVO CALIBRATION

const int TILT_INPUT_MIN  = 15; //Max 15 degrees due to physical blockage
const int TILT_INPUT_MAX  = 270;

const int PWM_FREQ        = 50;
const int PULSE_MIN_US    = 400;
const int PULSE_MAX_US    = 2500;
const int SERVO_INPUT_MAX = 270;

std::atomic<bool> busy(false);

//Load yaml
struct HomeConfig {
    double lat          = 0.0;
    double lon          = 0.0;
    double elevation    = 0.0;
    double bearing      = 180.0;  
    bool   pan_clockwise = false;  
};

static std::string trim(const std::string& s) {
    size_t a = s.find_first_not_of(" \t\r\n");
    size_t b = s.find_last_not_of(" \t\r\n");
    return (a == std::string::npos) ? "" : s.substr(a, b - a + 1);
}

bool loadConfig(const std::string& path, HomeConfig& cfg) {
    std::ifstream f(path);
    if (!f.is_open()) {
        std::cerr << "ERROR: Cannot open " << path << "\n";
        return false;
    }
    std::string line;
    while (std::getline(f, line)) {
        size_t hash = line.find('#');
        if (hash != std::string::npos) line = line.substr(0, hash);
        size_t colon = line.find(':');
        if (colon == std::string::npos) continue;
        std::string key = trim(line.substr(0, colon));
        std::string val = trim(line.substr(colon + 1));
        if (key.empty() || val.empty()) continue;
        try {
            if      (key == "home_lat")       cfg.lat          = std::stod(val);
            else if (key == "home_lon")       cfg.lon          = std::stod(val);
            else if (key == "home_elevation") cfg.elevation    = std::stod(val);
            else if (key == "home_bearing")   cfg.bearing      = std::stod(val);
            else if (key == "pan_clockwise")  cfg.pan_clockwise = (val == "true");
        } catch (...) {
            std::cerr << "WARNING: Could not parse value for key '" << key << "'\n";
        }
    }
    return true;
}

//Motor angle calculation
const double DEG2RAD = M_PI / 180.0;
const double RAD2DEG = 180.0 / M_PI;
const double EARTH_R = 6371000.0;

double haversineBearing(double latA, double lonA, double latB, double lonB) {
    double dLon = (lonB - lonA) * DEG2RAD;
    double la   = latA * DEG2RAD;
    double lb   = latB * DEG2RAD;
    double y = std::sin(dLon) * std::cos(lb);
    double x = std::cos(la) * std::sin(lb) - std::sin(la) * std::cos(lb) * std::cos(dLon);
    return std::fmod(std::atan2(y, x) * RAD2DEG + 360.0, 360.0);
}

double haversineDistance(double latA, double lonA, double latB, double lonB) {
    double dLat = (latB - latA) * DEG2RAD;
    double dLon = (lonB - lonA) * DEG2RAD;
    double a = std::sin(dLat / 2) * std::sin(dLat / 2)
             + std::cos(latA * DEG2RAD) * std::cos(latB * DEG2RAD)
             * std::sin(dLon / 2) * std::sin(dLon / 2);
    return EARTH_R * 2.0 * std::atan2(std::sqrt(a), std::sqrt(1 - a));
}

double elevationAngle(double distanceM, double homeElevM, double targetElevM) {
    double altDiff = targetElevM - homeElevM;
    return std::atan2(altDiff, distanceM) * RAD2DEG;
}


struct ServoInputs {
    int  pan;
    int  tilt;
    bool valid;
    bool backMode;
};

ServoInputs computeServoInputs(double bearing, double elevDeg, double homeBearing, bool panClockwise) {
    ServoInputs r = {0, 0, false, false};

    bearing = std::fmod(bearing + 360.0, 360.0);

    //If target below horizon (should never happen because planes fly high)
    if (elevDeg < 0.0) return r;
    if (elevDeg > 90.0) elevDeg = 90.0;

    double diff;
    if (panClockwise) {
        diff = std::fmod(bearing - homeBearing + 360.0, 360.0);
    } else {
        diff = std::fmod(homeBearing - bearing + 360.0, 360.0);
    }

    bool backMode = (diff > 180.0);
    r.backMode    = backMode;

    double panDiff;
    double tiltPhys;  

    if (!backMode) {
        panDiff  = diff;
        tiltPhys = elevDeg;
    } else {
        panDiff  = diff - 180.0;      
        tiltPhys = 180.0 - elevDeg;   
    }

    int panInput  = (int)std::round(panDiff  * (270.0 / 180.0));

    int tiltInput = (int)std::round(tiltPhys * (270.0 / 180.0));

    if (tiltInput < TILT_INPUT_MIN) tiltInput = TILT_INPUT_MIN;

    if (panInput  < 0)              panInput  = 0;
    if (panInput  > SERVO_INPUT_MAX) panInput  = SERVO_INPUT_MAX;
    if (tiltInput > TILT_INPUT_MAX) tiltInput = TILT_INPUT_MAX;

    r.pan   = panInput;
    r.tilt  = tiltInput;
    r.valid = true;
    return r;
}

//SERVO DRIVER
void setServo(int pin, int servoInput) {
    int pulseUs = PULSE_MIN_US + (int)std::round(
        (double)servoInput / SERVO_INPUT_MAX * (PULSE_MAX_US - PULSE_MIN_US)
    );
    unsigned int duty = (unsigned int)((double)pulseUs / 20000.0 * 1000000.0);
    gpioHardwarePWM(pin, PWM_FREQ, duty);
}

void stopServos() {
    gpioHardwarePWM(PAN_PIN,  0, 0);
    gpioHardwarePWM(TILT_PIN, 0, 0);
}

//Tracking function
void trackPlane(double lat, double lon, double alt, HomeConfig& cfg, int client_socket) {
    // use local parameters rather than modifying the const test targets
    double bearing = haversineBearing(cfg.lat, cfg.lon, lat, lon);
    double distance = haversineDistance(cfg.lat, cfg.lon, lat, lon);
    double elev = elevationAngle(distance, cfg.elevation, alt);

    ServoInputs s = computeServoInputs(bearing, elev, cfg.bearing, cfg.pan_clockwise);

    if (!s.valid) {
        send(client_socket, "error", strlen("error"), 0);
        close(client_socket);
        busy.store(false);
        return;
    }

    if (gpioInitialise() < 0) {
        send(client_socket, "error", strlen("error"), 0);
        close(client_socket);
        busy.store(false);
        return;
    }

    gpioSetMode(PAN_PIN, PI_OUTPUT);
    gpioSetMode(TILT_PIN, PI_OUTPUT);

    setServo(PAN_PIN, s.pan);
    setServo(TILT_PIN, s.tilt);

    stopServos();
    gpioTerminate();

    send(client_socket, "success", strlen("success"), 0);
    close(client_socket);
    busy.store(false);
}

//Main loop
int main() {
    HomeConfig cfg;
    if (!loadConfig("home.yaml", cfg)) return 1;

    std::cout << "\n--------------------------------------------\n";
    std::cout << "  Camera Tracker Server\n";
    std::cout << "--------------------------------------------\n";
    std::cout << "  Home   : " << cfg.lat << "°, " << cfg.lon << "°"
              << " @ " << cfg.elevation << " m\n";
    std::cout << "  Home bearing (pan=0): " << cfg.bearing << "°\n";
    std::cout << "  Pan direction: "
              << (cfg.pan_clockwise ? "clockwise" : "counter-clockwise") << "\n";
    std::cout << "--------------------------------------------\n";
    std::cout << "  Listening on port 12345...\n\n";

    int server_fd, new_socket;
    struct sockaddr_in address;
    int addrlen = sizeof(address);

    if ((server_fd = socket(AF_INET, SOCK_STREAM, 0)) == 0) {
        perror("socket failed");
        return 1;
    }

    address.sin_family = AF_INET;
    address.sin_addr.s_addr = INADDR_ANY;
    address.sin_port = htons(12345);

    if (bind(server_fd, (struct sockaddr *)&address, sizeof(address)) < 0) {
        perror("bind failed");
        return 1;
    }

    if (listen(server_fd, 3) < 0) {
        perror("listen");
        return 1;
    }

    while (true) {
        if ((new_socket = accept(server_fd, (struct sockaddr *)&address, (socklen_t*)&addrlen)) < 0) {
            perror("accept");
            continue;
        }

        char buffer[1024] = {0};
        int valread = read(new_socket, buffer, 1024);

        double lat, lon, alt;
        if (sscanf(buffer, "%lf,%lf,%lf", &lat, &lon, &alt) != 3) {
            send(new_socket, "error", strlen("error"), 0);
            close(new_socket);
            continue;
        }

        bool expected = false;
        if (!busy.compare_exchange_strong(expected, true)) {
            send(new_socket, "busy", strlen("busy"), 0);
            close(new_socket);
            continue;
        }

        std::thread tracker_thread(trackPlane, lat, lon, alt, std::ref(cfg), new_socket);
        tracker_thread.detach();
    }

    return 0;
}
