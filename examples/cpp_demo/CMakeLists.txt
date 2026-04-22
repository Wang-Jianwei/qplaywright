cmake_minimum_required(VERSION 3.14)
project(qplaywright_cpp_demo LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_AUTOMOC ON)

find_package(QT NAMES Qt6 Qt5 REQUIRED COMPONENTS Core Widgets Network Test)
find_package(Qt${QT_VERSION_MAJOR} REQUIRED COMPONENTS Core Widgets Network Test)

add_subdirectory(../../qplaywright/cpp qplaywright_cpp_build)

add_executable(demo_app
    main.cpp
    ../../qplaywright/cpp/qplaywright_agent.h
)

target_link_libraries(demo_app PRIVATE
    qplaywright_agent
    Qt${QT_VERSION_MAJOR}::Core
    Qt${QT_VERSION_MAJOR}::Widgets
    Qt${QT_VERSION_MAJOR}::Network
    Qt${QT_VERSION_MAJOR}::Test
)
target_include_directories(demo_app PRIVATE ../../qplaywright/cpp)