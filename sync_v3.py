from sqlalchemy.orm import Session

import models
import schemas
from sync_v2 import process_evidence_core


def process_evidence_v3(
    db: Session, user: models.User, evidence: schemas.OfflinePaymentEvidence
) -> schemas.OfflinePaymentResultV2:
    """Procesador compartido por el contrato v3, separado de la ruta HTTP v2."""
    return process_evidence_core(db, user, evidence)
