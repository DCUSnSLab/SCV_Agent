#include "agent.hpp"

#include "zstd_codec.hpp"

#include <rclcpp_components/register_node_macro.hpp>

#include <chrono>
#include <cstring>
#include <fstream>
#include <sstream>
#include <utility>

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

}  // namespace

Agent::Agent(const rclcpp::NodeOptions & options)
: Node("fleet_telemetry", options),
  zstd_level_(declare_parameter<int>("zstd_level")),
  session_(
    zenoh::Session::open(
      tierlink::make_config(
        "client", declare_parameter<std::vector<std::string>>("link.connect"), {}, std::nullopt))),
  allowance_(milliseconds(declare_parameter<int>("link.allowance_expires_ms")))
{
  const std::string prefix = declare_parameter<std::string>("link.prefix");
  const AgentConfig config =
    parse_config(read_file(declare_parameter<std::string>("streams_file")));
  std::vector<tierlink::StreamSpec> specs;
  for (const auto & s : config.streams) {
    specs.push_back(tierlink::StreamSpec{s.name, tierlink::Tier::Monitor, s.delivery, false, 64});
    const char * delivery = s.delivery == tierlink::Delivery::Reliable ? "reliable"
                            : s.delivery == tierlink::Delivery::Frame  ? "frame"
                                                                       : "latest";
    catalog_ += s.name + "\t" + s.type + "\t" + s.topic + "\t" + delivery + "\n";
  }
  uplink_ = std::make_unique<tierlink::Uplink>(
    session_,
    tierlink::UplinkConfig{
      prefix, tierlink::Tier::Monitor, std::move(specs),
      milliseconds(declare_parameter<int>("link.tick_ms")),
      milliseconds(declare_parameter<int>("link.burst_ms")),
      milliseconds(declare_parameter<int>("link.delay_window_ms"))},
    std::make_unique<tierlink::Aimd>(aimd_config(*this)));
  alive_.emplace(
    session_.liveliness_declare_token(zenoh::KeyExpr(tierlink::alive_key(prefix, "fleet_telemetry"))));
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
    milliseconds(declare_parameter<int>("link.cap_update_ms")), [this] { on_timer(); });
  allowance_sub_.emplace(
    session_, prefix, monitor, tierlink::kAllowanceName,
    [this](const std::vector<std::uint8_t> & m) {
      const auto bps = tierlink::decode_bps(m);
      if (bps) {
        std::lock_guard<std::mutex> lock(mutex_);
        allowance_.update(*bps, tierlink::steady_now());
      }
    });
  command_sub_.emplace(
    session_, prefix, monitor, "command",
    [this](const std::vector<std::uint8_t> & m) { on_command(m); });
}

void Agent::subscribe_streams(const AgentConfig & config)
{
  for (std::size_t i = 0; i < config.streams.size(); ++i) {
    const auto & s = config.streams[i];
    gates_.emplace_back(
      std::chrono::duration_cast<nanoseconds>(std::chrono::duration<double>(1.0 / s.rate_hz)));
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
  std::optional<std::uint64_t> cap;
  {
    std::lock_guard<std::mutex> lock(mutex_);
    cap = allowance_.cap(tierlink::steady_now());
  }
  uplink_->set_cap(cap);
  catalog_pub_->send(std::vector<std::uint8_t>(catalog_.begin(), catalog_.end()));
}

}  // namespace fleet_telemetry

RCLCPP_COMPONENTS_REGISTER_NODE(fleet_telemetry::Agent)
