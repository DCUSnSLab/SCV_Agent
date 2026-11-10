#include "zstd_codec.hpp"

#include <zstd.h>

#include <stdexcept>
#include <string>

namespace fleet_telemetry
{

std::vector<std::uint8_t> zstd_compress(const std::uint8_t * data, std::size_t size, int level)
{
  std::vector<std::uint8_t> out(ZSTD_compressBound(size));
  const std::size_t n = ZSTD_compress(out.data(), out.size(), data, size, level);
  if (ZSTD_isError(n)) {
    throw std::runtime_error(std::string("zstd: ") + ZSTD_getErrorName(n));
  }
  out.resize(n);
  return out;
}

}  // namespace fleet_telemetry
