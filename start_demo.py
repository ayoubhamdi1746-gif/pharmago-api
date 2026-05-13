"""Start the demo server and print info."""
import subprocess, sys, time, httpx

DETACH = 0x00000008
proc = subprocess.Popen(
    [sys.executable, "-m", "uvicorn", "app.main:app",
     "--host", "0.0.0.0", "--port", "8000"],
    cwd=__file__.rstrip("start_demo.py"),
    creationflags=DETACH,
    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
)
print(f"Started uvicorn PID: {proc.pid}")
time.sleep(4)

r = httpx.get("http://localhost:8000/openapi.json")
print(f"Server status: {r.status_code}")
api = r.json()
print(f"Title: {api['info']['title']}")
print(f"Paths ({len(api['paths'])}):")
for p in sorted(api["paths"]):
    print(f"  {p}")
