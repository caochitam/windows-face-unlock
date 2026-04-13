#include <windows.h>
#include <unknwn.h>
#include "guid.h"

EXTERN_C IMAGE_DOS_HEADER __ImageBase;

namespace FaceUnlock {
HRESULT CreateClassFactory(REFIID riid, void** ppv);
}

static LONG g_DllRefs = 0;

BOOL APIENTRY DllMain(HMODULE, DWORD reason, LPVOID) {
    if (reason == DLL_PROCESS_ATTACH) DisableThreadLibraryCalls(nullptr);
    return TRUE;
}

STDAPI DllCanUnloadNow(void) {
    return (g_DllRefs == 0) ? S_OK : S_FALSE;
}

STDAPI DllGetClassObject(REFCLSID rclsid, REFIID riid, LPVOID* ppv) {
    if (rclsid != CLSID_FaceCredentialProvider) return CLASS_E_CLASSNOTAVAILABLE;
    return FaceUnlock::CreateClassFactory(riid, ppv);
}

// Registration helpers: called via regsvr32. In production prefer an MSI.
static HRESULT WriteReg(HKEY root, PCWSTR sub, PCWSTR name, PCWSTR value) {
    HKEY k;
    LONG r = RegCreateKeyExW(root, sub, 0, nullptr, 0, KEY_WRITE, nullptr, &k, nullptr);
    if (r != ERROR_SUCCESS) return HRESULT_FROM_WIN32(r);
    r = RegSetValueExW(k, name, 0, REG_SZ,
                       (const BYTE*)value, (DWORD)((wcslen(value) + 1) * sizeof(WCHAR)));
    RegCloseKey(k);
    return HRESULT_FROM_WIN32(r);
}

STDAPI DllRegisterServer(void) {
    WCHAR path[MAX_PATH];
    GetModuleFileNameW((HMODULE)&__ImageBase, path, MAX_PATH);

    const WCHAR* clsid = L"{F8A0B4D9-3C7F-4B0A-9E21-8C1B1E2B7C10}";
    WCHAR sub[MAX_PATH];

    wsprintfW(sub, L"CLSID\\%s", clsid);
    WriteReg(HKEY_CLASSES_ROOT, sub, nullptr, L"Face Unlock Credential Provider");

    wsprintfW(sub, L"CLSID\\%s\\InprocServer32", clsid);
    WriteReg(HKEY_CLASSES_ROOT, sub, nullptr, path);
    WriteReg(HKEY_CLASSES_ROOT, sub, L"ThreadingModel", L"Apartment");

    wsprintfW(sub,
        L"SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Authentication\\Credential Providers\\%s",
        clsid);
    WriteReg(HKEY_LOCAL_MACHINE, sub, nullptr, L"Face Unlock Credential Provider");
    return S_OK;
}

STDAPI DllUnregisterServer(void) {
    const WCHAR* clsid = L"{F8A0B4D9-3C7F-4B0A-9E21-8C1B1E2B7C10}";
    WCHAR sub[MAX_PATH];
    wsprintfW(sub, L"CLSID\\%s", clsid);
    RegDeleteTreeW(HKEY_CLASSES_ROOT, sub);
    wsprintfW(sub,
        L"SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Authentication\\Credential Providers\\%s",
        clsid);
    RegDeleteTreeW(HKEY_LOCAL_MACHINE, sub);
    return S_OK;
}
