#include "command_gate.hpp"

#include <string>
#include <utility>
#include <vector>

namespace fleet_telemetry
{

namespace
{

constexpr std::uint8_t kVersion = 1;

void put_u64(std::vector<std::uint8_t> & out, std::uint64_t v)
{
  for (int i = 0; i < 8; ++i) {
    out.push_back(static_cast<std::uint8_t>(v >> (8 * i)));
  }
}

void put_bytes(std::vector<std::uint8_t> & out, const std::uint8_t * data, std::size_t n)
{
  put_u64(out, n);
  out.insert(out.end(), data, data + n);
}

void put_str(std::vector<std::uint8_t> & out, const std::string & s)
{
  put_bytes(out, reinterpret_cast<const std::uint8_t *>(s.data()), s.size());
}

// Every read checks the length; ok() is false once one ran past the end.
class Reader
{
public:
  explicit Reader(const std::vector<std::uint8_t> & b) : b_(b), ok_(!b.empty() && b[0] == kVersion)
  {
  }
  std::uint64_t u64()
  {
    if (!need(8)) {
      return 0;
    }
    std::uint64_t v = 0;
    for (int i = 0; i < 8; ++i) {
      v |= static_cast<std::uint64_t>(b_[at_ + i]) << (8 * i);
    }
    at_ += 8;
    return v;
  }
  std::uint8_t u8() { return need(1) ? b_[at_++] : 0; }
  std::vector<std::uint8_t> bytes()
  {
    const std::uint64_t n = u64();
    if (!need(n)) {
      return {};
    }
    std::vector<std::uint8_t> out(b_.begin() + at_, b_.begin() + at_ + n);
    at_ += n;
    return out;
  }
  std::string str()
  {
    const auto v = bytes();
    return std::string(v.begin(), v.end());
  }
  bool ok() const { return ok_ && at_ == b_.size(); }

private:
  bool need(std::uint64_t n)
  {
    ok_ = ok_ && n <= b_.size() - at_;
    return ok_;
  }
  const std::vector<std::uint8_t> & b_;
  bool ok_;
  std::size_t at_ = 1;
};

}  // namespace

std::vector<std::uint8_t> encode(const Command & c)
{
  std::vector<std::uint8_t> out{kVersion};
  put_str(out, c.cmd_id);
  put_str(out, c.interface_id);
  put_u64(out, c.issued_unix_ms);
  put_u64(out, c.ttl_ms);
  put_bytes(out, c.payload.data(), c.payload.size());
  return out;
}

std::optional<Command> decode_command(const std::vector<std::uint8_t> & b)
{
  Reader r(b);
  Command c{r.str(), r.str(), r.u64(), r.u64(), r.bytes()};
  if (!r.ok()) {
    return std::nullopt;
  }
  return c;
}

std::vector<std::uint8_t> encode(const CommandResult & r)
{
  std::vector<std::uint8_t> out{kVersion};
  put_str(out, r.cmd_id);
  out.push_back(static_cast<std::uint8_t>(r.status));
  return out;
}

std::optional<CommandResult> decode_result(const std::vector<std::uint8_t> & b)
{
  Reader r(b);
  CommandResult result{r.str(), static_cast<CommandStatus>(r.u8())};
  if (!r.ok() || result.status > CommandStatus::Invalid) {
    return std::nullopt;
  }
  return result;
}

CommandGate::CommandGate(
  const std::vector<CommandInterface> & interfaces, std::chrono::milliseconds max_ttl,
  std::size_t remember)
: interfaces_(interfaces), max_ttl_(max_ttl), remember_(remember)
{
}

CommandGate::Verdict CommandGate::check(const Command & c, std::uint64_t now_unix_ms)
{
  const CommandInterface * found = nullptr;
  for (const auto & i : interfaces_) {
    if (i.id == c.interface_id) {
      found = &i;
    }
  }
  if (found == nullptr) {
    return {CommandStatus::Unknown, nullptr};
  }
  if (c.ttl_ms == 0 || c.ttl_ms > static_cast<std::uint64_t>(max_ttl_.count())) {
    return {CommandStatus::Invalid, nullptr};
  }
  if (now_unix_ms > c.issued_unix_ms + c.ttl_ms) {
    return {CommandStatus::Expired, nullptr};
  }
  if (!recent_.insert(c.cmd_id).second) {
    return {CommandStatus::Duplicate, nullptr};
  }
  recent_order_.push_back(c.cmd_id);
  if (recent_order_.size() > remember_) {
    recent_.erase(recent_order_.front());
    recent_order_.pop_front();
  }
  return {CommandStatus::Done, found};
}

}  // namespace fleet_telemetry
