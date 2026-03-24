#include <arpa/inet.h>
#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <netinet/in.h>
#include <sstream>
#include <string>
#include <sys/socket.h>
#include <thread>
#include <unistd.h>
#include <vector>

namespace fs = std::filesystem;

const int DEFAULT_HTTP_PORT = 8080;
const int DISALLOWED_PORT = 12345;
const int DEFAULT_WIDTH = 1280;
const int DEFAULT_HEIGHT = 720;
const int DEFAULT_INTERVAL_MS = 350;
const int REQUEST_BUFFER_SIZE = 8192;

struct Settings {
    std::string bindHost = "0.0.0.0";
    int port = DEFAULT_HTTP_PORT;
    int width = DEFAULT_WIDTH;
    int height = DEFAULT_HEIGHT;
    int intervalMs = DEFAULT_INTERVAL_MS;
    std::string cameraArgs;
};

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

bool sendAll(int socketFd, const char* data, size_t length) {
    size_t sent = 0;
    while (sent < length) {
        const ssize_t bytesSent = send(socketFd, data + sent, length - sent, 0);
        if (bytesSent <= 0) {
            return false;
        }
        sent += static_cast<size_t>(bytesSent);
    }
    return true;
}

bool sendString(int socketFd, const std::string& text) {
    return sendAll(socketFd, text.c_str(), text.size());
}

void sendSimpleResponse(int clientSocket, const std::string& status, const std::string& contentType, const std::string& body) {
    std::ostringstream response;
    response << "HTTP/1.1 " << status << "\r\n"
             << "Content-Type: " << contentType << "\r\n"
             << "Content-Length: " << body.size() << "\r\n"
             << "Cache-Control: no-store\r\n"
             << "Connection: close\r\n\r\n"
             << body;
    sendString(clientSocket, response.str());
}

void sendHtmlPage(int clientSocket, const Settings& settings) {
    std::ostringstream html;
    html << "<!doctype html>\n"
         << "<html lang=\"en\">\n"
         << "<head>\n"
         << "  <meta charset=\"utf-8\" />\n"
         << "  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />\n"
         << "  <title>Camera Preview</title>\n"
         << "  <style>\n"
         << "    html, body { margin: 0; background: #000; }\n"
         << "    img { display: block; width: 100vw; height: auto; }\n"
         << "  </style>\n"
         << "</head>\n"
         << "<body>\n"
         << "  <img src=\"/stream.mjpg\" alt=\"Camera preview\" />\n"
         << "</body>\n"
         << "</html>\n";

    sendSimpleResponse(clientSocket, "200 OK", "text/html; charset=utf-8", html.str());
}

std::string readHttpRequest(int clientSocket) {
    std::string request;
    char buffer[REQUEST_BUFFER_SIZE];
    while (request.find("\r\n\r\n") == std::string::npos && request.size() < static_cast<size_t>(REQUEST_BUFFER_SIZE)) {
        const ssize_t bytesRead = recv(clientSocket, buffer, sizeof(buffer), 0);
        if (bytesRead <= 0) {
            break;
        }
        request.append(buffer, static_cast<size_t>(bytesRead));
    }
    return request;
}

std::string extractPath(const std::string& request) {
    const size_t lineEnd = request.find("\r\n");
    const std::string requestLine = request.substr(0, lineEnd);
    std::istringstream stream(requestLine);
    std::string method;
    std::string path;
    std::string version;
    stream >> method >> path >> version;
    if (method != "GET") {
        return "";
    }
    return path;
}

bool readFileBytes(const fs::path& filePath, std::string& outBytes) {
    std::ifstream file(filePath, std::ios::binary);
    if (!file.is_open()) {
        return false;
    }
    std::ostringstream buffer;
    buffer << file.rdbuf();
    outBytes = buffer.str();
    return true;
}

bool captureFrameBytes(const Settings& settings, std::string& outBytes, std::string& outError) {
    const fs::path tempDir = fs::temp_directory_path();
    const fs::path outputPath = tempDir / "camera_live_preview.jpg";
    const std::vector<std::string> commands = {"rpicam-still", "libcamera-still"};

    for (const auto& command : commands) {
        std::ostringstream shellCommand;
        shellCommand << command
                     << " -n"
                     << " --immediate"
                     << " -t 1"
                     << " --width " << settings.width
                     << " --height " << settings.height;

        if (!settings.cameraArgs.empty()) {
            shellCommand << " " << settings.cameraArgs;
        }

        shellCommand << " -o " << shellQuote(outputPath.string())
                     << " > /dev/null 2>&1";

        const int exitCode = std::system(shellCommand.str().c_str());
        if (exitCode == 0 && fs::exists(outputPath) && fs::file_size(outputPath) > 0) {
            if (readFileBytes(outputPath, outBytes)) {
                std::error_code removeError;
                fs::remove(outputPath, removeError);
                return true;
            }
            outError = "captured image but failed to read it";
        } else {
            outError = command + " failed";
        }
    }

    return false;
}

void streamMjpeg(int clientSocket, const Settings& settings) {
    std::ostringstream header;
    header << "HTTP/1.1 200 OK\r\n"
           << "Cache-Control: no-cache, private\r\n"
           << "Pragma: no-cache\r\n"
           << "Connection: close\r\n"
           << "Content-Type: multipart/x-mixed-replace; boundary=FRAME\r\n\r\n";

    if (!sendString(clientSocket, header.str())) {
        return;
    }

    while (true) {
        std::string frameBytes;
        std::string errorText;
        if (!captureFrameBytes(settings, frameBytes, errorText)) {
            std::this_thread::sleep_for(std::chrono::milliseconds(settings.intervalMs));
            continue;
        }

        std::ostringstream partHeader;
        partHeader << "--FRAME\r\n"
                   << "Content-Type: image/jpeg\r\n"
                   << "Content-Length: " << frameBytes.size() << "\r\n\r\n";

        if (!sendString(clientSocket, partHeader.str())) {
            break;
        }
        if (!sendAll(clientSocket, frameBytes.data(), frameBytes.size())) {
            break;
        }
        if (!sendString(clientSocket, "\r\n")) {
            break;
        }

        std::this_thread::sleep_for(std::chrono::milliseconds(settings.intervalMs));
    }
}

static std::string trim(const std::string& s) {
    const size_t start = s.find_first_not_of(" \t\r\n");
    const size_t end = s.find_last_not_of(" \t\r\n");
    if (start == std::string::npos) {
        return "";
    }
    return s.substr(start, end - start + 1);
}

void loadPreviewDefaultsFromProjectConfig(Settings& settings) {
    const std::vector<fs::path> configPaths = {
        fs::path("../config/config.yml"),
        fs::path("config/config.yml"),
    };

    for (const auto& configPath : configPaths) {
        std::ifstream file(configPath);
        if (!file.is_open()) {
            continue;
        }

        std::string line;
        while (std::getline(file, line)) {
            const size_t hash = line.find('#');
            if (hash != std::string::npos) {
                line = line.substr(0, hash);
            }
            const size_t colon = line.find(':');
            if (colon == std::string::npos) {
                continue;
            }

            const std::string key = trim(line.substr(0, colon));
            const std::string value = trim(line.substr(colon + 1));
            if (key == "cameraHost" && !value.empty()) {
                settings.bindHost = value;
            } else if (key == "cameraPreviewPort" && !value.empty()) {
                try {
                    size_t consumed = 0;
                    const int parsedPort = std::stoi(value, &consumed);
                    if (consumed == value.size() && parsedPort != DISALLOWED_PORT) {
                        settings.port = parsedPort;
                    }
                } catch (...) {
                }
            }
        }
        return;
    }
}

bool parseInteger(const std::string& value, int& output) {
    try {
        size_t consumed = 0;
        const int parsed = std::stoi(value, &consumed);
        if (consumed != value.size()) {
            return false;
        }
        output = parsed;
        return true;
    } catch (...) {
        return false;
    }
}

bool parseBindValue(const std::string& bindValue, Settings& settings) {
    const size_t colon = bindValue.rfind(':');
    if (colon == std::string::npos) {
        return false;
    }

    settings.bindHost = bindValue.substr(0, colon);
    if (settings.bindHost.empty()) {
        settings.bindHost = "0.0.0.0";
    }

    if (!parseInteger(bindValue.substr(colon + 1), settings.port)) {
        return false;
    }
    return true;
}

void printUsage() {
    std::cout << "Usage: ./camera_test [ip:port] [--width N] [--height N] [--interval-ms N] [--camera-args '...']\n";
    std::cout << "Example: ./camera_test 192.168.0.227:8080 --camera-args '--autofocus-mode manual --lens-position 10'\n";
    std::cout << "With no ip:port, the program uses cameraHost from ../config/config.yml and port 8080.\n";
    std::cout << "Choose any port except 12345.\n";
}

bool parseArgs(int argc, char* argv[], Settings& settings) {
    loadPreviewDefaultsFromProjectConfig(settings);

    int index = 1;
    if (argc >= 2 && std::string(argv[1]).rfind("--", 0) != 0) {
        if (!parseBindValue(argv[1], settings)) {
            std::cerr << "Invalid bind address. Use the form 192.168.0.227:8080\n";
            return false;
        }
        index = 2;
    }

    for (; index < argc; ++index) {
        const std::string arg = argv[index];
        if (arg == "--width" && index + 1 < argc) {
            if (!parseInteger(argv[++index], settings.width)) {
                std::cerr << "Invalid width value\n";
                return false;
            }
        } else if (arg == "--height" && index + 1 < argc) {
            if (!parseInteger(argv[++index], settings.height)) {
                std::cerr << "Invalid height value\n";
                return false;
            }
        } else if (arg == "--interval-ms" && index + 1 < argc) {
            if (!parseInteger(argv[++index], settings.intervalMs)) {
                std::cerr << "Invalid interval value\n";
                return false;
            }
        } else if (arg == "--camera-args" && index + 1 < argc) {
            settings.cameraArgs = argv[++index];
        } else {
            std::cerr << "Unknown argument: " << arg << "\n";
            return false;
        }
    }

    if (settings.port == DISALLOWED_PORT) {
        std::cerr << "Port 12345 is reserved for the tracker server. Choose another port.\n";
        return false;
    }

    return true;
}

int main(int argc, char* argv[]) {
    Settings settings;
    if (!parseArgs(argc, argv, settings)) {
        return 1;
    }

    const int serverFd = socket(AF_INET, SOCK_STREAM, 0);
    if (serverFd < 0) {
        std::cerr << "Failed to create socket\n";
        return 1;
    }

    int opt = 1;
    setsockopt(serverFd, SOL_SOCKET, SO_REUSEADDR, &opt, sizeof(opt));

    sockaddr_in address{};
    address.sin_family = AF_INET;
    address.sin_port = htons(static_cast<uint16_t>(settings.port));

    if (inet_pton(AF_INET, settings.bindHost.c_str(), &address.sin_addr) != 1) {
        std::cerr << "Invalid bind IP address: " << settings.bindHost << "\n";
        close(serverFd);
        return 1;
    }

    if (bind(serverFd, reinterpret_cast<sockaddr*>(&address), sizeof(address)) != 0) {
        std::cerr << "Bind failed for " << settings.bindHost << ":" << settings.port << "\n";
        close(serverFd);
        return 1;
    }

    if (listen(serverFd, 8) != 0) {
        std::cerr << "Listen failed\n";
        close(serverFd);
        return 1;
    }

    std::cout << "Pi camera live view running at http://" << settings.bindHost << ":" << settings.port << "/\n";
    std::cout << "Preview resolution: " << settings.width << "x" << settings.height << "\n";
    if (!settings.cameraArgs.empty()) {
        std::cout << "Extra camera args: " << settings.cameraArgs << "\n";
    }
    std::cout << "Open that URL on another device on the same network.\n";

    while (true) {
        sockaddr_in clientAddress{};
        socklen_t clientLength = sizeof(clientAddress);
        const int clientSocket = accept(serverFd, reinterpret_cast<sockaddr*>(&clientAddress), &clientLength);
        if (clientSocket < 0) {
            continue;
        }

        const std::string request = readHttpRequest(clientSocket);
        const std::string path = extractPath(request);

        if (path == "/" || path == "/index.html") {
            sendHtmlPage(clientSocket, settings);
        } else if (path == "/stream.mjpg") {
            streamMjpeg(clientSocket, settings);
        } else {
            sendSimpleResponse(clientSocket, "404 Not Found", "text/plain; charset=utf-8", "Not found\n");
        }

        close(clientSocket);
    }

    close(serverFd);
    return 0;
}

