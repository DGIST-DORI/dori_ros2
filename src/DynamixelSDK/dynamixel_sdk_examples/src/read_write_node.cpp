// Copyright 2021 ROBOTIS CO., LTD.
//
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
//     http://www.apache.org/licenses/LICENSE-2.0

#include <cstdio>
#include <memory>
#include <string>

#include "dynamixel_sdk/dynamixel_sdk.h"
#include "dynamixel_sdk_custom_interfaces/msg/set_position.hpp"
#include "dynamixel_sdk_custom_interfaces/srv/get_position.hpp"
#include "rclcpp/rclcpp.hpp"
#include "rcutils/cmdline_parser.h"

#include "read_write_node.hpp"

// Control table address for X series
#define ADDR_OPERATING_MODE 11
#define ADDR_TORQUE_ENABLE 64
#define ADDR_GOAL_POSITION 116
#define ADDR_PRESENT_POSITION 132

#define PROTOCOL_VERSION 2.0
#define BAUDRATE 57600
#define DEVICE_NAME "/dev/ttyUSB0"

dynamixel::PortHandler * portHandler;
dynamixel::PacketHandler * packetHandler;

uint8_t dxl_error = 0;
int dxl_comm_result = COMM_TX_FAIL;

ReadWriteNode::ReadWriteNode()
: Node("read_write_node")
{
  RCLCPP_INFO(this->get_logger(), "Run read write node");

  this->declare_parameter("qos_depth", 10);
  int qos_depth = this->get_parameter("qos_depth").as_int();

  const auto qos =
    rclcpp::QoS(rclcpp::KeepLast(qos_depth)).reliable().durability_volatile();

  set_position_subscriber_ =
    this->create_subscription<SetPosition>(
      "set_position",
      qos,
      [this](const SetPosition::SharedPtr msg) -> void
      {
        uint32_t goal_position = static_cast<uint32_t>(msg->position);

        // write only: some setups do not return status packet for write instruction
        dxl_comm_result = packetHandler->write4ByteTxOnly(
          portHandler,
          static_cast<uint8_t>(msg->id),
          ADDR_GOAL_POSITION,
          goal_position
        );

        if (dxl_comm_result != COMM_SUCCESS) {
          RCLCPP_ERROR(
            this->get_logger(),
            "Failed to send goal position for ID %d: %s",
            msg->id,
            packetHandler->getTxRxResult(dxl_comm_result));
        } else {
          RCLCPP_INFO(
            this->get_logger(),
            "Sent [ID: %d] [Goal Position: %d]",
            msg->id,
            msg->position);
        }
      });

  auto get_present_position =
    [this](
      const std::shared_ptr<GetPosition::Request> request,
      std::shared_ptr<GetPosition::Response> response) -> void
    {
      int32_t present_position = 0;
      uint8_t local_dxl_error = 0;

      dxl_comm_result = packetHandler->read4ByteTxRx(
        portHandler,
        static_cast<uint8_t>(request->id),
        ADDR_PRESENT_POSITION,
        reinterpret_cast<uint32_t *>(&present_position),
        &local_dxl_error
      );

      if (dxl_comm_result != COMM_SUCCESS) {
        RCLCPP_ERROR(
          this->get_logger(),
          "Failed to read present position for ID %d: %s",
          request->id,
          packetHandler->getTxRxResult(dxl_comm_result));
      } else if (local_dxl_error != 0) {
        RCLCPP_ERROR(
          this->get_logger(),
          "DXL error while reading present position for ID %d: %s",
          request->id,
          packetHandler->getRxPacketError(local_dxl_error));
      }

      RCLCPP_INFO(
        this->get_logger(),
        "Get [ID: %d] [Present Position: %d]",
        request->id,
        present_position
      );

      response->position = present_position;
    };

  get_position_server_ = create_service<GetPosition>("get_position", get_present_position);
}

ReadWriteNode::~ReadWriteNode()
{
}

void setupDynamixel(uint8_t dxl_id)
{
  // Position Control Mode
  dxl_comm_result = packetHandler->write1ByteTxRx(
    portHandler,
    dxl_id,
    ADDR_OPERATING_MODE,
    3,
    &dxl_error
  );

  if (dxl_comm_result != COMM_SUCCESS) {
    RCLCPP_ERROR(
      rclcpp::get_logger("read_write_node"),
      "Failed to set Position Control Mode: %s",
      packetHandler->getTxRxResult(dxl_comm_result));
  } else if (dxl_error != 0) {
    RCLCPP_ERROR(
      rclcpp::get_logger("read_write_node"),
      "DXL mode set error: %s",
      packetHandler->getRxPacketError(dxl_error));
  } else {
    RCLCPP_INFO(
      rclcpp::get_logger("read_write_node"),
      "Succeeded to set Position Control Mode.");
  }

  dxl_error = 0;

  // Torque Enable
  dxl_comm_result = packetHandler->write1ByteTxRx(
    portHandler,
    dxl_id,
    ADDR_TORQUE_ENABLE,
    1,
    &dxl_error
  );

  if (dxl_comm_result != COMM_SUCCESS) {
    RCLCPP_ERROR(
      rclcpp::get_logger("read_write_node"),
      "Failed to enable torque: %s",
      packetHandler->getTxRxResult(dxl_comm_result));
  } else if (dxl_error != 0) {
    RCLCPP_ERROR(
      rclcpp::get_logger("read_write_node"),
      "DXL torque enable error: %s",
      packetHandler->getRxPacketError(dxl_error));
  } else {
    RCLCPP_INFO(
      rclcpp::get_logger("read_write_node"),
      "Succeeded to enable torque.");
  }
}

int main(int argc, char * argv[])
{
  rclcpp::init(argc, argv);

  portHandler = dynamixel::PortHandler::getPortHandler(DEVICE_NAME);
  packetHandler = dynamixel::PacketHandler::getPacketHandler(PROTOCOL_VERSION);

  dxl_comm_result = portHandler->openPort();
  if (dxl_comm_result == false) {
    RCLCPP_ERROR(rclcpp::get_logger("read_write_node"), "Failed to open the port!");
    return -1;
  } else {
    RCLCPP_INFO(rclcpp::get_logger("read_write_node"), "Succeeded to open the port.");
  }

  dxl_comm_result = portHandler->setBaudRate(BAUDRATE);
  if (dxl_comm_result == false) {
    RCLCPP_ERROR(rclcpp::get_logger("read_write_node"), "Failed to set the baudrate!");
    return -1;
  } else {
    RCLCPP_INFO(rclcpp::get_logger("read_write_node"), "Succeeded to set the baudrate.");
  }

  // keep original-style init since read used to work with this structure
  setupDynamixel(BROADCAST_ID);

  auto readwritenode = std::make_shared<ReadWriteNode>();
  rclcpp::spin(readwritenode);
  rclcpp::shutdown();

  packetHandler->write1ByteTxOnly(
    portHandler,
    BROADCAST_ID,
    ADDR_TORQUE_ENABLE,
    0
  );

  return 0;
}
