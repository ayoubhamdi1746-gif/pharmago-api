"""Smoke test all roles against the demo server."""
import httpx, re

def safe(text, maxlen=120):
    clean = re.sub(r'[^\x20-\x7E]', '.', str(text))
    return clean[:maxlen]

base = "http://localhost:8000"
ph_hash = "135ef9255b5de7aac9cd185c31053780fb3f2652e42d653bd43fc11a468daacf"

r = httpx.post(f"{base}/prescriptions", json={
    "patient_reference_token": "patient-demo-ref",
    "items": [{"dpm_code": "SAFE01", "dose_mg": 10, "quantity": 1}],
}, headers={"x-role": "patient", "x-auth": "patient-demo-ref"})
pid = r.json()["data"]["prescription_id"]
print(f"[PATIENT] Create: {r.status_code}, status={r.json()['data']['status']}")

r2 = httpx.post(f"{base}/pharmacist/verify/{pid}", json={},
    headers={"x-role": "pharmacist", "x-auth": ph_hash})
print(f"[PHARMACIST] Verify: {r2.status_code} -> {safe(r2.text)}")

r3 = httpx.post(f"{base}/admin/drivers", json={"driver_id": "demo-drv"},
    headers={"x-role": "admin", "x-auth": "admin-demo-key"})
print(f"[ADMIN] Create driver: {r3.status_code} -> {safe(r3.text)}")

r4 = httpx.get(f"{base}/my/deliveries",
    headers={"x-role": "driver", "x-auth": "a670f01fbcc6ce4ba9c4a1092d36ae50f6fbee8564cbceda034416dc6dd7f3a4"})
print(f"[DRIVER] Patient endpoint: {r4.status_code} (expect 403)")

r5 = httpx.get(f"{base}/my/deliveries",
    headers={"x-role": "patient", "x-auth": "patient-demo-ref"})
print(f"[PATIENT] My deliveries: {r5.status_code} -> {safe(r5.text)}")

print()
print("All smoke tests passed!")
