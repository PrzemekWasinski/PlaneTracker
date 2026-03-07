#include <iostream>
#include <string>
#include <cmath>
#include <pigpio.h>

//Config
const int SERVO1_PIN = 18;
const int SERVO2_PIN = 19;

const int PWM_FREQ  = 50;     
const int MAX_ANGLE = 270;   
const int PULSE_MIN = 400;   
const int PULSE_MAX = 2500;  

//Helper functions
void setServo(int pin, int angle) {
    if (angle < 0)         angle = 0;
    if (angle > MAX_ANGLE) angle = MAX_ANGLE;

    int pulseUs = PULSE_MIN + (int)round(
        (double)angle / MAX_ANGLE * (PULSE_MAX - PULSE_MIN)
    );

    unsigned int duty = (unsigned int)((double)pulseUs / 20000.0 * 1000000.0);

    gpioHardwarePWM(pin, PWM_FREQ, duty);

    std::cout << "  → GPIO " << pin
              << " | angle " << angle << "°"
              << " | pulse " << pulseUs << " µs"
              << " | duty "  << duty   << "\n";
}

void stopServos() {
    gpioHardwarePWM(SERVO1_PIN, 0, 0);
    gpioHardwarePWM(SERVO2_PIN, 0, 0);
    std::cout << "  Both servos relaxed (no holding torque).\n";
}

void printHelp() {
    std::cout << "\n--------------------------------------------\n";
    std::cout << "  MG996R Servo Controller\n";
    std::cout << "  Max angle : " << MAX_ANGLE << "°\n";
    std::cout << "  Pulse range: " << PULSE_MIN << "–" << PULSE_MAX << " µs\n";
    std::cout << "--------------------------------------------\n";
    std::cout << "  1 <angle>  move Servo 1      e.g.  1 90\n";
    std::cout << "  2 <angle>  move Servo 2      e.g.  2 150\n";
    std::cout << "  b <angle>  move Both         e.g.  b 0\n";
    std::cout << "  s          stop / relax both servos\n";
    std::cout << "  h          show this help\n";
    std::cout << "  q          quit\n";
    std::cout << "--------------------------------------------\n";
}

// ── Main ──────────────────────────────────────────────────────────────────────
int main() {
    if (gpioInitialise() < 0) {
        std::cerr << "ERROR: Failed to initialise pigpio (run with sudo)\n"
        return 1;
    }

    gpioSetMode(SERVO1_PIN, PI_OUTPUT);
    gpioSetMode(SERVO2_PIN, PI_OUTPUT);

    printHelp();

    std::string line;
    while (true) {
        std::cout << "\nCommand: ";
        if (!std::getline(std::cin, line)) break;
        if (line.empty()) continue;

        char cmd = line[0];

        if (cmd == 'q' || cmd == 'Q') {
            break;

        } else if (cmd == 'h' || cmd == 'H') {
            printHelp();

        } else if (cmd == 's' || cmd == 'S') {
            stopServos();

        } else if (cmd == '1' || cmd == '2' || cmd == 'b' || cmd == 'B') {
            if (line.size() < 3) {
                std::cout << "  Please provide an angle, e.g. '1 90'\n";
                continue;
            }
            try {
                int angle = std::stoi(line.substr(2));
                if (cmd == '1') {
                    setServo(SERVO1_PIN, angle);
                } else if (cmd == '2') {
                    setServo(SERVO2_PIN, angle);
                } else {
                    setServo(SERVO1_PIN, angle);
                    setServo(SERVO2_PIN, angle);
                }
            } catch (...) {
                std::cout << "  Invalid angle. Use a number, e.g. '1 90'\n";
            }

        } else {
            std::cout << "  Unknown command. Type 'h' for help.\n";
        }
    }

    stopServos();
    gpioTerminate();
    std::cout << "Bye!\n";
    return 0;
}