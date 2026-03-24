#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BUILD_DIR="$SCRIPT_DIR/build"
mkdir -p "$BUILD_DIR" "$SCRIPT_DIR/model" "$SCRIPT_DIR/debug"

CXX="${CXX:-g++}"
COMMON_FLAGS=( -std=c++17 -O2 -Wall -Wextra )
OPENCV_FLAGS=( $(pkg-config --cflags --libs opencv4) )

compile() {
    local output_file="$1"
    shift
    echo "Compiling ${output_file}"
    "$CXX" "${COMMON_FLAGS[@]}" "$@" -o "$BUILD_DIR/$output_file" "${OPENCV_FLAGS[@]}"
}

compile train "$SCRIPT_DIR/train.cpp" "$SCRIPT_DIR/common.cpp"
compile predict "$SCRIPT_DIR/predict.cpp" "$SCRIPT_DIR/common.cpp"

echo "Build complete. Binaries are in: $BUILD_DIR"
