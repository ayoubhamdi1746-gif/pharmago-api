import uuid
import pytest
from app.models.prescription import Prescription
from app.models.pharmacy import LethalRiskSubstance
from app.models.patient import MedicalRecord
from app.services.safety_gate import check_safety_gate
from tests.conftest import make_ref

pytestmark = pytest.mark.asyncio


async def test_lethal_dose_triggers_high_risk_pending(db_session):
    """g) LD50 threshold exceeded triggers HIGH_RISK_PENDING."""
    ref = make_ref()
    pid = uuid.uuid4()

    db_session.add(LethalRiskSubstance(
        dpm_code="LETHAL01", generic_name="Test Toxin",
        ld50_threshold_mg_per_kg=10.0, suicide_risk_flag=False,
    ))
    db_session.add(Prescription(
        id=pid, patient_id="abc", pharmacy_id="abc",
        medications=[{"dpm_code": "LETHAL01", "dose_mg": 500, "quantity": 1}],
    ))
    db_session.add(MedicalRecord(reference_token="abc", patient_weight_kg=70.0))
    await db_session.commit()

    status = await check_safety_gate(db_session, pid, 70.0, ref)
    assert status == "HIGH_RISK_PENDING"
