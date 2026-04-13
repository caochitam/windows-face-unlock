"""Run N verify calls through the pipe and print timing."""
import json, sys, time
import win32file, pywintypes

PIPE = r"\\.\pipe\FaceUnlock"
N = int(sys.argv[1]) if len(sys.argv) > 1 else 3

for i in range(N):
    for _ in range(60):
        try:
            h = win32file.CreateFile(PIPE,
                win32file.GENERIC_READ | win32file.GENERIC_WRITE,
                0, None, win32file.OPEN_EXISTING, 0, None)
            break
        except pywintypes.error:
            time.sleep(0.5)
    else:
        print(f"call {i+1}: PIPE UNREACHABLE after 30s")
        sys.exit(1)

    t0 = time.time()
    try:
        win32file.WriteFile(h, json.dumps({"cmd": "verify"}).encode())
        _, data = win32file.ReadFile(h, 65536)
    finally:
        try: win32file.CloseHandle(h)
        except Exception: pass

    dt = time.time() - t0
    try:
        r = json.loads(data.decode())
    except Exception:
        r = {"raw": data}
    print(f"call {i+1}: {dt:.2f}s  match={r.get('match')} dist={r.get('distance', 0):.3f} real={r.get('real')}")
