#include <iostream>
#include <fstream>
#include <queue>
#include <string>
#include <sstream>
#include <thread>
#include <chrono>

//Test script to test communication between py and c++
struct Plane {
    std::string icao;
    double lat;
    double lon;
    int alt;
};

int main() {
    //Open log file
    std::ofstream log("cpp_debug.log", std::ios::app);
    
    std::queue<Plane> queue;
    std::string line;
    
    log << "Plane Queue Started\n";
    log.flush();
    
    while (true) {
        //Read input 
        if (std::getline(std::cin, line)) {
            std::stringstream ss(line);
            Plane p;
            std::string field;
            std::getline(ss, p.icao, ',');
            std::getline(ss, field, ','); p.lat = std::stod(field);
            std::getline(ss, field, ','); p.lon = std::stod(field);
            std::getline(ss, field, ','); p.alt = std::stoi(field);
            
            queue.push(p);
            log << "Queued: " << p.icao << "\n";
            log.flush();
        }
        
        //Process one plane at a time
        if (!queue.empty()) {
            Plane p = queue.front();
            queue.pop();
            
            log << "----------------------\n";
            log << " ICAO: " << p.icao << "\n";
            log << " LAT : " << p.lat << "\n";
            log << " LON : " << p.lon << "\n";
            log << " ALT : " << p.alt << "\n";
            log << "----------------------\n";
            log.flush();
            
        }
        
        std::this_thread::sleep_for(std::chrono::milliseconds(50));
    }
}