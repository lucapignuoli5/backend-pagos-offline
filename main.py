from typing import Annotated, Optional
import base64
import binascii
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from hashlib import sha256
from html import escape
import os
import re

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, rsa, padding, utils
from cryptography.exceptions import InvalidSignature

from fastapi import Depends, FastAPI, Header, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import func, inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from passlib.context import CryptContext
import mercadopago

import models
import schemas
from crypto_utils import verify_payment_contract_signature
from database import Base, SessionLocal, engine, get_db

from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse
from jose import jwt

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
mp_sdk = mercadopago.SDK("APP_USR-2595951267889831-061118-db149f1a52dab634ab15ed41166028d3-3468654848")

BRUTE_FORCE_ATTEMPTS: dict[str, int] = {}
JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "dev-change-me")
if JWT_SECRET_KEY == "dev-change-me":
    print("⚠️  [SECURITY WARNING]: JWT_SECRET_KEY es 'dev-change-me'. Peligro de falsificación de tokens. NUNCA usar en producción sin variables de entorno.")
JWT_ALGORITHM = "HS256"
MAX_LOGIN_ATTEMPTS = 5


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def _get_current_user(authorization: Optional[str] = Header(None), db: Session = Depends(get_db)) -> models.User:
    if authorization is None or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Credenciales inválidas")
    token = authorization.split(" ", 1)[1]
    try:
        payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
    except Exception:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token inválido")

    user_id = payload.get("sub")
    if user_id is None or not str(user_id).isdigit():
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token inválido")

    usuario = db.get(models.User, int(user_id))
    if usuario is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Usuario no encontrado")
    return usuario


def _ensure_password_hash_column() -> None:
    inspector = inspect(engine)
    columns = {column["name"] for column in inspector.get_columns("users")}
    if "password_hash" not in columns:
        with engine.begin() as connection:
            connection.exec_driver_sql("ALTER TABLE users ADD COLUMN password_hash VARCHAR")


@asynccontextmanager
async def lifespan(app: FastAPI):
    db = SessionLocal()
    try:
        _ensure_password_hash_column()
        comercio = db.get(models.User, 1)
        if comercio is None:
            comercio = models.User(
                id=1,
                nombre="Comercio de Prueba",
                saldo_real=Decimal("0"),
            )
            db.add(comercio)

        cliente = (
            db.query(models.User)
            .filter(func.lower(models.User.nombre) == "token-user-qr")
            .first()
        )
        if cliente is None:
            cliente = models.User(
                nombre="TOKEN-USER-QR",
                saldo_real=Decimal("100000.00"),
                password_hash=hash_password("123456"),
            )
            db.add(cliente)
        elif not cliente.password_hash:
            cliente.password_hash = hash_password("123456")

        db.commit()
        yield
    finally:
        db.close()


app = FastAPI(
    title="Backend de Administración",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://unfailing-bless-thrift.ngrok-free.dev"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request, exc):
    print(f"Ojo Luca, error de validación: {exc.errors()}") # Esto va a salir en tu terminal negra
    return JSONResponse(status_code=422, content={"detail": exc.errors()})


Base.metadata.create_all(bind=engine)

DbSession = Annotated[Session, Depends(get_db)]


@app.post("/api/login", response_model=schemas.LoginResponse)
def login_usuario(payload: schemas.LoginRequest, request: Request, db: DbSession) -> dict[str, object]:
    client_ip = request.client.host if request.client else "unknown"
    fallos = BRUTE_FORCE_ATTEMPTS.get(client_ip, 0)

    if fallos >= MAX_LOGIN_ATTEMPTS:
        raise HTTPException(status_code=429, detail="Demasiados intentos fallidos")

    identificador = payload.usuario or payload.token_id or ""
    usuario = None

    if identificador.isdigit():
        usuario = db.get(models.User, int(identificador))
    else:
        usuario = (
            db.query(models.User)
            .filter(func.lower(models.User.nombre) == identificador.lower())
            .first()
        )

    if usuario is None or not usuario.password_hash or not verify_password(payload.password, usuario.password_hash):
        BRUTE_FORCE_ATTEMPTS[client_ip] = fallos + 1
        raise HTTPException(status_code=401, detail="Usuario o contraseña incorrectos")

    BRUTE_FORCE_ATTEMPTS.pop(client_ip, None)

    expires_at = datetime.now(timezone.utc) + timedelta(hours=1)
    token = jwt.encode(
        {
            "sub": str(usuario.id),
            "token_id": str(usuario.id),
            "exp": int(expires_at.timestamp()),
        },
        JWT_SECRET_KEY,
        algorithm=JWT_ALGORITHM,
    )

    return {
        "access_token": token,
        "token_type": "bearer",
        "expires_in": 3600,
    }


@app.post(
    "/usuarios",
    response_model=schemas.UserRead,
    status_code=status.HTTP_201_CREATED,
)
def registrar_usuario(usuario: schemas.UserCreate, db: DbSession) -> models.User:
    nuevo_usuario = models.User(
        nombre=usuario.nombre,
        saldo_real=usuario.saldo_real,
    )
    db.add(nuevo_usuario)
    db.commit()
    db.refresh(nuevo_usuario)
    return nuevo_usuario


@app.get("/usuarios/{user_id}/saldo", response_model=schemas.UserSaldo)
def consultar_saldo(user_id: int, db: DbSession) -> models.User:
    usuario = db.get(models.User, user_id)
    if usuario is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Usuario no encontrado",
        )
    return usuario


@app.get("/api/billetera/saldo", tags=["billetera"])
def consultar_saldo_actual(usuario: models.User = Depends(_get_current_user)) -> dict[str, object]:
    return {"saldo_real": float(usuario.saldo_real)}


@app.post(
    "/api/billetera/recargar",
    response_model=schemas.RecargaResponse,
)
def recargar_saldo(payload: schemas.RecargaRequest, db: Session = Depends(get_db)) -> dict[str, object]:
    cliente = (
        db.query(models.User)
        .filter(func.lower(models.User.nombre) == payload.token_id.lower())
        .first()
    )

    if not cliente:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cliente no encontrado")

    monto_decimal = Decimal(str(payload.monto_recarga))
    cliente.saldo_real += monto_decimal
    db.commit()
    db.refresh(cliente)

    return {
        "exitoso": True,
        "nuevo_saldo": float(cliente.saldo_real),
    }


@app.post("/api/billetera/crear-link-pago")
def crear_link(payload: schemas.LinkPagoRequest) -> dict:
    preference_data = {
        "items": [
            {
                "title": "Recarga Billetera Offline",
                "quantity": 1,
                "currency_id": "ARS",
                "unit_price": payload.monto,
            }
        ],
        "external_reference": payload.token_id,
        "notification_url": "https://unfailing-bless-thrift.ngrok-free.dev/webhook/mercadopago",
    }

    preference_response = mp_sdk.preference().create(preference_data)

    if preference_response["status"] == 201:
        return {"init_point": preference_response["response"]["init_point"]}
    else:
        raise HTTPException(status_code=400, detail="Error al crear link de MP")


@app.post("/webhook/mercadopago")
async def mp_webhook(request: Request, db: DbSession):
    body = await request.json()
    topic = request.query_params.get("topic") or body.get("type") or body.get("action")
    payment_id = request.query_params.get("id") or body.get("data", {}).get("id")

    if topic in ["payment", "payment.created", "payment.updated"] and payment_id:
        payment_info = mp_sdk.payment().get(payment_id)

        if payment_info["status"] == 200:
            payment = payment_info["response"]

            if payment["status"] == "approved":
                external_ref = payment.get("external_reference")
                monto = Decimal(str(payment.get("transaction_amount")))

                if external_ref:
                    cliente = (
                        db.query(models.User)
                        .filter(func.lower(models.User.nombre) == external_ref.lower())
                        .first()
                    )
                    if cliente:
                        cliente.saldo_real += monto
                        db.commit()
                        print(f"✅ WEBHOOK MP: Se sumaron ${monto} a {cliente.nombre}")

    return {"status": "ok"}


@app.post("/verify-signature", response_model=schemas.SignatureVerificationResponse)
def verify_signature(
    request: schemas.SignatureVerificationRequest,
) -> schemas.SignatureVerificationResponse:
    is_valid = verify_payment_contract_signature(
        contract_json=request.contract_json,
        signature=request.firma,
        public_key_pem=request.llave_publica_pem,
    )
    return schemas.SignatureVerificationResponse(valid=is_valid)


@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(db: DbSession) -> HTMLResponse:
    transacciones = (
        db.query(models.TransaccionOfflineDB)
        .order_by(models.TransaccionOfflineDB.fecha_sincronizacion.desc())
        .all()
    )
    total_recaudado = sum(transaccion.monto for transaccion in transacciones)

    filas = "\n".join(
        _render_fila_dashboard(transaccion) for transaccion in transacciones
    )
    if not filas:
        filas = """
        <tr>
          <td colspan="4" class="px-6 py-10 text-center text-sm text-slate-500">
            Todavia no hay transacciones sincronizadas.
          </td>
        </tr>
        """

    html = f"""
    <!doctype html>
    <html lang="es">
      <head>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <meta http-equiv="refresh" content="5">
        <title>Dashboard Principal - Sincronización de Transacciones</title>
        <script src="https://cdn.tailwindcss.com"></script>
      </head>
      <body class="min-h-screen bg-stone-100 text-slate-900">
        <main class="mx-auto w-full max-w-6xl px-5 py-8">
          <header class="mb-8 flex flex-col gap-4 border-b border-stone-300 pb-6 sm:flex-row sm:items-end sm:justify-between">
            <div>
              <p class="text-sm font-semibold uppercase tracking-wide text-amber-700">Sistema de Administración</p>
              <h1 class="mt-2 text-3xl font-bold tracking-tight text-slate-950 sm:text-4xl">
                Dashboard Principal - Sincronización de Transacciones
              </h1>
            </div>
            <div class="text-sm text-slate-600">Actualizacion automatica cada 5 segundos</div>
          </header>

          <section class="mb-8 grid gap-4 sm:grid-cols-3">
            <div class="rounded-lg border border-stone-300 bg-white p-5 shadow-sm">
              <p class="text-sm font-medium text-slate-500">Total Recaudado</p>
              <p class="mt-2 text-3xl font-bold text-emerald-700">${total_recaudado:,.2f}</p>
            </div>
            <div class="rounded-lg border border-stone-300 bg-white p-5 shadow-sm">
              <p class="text-sm font-medium text-slate-500">Transacciones</p>
              <p class="mt-2 text-3xl font-bold text-slate-950">{len(transacciones)}</p>
            </div>
            <div class="rounded-lg border border-stone-300 bg-white p-5 shadow-sm">
              <p class="text-sm font-medium text-slate-500">Estado</p>
              <p class="mt-3 inline-flex rounded-full bg-emerald-100 px-3 py-1 text-sm font-semibold text-emerald-800">
                Firmas verificadas
              </p>
            </div>
          </section>

          <section class="overflow-hidden rounded-lg border border-stone-300 bg-white shadow-sm">
            <div class="overflow-x-auto">
              <table class="min-w-full divide-y divide-stone-200">
                <thead class="bg-slate-950 text-white">
                  <tr>
                    <th class="px-6 py-4 text-left text-xs font-semibold uppercase tracking-wide">ID Transaccion</th>
                    <th class="px-6 py-4 text-left text-xs font-semibold uppercase tracking-wide">Fecha Sincronizada</th>
                    <th class="px-6 py-4 text-left text-xs font-semibold uppercase tracking-wide">Monto</th>
                    <th class="px-6 py-4 text-left text-xs font-semibold uppercase tracking-wide">Estado de Firma</th>
                  </tr>
                </thead>
                <tbody class="divide-y divide-stone-200">
                  {filas}
                </tbody>
              </table>
            </div>
          </section>
        </main>
      </body>
    </html>
    """
    return HTMLResponse(content=html)


@app.post(
    "/sync-offline-payments",
    response_model=schemas.OfflinePaymentSyncResponse,
)
def sync_offline_payments(
    transacciones: list[schemas.OfflinePaymentSyncItem],
    db: DbSession,
) -> schemas.OfflinePaymentSyncResponse:
    if not transacciones:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Debe enviarse al menos una transaccion",
        )

    resultados: list[schemas.OfflinePaymentSyncResult] = []

    for transaccion in transacciones:
        if _transaccion_ya_existe(transaccion.id_transaccion, db):
            print(
                f"Seguridad: transaccion duplicada detectada para {transaccion.id_transaccion}"
            )
            resultados.append(
                schemas.OfflinePaymentSyncResult(
                    id_transaccion=transaccion.id_transaccion,
                    exitoso=False,
                    motivo="Transacción duplicada detectada (Replay Attack Mitigation)",
                )
            )
            continue

        try:
            _validar_firma_criptografica(transaccion)
            resultado = _procesar_transaccion_offline(transaccion, db)

            if resultado.exitoso:
                registro_offline = models.TransaccionOfflineDB(
                    id=transaccion.id_transaccion,
                    monto=float(Decimal(str(transaccion.monto)) / Decimal("100")),
                    timestamp=str(transaccion.timestamp),
                    firma_valida=True,
                )
                db.add(registro_offline)
                db.commit()

            resultados.append(resultado)
        except Exception as exc:
            db.rollback()
            resultados.append(
                schemas.OfflinePaymentSyncResult(
                    id_transaccion=transaccion.id_transaccion,
                    exitoso=False,
                    motivo=f"Error al procesar la transaccion: {exc}",
                )
            )

    exitosas = sum(1 for resultado in resultados if resultado.exitoso)
    fallidas = len(resultados) - exitosas

    return schemas.OfflinePaymentSyncResponse(
        exitosas=exitosas,
        fallidas=fallidas,
        resultados=resultados,
    )


def _procesar_transaccion_offline(
    transaccion: schemas.OfflinePaymentSyncItem,
    db: Session,
) -> schemas.OfflinePaymentSyncResult:
    try:
        _validar_y_aplicar_transaccion(transaccion, db)
        db.commit()
        return schemas.OfflinePaymentSyncResult(
            id_transaccion=transaccion.id_transaccion,
            exitoso=True,
        )
    except IntegrityError:
        db.rollback()
        return schemas.OfflinePaymentSyncResult(
            id_transaccion=transaccion.id_transaccion,
            exitoso=False,
            motivo="Transaccion ya procesada",
        )
    except ValueError as exc:
        db.rollback()
        return schemas.OfflinePaymentSyncResult(
            id_transaccion=transaccion.id_transaccion,
            exitoso=False,
            motivo=str(exc),
        )


def _validar_y_aplicar_transaccion(
    transaccion: schemas.OfflinePaymentSyncItem,
    db: Session,
) -> None:
    if _transaccion_ya_existe(transaccion.id_transaccion, db):
        raise ValueError("Transaccion ya procesada")

    cliente = _buscar_cliente_pagador(transaccion, db)
    comercio = db.get(models.User, transaccion.comercio_id)
    if comercio is None:
        raise ValueError("Comercio no encontrado")
    if cliente.id == comercio.id:
        raise ValueError("Cliente y comercio no pueden ser el mismo usuario")

    monto = Decimal(str(transaccion.monto)) / Decimal("100")
    if cliente.saldo_real < monto:
        raise ValueError("Fondos insuficientes del cliente")

    cliente.saldo_real -= monto
    comercio.saldo_real += monto

    db.add(
        models.FinalTransaction(
            id_transaccion=transaccion.id_transaccion,
            cliente_id=cliente.id,
            comercio_id=transaccion.comercio_id,
            monto=monto,
            timestamp=str(transaccion.timestamp),
            token_id=transaccion.token_id,
            firma=transaccion.firma,
            estado="ACREDITADO",
        )
    )
    db.flush()


def _render_fila_dashboard(transaccion: models.TransaccionOfflineDB) -> str:
    fecha = transaccion.fecha_sincronizacion
    fecha_sincronizada = fecha.strftime("%Y-%m-%d %H:%M:%S") if fecha else "-"
    estado_firma = (
        '<span class="inline-flex rounded-full bg-emerald-100 px-3 py-1 '
        'text-xs font-semibold text-emerald-800">✅ Validada por Keystore</span>'
        if transaccion.firma_valida
        else '<span class="inline-flex rounded-full bg-red-100 px-3 py-1 '
        'text-xs font-semibold text-red-800">Firma invalida</span>'
    )

    return f"""
    <tr class="hover:bg-stone-50">
      <td class="whitespace-nowrap px-6 py-4 font-mono text-sm text-slate-800">{escape(transaccion.id)}</td>
      <td class="whitespace-nowrap px-6 py-4 text-sm text-slate-600">{escape(fecha_sincronizada)}</td>
      <td class="whitespace-nowrap px-6 py-4 text-sm font-semibold text-slate-950">${transaccion.monto:,.2f}</td>
      <td class="whitespace-nowrap px-6 py-4">{estado_firma}</td>
    </tr>
    """


def _validar_firma_criptografica(transaccion: schemas.OfflinePaymentSyncItem) -> None:
    payload_str = transaccion.payload_original or _payload_firmado(transaccion)
    print(f"DEBUG BACKEND - String a verificar: '{payload_str}'")
    print(
        "DEBUG BACKEND - SHA256 string UTF-8: "
        f"{sha256(payload_str.encode('utf-8')).hexdigest()}"
    )
    if not verify_payment_contract_signature(
        payload_str=payload_str,
        signature_b64=transaccion.firma,
        public_key_b64=transaccion.clave_publica,
    ):
        print(
            "ADVERTENCIA: firma criptografica invalida para "
            f"transaccion {transaccion.id_transaccion}"
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Firma criptografica invalida",
        )


def _transaccion_ya_existe(id_transaccion: str, db: Session) -> bool:
    transaccion_offline = db.get(models.TransaccionOfflineDB, id_transaccion)
    if transaccion_offline is not None:
        return True

    transaccion_final = (
        db.query(models.FinalTransaction)
        .filter(models.FinalTransaction.id_transaccion == id_transaccion)
        .first()
    )
    if transaccion_final is not None:
        return True

    transaccion_procesada = (
        db.query(models.ProcessedTransaction)
        .filter(models.ProcessedTransaction.id_transaccion == id_transaccion)
        .first()
    )
    return transaccion_procesada is not None


def _transaccion_offline_ya_sincronizada(id_transaccion: str, db: Session) -> bool:
    return (
        db.query(models.TransaccionOfflineDB)
        .filter_by(id=id_transaccion)
        .first()
        is not None
    )


def verificar_firma(public_key_b64: str, firma_b64: str, datos_originales: str) -> bool:
    try:
        public_key_bytes = _decodificar_base64_android(public_key_b64)
        firma_bytes = _decodificar_base64_android(firma_b64)
        public_key = serialization.load_der_public_key(public_key_bytes)
    except (ValueError, TypeError, binascii.Error) as exc:
        print(f"DEBUG BACKEND - Error decodificando clave/firma: {exc}")
        return False

    print(
        "DEBUG BACKEND - Clave: "
        f"{public_key.__class__.__name__}, firma_bytes={len(firma_bytes)}, "
        f"public_key_sha256={sha256(public_key_bytes).hexdigest()}"
    )

    datos_bytes = datos_originales.encode("utf-8")

    try:
        if isinstance(public_key, ec.EllipticCurvePublicKey):
            for signature in _firmas_ecdsa_candidatas(firma_bytes, public_key):
                try:
                    public_key.verify(signature, datos_bytes, ec.ECDSA(hashes.SHA256()))
                    return True
                except InvalidSignature:
                    continue
            print("DEBUG BACKEND - ECDSA: la firma no coincide con el string verificado")
            return False

        if isinstance(public_key, rsa.RSAPublicKey):
            public_key.verify(
                firma_bytes,
                datos_bytes,
                padding.PKCS1v15(),
                hashes.SHA256(),
            )
            return True
    except (InvalidSignature, ValueError):
        print("DEBUG BACKEND - RSA: la firma no coincide con el string verificado")
        return False

    print("DEBUG BACKEND - Tipo de clave publica no soportado")
    return False


def _decodificar_base64_android(valor: str) -> bytes:
    normalizado = re.sub(r"\s+", "", valor)
    padding_necesario = (-len(normalizado)) % 4
    normalizado_con_padding = normalizado + ("=" * padding_necesario)

    try:
        return base64.b64decode(normalizado_con_padding, validate=True)
    except binascii.Error:
        return base64.urlsafe_b64decode(normalizado_con_padding)


def _firmas_ecdsa_candidatas(
    firma_bytes: bytes,
    public_key: ec.EllipticCurvePublicKey,
) -> list[bytes]:
    firmas = [firma_bytes]

    key_size_bytes = (public_key.curve.key_size + 7) // 8
    raw_signature_size = key_size_bytes * 2
    if len(firma_bytes) == raw_signature_size:
        r = int.from_bytes(firma_bytes[:key_size_bytes], "big")
        s = int.from_bytes(firma_bytes[key_size_bytes:], "big")
        firmas.append(utils.encode_dss_signature(r, s))

    return firmas


def _buscar_cliente_pagador(
    transaccion: schemas.OfflinePaymentSyncItem,
    db: Session,
) -> models.User:
    if transaccion.id_cliente is not None:
        cliente = db.get(models.User, transaccion.id_cliente)
        if cliente is None:
            raise ValueError("Cliente no encontrado")
        return cliente

    if transaccion.token_id is not None and transaccion.token_id.isdigit():
        token = db.get(models.OfflineToken, int(transaccion.token_id))
        if token is not None:
            cliente = db.get(models.User, token.user_id)
            if cliente is not None:
                return cliente

    if transaccion.token_id is not None and transaccion.token_id.upper().startswith("TOKEN-"):
        nombre_cliente = transaccion.token_id[6:].strip()
        cliente = (
            db.query(models.User)
            .filter(func.lower(models.User.nombre) == nombre_cliente.lower())
            .first()
        )
        if cliente is not None:
            return cliente

    raise ValueError("Cliente no encontrado")


def _buscar_token_offline(
    transaccion: schemas.OfflinePaymentSyncItem,
    db: Session,
) -> models.OfflineToken:
    if transaccion.token_id is not None:
        if not transaccion.token_id.isdigit():
            raise ValueError("Token offline no encontrado")

        token = db.get(models.OfflineToken, int(transaccion.token_id))
        if token is None or not token.activo:
            raise ValueError("Token offline no encontrado")
        if transaccion.id_cliente is not None and token.user_id != transaccion.id_cliente:
            raise ValueError("El token no pertenece al cliente informado")
        return token

    token = (
        db.query(models.OfflineToken)
        .filter(
            models.OfflineToken.user_id == transaccion.id_cliente,
            models.OfflineToken.activo.is_(True),
        )
        .order_by(models.OfflineToken.id.desc())
        .first()
    )
    if token is None:
        raise ValueError("Token offline no encontrado")

    return token


def _payload_firmado(transaccion: schemas.OfflinePaymentSyncItem) -> str:
    # Se usa el monto como entero (centavos) para prevenir errores criptograficos por el Locale del sistema
    return f"{transaccion.id_transaccion}|{int(transaccion.monto)}|{transaccion.timestamp}"


if __name__ == "__main__":
    import uvicorn
    from pyngrok import ngrok

    # 1. Configurar el token de seguridad
    ngrok.set_auth_token("2iaQVrqVAFfeumyIpp5fx3iqvaj_6GhFuY51acviSoqdyCY8H")

    # 2. Abrir el túnel hacia internet (Sintaxis corregida)
    puerto = 8000
    try:
        public_url = ngrok.connect(
            puerto,
            domain="unfailing-bless-thrift.ngrok-free.dev"
        )
    except Exception as exc:
        print("Advertencia al abrir túnel ngrok:", exc)
        # Intentar desconectar cualquier túnel existente con ese dominio y reintentar
        try:
            tunnels = ngrok.get_tunnels()
            for t in tunnels:
                if getattr(t, "public_url", "").startswith("https://unfailing-bless-thrift.ngrok-free.dev"):
                    try:
                        print(f"Desconectando túnel existente {t.public_url}")
                        ngrok.disconnect(t.public_url)
                    except Exception as e2:
                        print(f"No se pudo desconectar el túnel existente: {e2}")
            public_url = ngrok.connect(puerto, domain="unfailing-bless-thrift.ngrok-free.dev")
        except Exception as exc2:
            print("Reintento de ngrok falló, conectando sin dominio específico:", exc2)
            public_url = ngrok.connect(puerto)

    # 3. Imprimir la URL segura generada
    print("=" * 55)
    print(f"🌐 URL PÚBLICA PARA ANDROID (HTTPS): {public_url.public_url}/")
    print("=" * 55)

    # 4. Arrancar el servidor Uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=puerto, reload=True)
