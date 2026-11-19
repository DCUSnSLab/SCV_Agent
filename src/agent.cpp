#include "agent.hpp"

#include "zstd_codec.hpp"

#include <rclcpp/serialization.hpp>
#include <rclcpp_components/register_node_macro.hpp>
#include <sensor_msgs/msg/point_cloud2.hpp>

#include <chrono>
#include <cstring>
#include <fstream>
#include <memory>
#include <sstream>
#include <string>
#include <utility>
#include <vector>

namespace fleet_telemetry
{

namespace
{

using std::chrono::milliseconds;
using std::chrono::nanoseconds;

std::string read_file(const std::string & path)
{
  std::ifstream in(path);
  if (!in) {
    throw std::runtime_error("cannot read " + path);
  }
  std::stringstream s;
  s << in.rdbuf();
  return s.str();
}

std::uint64_t unix_ms()
{
  return static_cast<std::uint64_t>(
    std::chrono::duration_cast<milliseconds>(std::chrono::system_clock::now().time_since_epoch())
      .count());
}

tierlink::AimdConfig aimd_config(rclcpp::Node & node)
{
  const auto kbps = [&node](const char * name) {
    return static_cast<std::uint64_t>(node.declare_parameter<int>(name)) * 1000;
  };
  const auto ms = [&node](const char * name) {
    return nanoseconds(milliseconds(node.declare_parameter<int>(name)));
  };
  return tierlink::AimdConfig{
    kbps("rate.start_kbps"),
    kbps("rate.min_kbps"),
    kbps("rate.max_kbps"),
    kbps("rate.step_kbps"),
    node.declare_parameter<double>("rate.factor"),
    ms("rate.hold_ms"),
    ms("rate.probe_ms"),
    ms("rate.congested_above_ms"),
    ms("rate.clear_below_ms")};
}

std::optional<CloudLayout> layout_of(const sensor_msgs::msg::PointCloud2 & cloud)
{
  CloudLayout l{cloud.point_step, 0, 0, 0, 0, 0};
  int found = 0;
  for (const auto & f : cloud.fields) {
    const bool f32 = f.datatype == sensor_msgs::msg::PointField::FLOAT32;
    for (auto [name, offset] : {std::pair<const char *, std::size_t *>{"x", &l.x},
                                {"y", &l.y}, {"z", &l.z}, {"intensity", &l.intensity}}) {
      if (f.name == name && f32) {
        *offset = f.offset;
        ++found;
      }
    }
    if (f.name == "ring" && f.datatype == sensor_msgs::msg::PointField::UINT16) {
      l.ring = f.offset;
      ++found;
    }
  }
  if (found != 5 || cloud.is_bigendian) {
    return std::nullopt;
  }
  return l;
}

}  // namespace

Agent::Agent(const rclcpp::NodeOptions & options)
: Node("fleet_telemetry", options),
  zstd_level_(declare_parameter<int>("zstd_level")),
  session_(zenoh::Session::open(tierlink::make_config(
    "client", declare_parameter<std::vector<std::string>>("link.connect"), {}, std::nullopt))),
  budget_(std::make_shared<tierlink::BudgetSlot>())
{
  const std::string prefix = declare_parameter<std::string>("link.prefix");
  const AgentConfig config =
    parse_config(read_file(declare_parameter<std::string>("streams_file")));
  const auto udp_chunk = static_cast<std::size_t>(declare_parameter<int>("link.udp_chunk_bytes"));
  const auto fec_group = static_cast<std::uint8_t>(declare_parameter<int>("link.fec_group"));
  std::vector<tierlink::StreamSpec> specs;
  for (const auto & s : config.streams) {
    // A scan's sectors queue behind each other; older scans give way to newer ones.
    const std::size_t capacity = s.range ? static_cast<std::size_t>(2 * s.range->sectors) : 64;
    tierlink::StreamSpec spec{s.name, tierlink::Tier::Monitor, s.delivery, false, capacity};
    if (s.udp) {
      spec.best_effort = true;
      spec.chunk_bytes = udp_chunk;
      spec.fec_group = fec_group;
    }
    specs.push_back(spec);
    const char * delivery = s.delivery == tierlink::Delivery::Reliable ? "reliable"
                            : s.delivery == tierlink::Delivery::Frame  ? "frame"
                                                                       : "latest";
    // The server stores what arrives under this type; a range-coded scan is not CDR.
    const std::string sent_type = s.range ? std::string(kRangeSectorType) : s.type;
    catalog_ += s.name + "\t" + sent_type + "\t" + s.topic + "\t" + delivery + "\n";
  }
  uplink_ = std::make_unique<tierlink::Uplink>(
    session_,
    tierlink::UplinkConfig{
      prefix, tierlink::Tier::Monitor, std::move(specs),
      milliseconds(declare_parameter<int>("link.tick_ms")),
      milliseconds(declare_parameter<int>("link.burst_ms")),
      milliseconds(declare_parameter<int>("link.delay_window_ms")),
      milliseconds(declare_parameter<int>("link.report_ms")),
      static_cast<std::size_t>(declare_parameter<int>("link.chunk_bytes"))},
    std::make_unique<tierlink::Budgeted>(
      budget_, std::make_unique<tierlink::Aimd>(aimd_config(*this)),
      milliseconds(declare_parameter<int>("link.budget_expires_ms"))));
  alive_.emplace(session_.liveliness_declare_token(
    zenoh::KeyExpr(tierlink::alive_key(prefix, "fleet_telemetry"))));
  subscribe_streams(config);
  for (const auto & c : config.commands) {
    command_publishers_[c.id] = create_generic_publisher(c.topic, c.type, rclcpp::QoS(10));
  }
  gate_.emplace(
    config.commands, milliseconds(declare_parameter<int>("command.max_ttl_ms")),
    static_cast<std::size_t>(declare_parameter<int>("command.remember")));
  const auto monitor = tierlink::Tier::Monitor;
  catalog_pub_ = std::make_unique<tierlink::ControlPublisher>(session_, prefix, monitor, "catalog");
  result_pub_ = std::make_unique<tierlink::ControlPublisher>(session_, prefix, monitor, "result");
  timer_ = create_wall_timer(
    milliseconds(declare_parameter<int>("link.catalog_ms")), [this] { on_timer(); });
  budget_sub_.emplace(session_, prefix, monitor, budget_);
  command_sub_.emplace(
    session_, prefix, monitor, "command",
    [this](const std::vector<std::uint8_t> & m) { on_command(m); });
}

void Agent::subscribe_streams(const AgentConfig & config)
{
  scans_.assign(config.streams.size(), 0);
  for (std::size_t i = 0; i < config.streams.size(); ++i) {
    const auto & s = config.streams[i];
    gates_.emplace_back(
      std::chrono::duration_cast<nanoseconds>(std::chrono::duration<double>(1.0 / s.rate_hz)));
    if (s.range) {
      subscribe_scan(i, s);
      continue;
    }
    const std::size_t id = *uplink_->stream_id(s.name);
    subscriptions_.push_back(create_generic_subscription(
      s.topic, s.type, rclcpp::SensorDataQoS(),
      [this, i, id](std::shared_ptr<const rclcpp::SerializedMessage> msg) {
        if (!gates_[i].pass(tierlink::steady_now())) {
          return;
        }
        const auto & raw = msg->get_rcl_serialized_message();
        uplink_->push(id, zstd_compress(raw.buffer, raw.buffer_length, zstd_level_), false);
      }));
  }
}

void Agent::subscribe_scan(std::size_t i, const TopicStream & s)
{
  RangeCodecConfig codec = *s.range;
  codec.zstd_level = zstd_level_;
  const std::size_t id = *uplink_->stream_id(s.name);
  subscriptions_.push_back(create_generic_subscription(
    s.topic, s.type, rclcpp::SensorDataQoS(),
    [this, i, id, codec](std::shared_ptr<const rclcpp::SerializedMessage> msg) {
      if (!gates_[i].pass(tierlink::steady_now())) {
        return;
      }
      sensor_msgs::msg::PointCloud2 cloud;
      rclcpp::Serialization<sensor_msgs::msg::PointCloud2>().deserialize_message(msg.get(), &cloud);
      const auto layout = layout_of(cloud);
      const auto scan = layout ? organize(cloud.data.data(), cloud.width * cloud.height, *layout)
                               : std::nullopt;
      if (!scan) {
        RCLCPP_WARN_ONCE(
          get_logger(), "%s: needs an organized cloud with float x, y, z, intensity and uint16 ring",
          cloud.header.frame_id.c_str());
        return;
      }
      for (auto & sector : encode_scan(*scan, scans_[i]++, codec)) {
        uplink_->push(id, std::move(sector), false);
      }
    }));
}

void Agent::on_command(const std::vector<std::uint8_t> & message)
{
  const auto command = decode_command(message);
  if (!command) {
    return;
  }
  CommandGate::Verdict verdict{};
  {
    std::lock_guard<std::mutex> lock(mutex_);
    verdict = gate_->check(*command, unix_ms());
  }
  if (verdict.status == CommandStatus::Done) {
    rclcpp::SerializedMessage out(command->payload.size());
    auto & raw = out.get_rcl_serialized_message();
    std::memcpy(raw.buffer, command->payload.data(), command->payload.size());
    raw.buffer_length = command->payload.size();
    command_publishers_.at(verdict.interface->id)->publish(out);
  }
  result_pub_->send(encode(CommandResult{command->cmd_id, verdict.status}));
  RCLCPP_INFO(
    get_logger(), "command %s on %s: %d", command->cmd_id.c_str(), command->interface_id.c_str(),
    static_cast<int>(verdict.status));
}

void Agent::on_timer()
{
  catalog_pub_->send(std::vector<std::uint8_t>(catalog_.begin(), catalog_.end()));
}

}  // namespace fleet_telemetry

RCLCPP_COMPONENTS_REGISTER_NODE(fleet_telemetry::Agent)
