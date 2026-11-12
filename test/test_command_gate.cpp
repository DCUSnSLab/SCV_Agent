#include "command_gate.hpp"

#include <gtest/gtest.h>

#include <chrono>
#include <vector>

using fleet_telemetry::Command;
using fleet_telemetry::CommandGate;
using fleet_telemetry::CommandStatus;

namespace
{

CommandGate gate()
{
  return CommandGate({{"stop", "/teleop/stop", "std_msgs/msg/Empty"}}, std::chrono::seconds(10), 2);
}

Command command(const char * id, std::uint64_t issued, std::uint64_t ttl = 5000)
{
  return Command{id, "stop", issued, ttl, {1, 2, 3}};
}

}  // namespace

TEST(Command, RoundTripsAndRefusesTruncatedOrForeignVersions)
{
  const Command c = command("c1", 1000);
  const auto back = fleet_telemetry::decode_command(fleet_telemetry::encode(c));
  ASSERT_TRUE(back);
  EXPECT_EQ(back->cmd_id, "c1");
  EXPECT_EQ(back->ttl_ms, 5000u);
  EXPECT_EQ(back->payload, (std::vector<std::uint8_t>{1, 2, 3}));
  auto bytes = fleet_telemetry::encode(c);
  bytes.pop_back();
  EXPECT_FALSE(fleet_telemetry::decode_command(bytes));
  bytes = fleet_telemetry::encode(c);
  bytes[0] = 9;
  EXPECT_FALSE(fleet_telemetry::decode_command(bytes));
  const auto result = fleet_telemetry::decode_result(
    fleet_telemetry::encode(fleet_telemetry::CommandResult{"c1", CommandStatus::Expired}));
  ASSERT_TRUE(result);
  EXPECT_EQ(result->status, CommandStatus::Expired);
}

TEST(CommandGate, ChecksInterfaceTtlAndDuplicatesInOrder)
{
  auto g = gate();
  const auto ok = g.check(command("c1", 1000), 2000);
  EXPECT_EQ(ok.status, CommandStatus::Done);
  ASSERT_NE(ok.interface, nullptr);
  EXPECT_EQ(ok.interface->topic, "/teleop/stop");

  auto unknown = command("c2", 1000);
  unknown.interface_id = "drive";
  EXPECT_EQ(g.check(unknown, 2000).status, CommandStatus::Unknown);
  EXPECT_EQ(g.check(command("c3", 1000, 0), 2000).status, CommandStatus::Invalid);
  EXPECT_EQ(g.check(command("c4", 1000, 20000), 2000).status, CommandStatus::Invalid);
  EXPECT_EQ(g.check(command("c5", 1000), 7000).status, CommandStatus::Expired);
  EXPECT_EQ(g.check(command("c1", 1000), 2000).status, CommandStatus::Duplicate);
}

TEST(CommandGate, ForgetsOnlyBeyondItsMemory)
{
  auto g = gate();
  g.check(command("a", 1000), 1000);
  g.check(command("b", 1000), 1000);
  EXPECT_EQ(g.check(command("a", 1000), 1000).status, CommandStatus::Duplicate);
  g.check(command("c", 1000), 1000);
  EXPECT_EQ(g.check(command("a", 1000), 1000).status, CommandStatus::Done);
}
