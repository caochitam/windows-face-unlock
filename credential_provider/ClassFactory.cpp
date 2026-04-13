#include <windows.h>
#include <unknwn.h>
#include <new>

#include "guid.h"
#include "FaceCredentialProvider.h"

namespace FaceUnlock {

class ClassFactory : public IClassFactory {
public:
    ClassFactory() : m_cRef(1) {}
    IFACEMETHODIMP QueryInterface(REFIID riid, void** ppv) override {
        if (!ppv) return E_POINTER;
        *ppv = nullptr;
        if (riid == IID_IUnknown || riid == IID_IClassFactory) {
            *ppv = static_cast<IClassFactory*>(this);
            AddRef();
            return S_OK;
        }
        return E_NOINTERFACE;
    }
    IFACEMETHODIMP_(ULONG) AddRef()  override { return InterlockedIncrement(&m_cRef); }
    IFACEMETHODIMP_(ULONG) Release() override { LONG c = InterlockedDecrement(&m_cRef); if (c == 0) delete this; return c; }

    IFACEMETHODIMP CreateInstance(IUnknown* pUnkOuter, REFIID riid, void** ppv) override {
        if (pUnkOuter) return CLASS_E_NOAGGREGATION;
        auto* p = new (std::nothrow) FaceCredentialProvider();
        if (!p) return E_OUTOFMEMORY;
        HRESULT hr = p->QueryInterface(riid, ppv);
        p->Release();
        return hr;
    }
    IFACEMETHODIMP LockServer(BOOL) override { return S_OK; }

private:
    LONG m_cRef;
};

HRESULT CreateClassFactory(REFIID riid, void** ppv) {
    auto* cf = new (std::nothrow) ClassFactory();
    if (!cf) return E_OUTOFMEMORY;
    HRESULT hr = cf->QueryInterface(riid, ppv);
    cf->Release();
    return hr;
}

}  // namespace FaceUnlock
