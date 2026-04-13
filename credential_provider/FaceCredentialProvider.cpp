#include "FaceCredentialProvider.h"
#include "FaceCredential.h"
#include "helpers.h"
#include <new>

namespace FaceUnlock {

FaceCredentialProvider::FaceCredentialProvider()
    : m_cRef(1), m_cpus(CPUS_INVALID), m_pCred(nullptr) {}

FaceCredentialProvider::~FaceCredentialProvider() {
    if (m_pCred) { m_pCred->Release(); m_pCred = nullptr; }
}

IFACEMETHODIMP FaceCredentialProvider::QueryInterface(REFIID riid, void** ppv) {
    if (!ppv) return E_POINTER;
    *ppv = nullptr;
    if (riid == IID_IUnknown || riid == IID_ICredentialProvider) {
        *ppv = static_cast<ICredentialProvider*>(this);
        AddRef();
        return S_OK;
    }
    return E_NOINTERFACE;
}
IFACEMETHODIMP_(ULONG) FaceCredentialProvider::AddRef()  { return InterlockedIncrement(&m_cRef); }
IFACEMETHODIMP_(ULONG) FaceCredentialProvider::Release() { LONG c = InterlockedDecrement(&m_cRef); if (c == 0) delete this; return c; }

IFACEMETHODIMP FaceCredentialProvider::SetUsageScenario(CREDENTIAL_PROVIDER_USAGE_SCENARIO cpus, DWORD) {
    // We only participate in logon and unlock.
    switch (cpus) {
        case CPUS_LOGON:
        case CPUS_UNLOCK_WORKSTATION:
            m_cpus = cpus;
            if (!m_pCred) {
                m_pCred = new (std::nothrow) FaceCredential();
                if (!m_pCred) return E_OUTOFMEMORY;
                HRESULT hr = m_pCred->Initialize(cpus);
                if (FAILED(hr)) { m_pCred->Release(); m_pCred = nullptr; return hr; }
            }
            return S_OK;
        default:
            return E_NOTIMPL;
    }
}

IFACEMETHODIMP FaceCredentialProvider::SetSerialization(const CREDENTIAL_PROVIDER_CREDENTIAL_SERIALIZATION*) {
    return E_NOTIMPL;
}
IFACEMETHODIMP FaceCredentialProvider::Advise(ICredentialProviderEvents*, UINT_PTR) { return E_NOTIMPL; }
IFACEMETHODIMP FaceCredentialProvider::UnAdvise() { return E_NOTIMPL; }

IFACEMETHODIMP FaceCredentialProvider::GetFieldDescriptorCount(DWORD* pdwCount) {
    *pdwCount = FIELD_COUNT;
    return S_OK;
}

IFACEMETHODIMP FaceCredentialProvider::GetFieldDescriptorAt(DWORD dwIndex,
                                                            CREDENTIAL_PROVIDER_FIELD_DESCRIPTOR** ppcpfd) {
    if (dwIndex >= FIELD_COUNT) return E_INVALIDARG;
    CREDENTIAL_PROVIDER_FIELD_DESCRIPTOR src = s_FieldDescriptors[dwIndex];
    auto* out = (CREDENTIAL_PROVIDER_FIELD_DESCRIPTOR*)CoTaskMemAlloc(sizeof(src));
    if (!out) return E_OUTOFMEMORY;
    *out = src;
    // Label string must be its own CoTaskMem allocation.
    size_t cch = wcslen(src.pszLabel) + 1;
    out->pszLabel = (PWSTR)CoTaskMemAlloc(cch * sizeof(WCHAR));
    if (!out->pszLabel) { CoTaskMemFree(out); return E_OUTOFMEMORY; }
    wcscpy_s(out->pszLabel, cch, src.pszLabel);
    *ppcpfd = out;
    return S_OK;
}

IFACEMETHODIMP FaceCredentialProvider::GetCredentialCount(DWORD* pdwCount, DWORD* pdwDefault,
                                                          BOOL* pbAutoLogonWithDefault) {
    *pdwCount = m_pCred ? 1 : 0;
    // Make our face tile the default and trigger auto-verify the moment the
    // lock/login screen becomes visible. If face recognition fails, our
    // GetSerialization returns S_FALSE, which leaves LogonUI idle so the user
    // can click the password tile or re-trigger with the arrow.
    *pdwDefault = 0;
    *pbAutoLogonWithDefault = TRUE;
    return S_OK;
}

IFACEMETHODIMP FaceCredentialProvider::GetCredentialAt(DWORD dwIndex, ICredentialProviderCredential** ppcpc) {
    if (dwIndex != 0 || !m_pCred) return E_INVALIDARG;
    return m_pCred->QueryInterface(IID_ICredentialProviderCredential, (void**)ppcpc);
}

}  // namespace FaceUnlock
