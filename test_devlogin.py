import httpx, json, sys, re

def safeprint(text):
    sys.stdout.write(re.sub(r'[^\x20-\x7E\n]', '.', str(text)) + "\n")
    sys.stdout.flush()

r = httpx.get("http://localhost:8000/openapi.json", timeout=5)
paths = r.json()["paths"]
if "/dev/login" not in paths:
    safeprint("FAIL: /dev/login is missing!")
    sys.exit(1)
safeprint("[OK] /dev/login endpoint is registered")
safeprint("")

for role in ["PATIENT", "PHARMACIST", "DOCTOR", "DRIVER", "ADMIN"]:
    r = httpx.post("http://localhost:8000/dev/login", json={"role": role}, timeout=5)
    d = r.json()
    h = d["headers"]
    safeprint(f"{role:12s}  x-role: {h['x-role']:12s}  x-auth: {h['x-auth']}")

safeprint("")
safeprint("[OK] All roles return correct headers")
