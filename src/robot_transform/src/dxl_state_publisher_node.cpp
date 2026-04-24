#include "robot_transform/dxl_state_publisher_node.hpp"

#include <cmath>

DxlStatePublisherNode::DxlStatePublisherNode()
: Node("dxl_state_publisher_node"),
  logical_motor3_dxl_id_(1),
  logical_motor4_dxl_id_(2),
  motor3_joint_name_("motor_3_joint"),
  motor4_joint_name_("motor_4_joint"),
  dxl_position_min_(0),
  dxl_position_max_(4095),
  dxl_degree_min_(0.0),
  dxl_degree_max_(360.0),
  joint_pos_rad_{0.0, 0.0}
{
  this->declare_parameter("logical_motor3_dxl_id", logical_motor3_dxl_id_);
  this->declare_parameter("logical_motor4_dxl_id", logical_motor4_dxl_id_);
  this->declare_parameter("motor3_joint_name", motor3_joint_name_);
  this->declare_parameter("motor4_joint_name", motor4_joint_name_);
  this->declare_parameter("dxl_position_min", dxl_position_min_);
  this->declare_parameter("dxl_position_max", dxl_position_max_);
  this->declare_parameter("dxl_degree_min", dxl_degree_min_);
  this->declare_parameter("dxl_degree_max", dxl_degree_max_);

  this->get_parameter("logical_motor3_dxl_id", logical_motor3_dxl_id_);
  this->get_parameter("logical_motor4_dxl_id", logical_motor4_dxl_id_);
  this->get_parameter("motor3_joint_name", motor3_joint_name_);
  this->get_parameter("motor4_joint_name", motor4_joint_name_);
  this->get_parameter("dxl_position_min", dxl_position_min_);
  this->get_parameter("dxl_position_max", dxl_position_max_);
  this->get_parameter("dxl_degree_min", dxl_degree_min_);
  this->get_parameter("dxl_degree_max", dxl_degree_max_);

  get_position_client_ =
    this->create_client<dynamixel_sdk_custom_interfaces::srv::GetPosition>("/get_position");

  // /joint_states와 분리해서 publish
  joint_state_pub_ =
    this->create_publisher<sensor_msgs::msg::JointState>("/dxl_joint_states", 20);

  request_timer_ = this->create_wall_timer(
    std::chrono::milliseconds(100),
    std::bind(&DxlStatePublisherNode::requestTimerCallback, this));

  publish_timer_ = this->create_wall_timer(
    std::chrono::milliseconds(100),
    std::bind(&DxlStatePublisherNode::publishTimerCallback, this));

  RCLCPP_INFO(this->get_logger(), "dxl_state_publisher_node started");
  RCLCPP_INFO(this->get_logger(), "Publishing DXL states on /dxl_joint_states");
}

double DxlStatePublisherNode::positionValueToRad(int value) const
{
  const double ratio =
    static_cast<double>(value - dxl_position_min_) /
    static_cast<double>(dxl_position_max_ - dxl_position_min_);

  const double deg =
    dxl_degree_min_ + ratio * (dxl_degree_max_ - dxl_degree_min_);

  return deg * M_PI / 180.0;
}

void DxlStatePublisherNode::requestTimerCallback()
{
  if (!get_position_client_->wait_for_service(std::chrono::milliseconds(100))) {
    return;
  }

  {
    auto req = std::make_shared<dynamixel_sdk_custom_interfaces::srv::GetPosition::Request>();
    req->id = static_cast<uint8_t>(logical_motor3_dxl_id_);
    get_position_client_->async_send_request(
      req,
      [this](rclcpp::Client<dynamixel_sdk_custom_interfaces::srv::GetPosition>::SharedFuture future) {
        joint_pos_rad_[0] = positionValueToRad(future.get()->position);
      });
  }

  {
    auto req = std::make_shared<dynamixel_sdk_custom_interfaces::srv::GetPosition::Request>();
    req->id = static_cast<uint8_t>(logical_motor4_dxl_id_);
    get_position_client_->async_send_request(
      req,
      [this](rclcpp::Client<dynamixel_sdk_custom_interfaces::srv::GetPosition>::SharedFuture future) {
        joint_pos_rad_[1] = positionValueToRad(future.get()->position);
      });
  }
}

void DxlStatePublisherNode::publishTimerCallback()
{
  sensor_msgs::msg::JointState msg;
  msg.header.stamp = this->now();
  msg.name = {motor3_joint_name_, motor4_joint_name_};
  msg.position = {joint_pos_rad_[0], joint_pos_rad_[1]};
  msg.velocity = {0.0, 0.0};
  msg.effort = {0.0, 0.0};
  joint_state_pub_->publish(msg);
}

int main(int argc, char ** argv)
{
  rclcpp::init(argc, argv);
  rclcpp::spin(std::make_shared<DxlStatePublisherNode>());
  rclcpp::shutdown();
  return 0;
}
