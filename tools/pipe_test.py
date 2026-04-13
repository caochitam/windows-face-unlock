"""Quick pipe client for testing."""
import json, sys, time
import win32file, pywintypes

PIPE = r"\\.\pipe\FaceUnlock"
cmd = sys.argv[1] if len(sys.argv) > 1 else "ping"

for _ in range(30):
    try:
        h = win32file.CreateFile(PIPE,
            win32file.GENERIC_READ | win32file.GENERIC_WRITE,
            0, None, win32file.OPEN_EXISTING, 0, None)
        break
    except pywintypes.error:
        time.sleep(1)
else:
    print("pipe unreachable"); sys.exit(1)

win32file.WriteFile(h, json.dumps({"cmd": cmd}).encode())
_, data = win32file.ReadFile(h, 65536)
print(data.decode())
win32file.CloseHandle(h)
