#ifndef RANGE_CODEC_HPP_
#define RANGE_CODEC_HPP_

#include <cstddef>
#include <cstdint>
#include <optional>
#include <vector>

namespace fleet_telemetry
{

// A spinning lidar scan as a range image, cut into sectors of whole columns that each decode
// alone: a sector lost on the way leaves a gap instead of losing the scan.
inline constexpr const char * kRangeSectorType = "fleet_telemetry/RangeSector";

struct RangeCodecConfig
{
  double step_m;
  double max_range_m;
  int sectors;
  // 8 keeps the sensor's value; 4 keeps the upper half and saves about a fifth of the size.
  int intensity_bits;
  int zstd_level;
};

struct ScanPoint
{
  float x;
  float y;
  float z;
  float intensity;
};

// An organized scan (velodyne_pointcloud with organize_cloud): `rings` points per column, column
// after column, missing points as NaN.
struct OrganizedScan
{
  int rings;
  std::vector<ScanPoint> points;
};

// Field offsets in a PointCloud2 point: float32 x, y, z, intensity and uint16 ring.
struct CloudLayout
{
  std::size_t point_step;
  std::size_t x;
  std::size_t y;
  std::size_t z;
  std::size_t intensity;
  std::size_t ring;
};

// By the ring field, whether the cloud lists a column's rings together (velodyne_pointcloud) or
// each ring's columns together. Empty unless the rings form whole columns.
std::optional<OrganizedScan> organize(
  const std::uint8_t * data, std::size_t points, const CloudLayout & layout);

std::vector<std::vector<std::uint8_t>> encode_scan(
  const OrganizedScan & scan, std::uint32_t scan_seq, const RangeCodecConfig & config);

struct DecodedSector
{
  std::uint32_t scan_seq;
  int sector;
  int sectors;
  std::vector<ScanPoint> points;
};

std::optional<DecodedSector> decode_sector(const std::vector<std::uint8_t> & bytes);

}  // namespace fleet_telemetry

#endif  // RANGE_CODEC_HPP_
