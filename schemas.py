from decimal import Decimal
from typing import Optional, Union

from pydantic import BaseModel, ConfigDict, Field


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
    monto: float = Field(..., description="Monto informado por Android")
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
