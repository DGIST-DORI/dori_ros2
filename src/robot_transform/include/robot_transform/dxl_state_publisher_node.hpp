#pragma once

#include <array>
#include <string>

#include <rclcpp/rclcpp.hpp>
#include <sensor_msgs/msg/joint_state.hpp>
#include <dynamixel_sdk_custom_interfaces/srv/get_position.hpp>

class DxlStatePublisherNode : public rclcpp::Node
{
public:
  DxlStatePublisherNode();

private:
  double positionValueToRad(int value) const;
  void requestTimerCallback();
  void publishTimerCallback();

  rclcpp::Client<dynamixel_sdk_custom_interfaces::srv::GetPosition>::SharedPtr get_position_client_;
  rclcpp::Publisher<sensor_msgs::msg::JointState>::SharedPtr joint_state_pub_;
  rclcpp::TimerBase::SharedPtr request_timer_;
  rclcpp::TimerBase::SharedPtr publish_timer_;

  int logical_motor3_dxl_id_;
  int logical_motor4_dxl_id_;
  std::string motor3_joint_name_;
  std::string motor4_joint_name_;
  int dxl_position_min_;
  int dxl_position_max_;
  double dxl_degree_min_;
  double dxl_degree_max_;
  std::array<double, 2> joint_pos_rad_;
};
