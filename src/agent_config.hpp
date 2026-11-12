#ifndef AGENT_CONFIG_HPP_
#define AGENT_CONFIG_HPP_

#include <tierlink/stream.hpp>

#include <string>
#include <vector>

namespace fleet_telemetry
{

// One ROS topic sent to the server: received as raw CDR, thinned to rate_hz, compressed.
struct TopicStream
{
  std::string name;
  std::string topic;
  std::string type;
  tierlink::Delivery delivery;
  double rate_hz;
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
