#include "common.hpp"

#include <filesystem>
#include <iostream>
#include <set>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

#include <opencv2/core.hpp>
#include <opencv2/ml.hpp>

namespace fs = std::filesystem;

namespace {

std::vector<fs::path> collectImagePaths(const std::vector<std::pair<fs::path, int>>& directories) {
    std::vector<fs::path> paths;
    for (const auto& [dir, _label] : directories) {
        const auto dirPaths = imgrec::listImagesRecursive(dir);
        paths.insert(paths.end(), dirPaths.begin(), dirPaths.end());
    }
    return paths;
}

std::set<std::string> canonicalPathSet(const std::vector<fs::path>& paths) {
    std::set<std::string> canonical;
    for (const auto& path : paths) {
        canonical.insert(fs::weakly_canonical(path).string());
    }
    return canonical;
}

std::vector<std::pair<fs::path, int>> collectTrainingDirectories(const fs::path& dataDir) {
    const std::vector<std::pair<fs::path, int>> directories = {
        {dataDir / "aircraft", 1},
        {dataDir / "sky", 0},
    };

    std::vector<std::pair<fs::path, int>> existing;
    for (const auto& entry : directories) {
        if (fs::exists(entry.first)) {
            existing.push_back(entry);
        }
    }
    return existing;
}

std::vector<std::pair<fs::path, int>> collectTestDirectories(const fs::path& testDir) {
    std::vector<std::pair<fs::path, int>> directories;

    if (!fs::exists(testDir)) {
        return directories;
    }

    if (fs::exists(testDir / "aircraft")) {
        directories.push_back({testDir / "aircraft", 1});
    }

    if (fs::exists(testDir / "sky")) {
        directories.push_back({testDir / "sky", 0});
    }

    return directories;
}

}  // namespace

int main(int argc, char** argv) {
    try {
        const fs::path executablePath = argc > 0 ? fs::absolute(fs::path(argv[0])) : fs::current_path() / "train";
        const fs::path projectDir = executablePath.parent_path().parent_path();
        const fs::path dataDir = projectDir / "data";
        const fs::path modelPath = projectDir / "model" / "aircraft_svm.yml";
        const fs::path testDir = dataDir / "test";
        const cv::Size targetSize(128, 128);
        const cv::HOGDescriptor hog = imgrec::createHogDescriptor();

        const auto trainingDirs = collectTrainingDirectories(dataDir);
        if (trainingDirs.size() < 2) {
            throw std::runtime_error(
                "Training requires both data/aircraft and data/sky. I found " + std::to_string(trainingDirs.size()) +
                " class folder(s) under " + dataDir.string());
        }

        const auto testDirs = collectTestDirectories(testDir);
        if (!testDirs.empty() && testDirs.size() != 2) {
            throw std::runtime_error(
                "Evaluation requires both data/test/aircraft and data/test/sky when using labeled test folders.");
        }

        const auto trainingPaths = collectImagePaths(trainingDirs);
        const auto testPaths = collectImagePaths(testDirs);
        const auto trainingPathSet = canonicalPathSet(trainingPaths);
        const auto testPathSet = canonicalPathSet(testPaths);

        for (const auto& testPath : testPathSet) {
            if (trainingPathSet.count(testPath) > 0) {
                throw std::runtime_error("Test image is also present in training data: " + testPath);
            }
        }

        std::cout << "Loading training images...\n";
        imgrec::DatasetSplit train = imgrec::loadLabeledDirectories(trainingDirs, hog, targetSize);

        if (train.features.rows == 0) {
            throw std::runtime_error("No training images were loaded");
        }

        std::cout << "Training samples: " << train.features.rows << "\n";
        std::cout << "Training aircraft images: " << imgrec::listImagesRecursive(dataDir / "aircraft").size() << "\n";
        std::cout << "Training sky images: " << imgrec::listImagesRecursive(dataDir / "sky").size() << "\n";
        std::cout << "Feature length: " << train.features.cols << "\n";

        auto svm = cv::ml::SVM::create();
        svm->setType(cv::ml::SVM::C_SVC);
        svm->setKernel(cv::ml::SVM::LINEAR);
        svm->setTermCriteria(cv::TermCriteria(cv::TermCriteria::MAX_ITER, 2000, 1e-6));
        svm->train(train.features, cv::ml::ROW_SAMPLE, train.labels);
        svm->save(modelPath.string());

        std::cout << "Saved model to: " << modelPath << "\n";

        if (!testDirs.empty()) {
            std::cout << "Evaluating test images...\n";
            std::cout << "Test aircraft images: " << imgrec::listImagesRecursive(testDir / "aircraft").size() << "\n";
            std::cout << "Test sky images: " << imgrec::listImagesRecursive(testDir / "sky").size() << "\n";
            const imgrec::EvalResult result = imgrec::evaluateLabeledDirectories(testDirs, svm, hog, targetSize);
            std::cout << "Test total: " << result.total << "\n";
            std::cout << "Test correct: " << result.correct << "\n";
            if (result.total > 0) {
                const double accuracy = (100.0 * static_cast<double>(result.correct)) / static_cast<double>(result.total);
                std::cout << "Test accuracy: " << accuracy << "%\n";
            }
            std::cout << "TP=" << result.truePositive
                      << " TN=" << result.trueNegative
                      << " FP=" << result.falsePositive
                      << " FN=" << result.falseNegative << "\n";
        } else {
            std::cout << "No labeled test folders found in data/test. Training complete.\n";
        }

        return 0;
    } catch (const std::exception& ex) {
        std::cerr << "Training failed: " << ex.what() << "\n";
        return 1;
    }
}
