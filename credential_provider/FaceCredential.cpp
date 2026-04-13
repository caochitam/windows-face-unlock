#include "FaceCredential.h"
#include "helpers.h"
#include "PipeClient.h"
#include "guid.h"
#include <shlwapi.h>

namespace FaceUnlock {

static HRESULT AllocStr(PCWSTR src, PWSTR* dst) {
    size_t cch = wcslen(src) + 1;
    *dst = (PWSTR)CoTaskMemAlloc(cch * sizeof(WCHAR));
    if (!*dst) return E_OUTOFMEMORY;
    wcscpy_s(*dst, cch, src);
    return S_OK;
}

FaceCredential::FaceCredential()
    : m_cRef(1), m_cpus(CPUS_INVALID), m_pEvents(nullptr),
      m_label(L"Face Unlock"), m_status(L"Look at the camera") {}

FaceCredential::~FaceCredential() {}

HRESULT FaceCredential::Initialize(CREDENTIAL_PROVIDER_USAGE_SCENARIO cpus) {
    m_cpus = cpus;
    return S_OK;
}

IFACEMETHODIMP FaceCredential::QueryInterface(REFIID riid, void** ppv) {
    if (!ppv) return E_POINTER;
    *ppv = nullptr;
    if (riid == IID_IUnknown || riid == IID_ICredentialProviderCredential) {
        *ppv = static_cast<ICredentialProviderCredential*>(this);
        AddRef();
        return S_OK;
    }
    return E_NOINTERFACE;
}
IFACEMETHODIMP_(ULONG) FaceCredential::AddRef()  { return InterlockedIncrement(&m_cRef); }
IFACEMETHODIMP_(ULONG) FaceCredential::Release() { LONG c = InterlockedDecrement(&m_cRef); if (c == 0) delete this; return c; }

IFACEMETHODIMP FaceCredential::Advise(ICredentialProviderCredentialEvents* e) {
    if (m_pEvents) m_pEvents->Release();
    m_pEvents = e;
    if (e) e->AddRef();
    return S_OK;
}
IFACEMETHODIMP FaceCredential::UnAdvise() {
    if (m_pEvents) { m_pEvents->Release(); m_pEvents = nullptr; }
    return S_OK;
}

IFACEMETHODIMP FaceCredential::SetSelected(BOOL* pbAutoLogon) {
    // Trigger verification as soon as the tile is selected — including the
    // implicit auto-selection from GetCredentialCount's pbAutoLogonWithDefault.
    // Safety: GetSerialization has a 12-second hard timeout and returns S_FALSE
    // on failure, so a bad attempt won't prevent the user from switching to
    // the password tile.
    *pbAutoLogon = TRUE;
    m_status = L"Look at the camera";
    if (m_pEvents) m_pEvents->SetFieldString(this, FIELD_STATUS, m_status.c_str());
    return S_OK;
}

IFACEMETHODIMP FaceCredential::SetDeselected() { return S_OK; }

IFACEMETHODIMP FaceCredential::GetFieldState(DWORD dwFieldID,
                                             CREDENTIAL_PROVIDER_FIELD_STATE* pcpfs,
                                             CREDENTIAL_PROVIDER_FIELD_INTERACTIVE_STATE* pcpfis) {
    if (dwFieldID >= FIELD_COUNT) return E_INVALIDARG;
    *pcpfs  = s_FieldStatePairs[dwFieldID].cpfs;
    *pcpfis = s_FieldStatePairs[dwFieldID].cpfis;
    return S_OK;
}

IFACEMETHODIMP FaceCredential::GetStringValue(DWORD dwFieldID, PWSTR* ppwsz) {
    switch (dwFieldID) {
        case FIELD_LABEL:  return AllocStr(m_label.c_str(),  ppwsz);
        case FIELD_STATUS: return AllocStr(m_status.c_str(), ppwsz);
    }
    return E_INVALIDARG;
}

IFACEMETHODIMP FaceCredential::GetBitmapValue(DWORD dwFieldID, HBITMAP* phbmp) {
    // Use default logo — custom bitmap omitted in MVP.
    if (dwFieldID != FIELD_TILE_IMAGE) return E_INVALIDARG;
    *phbmp = nullptr;
    return E_NOTIMPL;
}

IFACEMETHODIMP FaceCredential::GetSubmitButtonValue(DWORD dwFieldID, DWORD* pdwAdjacentTo) {
    if (dwFieldID != FIELD_SUBMIT) return E_INVALIDARG;
    *pdwAdjacentTo = FIELD_STATUS;
    return S_OK;
}

IFACEMETHODIMP FaceCredential::GetSerialization(
    CREDENTIAL_PROVIDER_GET_SERIALIZATION_RESPONSE* pcpgsr,
    CREDENTIAL_PROVIDER_CREDENTIAL_SERIALIZATION* pcpcs,
    PWSTR* ppwszOptionalStatusText,
    CREDENTIAL_PROVIDER_STATUS_ICON* pcpsiOptionalStatusIcon) {

    // Default safe response: tell LogonUI nothing happened, so the user can
    // immediately switch to the password tile or retry.
    *pcpgsr = CPGSR_NO_CREDENTIAL_NOT_FINISHED;
    *pcpsiOptionalStatusIcon = CPSI_NONE;
    if (ppwszOptionalStatusText) *ppwszOptionalStatusText = nullptr;

    // All heavy work goes through PipeCall which has a hard 12s timeout and
    // wraps every Win32 call in error checks — there are no raw exceptions
    // that can escape here, so we rely on return codes rather than SEH
    // (SEH can't coexist with objects that have destructors in the same scope).
    std::wstring user, pw, dom;
    std::string err;
    bool ok = false;
    try {
        ok = RequestUnlock(user, pw, dom, err);
    } catch (...) {
        ok = false;
        err = "cpp-exception";
    }

    if (!ok) {
        m_status = L"Face not recognised. Use password tile instead.";
        if (m_pEvents) m_pEvents->SetFieldString(this, FIELD_STATUS, m_status.c_str());
        *pcpsiOptionalStatusIcon = CPSI_ERROR;
        AllocStr(L"Face Unlock failed - use password tile", ppwszOptionalStatusText);
        return S_FALSE;  // LogonUI treats as non-fatal; user picks another tile
    }

    HRESULT hr = E_FAIL;
    try {
        hr = KerbPackInteractiveUnlock(dom, user, pw, m_cpus, pcpcs);
    } catch (...) {
        hr = E_FAIL;
    }
    if (FAILED(hr)) {
        m_status = L"Credential packing failed";
        if (m_pEvents) m_pEvents->SetFieldString(this, FIELD_STATUS, m_status.c_str());
        *pcpsiOptionalStatusIcon = CPSI_ERROR;
        return S_FALSE;
    }
    pcpcs->clsidCredentialProvider = CLSID_FaceCredentialProvider;
    *pcpgsr = CPGSR_RETURN_CREDENTIAL_FINISHED;
    return S_OK;
}

IFACEMETHODIMP FaceCredential::ReportResult(NTSTATUS ntsStatus, NTSTATUS ntsSubstatus,
                                            PWSTR* ppwszOptionalStatusText,
                                            CREDENTIAL_PROVIDER_STATUS_ICON* pcpsiOptionalStatusIcon) {
    (void)ntsStatus; (void)ntsSubstatus;
    *ppwszOptionalStatusText = nullptr;
    *pcpsiOptionalStatusIcon = CPSI_NONE;
    return S_OK;
}

}  // namespace FaceUnlock
