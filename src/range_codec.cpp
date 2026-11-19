#include "range_codec.hpp"

#include "zstd_codec.hpp"

#include <zstd.h>

#include <algorithm>
#include <cmath>
#include <complex>
#include <cstring>
#include <stdexcept>

namespace fleet_telemetry
{

namespace
{

constexpr double kTwoPi = 6.283185307179586;
constexpr std::uint8_t kMagic = 'R';
constexpr std::uint8_t kVersion = 1;
constexpr std::size_t kFixed = 2 + 4 + 4 + 4 * 2;

// Azimuths are stored as a fraction of a turn in 16 bits (0.0055 deg, 1 cm at 100 m).
std::uint16_t turn16(double rad)
{
  double t = std::fmod(rad / kTwoPi, 1.0);
  t = t < 0.0 ? t + 1.0 : t;
  return static_cast<std::uint16_t>(std::lround(t * 65536.0) & 0xFFFF);
}

double wrap(double rad)
{
  return std::remainder(rad, kTwoPi);
}

template <typename T>
void put(std::vector<std::uint8_t> & out, T v)
{
  std::uint8_t b[sizeof(T)];
  std::memcpy(b, &v, sizeof(T));
  out.insert(out.end(), b, b + sizeof(T));
}

template <typename T>
T get(const std::vector<std::uint8_t> & in, std::size_t & at)
{
  T v;
  std::memcpy(&v, in.data() + at, sizeof(T));
  at += sizeof(T);
  return v;
}

struct Polar
{
  double range;
  double azimuth;
  double elevation;
  bool valid;
};

double median(std::vector<double> v)
{
  if (v.empty()) {
    return 0.0;
  }
  std::nth_element(v.begin(), v.begin() + static_cast<std::ptrdiff_t>(v.size() / 2), v.end());
  return v[v.size() / 2];
}

}  // namespace

std::optional<OrganizedScan> organize(
  const std::uint8_t * data, std::size_t points, const CloudLayout & layout)
{
  const auto f32 = [&](std::size_t i, std::size_t off) {
    float v;
    std::memcpy(&v, data + i * layout.point_step + off, 4);
    return v;
  };
  const auto ring = [&](std::size_t i) {
    std::uint16_t v;
    std::memcpy(&v, data + i * layout.point_step + layout.ring, 2);
    return static_cast<std::size_t>(v);
  };
  std::size_t rings = 0;
  for (std::size_t i = 0; i < points; ++i) {
    rings = std::max(rings, ring(i) + 1);
  }
  if (rings == 0 || rings > 255 || points % rings != 0) {
    return std::nullopt;
  }
  const std::size_t columns = points / rings;
  // Ring-major clouds repeat one ring for a whole row.
  const bool column_major = points < 2 || ring(0) != ring(1);
  OrganizedScan scan{static_cast<int>(rings), std::vector<ScanPoint>(points)};
  std::vector<bool> filled(points, false);
  for (std::size_t i = 0; i < points; ++i) {
    const std::size_t col = column_major ? i / rings : i % columns;
    const std::size_t at = col * rings + ring(i);
    if (filled[at]) {
      return std::nullopt;
    }
    filled[at] = true;
    scan.points[at] = ScanPoint{
      f32(i, layout.x), f32(i, layout.y), f32(i, layout.z), f32(i, layout.intensity)};
  }
  return scan;
}

std::vector<std::vector<std::uint8_t>> encode_scan(
  const OrganizedScan & scan, std::uint32_t scan_seq, const RangeCodecConfig & config)
{
  const int rings = scan.rings;
  if (rings <= 0 || rings > 255 || scan.points.size() % static_cast<std::size_t>(rings) != 0) {
    throw std::invalid_argument("range codec: the scan is not organized in whole columns");
  }
  if (config.intensity_bits != 4 && config.intensity_bits != 8) {
    throw std::invalid_argument("range codec: intensity_bits must be 4 or 8");
  }
  const int columns = static_cast<int>(scan.points.size()) / rings;
  std::vector<Polar> polar(scan.points.size());
  for (std::size_t i = 0; i < scan.points.size(); ++i) {
    const auto & p = scan.points[i];
    const double r = std::sqrt(double(p.x) * p.x + double(p.y) * p.y + double(p.z) * p.z);
    const bool valid = std::isfinite(r) && r > 0.0 && r <= config.max_range_m;
    polar[i] = Polar{r, std::atan2(p.y, p.x), valid ? std::asin(p.z / r) : 0.0, valid};
  }
  const auto at = [rings](int col, int ring) {
    return static_cast<std::size_t>(col) * static_cast<std::size_t>(rings) +
           static_cast<std::size_t>(ring);
  };
  // The lasers of one column fire at one azimuth plus a fixed offset per laser: the column's
  // azimuth and the ring's offset rebuild every point's azimuth.
  std::vector<double> raw(columns, 0.0);
  for (int c = 0; c < columns; ++c) {
    std::complex<double> sum;
    for (int r = 0; r < rings; ++r) {
      if (polar[at(c, r)].valid) {
        sum += std::polar(1.0, polar[at(c, r)].azimuth);
      }
    }
    raw[c] = std::arg(sum);
  }
  std::vector<double> elevation(rings);
  std::vector<double> offset(rings);
  for (int r = 0; r < rings; ++r) {
    std::vector<double> el;
    std::vector<double> off;
    for (int c = 0; c < columns; ++c) {
      if (polar[at(c, r)].valid) {
        el.push_back(polar[at(c, r)].elevation);
        off.push_back(wrap(polar[at(c, r)].azimuth - raw[c]));
      }
    }
    elevation[r] = median(el);
    offset[r] = median(off);
  }
  std::vector<std::uint16_t> column_azimuth(columns);
  for (int c = 0; c < columns; ++c) {
    std::complex<double> sum;
    for (int r = 0; r < rings; ++r) {
      if (polar[at(c, r)].valid) {
        sum += std::polar(1.0, polar[at(c, r)].azimuth - offset[r]);
      }
    }
    column_azimuth[c] = turn16(std::abs(sum) > 0.0 ? std::arg(sum) : raw[c]);
  }

  const int sectors = std::clamp(config.sectors, 1, std::max(columns, 1));
  const auto step_01mm = static_cast<std::uint16_t>(std::lround(config.step_m * 1e4));
  std::vector<std::vector<std::uint8_t>> out;
  for (int s = 0; s < sectors; ++s) {
    const int first = columns * s / sectors;
    const int last = columns * (s + 1) / sectors;
    const int count = last - first;
    std::vector<std::uint8_t> body;
    // Ranges as differences along each ring, which zstd packs well.
    for (int r = 0; r < rings; ++r) {
      std::int32_t previous = 0;
      for (int c = first; c < last; ++c) {
        const Polar & p = polar[at(c, r)];
        const std::int32_t q =
          p.valid ? static_cast<std::int32_t>(std::lround(p.range / config.step_m)) : 0;
        put<std::int16_t>(body, static_cast<std::int16_t>(q - previous));
        previous = q;
      }
    }
    std::uint8_t pending = 0;
    std::size_t n = 0;
    for (int r = 0; r < rings; ++r) {
      for (int c = first; c < last; ++c) {
        const Polar & p = polar[at(c, r)];
        const float raw_i = scan.points[at(c, r)].intensity;
        const auto i8 = static_cast<std::uint8_t>(
          p.valid && std::isfinite(raw_i) ? std::clamp(std::lround(raw_i), 0L, 255L) : 0);
        if (config.intensity_bits == 8) {
          body.push_back(i8);
        } else if (n++ % 2 == 0) {
          pending = i8 >> 4;
        } else {
          body.push_back(static_cast<std::uint8_t>(pending | (i8 & 0xF0)));
        }
      }
    }
    if (config.intensity_bits == 4 && n % 2 == 1) {
      body.push_back(pending);
    }
    for (int c = first; c < last; ++c) {
      put<std::uint16_t>(body, column_azimuth[c]);
    }

    std::vector<std::uint8_t> item{kMagic, kVersion};
    put<std::uint32_t>(item, scan_seq);
    item.push_back(static_cast<std::uint8_t>(s));
    item.push_back(static_cast<std::uint8_t>(sectors));
    item.push_back(static_cast<std::uint8_t>(rings));
    item.push_back(static_cast<std::uint8_t>(config.intensity_bits));
    put<std::uint16_t>(item, static_cast<std::uint16_t>(columns));
    put<std::uint16_t>(item, static_cast<std::uint16_t>(first));
    put<std::uint16_t>(item, static_cast<std::uint16_t>(count));
    put<std::uint16_t>(item, step_01mm);
    for (int r = 0; r < rings; ++r) {
      put<float>(item, static_cast<float>(elevation[r]));
      put<std::int16_t>(item, static_cast<std::int16_t>(std::lround(offset[r] / kTwoPi * 65536.0)));
    }
    const auto packed = zstd_compress(body.data(), body.size(), config.zstd_level);
    item.insert(item.end(), packed.begin(), packed.end());
    out.push_back(std::move(item));
  }
  return out;
}

std::optional<DecodedSector> decode_sector(const std::vector<std::uint8_t> & bytes)
{
  if (bytes.size() < kFixed || bytes[0] != kMagic || bytes[1] != kVersion) {
    return std::nullopt;
  }
  std::size_t at = 2;
  DecodedSector d;
  d.scan_seq = get<std::uint32_t>(bytes, at);
  d.sector = bytes[at++];
  d.sectors = bytes[at++];
  const int rings = bytes[at++];
  const int intensity_bits = bytes[at++];
  get<std::uint16_t>(bytes, at);
  get<std::uint16_t>(bytes, at);
  const int count = get<std::uint16_t>(bytes, at);
  const double step = get<std::uint16_t>(bytes, at) / 1e4;
  if (bytes.size() < at + static_cast<std::size_t>(rings) * 6) {
    return std::nullopt;
  }
  std::vector<double> elevation(rings);
  std::vector<double> offset(rings);
  for (int r = 0; r < rings; ++r) {
    elevation[r] = get<float>(bytes, at);
    offset[r] = get<std::int16_t>(bytes, at) / 65536.0 * kTwoPi;
  }
  const std::size_t cells = static_cast<std::size_t>(rings) * static_cast<std::size_t>(count);
  const std::size_t intensity_bytes = intensity_bits == 8 ? cells : (cells + 1) / 2;
  const std::size_t body_size = cells * 2 + intensity_bytes + static_cast<std::size_t>(count) * 2;
  std::vector<std::uint8_t> body(body_size);
  const std::size_t got =
    ZSTD_decompress(body.data(), body.size(), bytes.data() + at, bytes.size() - at);
  if (ZSTD_isError(got) || got != body_size) {
    return std::nullopt;
  }
  std::size_t b = 0;
  std::vector<std::int32_t> range(cells);
  for (int r = 0; r < rings; ++r) {
    std::int32_t q = 0;
    for (int c = 0; c < count; ++c) {
      q += get<std::int16_t>(body, b);
      range[static_cast<std::size_t>(r) * count + c] = q;
    }
  }
  std::vector<std::uint8_t> intensity(cells);
  for (std::size_t i = 0; i < cells; ++i) {
    intensity[i] = intensity_bits == 8 ? body[b + i]
                   : i % 2 == 0        ? static_cast<std::uint8_t>(body[b + i / 2] << 4)
                                       : static_cast<std::uint8_t>(body[b + i / 2] & 0xF0);
  }
  b += intensity_bytes;
  std::vector<double> column(count);
  for (int c = 0; c < count; ++c) {
    column[c] = get<std::uint16_t>(body, b) / 65536.0 * kTwoPi;
  }
  // Column after column, as the scan came in.
  for (int c = 0; c < count; ++c) {
    for (int r = 0; r < rings; ++r) {
      const std::size_t i = static_cast<std::size_t>(r) * count + c;
      if (range[i] == 0) {
        continue;
      }
      const double rr = range[i] * step;
      const double a = column[c] + offset[r];
      const double ce = std::cos(elevation[r]);
      d.points.push_back(ScanPoint{
        static_cast<float>(rr * ce * std::cos(a)), static_cast<float>(rr * ce * std::sin(a)),
        static_cast<float>(rr * std::sin(elevation[r])), static_cast<float>(intensity[i])});
    }
  }
  return d;
}

}  // namespace fleet_telemetry
