#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BUILD_DIR="$SCRIPT_DIR/build"

mkdir -p "$BUILD_DIR"

CXX="${CXX:-g++}"
COMMON_FLAGS=( -std=c++17 -O2 -Wall -Wextra )

compile() {
    local source_file="$1"
    local output_file="$2"
    shift 2
    echo "Compiling ${source_file} to ${output_file}"
    "$CXX" "${COMMON_FLAGS[@]}" "$SCRIPT_DIR/$source_file" -o "$BUILD_DIR/$output_file" "$@"
}

compile "camera_test.cpp" "camera_test"
compile "servo_test.cpp" "servo_test" -lpigpio -lrt
compile "tracker.cpp" "tracker" -lpigpio -lpthread -lrt

echo "Build complete. Binaries are in: $BUILD_DIR"
