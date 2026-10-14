"""Administrative revocation with explicit database and effective UTC timestamp."""
import argparse
import os
from datetime import datetime, timezone
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", required=True, type=Path)
    parser.add_argument("--key-id", required=True)
    parser.add_argument("--effective-at", required=True, help="UTC YYYY-MM-DDTHH:MM:SSZ")
    parser.add_argument("--confirm-database-change", action="store_true", required=True)
    args = parser.parse_args()
    if not args.database.is_file():
        parser.error("Existing database required")
    effective = datetime.strptime(args.effective_at, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    os.environ["DATABASE_URL"] = "sqlite:///" + args.database.resolve().as_posix()
    from database import SessionLocal
    import models
    with SessionLocal() as db:
        key = db.get(models.RegisteredKey, args.key_id)
        if key is None or key.revoked:
            parser.error("Key missing or already revoked; historical revocation is immutable")
        key.revoked = True
        key.revoked_at = effective
        db.commit()
    print("Revocacion registrada; evidencias posteriores requieren revision.")


if __name__ == "__main__":
    main()
