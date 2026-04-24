cmake_minimum_required(VERSION 3.14)
project(qplaywright_cpp_demo LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 11)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_AUTOMOC ON)

set(app_name demo_app)

find_package(QT NAMES Qt6 Qt5 REQUIRED COMPONENTS Core Widgets Network Test)
find_package(Qt${QT_VERSION_MAJOR} REQUIRED COMPONENTS Core Widgets Network Test)

add_subdirectory(../../qplaywright/cpp qplaywright_cpp_build)

add_executable(${app_name}
    main.cpp
    ../../qplaywright/cpp/qplaywright_agent.h
)

target_link_libraries(${app_name} PRIVATE
    qplaywright_agent
    Qt${QT_VERSION_MAJOR}::Core
    Qt${QT_VERSION_MAJOR}::Widgets
    Qt${QT_VERSION_MAJOR}::Network
    Qt${QT_VERSION_MAJOR}::Test
)
target_include_directories(${app_name} PRIVATE ../../qplaywright/cpp)

if(WIN32)
    get_target_property(qt_qmake_executable Qt${QT_VERSION_MAJOR}::qmake IMPORTED_LOCATION)
    if(qt_qmake_executable)
        get_filename_component(qt_bin_dir "${qt_qmake_executable}" DIRECTORY)
        set(windeployqt_executable "${qt_bin_dir}/windeployqt.exe")
        if(EXISTS "${windeployqt_executable}")
            add_custom_command(TARGET ${app_name} POST_BUILD
                COMMAND "${windeployqt_executable}"
                    --no-compiler-runtime
                    --dir "$<TARGET_FILE_DIR:${app_name}>"
                    "$<TARGET_FILE:${app_name}>"
                COMMENT "Deploying Qt runtime for ${app_name}"
            )
        else()
            message(WARNING "windeployqt.exe not found, Qt runtime will not be copied automatically")
        endif()
    else()
        message(WARNING "Qt${QT_VERSION_MAJOR}::qmake location not found, Qt runtime will not be copied automatically")
    endif()
endif()