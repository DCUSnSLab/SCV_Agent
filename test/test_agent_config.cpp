#include "agent_config.hpp"
#include "rate_gate.hpp"
#include "zstd_codec.hpp"

#include <gtest/gtest.h>
#include <zstd.h>

#include <chrono>
#include <stdexcept>
#include <vector>

TEST(AgentConfig, ReadsStreamsAndCommands)
{
  const auto c = fleet_telemetry::parse_config(R"(
streams:
  - {name: odom, topic: /odom, type: nav_msgs/msg/Odometry, delivery: latest, rate_hz: 2}
  - {name: alerts, topic: /diagnostics, type: diagnostic_msgs/msg/DiagnosticArray,
     delivery: reliable, rate_hz: 10}
commands:
  - {id: stop, topic: /teleop/stop, type: std_msgs/msg/Empty}
)");
  ASSERT_EQ(c.streams.size(), 2u);
  EXPECT_EQ(c.streams[0].type, "nav_msgs/msg/Odometry");
  EXPECT_EQ(c.streams[1].delivery, tierlink::Delivery::Reliable);
  EXPECT_EQ(c.streams[0].rate_hz, 2.0);
  ASSERT_EQ(c.commands.size(), 1u);
  EXPECT_EQ(c.commands[0].topic, "/teleop/stop");
}

TEST(AgentConfig, NamesTheWrongEntry)
{
  try {
    fleet_telemetry::parse_config("streams:\n  - {name: odom, topic: /odom, rate_hz: 2}\n");
    FAIL();
  } catch (const std::runtime_error & e) {
    EXPECT_STREQ(e.what(), "stream odom: missing type");
  }
  EXPECT_THROW(
    fleet_telemetry::parse_config(
      "streams:\n  - {name: a, topic: /a, type: t, delivery: sometimes, rate_hz: 1}\n"),
    std::runtime_error);
}

TEST(RateGate, PassesOncePerPeriod)
{
  fleet_telemetry::RateGate g(std::chrono::milliseconds(500));
  EXPECT_TRUE(g.pass(std::chrono::milliseconds(0)));
  EXPECT_FALSE(g.pass(std::chrono::milliseconds(33)));
  EXPECT_FALSE(g.pass(std::chrono::milliseconds(499)));
  EXPECT_TRUE(g.pass(std::chrono::milliseconds(500)));
}

TEST(Zstd, RoundTrips)
{
  const std::vector<std::uint8_t> in(4096, 7);
  const auto packed = fleet_telemetry::zstd_compress(in.data(), in.size(), 3);
  EXPECT_LT(packed.size(), in.size() / 10);
  std::vector<std::uint8_t> out(in.size());
  EXPECT_EQ(ZSTD_decompress(out.data(), out.size(), packed.data(), packed.size()), in.size());
  EXPECT_EQ(out, in);
}
