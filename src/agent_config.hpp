#ifndef AGENT_CONFIG_HPP_
#define AGENT_CONFIG_HPP_

#include "range_codec.hpp"

#include <tierlink/stream.hpp>

#include <optional>
#include <string>
#include <vector>

namespace fleet_telemetry
{

// One ROS topic sent to the server: received as raw CDR, thinned to rate_hz, compressed. With
// `range`, a lidar scan (sensor_msgs/msg/PointCloud2) goes out as range-image sectors instead.
struct TopicStream
{
  std::string name;
  std::string topic;
  std::string type;
  tierlink::Delivery delivery;
  double rate_hz;
  std::optional<RangeCodecConfig> range;
  // transport: udp. Published best effort, so it takes the UDP link.
  bool udp = false;
};

// A ROS topic the server may publish to. Nothing else can be reached by a command.
struct CommandInterface
{
  std::string id;
  std::string topic;
  std::string type;
};

struct AgentConfig
{
  std::vector<TopicStream> streams;
  std::vector<CommandInterface> commands;
};

// Parses the streams file. Throws std::runtime_error naming the entry that is wrong.
AgentConfig parse_config(const std::string & yaml_text);

}  // namespace fleet_telemetry

#endif  // AGENT_CONFIG_HPP_
