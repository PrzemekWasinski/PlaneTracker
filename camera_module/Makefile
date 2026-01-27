CXX = g++
CXXFLAGS = -Wall -pthread
LIBS = -lpigpio -lrt

all: tracker calibrate

tracker: tracker.cpp pan_tilt.hpp
	$(CXX) $(CXXFLAGS) -o tracker tracker.cpp $(LIBS)

calibrate: calibrate.cpp pan_tilt.hpp
	$(CXX) $(CXXFLAGS) -o calibrate calibrate.cpp $(LIBS)

clean:
	rm -f tracker calibrate
