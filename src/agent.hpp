#ifndef AGENT_HPP_
#define AGENT_HPP_

#include "agent_config.hpp"
#include "command_gate.hpp"
#include "rate_gate.hpp"

#include <rclcpp/rclcpp.hpp>
#include <tierlink/control.hpp>
#include <tierlink/scheduler.hpp>
#include <tierlink/zenoh_link.hpp>

#include <map>
#include <memory>
#include <mutex>
#include <optional>
#include <string>
#include <vector>

namespace fleet_telemetry
{

// The vehicle's monitoring agent: chosen ROS topics to the server on tierlink's monitor tier, and
// registered server commands back to ROS. It stays within the budget the teleop process
// publishes, and runs on its own controller while that budget is absent.
class Agent : public rclcpp::Node
{
public:
  explicit Agent(const rclcpp::NodeOptions & options);

private:
  void subscribe_streams(const AgentConfig & config);
  void on_command(const std::vector<std::uint8_t> & message);
  void on_timer();

  int zstd_level_;
  std::string catalog_;
  zenoh::Session session_;
  std::unique_ptr<tierlink::Uplink> uplink_;
  std::optional<zenoh::LivelinessToken> alive_;
  std::vector<RateGate> gates_;
  std::vector<rclcpp::GenericSubscription::SharedPtr> subscriptions_;
  std::map<std::string, rclcpp::GenericPublisher::SharedPtr> command_publishers_;
  std::unique_ptr<tierlink::ControlPublisher> catalog_pub_;
  std::unique_ptr<tierlink::ControlPublisher> result_pub_;
  rclcpp::TimerBase::SharedPtr timer_;

  // The link manager's budget for the monitor tier; the Uplink's controller follows it while fresh.
  std::shared_ptr<tierlink::BudgetSlot> budget_;
  // Commands arrive on Zenoh threads.
  std::mutex mutex_;
  std::optional<CommandGate> gate_;
  // Declared last, so they are undeclared first and no callback outlives the members above.
  std::optional<tierlink::BudgetSubscriber> budget_sub_;
  std::optional<tierlink::ControlSubscriber> command_sub_;
};

}  // namespace fleet_telemetry

#endif  // AGENT_HPP_
