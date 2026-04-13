#include "helpers.h"
#include <wincred.h>
#include <intsafe.h>

#pragma comment(lib, "credui.lib")
#pragma comment(lib, "secur32.lib")

namespace FaceUnlock {

// Static field layout for our tile.
const CREDENTIAL_PROVIDER_FIELD_DESCRIPTOR s_FieldDescriptors[FIELD_COUNT] = {
    { FIELD_TILE_IMAGE, CPFT_TILE_IMAGE,    const_cast<PWSTR>(L"Image"),  GUID_NULL },
    { FIELD_LABEL,      CPFT_LARGE_TEXT,    const_cast<PWSTR>(L"Label"),  GUID_NULL },
    { FIELD_SUBMIT,     CPFT_SUBMIT_BUTTON, const_cast<PWSTR>(L"Submit"), GUID_NULL },
    { FIELD_STATUS,     CPFT_SMALL_TEXT,    const_cast<PWSTR>(L"Status"), GUID_NULL },
};

const FIELD_STATE_PAIR s_FieldStatePairs[FIELD_COUNT] = {
    { CPFS_DISPLAY_IN_BOTH,           CPFIS_NONE },
    { CPFS_DISPLAY_IN_SELECTED_TILE,  CPFIS_NONE },
    { CPFS_DISPLAY_IN_SELECTED_TILE,  CPFIS_NONE },
    { CPFS_DISPLAY_IN_SELECTED_TILE,  CPFIS_NONE },
};

// Copy `src` into buffer at cursor, set UNICODE_STRING fields so that
// Buffer is an OFFSET (in bytes) from the start of the serialization
// buffer — this is what LSA expects for CPGSR_RETURN_CREDENTIAL_FINISHED.
static void PackString(UNICODE_STRING& u, PCWSTR src, BYTE* base, USHORT& cursor) {
    USHORT len = (USHORT)(wcslen(src) * sizeof(WCHAR));
    u.Length = len;
    u.MaximumLength = len;
    if (len > 0) {
        memcpy(base + cursor, src, len);
        u.Buffer = (PWSTR)(ULONG_PTR)cursor;   // store as OFFSET, not pointer
        cursor = (USHORT)(cursor + len);
    } else {
        u.Buffer = nullptr;
    }
}

HRESULT KerbPackInteractiveUnlock(const std::wstring& domain,
                                  const std::wstring& username,
                                  const std::wstring& password,
                                  CREDENTIAL_PROVIDER_USAGE_SCENARIO cpus,
                                  CREDENTIAL_PROVIDER_CREDENTIAL_SERIALIZATION* pcpcs) {
    const bool isUnlock = (cpus == CPUS_UNLOCK_WORKSTATION);

    const USHORT dLen = (USHORT)(domain.size()   * sizeof(WCHAR));
    const USHORT uLen = (USHORT)(username.size() * sizeof(WCHAR));
    const USHORT pLen = (USHORT)(password.size() * sizeof(WCHAR));

    // Always allocate at least KERB_INTERACTIVE_UNLOCK_LOGON (it's a superset
    // of KERB_INTERACTIVE_LOGON) so the LogonId field is zeroed for both scenarios.
    const size_t headerSize = sizeof(KERB_INTERACTIVE_UNLOCK_LOGON);
    const size_t total = headerSize + dLen + uLen + pLen;

    BYTE* buffer = (BYTE*)CoTaskMemAlloc(total);
    if (!buffer) return E_OUTOFMEMORY;
    ZeroMemory(buffer, total);

    KERB_INTERACTIVE_UNLOCK_LOGON* kiul = (KERB_INTERACTIVE_UNLOCK_LOGON*)buffer;
    KERB_INTERACTIVE_LOGON* logon = &kiul->Logon;

    logon->MessageType = isUnlock ? KerbWorkstationUnlockLogon : KerbInteractiveLogon;

    USHORT cursor = (USHORT)headerSize;
    PackString(logon->LogonDomainName, domain.c_str(),   buffer, cursor);
    PackString(logon->UserName,        username.c_str(), buffer, cursor);
    PackString(logon->Password,        password.c_str(), buffer, cursor);

    pcpcs->rgbSerialization = buffer;
    pcpcs->cbSerialization  = (ULONG)total;

    // Authentication package: use "Negotiate" (auto-picks Kerberos vs NTLM).
    // MUST succeed — passing 0 would be rejected by LogonUI as invalid.
    HANDLE lsa = nullptr;
    NTSTATUS st = LsaConnectUntrusted(&lsa);
    if (st != 0) {
        SecureZeroMemory(buffer, total);
        CoTaskMemFree(buffer);
        pcpcs->rgbSerialization = nullptr;
        pcpcs->cbSerialization = 0;
        return HRESULT_FROM_NT(st);
    }

    LSA_STRING name;
    const char pkgName[] = "Negotiate";  // NEGOSSP_NAME_A
    name.Buffer = const_cast<PCHAR>(pkgName);
    name.Length = (USHORT)(sizeof(pkgName) - 1);
    name.MaximumLength = (USHORT)sizeof(pkgName);  // include NUL

    ULONG pkgId = 0;
    st = LsaLookupAuthenticationPackage(lsa, &name, &pkgId);
    LsaDeregisterLogonProcess(lsa);
    if (st != 0) {
        SecureZeroMemory(buffer, total);
        CoTaskMemFree(buffer);
        pcpcs->rgbSerialization = nullptr;
        pcpcs->cbSerialization = 0;
        return HRESULT_FROM_NT(st);
    }
    pcpcs->ulAuthenticationPackage = pkgId;
    pcpcs->clsidCredentialProvider = GUID_NULL;  // filled by caller
    return S_OK;
}

void KerbUnpackFree(CREDENTIAL_PROVIDER_CREDENTIAL_SERIALIZATION* pcpcs) {
    if (pcpcs && pcpcs->rgbSerialization) {
        SecureZeroMemory(pcpcs->rgbSerialization, pcpcs->cbSerialization);
        CoTaskMemFree(pcpcs->rgbSerialization);
        pcpcs->rgbSerialization = nullptr;
        pcpcs->cbSerialization = 0;
    }
}

}  // namespace FaceUnlock
