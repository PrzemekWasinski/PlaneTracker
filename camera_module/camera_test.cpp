#include <chrono>
#include <cstdlib>
#include <filesystem>
#include <iomanip>
#include <iostream>
#include <sstream>
#include <string>
#include <vector>

namespace fs = std::filesystem;

std::string shellQuote(const std::string& value) {
    std::string quoted = "'";
    for (char ch : value) {
        if (ch == '\'') {
            quoted += "'\\''";
        } else {
            quoted += ch;
        }
    }
    quoted += "'";
    return quoted;
}

std::string makeTimestamp() {
    const auto now = std::chrono::system_clock::now();
    const std::time_t nowTime = std::chrono::system_clock::to_time_t(now);

    std::tm localTime{};
#ifdef _WIN32
    localtime_s(&localTime, &nowTime);
#else
    localtime_r(&nowTime, &localTime);
#endif

    std::ostringstream stream;
    stream << std::put_time(&localTime, "%Y%m%d_%H%M%S");
    return stream.str();
}

int main() {
    const fs::path scriptDir = fs::absolute(fs::path(__FILE__)).parent_path();
    const fs::path outputDir = scriptDir / "test_pictures";
    const fs::path outputPath = outputDir / ("camera_test_" + makeTimestamp() + ".jpg");

    std::error_code error;
    fs::create_directories(outputDir, error);
    if (error) {
        std::cerr << "Failed to create output directory: " << outputDir << "\n";
        return 1;
    }

    const std::vector<std::string> commands = {
        "rpicam-still",
        "libcamera-still",
    };

    for (const auto& command : commands) {
        std::ostringstream shellCommand;
        shellCommand
            << command
            << " -n"
            << " -t 2000"
            << " -o " << shellQuote(outputPath.string());

        std::cout << "Trying " << command << "...\n";
        const int exitCode = std::system(shellCommand.str().c_str());
        if (exitCode == 0 && fs::exists(outputPath)) {
            std::cout << "Saved image to: " << outputPath << "\n";
            return 0;
        }
    }

    std::cerr << "Unable to capture image\n";
    return 1;
}
