cmake_minimum_required(VERSION 3.8)
project(robot_drive)

if(CMAKE_COMPILER_IS_GNUCXX OR CMAKE_CXX_COMPILER_ID MATCHES "Clang")
  add_compile_options(-Wall -Wextra -Wpedantic)
endif()

find_package(ament_cmake REQUIRED)
find_package(rclcpp REQUIRED)
find_package(geometry_msgs REQUIRED)
find_package(std_msgs REQUIRED)
find_package(robot_msgs REQUIRED)
find_package(controller_manager_msgs REQUIRED)

include_directories(include)

add_executable(drive_controller_node src/drive_controller_node.cpp)
ament_target_dependencies(drive_controller_node
  rclcpp
  geometry_msgs
  std_msgs
  robot_msgs
)

add_executable(bldc_command_bridge_node src/bldc_command_bridge_node.cpp)
ament_target_dependencies(bldc_command_bridge_node
  rclcpp
  geometry_msgs
  std_msgs
  robot_msgs
  controller_manager_msgs
)

install(TARGETS
  drive_controller_node
  bldc_command_bridge_node
  DESTINATION lib/${PROJECT_NAME}
)

install(DIRECTORY include/
  DESTINATION include/
)

install(DIRECTORY launch config
  DESTINATION share/${PROJECT_NAME}
)

ament_package()
