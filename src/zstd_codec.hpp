#ifndef ZSTD_CODEC_HPP_
#define ZSTD_CODEC_HPP_

#include <cstddef>
#include <cstdint>
#include <vector>

namespace fleet_telemetry
{

std::vector<std::uint8_t> zstd_compress(const std::uint8_t * data, std::size_t size, int level);

}  // namespace fleet_telemetry

#endif  // ZSTD_CODEC_HPP_
