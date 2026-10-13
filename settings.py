import os


def env_flag(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY")
DEMO_SEED_ENABLED = env_flag("DEMO_SEED_ENABLED")
DEMO_SEED_PASSWORD = os.getenv("DEMO_SEED_PASSWORD")

MERCADO_PAGO_ENABLED = env_flag("MERCADO_PAGO_ENABLED")
MERCADO_PAGO_ACCESS_TOKEN = os.getenv("MERCADO_PAGO_ACCESS_TOKEN")
MERCADO_PAGO_NOTIFICATION_URL = os.getenv("MERCADO_PAGO_NOTIFICATION_URL")

NGROK_ENABLED = env_flag("NGROK_ENABLED")
NGROK_AUTH_TOKEN = os.getenv("NGROK_AUTH_TOKEN")
NGROK_DOMAIN = os.getenv("NGROK_DOMAIN")

CORS_ORIGINS = [
    origin.strip()
    for origin in os.getenv("CORS_ORIGINS", "http://127.0.0.1:8000").split(",")
    if origin.strip()
]

INITIAL_BALANCE_CENTS = int(os.getenv("INITIAL_BALANCE_CENTS", "1000000"))
MAX_PAYMENT_CENTS = int(os.getenv("MAX_PAYMENT_CENTS", "100000"))
MAX_OFFLINE_PAYMENTS = int(os.getenv("MAX_OFFLINE_PAYMENTS", "10"))
OFFLINE_AUTHORIZATION_SECONDS = int(os.getenv("OFFLINE_AUTHORIZATION_SECONDS", "86400"))
POS_REQUEST_SECONDS = int(os.getenv("POS_REQUEST_SECONDS", "120"))
