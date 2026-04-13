#pragma once
#include <windows.h>
#include <credentialprovider.h>

namespace FaceUnlock {

class FaceCredential;

class FaceCredentialProvider : public ICredentialProvider {
public:
    FaceCredentialProvider();
    ~FaceCredentialProvider();

    IFACEMETHODIMP QueryInterface(REFIID, void**) override;
    IFACEMETHODIMP_(ULONG) AddRef() override;
    IFACEMETHODIMP_(ULONG) Release() override;

    IFACEMETHODIMP SetUsageScenario(CREDENTIAL_PROVIDER_USAGE_SCENARIO cpus, DWORD dwFlags) override;
    IFACEMETHODIMP SetSerialization(const CREDENTIAL_PROVIDER_CREDENTIAL_SERIALIZATION*) override;
    IFACEMETHODIMP Advise(ICredentialProviderEvents*, UINT_PTR) override;
    IFACEMETHODIMP UnAdvise() override;
    IFACEMETHODIMP GetFieldDescriptorCount(DWORD* pdwCount) override;
    IFACEMETHODIMP GetFieldDescriptorAt(DWORD dwIndex,
                                        CREDENTIAL_PROVIDER_FIELD_DESCRIPTOR** ppcpfd) override;
    IFACEMETHODIMP GetCredentialCount(DWORD* pdwCount, DWORD* pdwDefault,
                                      BOOL* pbAutoLogonWithDefault) override;
    IFACEMETHODIMP GetCredentialAt(DWORD dwIndex, ICredentialProviderCredential** ppcpc) override;

private:
    LONG m_cRef;
    CREDENTIAL_PROVIDER_USAGE_SCENARIO m_cpus;
    FaceCredential* m_pCred;
};

}  // namespace FaceUnlock
