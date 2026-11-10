cmake_minimum_required(VERSION 3.16)
project(fleet_telemetry)

# colcon passes no build type.
if(NOT CMAKE_BUILD_TYPE AND NOT CMAKE_CONFIGURATION_TYPES)
  set(CMAKE_BUILD_TYPE RelWithDebInfo CACHE STRING "" FORCE)
endif()

find_package(ament_cmake REQUIRED)
find_package(PkgConfig REQUIRED)
find_package(rclcpp REQUIRED)
find_package(rclcpp_components REQUIRED)
find_package(tierlink REQUIRED)
find_package(yaml_cpp_vendor REQUIRED)
find_package(yaml-cpp REQUIRED)
pkg_check_modules(ZSTD REQUIRED IMPORTED_TARGET libzstd)

add_library(fleet_telemetry_core STATIC
  src/agent_config.cpp src/command_gate.cpp src/zstd_codec.cpp)
set_target_properties(fleet_telemetry_core PROPERTIES POSITION_INDEPENDENT_CODE ON)
target_compile_features(fleet_telemetry_core PUBLIC cxx_std_17)
target_compile_options(fleet_telemetry_core PRIVATE -Wall -Wextra -Wpedantic)
target_include_directories(fleet_telemetry_core PUBLIC src)
target_link_libraries(fleet_telemetry_core PUBLIC tierlink::tierlink yaml-cpp PkgConfig::ZSTD)

add_library(fleet_telemetry_component SHARED src/agent.cpp)
target_compile_options(fleet_telemetry_component PRIVATE -Wall -Wextra -Wpedantic)
target_link_libraries(fleet_telemetry_component fleet_telemetry_core)
ament_target_dependencies(fleet_telemetry_component rclcpp rclcpp_components)
rclcpp_components_register_node(fleet_telemetry_component
  PLUGIN "fleet_telemetry::Agent" EXECUTABLE fleet_telemetry_node)

# A debugging server: sends one command and prints the answer.
add_executable(send_command src/send_command_main.cpp)
target_link_libraries(send_command fleet_telemetry_core)

install(TARGETS send_command DESTINATION lib/${PROJECT_NAME})
install(TARGETS fleet_telemetry_component
  ARCHIVE DESTINATION lib
  LIBRARY DESTINATION lib
  RUNTIME DESTINATION bin)
install(DIRECTORY config launch DESTINATION share/${PROJECT_NAME})

if(BUILD_TESTING)
  find_package(ament_cmake_gtest REQUIRED)
  foreach(name agent_config command_gate)
    ament_add_gtest(test_${name} test/test_${name}.cpp)
    target_link_libraries(test_${name} fleet_telemetry_core)
  endforeach()
endif()

ament_package()
