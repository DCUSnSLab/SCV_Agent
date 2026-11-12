#include "command_gate.hpp"

#include <tierlink/control.hpp>
#include <tierlink/zenoh_link.hpp>

#include <chrono>
#include <condition_variable>
#include <cstdio>
#include <mutex>
#include <optional>
#include <random>
#include <string>
#include <thread>
#include <vector>

// A debugging server: sends one command and prints the vehicle's answer. The payload is CDR in hex,
// empty for std_msgs/msg/Empty-like types that carry only the CDR header.
//
// send_command <endpoint> <prefix> <interface id> <ttl ms> [payload hex]

int main(int argc, char ** argv)
{
  using fleet_telemetry::CommandStatus;
  if (argc != 5 && argc != 6) {
    std::fprintf(stderr, "usage: %s <endpoint> <prefix> <interface> <ttl ms> [hex]\n", argv[0]);
    return 2;
  }
  std::vector<std::uint8_t> payload;
  const std::string hex = argc == 6 ? argv[5] : "";
  for (std::size_t i = 0; i + 1 < hex.size(); i += 2) {
    payload.push_back(static_cast<std::uint8_t>(std::stoi(hex.substr(i, 2), nullptr, 16)));
  }
  auto session = zenoh::Session::open(tierlink::make_config("client", {argv[1]}, {}, std::nullopt));
  const std::string cmd_id = "cmd-" + std::to_string(std::random_device{}());
  std::mutex mutex;
  std::condition_variable cv;
  std::optional<CommandStatus> status;
  tierlink::ControlSubscriber results(
    session, argv[2], tierlink::Tier::Monitor, "result", [&](const std::vector<std::uint8_t> & m) {
      const auto r = fleet_telemetry::decode_result(m);
      if (r && r->cmd_id == cmd_id) {
        std::lock_guard<std::mutex> lock(mutex);
        status = r->status;
        cv.notify_one();
      }
    });
  tierlink::ControlPublisher commands(session, argv[2], tierlink::Tier::Monitor, "command");
  std::this_thread::sleep_for(std::chrono::milliseconds(500));
  const auto now = std::chrono::duration_cast<std::chrono::milliseconds>(
                     std::chrono::system_clock::now().time_since_epoch())
                     .count();
  commands.send(fleet_telemetry::encode(fleet_telemetry::Command{
    cmd_id, argv[3], static_cast<std::uint64_t>(now), std::stoull(argv[4]), payload}));
  std::unique_lock<std::mutex> lock(mutex);
  if (!cv.wait_for(lock, std::chrono::seconds(3), [&] { return status.has_value(); })) {
    std::fprintf(stderr, "no answer from the vehicle\n");
    return 1;
  }
  static const char * kNames[] = {"done", "unknown interface", "expired", "duplicate", "invalid"};
  std::printf("%s: %s\n", cmd_id.c_str(), kNames[static_cast<int>(*status)]);
  return *status == CommandStatus::Done ? 0 : 1;
}
