"""Quick server start + test."""
import httpx, time, subprocess, sys

proc = subprocess.Popen(
    [sys.executable, "-m", "uvicorn", "app.main:app",
     "--host", "0.0.0.0", "--port", "8000"],
    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
)
print(f"Server PID: {proc.pid}")
time.sleep(4)

try:
    r = httpx.get("http://localhost:8000/openapi.json", timeout=5)
    print(f"Server status: {r.status_code}")
    api = r.json()
    print(f"Paths ({len(api['paths'])}):")
    for p in sorted(api["paths"]):
        print(f"  {p}")
except Exception as e:
    print(f"Error: {e}")
