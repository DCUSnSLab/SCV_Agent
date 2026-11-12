#ifndef COMMAND_GATE_HPP_
#define COMMAND_GATE_HPP_

#include "agent_config.hpp"

#include <chrono>
#include <cstdint>
#include <deque>
#include <optional>
#include <string>
#include <unordered_set>
#include <vector>

namespace fleet_telemetry
{

// A server command: publish `payload` (CDR of the interface's type) on a registered interface.
struct Command
{
  std::string cmd_id;
  std::string interface_id;
  std::uint64_t issued_unix_ms;
  std::uint64_t ttl_ms;
  std::vector<std::uint8_t> payload;
};

enum class CommandStatus : std::uint8_t { Done, Unknown, Expired, Duplicate, Invalid };

struct CommandResult
{
  std::string cmd_id;
  CommandStatus status;
};

std::vector<std::uint8_t> encode(const Command & c);
std::optional<Command> decode_command(const std::vector<std::uint8_t> & b);
std::vector<std::uint8_t> encode(const CommandResult & r);
std::optional<CommandResult> decode_result(const std::vector<std::uint8_t> & b);

// Checks in a fixed order: registered interface, time to live (no command without one, none above
// max_ttl), and a cmd_id not seen among the last `remember` commands, so a resent command runs
// once.
class CommandGate
{
public:
  CommandGate(
    const std::vector<CommandInterface> & interfaces, std::chrono::milliseconds max_ttl,
    std::size_t remember);

  struct Verdict
  {
    CommandStatus status;
    // Set only when status is Done: where to publish.
    const CommandInterface * interface;
  };
  Verdict check(const Command & c, std::uint64_t now_unix_ms);

private:
  std::vector<CommandInterface> interfaces_;
  std::chrono::milliseconds max_ttl_;
  std::size_t remember_;
  std::deque<std::string> recent_order_;
  std::unordered_set<std::string> recent_;
};

}  // namespace fleet_telemetry

#endif  // COMMAND_GATE_HPP_
