"""Explicit new demonstration only. Never reuse or migrate an existing database."""
import argparse
import json
import os
from pathlib import Path
import secrets
from urllib.parse import urlparse
from decimal import Decimal


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--directory", required=True, type=Path)
    parser.add_argument("--backend-url", default="https://example.invalid/")
    args = parser.parse_args()
    target = args.directory.expanduser().resolve()
    source = Path(__file__).resolve().parents[1]
    if (target.exists() or target.is_relative_to(source)
            or any((p / ".git").exists() for p in target.parents)):
        parser.error("Use a NEW external directory outside Git; existing directories are refused")
    url = urlparse(args.backend_url)
    if url.scheme != "https" or not url.hostname or url.username or url.query or url.fragment:
        parser.error("Provide your HTTPS backend URL without credentials, query or fragment")
    target.mkdir(parents=True, exist_ok=False)
    database_path = target / "demo.sqlite"
    database_url = "sqlite:///" + database_path.as_posix()
    os.environ["DATABASE_URL"] = database_url
    os.environ["MERCADO_PAGO_ENABLED"] = "false"
    os.environ["NGROK_ENABLED"] = "false"
    from issuer_keys import IssuerIdentity
    from pos_desktop.key_store import WindowsDpapiProtector
    from database import Base, engine, SessionLocal
    import models
    import bcrypt
    identity = IssuerIdentity.create_external(target / "issuer.dpapi.json", "issuer-demo-v3")
    (target / "issuer-public.json").write_text(
        json.dumps([identity.public_record()], separators=(",", ":")), encoding="utf-8"
    )
    client_password, merchant_password = secrets.token_urlsafe(20), secrets.token_urlsafe(20)
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        for name, role, cents, password in (
            ("cliente-demo", "cliente", 1000000, client_password),
            ("comercio-demo", "comercio", 0, merchant_password),
        ):
            user = models.User(nombre=name, role=role, saldo_real=Decimal(cents) / 100,
                               password_hash=bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode())
            db.add(user)
            db.flush()
            db.add(models.Wallet(id=f"wallet-{user.id}", user_id=user.id,
                                 confirmed_balance_cents=cents, currency="ARS"))
        db.commit()
    engine.dispose()
    config = {
        "DATABASE_URL": database_url, "JWT_SECRET_KEY": secrets.token_urlsafe(48),
        "ISSUER_KEY_PATH": str(target / "issuer.dpapi.json"),
        "ISSUER_KEY_FINGERPRINT": identity.fingerprint,
        "ISSUER_TRUST_PATH": str(target / "issuer-public.json"),
        "MERCADO_PAGO_ENABLED": "false", "NGROK_ENABLED": "false",
        "DEMO_SEED_ENABLED": "false", "LEGACY_INVENTORY_OPEN": "false",
        "API_BASE_URL": args.backend_url.rstrip("/") + "/",
        "DEMO_USERNAME": "cliente-demo", "DEMO_PASSWORD": client_password,
        "DEMO_MERCHANT_USERNAME": "comercio-demo", "DEMO_MERCHANT_PASSWORD": merchant_password,
        "ISSUER_PUBLIC_KEY_B64": identity.public_key_b64, "ISSUER_KEY_ID": identity.key_id,
        "ISSUER_TRUST_JSON": json.dumps([identity.public_record()], separators=(",", ":")),
        "TFG_POS_DATABASE": str(target / "pos.sqlite"),
        "TFG_BACKEND_URL": args.backend_url.rstrip("/"),
        "TFG_POS_TERMINAL_ID": "desktop-demo-terminal", "TFG_POS_KEY_ID": "desktop-demo-key",
        "TFG_ISSUER_PUBLIC_KEY_B64": identity.public_key_b64, "TFG_ISSUER_KEY_ID": identity.key_id,
        "TFG_ISSUER_TRUST_PATH": str(target / "issuer-public.json"),
    }
    protected = WindowsDpapiProtector().protect(json.dumps(config).encode())
    with (target / "config.dpapi").open("xb") as stream:
        stream.write(protected)
    print("Demostracion nueva preparada. Configuracion protegida para este usuario Windows.")
    print("Use tools.run_demo para compilar Android o iniciar backend/POS; no se inicio ningun servicio.")


if __name__ == "__main__":
    main()
