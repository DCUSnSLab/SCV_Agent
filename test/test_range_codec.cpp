#include "range_codec.hpp"

#include <gtest/gtest.h>

#include <algorithm>
#include <cmath>
#include <stdexcept>
#include <cstdint>
#include <limits>
#include <vector>

using fleet_telemetry::OrganizedScan;
using fleet_telemetry::RangeCodecConfig;
using fleet_telemetry::ScanPoint;

namespace
{

constexpr int kRings = 32;
constexpr int kColumns = 1800;
constexpr RangeCodecConfig kConfig{0.02, 120.0, 8, 8, 3};

// A 32-laser scan in a room-like box: lasers with their own elevation and azimuth offset fire
// together each column; laser 15 never returns and every 7th column of laser 3 is missing.
OrganizedScan scan()
{
  OrganizedScan s{kRings, {}};
  for (int c = 0; c < kColumns; ++c) {
    const double column = 2.0 * M_PI * c / kColumns + 0.0003 * std::sin(c * 0.01);
    for (int r = 0; r < kRings; ++r) {
      const double el = (-25.0 + 40.0 * r / (kRings - 1)) * M_PI / 180.0;
      const double az = column + 0.02 * (r % 4 - 1.5);
      const double range = 5.0 + 3.0 * std::fabs(std::sin(az * 2.0)) + 0.1 * r;
      if (r == 15 || (r == 3 && c % 7 == 0)) {
        const float nan = std::numeric_limits<float>::quiet_NaN();
        s.points.push_back(ScanPoint{nan, nan, nan, nan});
        continue;
      }
      s.points.push_back(ScanPoint{
        static_cast<float>(range * std::cos(el) * std::cos(az)),
        static_cast<float>(range * std::cos(el) * std::sin(az)),
        static_cast<float>(range * std::sin(el)), static_cast<float>((c + r) % 256)});
    }
  }
  return s;
}

}  // namespace

TEST(RangeCodec, EverySectorDecodesAloneAndThePointsComeBackWithinTheStep)
{
  const OrganizedScan s = scan();
  const auto sectors = fleet_telemetry::encode_scan(s, 42, kConfig);
  ASSERT_EQ(sectors.size(), 8u);
  std::vector<ScanPoint> valid;
  for (const auto & p : s.points) {
    if (std::isfinite(p.x)) {
      valid.push_back(p);
    }
  }
  std::size_t total = 0;
  double worst = 0.0;
  std::size_t bytes = 0;
  for (std::size_t i = 0; i < sectors.size(); ++i) {
    bytes += sectors[i].size();
    const auto d = fleet_telemetry::decode_sector(sectors[i]);
    ASSERT_TRUE(d);
    EXPECT_EQ(d->scan_seq, 42u);
    EXPECT_EQ(d->sector, static_cast<int>(i));
    EXPECT_EQ(d->sectors, 8);
    for (std::size_t k = 0; k < d->points.size(); ++k) {
      const auto & a = d->points[k];
      const auto & b = valid[total + k];
      worst = std::max<double>(
        worst, std::sqrt((a.x - b.x) * (a.x - b.x) + (a.y - b.y) * (a.y - b.y) +
                         (a.z - b.z) * (a.z - b.z)));
      EXPECT_EQ(a.intensity, b.intensity);
    }
    total += d->points.size();
  }
  EXPECT_EQ(total, valid.size());
  // Half a range step, plus the 16-bit azimuth and the float elevation at 10 m.
  EXPECT_LT(worst, 0.015);
  // Raw XYZI is 16 bytes a point.
  EXPECT_LT(bytes, valid.size() * 16 / 4);
}

TEST(RangeCodec, FourBitIntensityKeepsTheUpperBits)
{
  auto config = kConfig;
  config.intensity_bits = 4;
  config.sectors = 3;
  const OrganizedScan s = scan();
  const auto d = fleet_telemetry::decode_sector(fleet_telemetry::encode_scan(s, 1, config)[0]);
  ASSERT_TRUE(d);
  std::vector<float> intensity;
  for (const auto & p : s.points) {
    if (std::isfinite(p.x)) {
      intensity.push_back(p.intensity);
    }
  }
  for (std::size_t i = 0; i < d->points.size(); ++i) {
    ASSERT_EQ(d->points[i].intensity, static_cast<float>(static_cast<int>(intensity[i]) & 0xF0));
  }
}

TEST(RangeCodec, RefusesAScanThatIsNotWholeColumnsAndGarbage)
{
  OrganizedScan s{kRings, std::vector<ScanPoint>(kRings * 3 + 1)};
  EXPECT_THROW(fleet_telemetry::encode_scan(s, 0, kConfig), std::invalid_argument);
  EXPECT_FALSE(fleet_telemetry::decode_sector({'R', 1, 0}));
  auto item = fleet_telemetry::encode_scan(scan(), 0, kConfig)[0];
  item.resize(item.size() - 3);
  EXPECT_FALSE(fleet_telemetry::decode_sector(item));
}
