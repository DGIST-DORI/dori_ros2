#include "cubemars_hardware/system.hpp"

#include <algorithm>
#include <cmath>
#include <limits>
#include <unordered_set>
#include <vector>

#include <linux/can.h>

#include "hardware_interface/types/hardware_interface_type_values.hpp"
#include "rclcpp/rclcpp.hpp"

namespace
{
constexpr double PI_CONST = 3.14159265358979323846;
}

namespace cubemars_hardware
{

CubeMarsSystemHardware::~CubeMarsSystemHardware()
{
  on_cleanup(rclcpp_lifecycle::State());
}

int CubeMarsSystemHardware::float_to_uint(double x, double x_min, double x_max, unsigned int bits)
{
  const double span = x_max - x_min;
  if (span <= 0.0) {
    return 0;
  }

  if (x < x_min) {
    x = x_min;
  }
  if (x > x_max) {
    x = x_max;
  }

  const double scale = static_cast<double>((1u << bits) - 1u) / span;
  return static_cast<int>((x - x_min) * scale);
}

double CubeMarsSystemHardware::uint_to_float(int x_int, double x_min, double x_max, unsigned int bits)
{
  const double span = x_max - x_min;
  if (span <= 0.0) {
    return x_min;
  }

  return static_cast<double>(x_int) * span / static_cast<double>((1u << bits) - 1u) + x_min;
}

bool CubeMarsSystemHardware::send_mit_enable(std::uint32_t can_id)
{
  const std::uint8_t data[8] = {0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFC};
  return can_.write_message(can_id, data, 8, CanSocket::FrameType::STANDARD);
}

bool CubeMarsSystemHardware::send_mit_disable(std::uint32_t can_id)
{
  const std::uint8_t data[8] = {0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFD};
  return can_.write_message(can_id, data, 8, CanSocket::FrameType::STANDARD);
}

bool CubeMarsSystemHardware::send_mit_zero(std::uint32_t can_id)
{
  const std::uint8_t data[8] = {0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFE};
  return can_.write_message(can_id, data, 8, CanSocket::FrameType::STANDARD);
}

bool CubeMarsSystemHardware::send_mit_command(
  std::size_t i,
  double p_des,
  double v_des,
  double kp,
  double kd,
  double t_ff)
{
  const int p_int  = float_to_uint(p_des, mit_p_min_[i],  mit_p_max_[i], 16);
  const int v_int  = float_to_uint(v_des, mit_v_min_[i],  mit_v_max_[i], 12);
  const int kp_int = float_to_uint(kp,    mit_kp_min_[i], mit_kp_max_[i], 12);
  const int kd_int = float_to_uint(kd,    mit_kd_min_[i], mit_kd_max_[i], 12);
  const int t_int  = float_to_uint(t_ff,  mit_t_min_[i],  mit_t_max_[i], 12);

  std::uint8_t data[8];
  data[0] = (p_int >> 8) & 0xFF;
  data[1] = p_int & 0xFF;
  data[2] = (v_int >> 4) & 0xFF;
  data[3] = ((v_int & 0x0F) << 4) | ((kp_int >> 8) & 0x0F);
  data[4] = kp_int & 0xFF;
  data[5] = (kd_int >> 4) & 0xFF;
  data[6] = ((kd_int & 0x0F) << 4) | ((t_int >> 8) & 0x0F);
  data[7] = t_int & 0xFF;

  return can_.write_message(can_ids_[i], data, 8, CanSocket::FrameType::STANDARD);
}

bool CubeMarsSystemHardware::parse_mit_feedback(
  std::uint32_t read_id,
  const std::uint8_t data[],
  std::uint8_t len)
{
  if (len < 7) {
    return false;
  }

  const std::uint32_t rx_id = read_id & CAN_SFF_MASK;
  auto it = std::find(can_ids_.begin(), can_ids_.end(), rx_id);
  if (it == can_ids_.end()) {
    return false;
  }

  const int i = std::distance(can_ids_.begin(), it);

  const int p_int = (static_cast<int>(data[1]) << 8) | static_cast<int>(data[2]);
  const int v_int = (static_cast<int>(data[3]) << 4) | (static_cast<int>(data[4]) >> 4);
  const int t_int = ((static_cast<int>(data[4]) & 0x0F) << 8) | static_cast<int>(data[5]);
  const int temp_raw = static_cast<int>(data[6]);

  const double raw_pos = uint_to_float(p_int, mit_p_min_[i], mit_p_max_[i], 16);
  const double vel = uint_to_float(v_int, mit_v_min_[i], mit_v_max_[i], 12);
  const double trq = uint_to_float(t_int, mit_t_min_[i], mit_t_max_[i], 12);

  double direction_sign = 1.0;
  if (info_.joints[i].parameters.count("direction_sign") != 0) {
    direction_sign = std::stod(info_.joints[i].parameters.at("direction_sign"));
  }

  // 최소 버전: raw MIT absolute angle만 사용
  hw_states_positions_[i] = (raw_pos - enc_offs_[i]) * direction_sign;
  hw_states_velocities_[i] = vel * direction_sign;
  hw_states_efforts_[i] = trq * direction_sign;
  hw_states_temperatures_[i] = static_cast<double>(temp_raw);

  RCLCPP_INFO(
    rclcpp::get_logger("CubeMarsSystemHardware"),
    "MIT feedback joint=%d raw_pos=%f ext_pos=%f vel=%f trq=%f temp=%f",
    i,
    raw_pos,
    hw_states_positions_[i],
    hw_states_velocities_[i],
    hw_states_efforts_[i],
    hw_states_temperatures_[i]);

  return true;
}

bool CubeMarsSystemHardware::parse_servo_feedback(
  std::uint32_t read_id,
  const std::uint8_t data[],
  std::uint8_t len)
{
  if (len < 8) {
    return false;
  }

  auto it = std::find(can_ids_.begin(), can_ids_.end(), (read_id & 0xFF));
  if (it == can_ids_.end()) {
    return false;
  }

  const int i = std::distance(can_ids_.begin(), it);

  if (data[7] != 0)
  {
    switch (data[7])
    {
      case 1:
        RCLCPP_ERROR(rclcpp::get_logger("CubeMarsSystemHardware"), "Motor over-temperature fault.");
        break;
      case 2:
        RCLCPP_ERROR(rclcpp::get_logger("CubeMarsSystemHardware"), "Over-current fault.");
        break;
      case 3:
        RCLCPP_ERROR(rclcpp::get_logger("CubeMarsSystemHardware"), "Over-voltage fault.");
        break;
      case 4:
        RCLCPP_ERROR(rclcpp::get_logger("CubeMarsSystemHardware"), "Under-voltage fault.");
        break;
      case 5:
        RCLCPP_ERROR(rclcpp::get_logger("CubeMarsSystemHardware"), "Encoder fault.");
        break;
      case 6:
        RCLCPP_ERROR(rclcpp::get_logger("CubeMarsSystemHardware"), "MOSFET over-temperature fault.");
        break;
      case 7:
        RCLCPP_ERROR(rclcpp::get_logger("CubeMarsSystemHardware"), "Motor stall.");
        break;
      default:
        RCLCPP_ERROR(
          rclcpp::get_logger("CubeMarsSystemHardware"),
          "Unknown servo error code: %d", data[7]);
        break;
    }
  }

  const std::int16_t pos_int =
    static_cast<std::int16_t>((static_cast<std::uint16_t>(data[0]) << 8) | data[1]);
  const std::int16_t spd_int =
    static_cast<std::int16_t>((static_cast<std::uint16_t>(data[2]) << 8) | data[3]);
  const std::int16_t cur_int =
    static_cast<std::int16_t>((static_cast<std::uint16_t>(data[4]) << 8) | data[5]);

  double direction_sign = 1.0;
  if (info_.joints[i].parameters.count("direction_sign") != 0) {
    direction_sign = std::stod(info_.joints[i].parameters.at("direction_sign"));
  }

  hw_states_positions_[i] =
    ((pos_int * 0.1 * PI_CONST / 180.0) - enc_offs_[i]) * direction_sign;

  hw_states_velocities_[i] =
    (spd_int * 10.0 / erpm_conversions_[i]) * direction_sign;

  hw_states_efforts_[i] =
    (cur_int * 0.01 * torque_constants_[i] *
    std::stoi(info_.joints[i].parameters.at("gear_ratio"))) * direction_sign;

  hw_states_temperatures_[i] = static_cast<double>(data[6]);

  return true;
}

hardware_interface::CallbackReturn CubeMarsSystemHardware::on_init(
  const hardware_interface::HardwareInfo & info)
{
  if (
    hardware_interface::SystemInterface::on_init(info) !=
    hardware_interface::CallbackReturn::SUCCESS)
  {
    return hardware_interface::CallbackReturn::ERROR;
  }

  if (info_.hardware_parameters.count("can_interface") != 0) {
    can_itf_ = info_.hardware_parameters.at("can_interface");
  } else {
    RCLCPP_FATAL(
      rclcpp::get_logger("CubeMarsSystemHardware"),
      "No can_interface specified in URDF");
    return hardware_interface::CallbackReturn::ERROR;
  }

  if (info_.hardware_parameters.count("protocol_mode") != 0) {
    const auto mode = info_.hardware_parameters.at("protocol_mode");
    protocol_mode_ = (mode == "mit") ? MIT_PROTOCOL : SERVO_PROTOCOL;
  } else {
    protocol_mode_ = SERVO_PROTOCOL;
  }

  hw_states_positions_.resize(info_.joints.size(), 0.0);
  hw_states_velocities_.resize(info_.joints.size(), 0.0);
  hw_states_efforts_.resize(info_.joints.size(), 0.0);
  hw_states_temperatures_.resize(info_.joints.size(), 0.0);

  hw_commands_positions_.resize(info_.joints.size(), std::numeric_limits<double>::quiet_NaN());
  hw_commands_velocities_.resize(info_.joints.size(), std::numeric_limits<double>::quiet_NaN());
  hw_commands_accelerations_.resize(info_.joints.size(), std::numeric_limits<double>::quiet_NaN());
  hw_commands_efforts_.resize(info_.joints.size(), std::numeric_limits<double>::quiet_NaN());

  control_mode_.resize(info_.joints.size(), control_mode_t::UNDEFINED);

  for (const hardware_interface::ComponentInfo & joint : info_.joints)
  {
    if (joint.parameters.count("can_id") != 0 &&
      joint.parameters.count("kt") != 0 &&
      joint.parameters.count("pole_pairs") != 0 &&
      joint.parameters.count("gear_ratio") != 0)
    {
      can_ids_.emplace_back(std::stoul(joint.parameters.at("can_id")));
      torque_constants_.emplace_back(std::stod(joint.parameters.at("kt")));

      double erpm_conversion =
        std::stoi(joint.parameters.at("pole_pairs")) *
        std::stoi(joint.parameters.at("gear_ratio")) * 60.0 / (2.0 * PI_CONST);
      erpm_conversions_.emplace_back(erpm_conversion);

      if (joint.parameters.count("acc_limit") != 0 &&
        joint.parameters.count("vel_limit") != 0)
      {
        std::pair<std::int16_t, std::int16_t> limits;
        limits.first = static_cast<std::int16_t>(
          std::stoi(joint.parameters.at("vel_limit")) / 10.0 * erpm_conversion);
        limits.second = static_cast<std::int16_t>(
          std::stoi(joint.parameters.at("acc_limit")) / 10.0 * erpm_conversion);

        if (limits.first >= 32767 || limits.first <= 0)
        {
          RCLCPP_ERROR(
            rclcpp::get_logger("CubeMarsSystemHardware"),
            "velocity limit is not in range 0-32767: %d", limits.first);
          return hardware_interface::CallbackReturn::ERROR;
        }
        if (limits.second >= 32767 || limits.second <= 0)
        {
          RCLCPP_ERROR(
            rclcpp::get_logger("CubeMarsSystemHardware"),
            "acceleration limit is not in range 0-32767: %d", limits.second);
          return hardware_interface::CallbackReturn::ERROR;
        }
        limits_.emplace_back(limits);
      }
      else
      {
        limits_.emplace_back(std::make_pair(0, 0));
      }
    }
    else
    {
      RCLCPP_FATAL(
        rclcpp::get_logger("CubeMarsSystemHardware"),
        "Missing parameters in URDF for %s", joint.name.c_str());
      return hardware_interface::CallbackReturn::ERROR;
    }

    if (joint.parameters.count("enc_off") != 0)
    {
      enc_offs_.emplace_back(std::stod(joint.parameters.at("enc_off")));
    }
    else
    {
      enc_offs_.emplace_back(0.0);
    }

    if (joint.parameters.count("trq_limit") != 0 && std::stod(joint.parameters.at("trq_limit")) > 0.0)
    {
      trq_limits_.emplace_back(std::stod(joint.parameters.at("trq_limit")));
    }
    else
    {
      trq_limits_.emplace_back(0.0);
    }

    if (joint.parameters.count("read_only") != 0 && std::stoi(joint.parameters.at("read_only")) == 1)
    {
      read_only_.emplace_back(true);
    }
    else
    {
      read_only_.emplace_back(false);
    }

    auto get_param_or = [&](const std::string & key, double default_value) -> double {
      if (joint.parameters.count(key) != 0) {
        return std::stod(joint.parameters.at(key));
      }
      return default_value;
    };

    mit_p_min_.push_back(get_param_or("mit_p_min", -12.5));
    mit_p_max_.push_back(get_param_or("mit_p_max", 12.5));
    mit_v_min_.push_back(get_param_or("mit_v_min", -30.0));
    mit_v_max_.push_back(get_param_or("mit_v_max", 30.0));
    mit_t_min_.push_back(get_param_or("mit_t_min", -18.0));
    mit_t_max_.push_back(get_param_or("mit_t_max", 18.0));
    mit_kp_min_.push_back(get_param_or("mit_kp_min", 0.0));
    mit_kp_max_.push_back(get_param_or("mit_kp_max", 500.0));
    mit_kd_min_.push_back(get_param_or("mit_kd_min", 0.0));
    mit_kd_max_.push_back(get_param_or("mit_kd_max", 5.0));

    mit_pos_kp_.push_back(get_param_or("mit_pos_kp", 30.0));
    mit_pos_kd_.push_back(get_param_or("mit_pos_kd", 1.0));
    mit_vel_kd_.push_back(get_param_or("mit_vel_kd", 1.0));
  }

  return hardware_interface::CallbackReturn::SUCCESS;
}

hardware_interface::CallbackReturn CubeMarsSystemHardware::on_configure(
  const rclcpp_lifecycle::State &)
{
  const hardware_interface::CallbackReturn result =
    can_.connect(can_itf_, can_ids_, 0x00000000U)
    ? hardware_interface::CallbackReturn::SUCCESS
    : hardware_interface::CallbackReturn::FAILURE;

  RCLCPP_INFO(rclcpp::get_logger("CubeMarsSystemHardware"), "Communication active");
  return result;
}

hardware_interface::CallbackReturn CubeMarsSystemHardware::on_cleanup(
  const rclcpp_lifecycle::State &)
{
  const hardware_interface::CallbackReturn result =
    can_.disconnect()
    ? hardware_interface::CallbackReturn::SUCCESS
    : hardware_interface::CallbackReturn::FAILURE;

  RCLCPP_INFO(rclcpp::get_logger("CubeMarsSystemHardware"), "Communication closed");
  return result;
}

std::vector<hardware_interface::StateInterface>
CubeMarsSystemHardware::export_state_interfaces()
{
  std::vector<hardware_interface::StateInterface> state_interfaces;
  for (std::size_t i = 0; i < info_.joints.size(); i++)
  {
    state_interfaces.emplace_back(hardware_interface::StateInterface(
      info_.joints[i].name, hardware_interface::HW_IF_POSITION, &hw_states_positions_[i]));
    state_interfaces.emplace_back(hardware_interface::StateInterface(
      info_.joints[i].name, hardware_interface::HW_IF_VELOCITY, &hw_states_velocities_[i]));
    state_interfaces.emplace_back(hardware_interface::StateInterface(
      info_.joints[i].name, hardware_interface::HW_IF_EFFORT, &hw_states_efforts_[i]));
    state_interfaces.emplace_back(hardware_interface::StateInterface(
      info_.joints[i].name, "temperature", &hw_states_temperatures_[i]));
  }

  return state_interfaces;
}

std::vector<hardware_interface::CommandInterface>
CubeMarsSystemHardware::export_command_interfaces()
{
  std::vector<hardware_interface::CommandInterface> command_interfaces;
  for (std::size_t i = 0; i < info_.joints.size(); i++)
  {
    command_interfaces.emplace_back(hardware_interface::CommandInterface(
      info_.joints[i].name, hardware_interface::HW_IF_POSITION, &hw_commands_positions_[i]));
    command_interfaces.emplace_back(hardware_interface::CommandInterface(
      info_.joints[i].name, hardware_interface::HW_IF_VELOCITY, &hw_commands_velocities_[i]));
    command_interfaces.emplace_back(hardware_interface::CommandInterface(
      info_.joints[i].name, hardware_interface::HW_IF_ACCELERATION, &hw_commands_accelerations_[i]));
    command_interfaces.emplace_back(hardware_interface::CommandInterface(
      info_.joints[i].name, hardware_interface::HW_IF_EFFORT, &hw_commands_efforts_[i]));
  }

  return command_interfaces;
}

hardware_interface::return_type CubeMarsSystemHardware::prepare_command_mode_switch(
  const std::vector<std::string> & start_interfaces,
  const std::vector<std::string> & stop_interfaces)
{
  stop_modes_.clear();
  start_modes_.clear();

  stop_modes_.resize(info_.joints.size(), false);

  std::unordered_set<std::string> eff{"effort"};
  std::unordered_set<std::string> vel{"velocity"};
  std::unordered_set<std::string> pos{"position"};

  std::unordered_set<std::string> joint_interfaces;

  for (std::size_t i = 0; i < info_.joints.size(); i++)
  {
    for (const std::string & key : stop_interfaces)
    {
      if (key.find(info_.joints[i].name) != std::string::npos)
      {
        stop_modes_[i] = true;
        break;
      }
    }

    joint_interfaces.clear();
    for (const std::string & key : start_interfaces)
    {
      if (key.find(info_.joints[i].name) != std::string::npos)
      {
        joint_interfaces.insert(key.substr(key.find("/") + 1));
      }
    }

    if (joint_interfaces == eff)
    {
      start_modes_.push_back(CURRENT_LOOP);
    }
    else if (joint_interfaces == vel)
    {
      start_modes_.push_back(SPEED_LOOP);
    }
    else if (joint_interfaces == pos)
    {
      if (limits_[i].first == 0 || limits_[i].second == 0)
      {
        start_modes_.push_back(POSITION_LOOP);
      }
      else
      {
        start_modes_.push_back(POSITION_SPEED_LOOP);
      }
    }
    else if (joint_interfaces.empty())
    {
      if (stop_modes_[i])
      {
        start_modes_.push_back(UNDEFINED);
      }
      else
      {
        start_modes_.push_back(control_mode_[i]);
      }
    }
    else
    {
      return hardware_interface::return_type::ERROR;
    }
  }

  return hardware_interface::return_type::OK;
}

hardware_interface::return_type CubeMarsSystemHardware::perform_command_mode_switch(
  const std::vector<std::string> &,
  const std::vector<std::string> &)
{
  for (std::size_t i = 0; i < info_.joints.size(); i++)
  {
    if (stop_modes_[i])
    {
      hw_commands_efforts_[i] = std::numeric_limits<double>::quiet_NaN();
      hw_commands_velocities_[i] = std::numeric_limits<double>::quiet_NaN();
      hw_commands_positions_[i] = std::numeric_limits<double>::quiet_NaN();
    }

    control_mode_[i] = start_modes_[i];
  }

  return hardware_interface::return_type::OK;
}

hardware_interface::CallbackReturn CubeMarsSystemHardware::on_activate(
  const rclcpp_lifecycle::State &)
{
  if (protocol_mode_ == MIT_PROTOCOL)
  {
    for (std::size_t i = 0; i < can_ids_.size(); ++i)
    {
      if (!read_only_[i])
      {
        if (!send_mit_enable(can_ids_[i])) {
          return hardware_interface::CallbackReturn::ERROR;
        }
      }
    }
  }

  return hardware_interface::CallbackReturn::SUCCESS;
}

hardware_interface::CallbackReturn CubeMarsSystemHardware::on_deactivate(
  const rclcpp_lifecycle::State &)
{
  if (protocol_mode_ == MIT_PROTOCOL)
  {
    for (std::size_t i = 0; i < can_ids_.size(); ++i)
    {
      if (!read_only_[i]) {
        send_mit_disable(can_ids_[i]);
      }
    }
  }

  return hardware_interface::CallbackReturn::SUCCESS;
}

hardware_interface::return_type CubeMarsSystemHardware::read(
  const rclcpp::Time &, const rclcpp::Duration &)
{
  std::uint32_t read_id;
  std::uint8_t read_data[8];
  std::uint8_t read_len;

  while (can_.read_nonblocking(read_id, read_data, read_len))
  {
    RCLCPP_INFO(
      rclcpp::get_logger("CubeMarsSystemHardware"),
      "RX id=0x%X len=%u data=%02X %02X %02X %02X %02X %02X %02X %02X",
      read_id, read_len,
      read_data[0], read_data[1], read_data[2], read_data[3],
      read_data[4], read_data[5], read_data[6], read_data[7]);

    if (protocol_mode_ == MIT_PROTOCOL) {
      parse_mit_feedback(read_id, read_data, read_len);
    } else {
      parse_servo_feedback(read_id, read_data, read_len);
    }
  }

  for (std::size_t i = 0; i < info_.joints.size(); i++)
  {
    if (trq_limits_[i] != 0.0 && std::abs(hw_states_efforts_[i]) > trq_limits_[i])
    {
      RCLCPP_ERROR(
        rclcpp::get_logger("CubeMarsSystemHardware"),
        "Joint %lu went over torque limit.", i);

      if (protocol_mode_ == MIT_PROTOCOL)
      {
        send_mit_disable(can_ids_[i]);
      }
      else
      {
        std::uint8_t data[4] = {0, 0, 0, 0};
        can_.write_message(
          can_ids_[i] | (CURRENT_LOOP << 8),
          data,
          4,
          CanSocket::FrameType::EXTENDED);
      }

      return hardware_interface::return_type::ERROR;
    }
  }

  return hardware_interface::return_type::OK;
}

hardware_interface::return_type CubeMarsSystemHardware::write(
  const rclcpp::Time &, const rclcpp::Duration &)
{
  for (std::size_t i = 0; i < info_.joints.size(); i++)
  {
    if (read_only_[i]) {
      continue;
    }

    double direction_sign = 1.0;
    if (info_.joints[i].parameters.count("direction_sign") != 0)
    {
      direction_sign = std::stod(info_.joints[i].parameters.at("direction_sign"));
    }

    if (protocol_mode_ == MIT_PROTOCOL)
    {
      switch (control_mode_[i])
      {
        case CURRENT_LOOP:
        {
          if (!std::isnan(hw_commands_efforts_[i]))
          {
            const double tau = hw_commands_efforts_[i] * direction_sign;

            if (!send_mit_command(i, 0.0, 0.0, 0.0, 0.0, tau))
            {
              return hardware_interface::return_type::ERROR;
            }
          }
          break;
        }

        case SPEED_LOOP:
        {
          if (!std::isnan(hw_commands_velocities_[i]))
          {
            const double v_des = hw_commands_velocities_[i] * direction_sign;

            double tau_ff = 0.0;
            if (std::abs(v_des) > 0.05) {
              tau_ff = (v_des > 0.0) ? 0.35 : -0.35;
            }

            RCLCPP_INFO(
              rclcpp::get_logger("CubeMarsSystemHardware"),
              "MIT SPEED cmd joint=%zu raw_vel=%f signed_vel=%f fb_vel=%f kp=%f kd=%f tau_ff=%f",
              i,
              hw_commands_velocities_[i],
              v_des,
              hw_states_velocities_[i],
              0.0,
              mit_vel_kd_[i],
              tau_ff);

            if (!send_mit_command(
                  i,
                  0.0,
                  v_des,
                  0.0,
                  mit_vel_kd_[i],
                  tau_ff))
            {
              return hardware_interface::return_type::ERROR;
            }
          }
          break;
        }

        case POSITION_LOOP:
        case POSITION_SPEED_LOOP:
        {
          if (!std::isnan(hw_commands_positions_[i]))
          {
            // 최소 버전: transform_controller가 계산한 raw target을 그대로 MIT p_des로 사용
            double p_des = hw_commands_positions_[i] * direction_sign;

            if (p_des > mit_p_max_[i]) {
              p_des = mit_p_max_[i];
            } else if (p_des < mit_p_min_[i]) {
              p_des = mit_p_min_[i];
            }

            RCLCPP_INFO(
              rclcpp::get_logger("CubeMarsSystemHardware"),
              "MIT POS cmd joint=%zu raw_target=%f clipped_p_des=%f",
              i,
              hw_commands_positions_[i] * direction_sign,
              p_des);

            if (!send_mit_command(i, p_des, 0.0, mit_pos_kp_[i], mit_pos_kd_[i], 0.0))
            {
              return hardware_interface::return_type::ERROR;
            }
          }
          break;
        }

        case UNDEFINED:
        default:
          break;
      }

      continue;
    }

    switch (control_mode_[i])
    {
      case UNDEFINED:
      {
        break;
      }

      case CURRENT_LOOP:
      {
        if (!std::isnan(hw_commands_efforts_[i]))
        {
          double commanded_effort = hw_commands_efforts_[i] * direction_sign;
          std::int32_t current = static_cast<std::int32_t>(
            commanded_effort * 1000.0 / torque_constants_[i]);

          if (std::abs(current) >= 60000)
          {
            RCLCPP_ERROR(
              rclcpp::get_logger("CubeMarsSystemHardware"),
              "current command is over maximal allowed value of 60000: %d", current);
            return hardware_interface::return_type::ERROR;
          }

          std::uint8_t data[4];
          data[0] = (current >> 24) & 0xFF;
          data[1] = (current >> 16) & 0xFF;
          data[2] = (current >> 8) & 0xFF;
          data[3] = current & 0xFF;

          can_.write_message(
            can_ids_[i] | (CURRENT_LOOP << 8),
            data,
            4,
            CanSocket::FrameType::EXTENDED);
        }
        break;
      }

      case SPEED_LOOP:
      {
        if (!std::isnan(hw_commands_velocities_[i]))
        {
          double commanded_velocity = hw_commands_velocities_[i] * direction_sign;
          std::int32_t speed = static_cast<std::int32_t>(
            commanded_velocity * erpm_conversions_[i]);

          if (std::abs(speed) >= 100000)
          {
            RCLCPP_ERROR(
              rclcpp::get_logger("CubeMarsSystemHardware"),
              "speed command is over maximal allowed value of 100000: %d", speed);
            return hardware_interface::return_type::ERROR;
          }

          std::uint8_t data[4];
          data[0] = (speed >> 24) & 0xFF;
          data[1] = (speed >> 16) & 0xFF;
          data[2] = (speed >> 8) & 0xFF;
          data[3] = speed & 0xFF;

          can_.write_message(
            can_ids_[i] | (SPEED_LOOP << 8),
            data,
            4,
            CanSocket::FrameType::EXTENDED);
        }
        break;
      }

      case POSITION_LOOP:
      {
        if (!std::isnan(hw_commands_positions_[i]))
        {
          double commanded_position = hw_commands_positions_[i] * direction_sign;
          std::int32_t position = static_cast<std::int32_t>(
            (commanded_position + enc_offs_[i]) * 10000.0 * 180.0 / PI_CONST);

          if (std::abs(position) >= 360000000)
          {
            RCLCPP_ERROR(
              rclcpp::get_logger("CubeMarsSystemHardware"),
              "position command is over maximal allowed value of 360000000: %d", position);
            return hardware_interface::return_type::ERROR;
          }

          std::uint8_t data[4];
          data[0] = (position >> 24) & 0xFF;
          data[1] = (position >> 16) & 0xFF;
          data[2] = (position >> 8) & 0xFF;
          data[3] = position & 0xFF;

          can_.write_message(
            can_ids_[i] | (POSITION_LOOP << 8),
            data,
            4,
            CanSocket::FrameType::EXTENDED);
        }
        break;
      }

      case POSITION_SPEED_LOOP:
      {
        if (!std::isnan(hw_commands_positions_[i]))
        {
          double commanded_position = hw_commands_positions_[i] * direction_sign;
          std::int32_t position = static_cast<std::int32_t>(
            (commanded_position + enc_offs_[i]) * 10000.0 * 180.0 / PI_CONST);
          std::int16_t vel = limits_[i].first;
          std::int16_t acc = limits_[i].second;

          if (std::abs(position) >= 360000000)
          {
            RCLCPP_ERROR(
              rclcpp::get_logger("CubeMarsSystemHardware"),
              "position command is over maximal allowed value of 360000000: %d", position);
            return hardware_interface::return_type::ERROR;
          }

          std::uint8_t data[8];
          data[0] = (position >> 24) & 0xFF;
          data[1] = (position >> 16) & 0xFF;
          data[2] = (position >> 8) & 0xFF;
          data[3] = position & 0xFF;
          data[4] = (vel >> 8) & 0xFF;
          data[5] = vel & 0xFF;
          data[6] = (acc >> 8) & 0xFF;
          data[7] = acc & 0xFF;

          can_.write_message(
            can_ids_[i] | (POSITION_SPEED_LOOP << 8),
            data,
            8,
            CanSocket::FrameType::EXTENDED);
        }
        break;
      }
    }
  }

  return hardware_interface::return_type::OK;
}

}  // namespace cubemars_hardware

#include "pluginlib/class_list_macros.hpp"

PLUGINLIB_EXPORT_CLASS(
  cubemars_hardware::CubeMarsSystemHardware, hardware_interface::SystemInterface)
