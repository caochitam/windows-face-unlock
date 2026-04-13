#pragma once
#include <windows.h>
#include <credentialprovider.h>
#include <ntsecapi.h>
#include <string>

namespace FaceUnlock {

// FIELD_STATE_PAIR is only declared in Microsoft's SampleCredentialProvider
// header set, not in the public Windows SDK. Define it ourselves.
struct FIELD_STATE_PAIR {
    CREDENTIAL_PROVIDER_FIELD_STATE cpfs;
    CREDENTIAL_PROVIDER_FIELD_INTERACTIVE_STATE cpfis;
};

// Field indices for our single-tile UI.
enum FIELD_ID : DWORD {
    FIELD_TILE_IMAGE = 0,
    FIELD_LABEL      = 1,
    FIELD_SUBMIT     = 2,
    FIELD_STATUS     = 3,
    FIELD_COUNT
};

extern const CREDENTIAL_PROVIDER_FIELD_DESCRIPTOR s_FieldDescriptors[FIELD_COUNT];
extern const FIELD_STATE_PAIR s_FieldStatePairs[FIELD_COUNT];

// Wraps username/password/domain into a KERB_INTERACTIVE_UNLOCK_LOGON that the
// LogonUI expects in CREDENTIAL_PROVIDER_CREDENTIAL_SERIALIZATION.rgbSerialization.
// Caller must CoTaskMemFree(*ppSerialization).
HRESULT KerbPackInteractiveUnlock(const std::wstring& domain,
                                  const std::wstring& username,
                                  const std::wstring& password,
                                  CREDENTIAL_PROVIDER_USAGE_SCENARIO cpus,
                                  CREDENTIAL_PROVIDER_CREDENTIAL_SERIALIZATION* pcpcs);

void KerbUnpackFree(CREDENTIAL_PROVIDER_CREDENTIAL_SERIALIZATION* pcpcs);

}  // namespace FaceUnlock
