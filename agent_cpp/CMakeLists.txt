cmake_minimum_required(VERSION 3.14)
project(qplaywright_agent LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_AUTOMOC ON)

# Support both Qt5 and Qt6
find_package(QT NAMES Qt6 Qt5 REQUIRED COMPONENTS Widgets Network Test)
find_package(Qt${QT_VERSION_MAJOR} REQUIRED COMPONENTS Widgets Network Test)

message(STATUS "Using Qt${QT_VERSION_MAJOR}: ${Qt${QT_VERSION_MAJOR}_DIR}")

# ---- Agent as a header-only library (with MOC) ----
add_library(qplaywright_agent INTERFACE)
target_include_directories(qplaywright_agent INTERFACE ${CMAKE_CURRENT_SOURCE_DIR})
target_link_libraries(qplaywright_agent INTERFACE
    Qt${QT_VERSION_MAJOR}::Widgets
    Qt${QT_VERSION_MAJOR}::Network
    Qt${QT_VERSION_MAJOR}::Test
)

# ---- Demo app ----
add_executable(demo_app
    ${CMAKE_CURRENT_SOURCE_DIR}/../examples/cpp_demo/main.cpp
    ${CMAKE_CURRENT_SOURCE_DIR}/qplaywright_agent.h
)
target_link_libraries(demo_app PRIVATE
    Qt${QT_VERSION_MAJOR}::Widgets
    Qt${QT_VERSION_MAJOR}::Network
    Qt${QT_VERSION_MAJOR}::Test
)
target_include_directories(demo_app PRIVATE ${CMAKE_CURRENT_SOURCE_DIR})
