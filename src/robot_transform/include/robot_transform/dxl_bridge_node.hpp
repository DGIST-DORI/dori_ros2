#pragma once

#include <rclcpp/rclcpp.hpp>
#include <std_msgs/msg/float64_multi_array.hpp>
#include <dynamixel_sdk_custom_interfaces/msg/set_position.hpp>

class DxlBridgeNode : public rclcpp::Node
{
public:
  DxlBridgeNode();

private:
  void dxlCmdCallback(const std_msgs::msg::Float64MultiArray::SharedPtr msg);
  int logicalMotorToDxlId(int logical_motor_id) const;
  int degreeToPositionValue(double target_deg) const;
  int clampPositionValue(int value) const;

  rclcpp::Subscription<std_msgs::msg::Float64MultiArray>::SharedPtr dxl_cmd_sub_;
  rclcpp::Publisher<dynamixel_sdk_custom_interfaces::msg::SetPosition>::SharedPtr set_position_pub_;

  int logical_motor3_dxl_id_;
  int logical_motor4_dxl_id_;
  int dxl_position_min_;
  int dxl_position_max_;
  double dxl_degree_min_;
  double dxl_degree_max_;
};
