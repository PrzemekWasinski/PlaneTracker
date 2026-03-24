#pragma once

#include <filesystem>
#include <map>
#include <string>
#include <vector>

#include <opencv2/core.hpp>
#include <opencv2/ml.hpp>
#include <opencv2/objdetect.hpp>

namespace imgrec {

struct DatasetSplit {
    cv::Mat features;
    cv::Mat labels;
    std::vector<std::string> paths;
};

struct EvalResult {
    int total = 0;
    int correct = 0;
    int truePositive = 0;
    int trueNegative = 0;
    int falsePositive = 0;
    int falseNegative = 0;
};

cv::HOGDescriptor createHogDescriptor();
cv::Mat preprocessImage(const cv::Mat& image, const cv::Size& targetSize);
cv::Mat extractFeatures(const cv::Mat& image, const cv::HOGDescriptor& hog, const cv::Size& targetSize);
std::vector<std::filesystem::path> listImages(const std::filesystem::path& dir);
std::vector<std::filesystem::path> listImagesRecursive(const std::filesystem::path& dir);
DatasetSplit loadLabeledDirectories(
    const std::vector<std::pair<std::filesystem::path, int>>& directories,
    const cv::HOGDescriptor& hog,
    const cv::Size& targetSize);
std::map<std::string, int> loadLabelCsv(const std::filesystem::path& csvPath);
EvalResult evaluateLabeledCsv(
    const std::filesystem::path& testDir,
    const std::map<std::string, int>& labels,
    const cv::Ptr<cv::ml::SVM>& svm,
    const cv::HOGDescriptor& hog,
    const cv::Size& targetSize);
EvalResult evaluateLabeledDirectories(
    const std::vector<std::pair<std::filesystem::path, int>>& directories,
    const cv::Ptr<cv::ml::SVM>& svm,
    const cv::HOGDescriptor& hog,
    const cv::Size& targetSize);
float predictLabel(
    const cv::Ptr<cv::ml::SVM>& svm,
    const cv::Mat& image,
    const cv::HOGDescriptor& hog,
    const cv::Size& targetSize,
    float* rawScore = nullptr);
std::string labelToString(float label);

}  // namespace imgrec
