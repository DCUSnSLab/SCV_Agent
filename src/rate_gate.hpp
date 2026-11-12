#ifndef RATE_GATE_HPP_
#define RATE_GATE_HPP_

#include <chrono>
#include <optional>

namespace fleet_telemetry
{

// Lets messages through at most once per period. Decided before anything is copied, so a camera
// at 30 Hz thinned to 1 Hz costs one copy a second, not thirty.
class RateGate
{
public:
  explicit RateGate(std::chrono::nanoseconds period) : period_(period) {}

  bool pass(std::chrono::nanoseconds now)
  {
    if (last_ && now - *last_ < period_) {
      return false;
    }
    last_ = now;
    return true;
  }

private:
  std::chrono::nanoseconds period_;
  std::optional<std::chrono::nanoseconds> last_;
};

}  // namespace fleet_telemetry

#endif  // RATE_GATE_HPP_
