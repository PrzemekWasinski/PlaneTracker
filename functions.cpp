#include <iostream>
#include <cmath>

extern "C" {
    #include <cmath>

extern "C" {
    double calculateHeading(double prevLat, double prevLon, double lat, double lon) {
        double prevLat_rad = prevLat * M_PI / 180.0;
        double prevLon_rad = prevLon * M_PI / 180.0;
        double lat_rad = lat * M_PI / 180.0;
        double lon_rad = lon * M_PI / 180.0;

        double y = std::sin(lon_rad - prevLon_rad) * std::cos(lat_rad);
        double x = std::cos(prevLat_rad) * std::sin(lat_rad) -
                   std::sin(prevLat_rad) * std::cos(lat_rad) * std::cos(lon_rad - prevLon_rad);

        double bearing = std::atan2(y, x) * 180.0 / M_PI;

        if (bearing < 0) bearing += 360.0;

        return bearing;
    }
}

}

int main() {
    std::cout << "Test"; 
    return 0;
}