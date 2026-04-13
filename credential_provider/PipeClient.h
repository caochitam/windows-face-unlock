#pragma once
#include <windows.h>
#include <string>

// Minimal blocking named-pipe client matching the Python FaceService protocol.
// Sends a single JSON request and reads a single JSON reply. Timeout is best-effort.
namespace FaceUnlock {

// Returns true on success; on success, fills `response` with the raw reply JSON.
bool PipeCall(const std::wstring& pipeName,
              const std::string& requestJson,
              std::string& response,
              DWORD timeoutMs = 30000);

// Convenience: assemble {"cmd":"unlock"} and parse out username/password/domain.
// Any parse error -> returns false.
bool RequestUnlock(std::wstring& username,
                   std::wstring& password,
                   std::wstring& domain,
                   std::string& errorOut);

}  // namespace FaceUnlock
