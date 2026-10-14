from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    LargeBinary,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    nombre: Mapped[str] = mapped_column(String(120), nullable=False)
    saldo_real: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    password_hash: Mapped[str | None] = mapped_column(String, nullable=True)
    role: Mapped[str] = mapped_column(String(20), nullable=False, default="cliente", server_default="cliente")

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
    token_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
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


class ExternalPaymentEvent(Base):
    __tablename__ = "external_payment_events"
    __table_args__ = (
        UniqueConstraint("provider", "provider_payment_id", name="uq_external_payment_provider_id"),
        CheckConstraint("amount_cents > 0", name="ck_external_payment_amount_positive"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    provider: Mapped[str] = mapped_column(String(40), nullable=False)
    provider_payment_id: Mapped[str] = mapped_column(String(120), nullable=False)
    external_reference: Mapped[str] = mapped_column(String(120), nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    amount_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class ExternalTopupOrder(Base):
    __tablename__ = "external_topup_orders"
    __table_args__ = (CheckConstraint("amount_cents > 0", name="ck_external_topup_order_positive"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    wallet_id: Mapped[str] = mapped_column(ForeignKey("wallets.id"), nullable=False, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    amount_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="ARS")
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="PENDING")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class SimulatedTopup(Base):
    __tablename__ = "simulated_topups"
    __table_args__ = (CheckConstraint("amount_cents > 0", name="ck_simulated_topup_positive"),)

    request_id: Mapped[str] = mapped_column(String(120), primary_key=True)
    wallet_id: Mapped[str] = mapped_column(ForeignKey("wallets.id"), nullable=False, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    amount_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class LegacyEvidenceInventory(Base):
    __tablename__ = "legacy_evidence_inventory"

    operation_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    wallet_id: Mapped[str] = mapped_column(ForeignKey("wallets.id"), nullable=False, index=True)
    authorization_id: Mapped[str] = mapped_column(ForeignKey("offline_authorizations.id"), nullable=False, index=True)
    receipt_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    imported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class Wallet(Base):
    __tablename__ = "wallets"
    __table_args__ = (
        CheckConstraint("confirmed_balance_cents >= 0", name="ck_wallet_balance_nonnegative"),
    )

    id: Mapped[str] = mapped_column(String(120), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True, nullable=False, index=True)
    confirmed_balance_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="ARS", server_default="ARS")
    offline_review_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="0")


class Terminal(Base):
    __tablename__ = "terminals"

    id: Mapped[str] = mapped_column(String(120), primary_key=True)
    merchant_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    merchant_id: Mapped[str] = mapped_column(String(120), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="1")


class RegisteredKey(Base):
    __tablename__ = "registered_keys"
    __table_args__ = (
        UniqueConstraint("fingerprint", name="uq_registered_key_fingerprint"),
        UniqueConstraint("proof_nonce", name="uq_registered_key_proof_nonce"),
    )

    key_id: Mapped[str] = mapped_column(String(120), primary_key=True)
    owner_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    purpose: Mapped[str] = mapped_column(String(20), nullable=False)
    wallet_id: Mapped[str | None] = mapped_column(ForeignKey("wallets.id"), nullable=True, index=True)
    terminal_id: Mapped[str | None] = mapped_column(ForeignKey("terminals.id"), nullable=True, index=True)
    public_key_b64: Mapped[str] = mapped_column(String, nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    proof_nonce: Mapped[str] = mapped_column(String(120), nullable=False)
    revoked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="0")
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class OfflineAuthorization(Base):
    __tablename__ = "offline_authorizations"
    __table_args__ = (
        CheckConstraint("max_payment_cents > 0", name="ck_auth_max_payment_positive"),
        CheckConstraint("remaining_amount_cents >= 0", name="ck_auth_remaining_amount_nonnegative"),
        CheckConstraint("remaining_payments >= 0", name="ck_auth_remaining_payments_nonnegative"),
    )

    id: Mapped[str] = mapped_column(String(120), primary_key=True)
    issuance_request_id: Mapped[str | None] = mapped_column(String(120), unique=True, nullable=True)
    wallet_id: Mapped[str] = mapped_column(ForeignKey("wallets.id"), nullable=False, index=True)
    wallet_key_id: Mapped[str] = mapped_column(ForeignKey("registered_keys.key_id"), nullable=False, index=True)
    max_payment_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    remaining_amount_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    remaining_payments: Mapped[int] = mapped_column(Integer, nullable=False)
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="1")


class OfflinePaymentV2(Base):
    __tablename__ = "offline_payments_v2"
    __table_args__ = (
        CheckConstraint("amount_cents > 0", name="ck_payment_amount_positive"),
    )

    operation_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    wallet_id: Mapped[str] = mapped_column(ForeignKey("wallets.id"), nullable=False, index=True)
    merchant_id: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    terminal_id: Mapped[str] = mapped_column(ForeignKey("terminals.id"), nullable=False, index=True)
    authorization_id: Mapped[str] = mapped_column(ForeignKey("offline_authorizations.id"), nullable=False, index=True)
    amount_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    nonce: Mapped[str] = mapped_column(String(22), unique=True, nullable=False)
    request_envelope: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    receipt_envelope: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    ack_envelope: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    state: Mapped[str] = mapped_column(String(30), nullable=False)
    rejection_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class LedgerEntry(Base):
    __tablename__ = "ledger_entries"
    __table_args__ = (
        UniqueConstraint("operation_id", "entry_type", name="uq_ledger_operation_entry_type"),
        CheckConstraint("delta_cents != 0", name="ck_ledger_delta_nonzero"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    operation_id: Mapped[str] = mapped_column(ForeignKey("offline_payments_v2.operation_id"), nullable=False, index=True)
    wallet_id: Mapped[str] = mapped_column(ForeignKey("wallets.id"), nullable=False, index=True)
    entry_type: Mapped[str] = mapped_column(String(20), nullable=False)
    delta_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class OfflineCommitment(Base):
    __tablename__ = "offline_commitments"
    __table_args__ = (
        CheckConstraint("reserved_cents >= 0", name="ck_commitment_reserved_nonnegative"),
        CheckConstraint("emitted_cents >= 0", name="ck_commitment_emitted_nonnegative"),
    )

    authorization_id: Mapped[str] = mapped_column(ForeignKey("offline_authorizations.id"), primary_key=True)
    wallet_id: Mapped[str] = mapped_column(ForeignKey("wallets.id"), nullable=False, index=True)
    reserved_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    emitted_cents: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    emitted_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    closed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    closure_id: Mapped[str | None] = mapped_column(String(120), unique=True, nullable=True)
    authorization_envelope: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class CommitmentEmission(Base):
    __tablename__ = "offline_commitment_emissions"
    __table_args__ = (
        UniqueConstraint("authorization_id", "operation_id", name="uq_commitment_operation"),
        UniqueConstraint("authorization_id", "issuance_index", name="uq_commitment_issuance_index"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    authorization_id: Mapped[str] = mapped_column(ForeignKey("offline_authorizations.id"), nullable=False, index=True)
    operation_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    issuance_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    amount_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class PaymentResolution(Base):
    __tablename__ = "offline_payment_resolutions"
    operation_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    resolution_envelope: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
