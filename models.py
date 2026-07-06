from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from typing import Optional

from database import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    nombre: Mapped[str] = mapped_column(String(120), nullable=False)
    saldo_real: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    password_hash: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    offline_tokens: Mapped[list["OfflineToken"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )


class OfflineToken(Base):
    __tablename__ = "offline_tokens"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    monto_autorizado: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    llave_publica_pem: Mapped[str] = mapped_column(String, nullable=False)
    activo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    user: Mapped[User] = relationship(back_populates="offline_tokens")


class ProcessedTransaction(Base):
    __tablename__ = "processed_transactions"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    id_transaccion: Mapped[str] = mapped_column(String(120), unique=True, nullable=False, index=True)
    offline_token_id: Mapped[int] = mapped_column(ForeignKey("offline_tokens.id"), nullable=False, index=True)
    cliente_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    comercio_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    monto: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    timestamp: Mapped[str] = mapped_column(String(80), nullable=False)
    procesado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class FinalTransaction(Base):
    __tablename__ = "transacciones_finales"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    id_transaccion: Mapped[str] = mapped_column(String(120), unique=True, nullable=False, index=True)
    cliente_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    comercio_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    monto: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    timestamp: Mapped[str] = mapped_column(String(80), nullable=False)
    token_id: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    firma: Mapped[str] = mapped_column(String, nullable=False)
    estado: Mapped[str] = mapped_column(String(30), nullable=False, default="ACREDITADO")
    creado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class TransaccionOfflineDB(Base):
    __tablename__ = "transacciones_offline"

    id: Mapped[str] = mapped_column(String(120), primary_key=True, index=True)
    monto: Mapped[float] = mapped_column(Float, nullable=False)
    timestamp: Mapped[str] = mapped_column(String(80), nullable=False)
    firma_valida: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    fecha_sincronizacion: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
