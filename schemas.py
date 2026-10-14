from decimal import Decimal
from datetime import datetime
from typing import Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, model_validator


class UserBase(BaseModel):
    nombre: str = Field(..., min_length=1, max_length=120)
    saldo_real: Decimal = Field(..., ge=0, decimal_places=2)


class UserCreate(UserBase):
    pass


class UserRead(UserBase):
    id: int

    model_config = ConfigDict(from_attributes=True)


class UserSaldo(BaseModel):
    id: int
    nombre: str
    saldo_real: Decimal

    model_config = ConfigDict(from_attributes=True)


class OfflineTokenBase(BaseModel):
    user_id: int
    monto_autorizado: Decimal = Field(..., gt=0, decimal_places=2)
    llave_publica_pem: str = Field(..., min_length=1)
    activo: bool = True


class OfflineTokenCreate(OfflineTokenBase):
    pass


class OfflineTokenRead(OfflineTokenBase):
    id: int

    model_config = ConfigDict(from_attributes=True)


class SignatureVerificationRequest(BaseModel):
    contract_json: str = Field(..., alias="json", min_length=1)
    firma: str = Field(..., min_length=1)
    llave_publica_pem: str = Field(..., min_length=1)

    model_config = ConfigDict(populate_by_name=True)


class SignatureVerificationResponse(BaseModel):
    valid: bool


class OfflinePaymentSyncItem(BaseModel):
    id_transaccion: str = Field(..., min_length=1, max_length=120)
    monto: int = Field(..., description="Monto en centavos informado por Android")
    timestamp: Union[int, str]
    comercio_id: int = Field(..., gt=0)
    firma: str = Field(..., min_length=1)
    clave_publica: str = Field(..., min_length=1)
    id_cliente: Optional[int] = Field(default=None, gt=0)
    token_id: Optional[str] = Field(default=None, min_length=1)
    payload_original: Optional[str] = Field(default=None, min_length=1)


class OfflinePaymentSyncResult(BaseModel):
    id_transaccion: str
    exitoso: bool
    motivo: Optional[str] = None


class OfflinePaymentSyncResponse(BaseModel):
    exitosas: int
    fallidas: int
    resultados: list[OfflinePaymentSyncResult]


class LoginRequest(BaseModel):
    usuario: Optional[str] = Field(default=None, min_length=1, max_length=120)
    token_id: Optional[str] = Field(default=None, min_length=1, max_length=120)
    password: str = Field(..., min_length=1, max_length=128)

    @model_validator(mode="after")
    def validar_identificador(self):
        if not self.usuario and not self.token_id:
            raise ValueError("Debe enviar usuario o token_id")
        return self


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int = 3600
    user_id: int
    wallet_id: str


class RecargaRequest(BaseModel):
    token_id: str = Field(..., min_length=1)
    monto_recarga: float = Field(..., gt=0)


class RecargaResponse(BaseModel):
    exitoso: bool
    nuevo_saldo: float


class LinkPagoRequest(BaseModel):
    token_id: str = Field(..., min_length=1)
    monto: float = Field(..., gt=0)


class KeyRegistrationRequest(BaseModel):
    public_key_b64: str = Field(..., min_length=1, max_length=1024)
    proof_payload_b64: str = Field(..., min_length=1, max_length=4096)
    proof_signature_b64: str = Field(..., min_length=1, max_length=1024)


class KeyRegistrationResponse(BaseModel):
    key_id: str
    fingerprint: str
    purpose: Literal["wallet", "pos"]
    scope_id: str
    created: bool
    merchant_id: Optional[str] = None


class TrustedKeyResponse(BaseModel):
    key_id: str
    fingerprint: str
    purpose: Literal["wallet", "pos"]
    scope_id: str
    public_key_b64: str


class OfflineAuthorizationRequest(BaseModel):
    wallet_id: str = Field(..., min_length=1, max_length=120)
    wallet_key_id: str = Field(..., min_length=1, max_length=120)
    max_payment_cents: int = Field(..., strict=True, gt=0)
    max_payments: int = Field(..., strict=True, gt=0)


class OfflineAuthorizationResponse(BaseModel):
    authorization_id: str
    wallet_id: str
    wallet_key_id: str
    currency: Literal["ARS"] = "ARS"
    max_payment_cents: int
    max_payments: int
    authorized_total_cents: int
    issued_at: datetime
    expires_at: datetime


class WalletBalanceResponse(BaseModel):
    wallet_id: str
    currency: Literal["ARS"] = "ARS"
    confirmed_balance_cents: int
    authorized_offline_cents: int
    available_for_authorization_cents: int


class OfflinePaymentEvidence(BaseModel):
    operation_id: str = Field(..., min_length=36, max_length=36)
    request_envelope_b64: str = Field(..., min_length=1, max_length=8192)
    receipt_envelope_b64: str = Field(..., min_length=1, max_length=8192)
    ack_envelope_b64: Optional[str] = Field(default=None, min_length=1, max_length=8192)


class OfflinePaymentSyncV2Request(BaseModel):
    operations: list[OfflinePaymentEvidence] = Field(..., min_length=1, max_length=100)


class OfflinePaymentResultV2(BaseModel):
    operation_id: str
    status: Literal["ACCEPTED", "REJECTED", "CONFLICT", "PENDING_EVIDENCE", "RETRYABLE_ERROR"]
    code: Optional[str] = None


class OfflinePaymentSyncV2Response(BaseModel):
    results: list[OfflinePaymentResultV2]


class OfflinePaymentStatusResponse(BaseModel):
    operation_id: str
    status: str
    code: Optional[str] = None


class OfflineAuthorizationV3Request(BaseModel):
    wallet_id: str = Field(..., min_length=1, max_length=120)
    wallet_key_id: str = Field(..., min_length=1, max_length=120)
    max_payment_cents: int = Field(..., strict=True, gt=0)
    max_payments: int = Field(..., strict=True, gt=0)


class OfflineAuthorizationV3Response(BaseModel):
    authorization_id: str
    wallet_id: str
    authorized_total_cents: int
    authorization_envelope_b64: str
    issued_at: datetime
    spend_expires_at: datetime


class OfflineCommitmentResponse(BaseModel):
    authorization_id: str
    reserved_cents: int
    emitted_cents: int
    emitted_count: int
    closed: bool

class OfflineAuthorizationCloseRequest(BaseModel):
    close_envelope_b64: str = Field(..., min_length=1, max_length=8192)
    manifest_b64: str = Field(..., min_length=1, max_length=8192)

class PaymentResolutionRequest(BaseModel):
    resolution_envelope_b64: str = Field(..., min_length=1, max_length=8192)
