import hashlib

PATIENT_TOKEN = "patient-demo-ref"

PHARMACIST_LICENSE = "pharmacist-demo-lic"
PHARMACIST_HASH = hashlib.sha256(PHARMACIST_LICENSE.encode()).hexdigest()

DOCTOR_LICENSE = "doctor-demo-lic"
DOCTOR_HASH = hashlib.sha256(DOCTOR_LICENSE.encode()).hexdigest()

DRIVER_TOKEN = "driver-demo-token"
DRIVER_HASH = hashlib.sha256(DRIVER_TOKEN.encode()).hexdigest()

ADMIN_KEY = "admin-demo-key"


ROLE_HEADERS = {
    "PATIENT":   {"x-role": "patient",   "x-auth": PATIENT_TOKEN},
    "PHARMACIST":{"x-role": "pharmacist","x-auth": PHARMACIST_HASH},
    "DOCTOR":    {"x-role": "doctor",    "x-auth": DOCTOR_HASH},
    "DRIVER":    {"x-role": "driver",    "x-auth": DRIVER_HASH},
    "ADMIN":     {"x-role": "admin",     "x-auth": ADMIN_KEY},
}
