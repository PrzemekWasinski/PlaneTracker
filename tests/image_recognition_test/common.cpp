#include "common.hpp"

#include <algorithm>
#include <cctype>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <sstream>
#include <stdexcept>

#include <opencv2/imgcodecs.hpp>
#include <opencv2/imgproc.hpp>

namespace fs = std::filesystem;

namespace imgrec {
namespace {

bool hasImageExtension(const fs::path& path) {
    const std::string ext = path.extension().string();
    std::string lower;
    lower.reserve(ext.size());
    for (char c : ext) {
        lower.push_back(static_cast<char>(std::tolower(static_cast<unsigned char>(c))));
    }
    return lower == ".jpg" || lower == ".jpeg" || lower == ".png" || lower == ".bmp";
}

std::string trim(const std::string& value) {
    const auto begin = value.find_first_not_of(" \t\r\n");
    if (begin == std::string::npos) {
        return "";
    }
    const auto end = value.find_last_not_of(" \t\r\n");
    return value.substr(begin, end - begin + 1);
}

}  // namespace

cv::HOGDescriptor createHogDescriptor() {
    return cv::HOGDescriptor(
        cv::Size(128, 128),
        cv::Size(32, 32),
        cv::Size(16, 16),
        cv::Size(16, 16),
        9);
}

cv::Mat preprocessImage(const cv::Mat& image, const cv::Size& targetSize) {
    if (image.empty()) {
        throw std::runtime_error("Cannot preprocess an empty image");
    }

    cv::Mat resized;
    cv::resize(image, resized, targetSize, 0.0, 0.0, cv::INTER_AREA);

    cv::Mat gray;
    if (resized.channels() == 3) {
        cv::cvtColor(resized, gray, cv::COLOR_BGR2GRAY);
    } else if (resized.channels() == 4) {
        cv::cvtColor(resized, gray, cv::COLOR_BGRA2GRAY);
    } else {
        gray = resized.clone();
    }

    cv::Mat equalized;
    cv::equalizeHist(gray, equalized);

    cv::Mat blurred;
    cv::GaussianBlur(equalized, blurred, cv::Size(3, 3), 0.0);
    return blurred;
}

cv::Mat extractFeatures(const cv::Mat& image, const cv::HOGDescriptor& hog, const cv::Size& targetSize) {
    const cv::Mat processed = preprocessImage(image, targetSize);
    std::vector<float> descriptors;
    hog.compute(processed, descriptors);
    cv::Mat featureRow(1, static_cast<int>(descriptors.size()), CV_32F);
    for (int i = 0; i < static_cast<int>(descriptors.size()); ++i) {
        featureRow.at<float>(0, i) = descriptors[static_cast<size_t>(i)];
    }
    return featureRow;
}

std::vector<fs::path> listImages(const fs::path& dir) {
    if (!fs::exists(dir)) {
        throw std::runtime_error("Directory does not exist: " + dir.string());
    }

    std::vector<fs::path> paths;
    for (const auto& entry : fs::directory_iterator(dir)) {
        if (entry.is_regular_file() && hasImageExtension(entry.path())) {
            paths.push_back(entry.path());
        }
    }
    std::sort(paths.begin(), paths.end());
    return paths;
}

std::vector<fs::path> listImagesRecursive(const fs::path& dir) {
    if (!fs::exists(dir)) {
        throw std::runtime_error("Directory does not exist: " + dir.string());
    }

    std::vector<fs::path> paths;
    for (const auto& entry : fs::recursive_directory_iterator(dir)) {
        if (entry.is_regular_file() && hasImageExtension(entry.path())) {
            paths.push_back(entry.path());
        }
    }
    std::sort(paths.begin(), paths.end());
    return paths;
}

DatasetSplit loadLabeledDirectories(
    const std::vector<std::pair<fs::path, int>>& directories,
    const cv::HOGDescriptor& hog,
    const cv::Size& targetSize) {
    DatasetSplit split;

    for (const auto& [dir, label] : directories) {
        const auto paths = listImagesRecursive(dir);
        for (const auto& path : paths) {
            const cv::Mat image = cv::imread(path.string(), cv::IMREAD_COLOR);
            if (image.empty()) {
                std::cerr << "Skipping unreadable image: " << path << "\n";
                continue;
            }

            cv::Mat featureRow = extractFeatures(image, hog, targetSize);
            split.features.push_back(featureRow);
            split.labels.push_back(label);
            split.paths.push_back(path.string());
        }
    }

    split.labels.convertTo(split.labels, CV_32S);
    return split;
}

std::map<std::string, int> loadLabelCsv(const fs::path& csvPath) {
    std::ifstream file(csvPath);
    if (!file.is_open()) {
        throw std::runtime_error("Unable to open label CSV: " + csvPath.string());
    }

    std::map<std::string, int> labels;
    std::string line;
    bool firstLine = true;
    while (std::getline(file, line)) {
        line = trim(line);
        if (line.empty() || line.rfind('#', 0) == 0) {
            continue;
        }

        if (firstLine && line == "filename,label") {
            firstLine = false;
            continue;
        }
        firstLine = false;

        const auto comma = line.find(',');
        if (comma == std::string::npos) {
            throw std::runtime_error("Invalid CSV row: " + line);
        }

        const std::string filename = trim(line.substr(0, comma));
        const std::string rawLabel = trim(line.substr(comma + 1));
        int label = -1;
        if (rawLabel == "1" || rawLabel == "valid" || rawLabel == "aircraft") {
            label = 1;
        } else if (rawLabel == "0" || rawLabel == "invalid" || rawLabel == "sky") {
            label = 0;
        } else {
            throw std::runtime_error("Unsupported label in CSV: " + rawLabel);
        }
        labels[filename] = label;
    }
    return labels;
}

float predictLabel(
    const cv::Ptr<cv::ml::SVM>& svm,
    const cv::Mat& image,
    const cv::HOGDescriptor& hog,
    const cv::Size& targetSize,
    float* rawScore) {
    cv::Mat featureRow = extractFeatures(image, hog, targetSize);
    float score = svm->predict(featureRow, cv::noArray(), cv::ml::StatModel::RAW_OUTPUT);
    if (rawScore != nullptr) {
        *rawScore = score;
    }
    return score <= 0.0f ? 1.0f : 0.0f;
}

EvalResult evaluateLabeledCsv(
    const fs::path& testDir,
    const std::map<std::string, int>& labels,
    const cv::Ptr<cv::ml::SVM>& svm,
    const cv::HOGDescriptor& hog,
    const cv::Size& targetSize) {
    EvalResult result;

    for (const auto& [filename, expected] : labels) {
        const fs::path imagePath = testDir / filename;
        const cv::Mat image = cv::imread(imagePath.string(), cv::IMREAD_COLOR);
        if (image.empty()) {
            std::cerr << "Skipping unreadable test image: " << imagePath << "\n";
            continue;
        }

        float rawScore = 0.0f;
        const int predicted = static_cast<int>(predictLabel(svm, image, hog, targetSize, &rawScore));
        ++result.total;
        if (predicted == expected) {
            ++result.correct;
        }
        if (predicted == 1 && expected == 1) {
            ++result.truePositive;
        } else if (predicted == 0 && expected == 0) {
            ++result.trueNegative;
        } else if (predicted == 1 && expected == 0) {
            ++result.falsePositive;
        } else if (predicted == 0 && expected == 1) {
            ++result.falseNegative;
        }

        std::cout << filename << ",expected=" << expected
                  << ",predicted=" << predicted
                  << ",raw_score=" << std::fixed << std::setprecision(4) << rawScore << "\n";
    }

    return result;
}

EvalResult evaluateLabeledDirectories(
    const std::vector<std::pair<fs::path, int>>& directories,
    const cv::Ptr<cv::ml::SVM>& svm,
    const cv::HOGDescriptor& hog,
    const cv::Size& targetSize) {
    EvalResult result;

    for (const auto& [dir, expected] : directories) {
        auto imagePaths = listImages(dir);
        if (imagePaths.empty()) {
            imagePaths = listImagesRecursive(dir);
        }

        for (const auto& imagePath : imagePaths) {
            const cv::Mat image = cv::imread(imagePath.string(), cv::IMREAD_COLOR);
            if (image.empty()) {
                std::cerr << "Skipping unreadable test image: " << imagePath << "\n";
                continue;
            }

            float rawScore = 0.0f;
            const int predicted = static_cast<int>(predictLabel(svm, image, hog, targetSize, &rawScore));
            ++result.total;
            if (predicted == expected) {
                ++result.correct;
            }
            if (predicted == 1 && expected == 1) {
                ++result.truePositive;
            } else if (predicted == 0 && expected == 0) {
                ++result.trueNegative;
            } else if (predicted == 1 && expected == 0) {
                ++result.falsePositive;
            } else if (predicted == 0 && expected == 1) {
                ++result.falseNegative;
            }

            std::cout << imagePath.filename().string()
                      << ",expected=" << labelToString(static_cast<float>(expected))
                      << ",predicted=" << labelToString(static_cast<float>(predicted))
                      << ",raw_score=" << std::fixed << std::setprecision(4) << rawScore << "\n";
        }
    }

    return result;
}

std::string labelToString(float label) {
    return label >= 0.5f ? "AIRCRAFT" : "SKY";
}

}  // namespace imgrec

