from datetime import timezone


def requires_review(key, evidence_time):
    """Unknown revocation dates never silently authorize historical evidence."""
    if not key.revoked:
        return False
    if key.revoked_at is None:
        return True
    effective = key.revoked_at
    if effective.tzinfo is None:
        effective = effective.replace(tzinfo=timezone.utc)
    return evidence_time >= effective
