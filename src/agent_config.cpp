#include "agent_config.hpp"

#include <yaml-cpp/yaml.h>

#include <stdexcept>
#include <string>

namespace fleet_telemetry
{

namespace
{

std::string required(const YAML::Node & entry, const char * key, const std::string & where)
{
  if (!entry[key]) {
    throw std::runtime_error(where + ": missing " + key);
  }
  return entry[key].as<std::string>();
}

tierlink::Delivery delivery_of(const std::string & name, const std::string & where)
{
  if (name == "latest") return tierlink::Delivery::Latest;
  if (name == "reliable") return tierlink::Delivery::Reliable;
  if (name == "frame") return tierlink::Delivery::Frame;
  throw std::runtime_error(where + ": delivery must be latest, reliable or frame");
}

}  // namespace

AgentConfig parse_config(const std::string & yaml_text)
{
  const YAML::Node root = YAML::Load(yaml_text);
  AgentConfig config;
  for (const auto & s : root["streams"]) {
    const std::string where = "stream " + required(s, "name", "a stream");
    const double rate = std::stod(required(s, "rate_hz", where));
    if (rate <= 0.0) {
      throw std::runtime_error(where + ": rate_hz must be positive");
    }
    TopicStream stream{
      required(s, "name", where), required(s, "topic", where), required(s, "type", where),
      delivery_of(required(s, "delivery", where), where), rate, std::nullopt, false};
    if (s["range"]) {
      const YAML::Node r = s["range"];
      const std::string at = where + ": range";
      stream.range = RangeCodecConfig{
        std::stod(required(r, "step_m", at)), std::stod(required(r, "max_range_m", at)),
        std::stoi(required(r, "sectors", at)), std::stoi(required(r, "intensity_bits", at)), 0};
      if (stream.type != "sensor_msgs/msg/PointCloud2") {
        throw std::runtime_error(where + ": range needs type sensor_msgs/msg/PointCloud2");
      }
      if (stream.range->intensity_bits != 4 && stream.range->intensity_bits != 8) {
        throw std::runtime_error(at + ": intensity_bits must be 4 or 8");
      }
    }
    if (s["transport"]) {
      const std::string t = s["transport"].as<std::string>();
      if (t != "udp" && t != "tcp") {
        throw std::runtime_error(where + ": transport must be tcp or udp");
      }
      stream.udp = t == "udp";
    }
    config.streams.push_back(std::move(stream));
  }
  for (const auto & c : root["commands"]) {
    const std::string where = "command " + required(c, "id", "a command");
    config.commands.push_back(CommandInterface{
      required(c, "id", where), required(c, "topic", where), required(c, "type", where)});
  }
  return config;
}

}  // namespace fleet_telemetry
