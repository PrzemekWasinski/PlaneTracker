#include <iostream>
    
extern "C" {
    #include <cmath>

    double calculateHeading(double prevLat, double prevLon, double lat, double lon) {
        double pi = 3.14159265358979323846;

        double prevLat_rad = prevLat * pi / 180.0;
        double prevLon_rad = prevLon * pi / 180.0;
        double lat_rad = lat * pi / 180.0;
        double lon_rad = lon * pi / 180.0;

        double y = std::sin(lon_rad - prevLon_rad) * std::cos(lat_rad);
        double x = std::cos(prevLat_rad) * std::sin(lat_rad) -
                   std::sin(prevLat_rad) * std::cos(lat_rad) * std::cos(lon_rad - prevLon_rad);

        double bearing = std::atan2(y, x) * 180.0 / pi;

        if (bearing < 0) bearing += 360.0;

        return bearing;
    }
}

int main() {
    std::cout << "Test"; 
    return 0;
}