from typing import Any, Literal
from pydantic import BaseModel, Field
import uuid


class APIResponse(BaseModel):
    status: Literal["ok", "processing", "error"]
    message: str
    data: dict | None = None
    ref: str = Field(default_factory=lambda: str(uuid.uuid4()))


class PrescriptionItem(BaseModel):
    dpm_code: str = ""
    medication_name: str = ""
    dose_mg: float = Field(gt=0)
    quantity: int = Field(gt=0)


class PrescriptionCreate(BaseModel):
    patient_reference_token: str
    items: list[PrescriptionItem]
    doctor_name: str | None = None
    doctor_phone: str | None = None
    doctor_email: str | None = None
    pharmacy_id: str | None = None


class VerifyRequest(BaseModel):
    prescription_id: str
    pharmacist_license_hash: str
    doctor_signed_token: str | None = None


class AssignDriverRequest(BaseModel):
    prescription_id: str
    pickup_coords: str
    encrypted_dropoff: str


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RefreshRequest(BaseModel):
    refresh_token: str


class SubscriptionCreate(BaseModel):
    pharmacy_name: str
    pharmacy_id: str
    plan: str


class BillingSubscribe(BaseModel):
    pharmacy_name: str
    plan: str
    phone: str
    payment_provider: str  # "KONNECT" | "FLOUCI"


class RegisterPharmacyRequest(BaseModel):
    pharmacy_name: str
    responsible_name: str
    phone: str
    city: str
    email: str = ""
    password: str = ""
    plan: str
    payment_provider: str  # "KONNECT" | "FLOUCI"


class AdminCreateDriverRequest(BaseModel):
    driver_id: str = ""
    pharmacy_id: str | None = None


class PharmacistVerifyRequest(BaseModel):
    doctor_signed_token: str | None = None


class PharmacistAddMedicationRequest(BaseModel):
    pharmacy_id: str
    medication_name: str
    dosage: str
    stock_quantity: int = 0
    is_available: bool = True


class PharmacistUpdateMedicationRequest(BaseModel):
    medication_name: str | None = None
    dosage: str | None = None
    stock_quantity: int | None = None
    is_available: bool | None = None


class DeliveryAssignRequest(BaseModel):
    pickup_coords: str = ""
    encrypted_dropoff: str = ""


class DeliveryFulfillRequest(BaseModel):
    otp: str = ""


class DoctorConfirmRequest(BaseModel):
    signed_token: str = ""
