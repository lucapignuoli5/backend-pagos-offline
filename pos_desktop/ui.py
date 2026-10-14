from __future__ import annotations

from decimal import Decimal, InvalidOperation
from dataclasses import replace

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal, Slot
from PySide6.QtWidgets import (
    QFormLayout, QHBoxLayout, QLabel, QLineEdit, QMainWindow, QPushButton,
    QStackedWidget, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from pos_desktop.backend_client import PosBackendClient
from pos_desktop.service import PosService
from pos_desktop.simulator import AndroidHceSimulator
from pos_desktop.sync import PosSyncService


class WorkerSignals(QObject):
    succeeded = Signal(object)
    failed = Signal(str)
    finished = Signal()


class Worker(QRunnable):
    def __init__(self, action):
        super().__init__()
        self.action = action
        self.signals = WorkerSignals()

    @Slot()
    def run(self):
        try:
            self.signals.succeeded.emit(self.action())
        except Exception as exc:
            self.signals.failed.emit(str(exc))
        finally:
            self.signals.finished.emit()


class PosWindow(QMainWindow):
    def __init__(
        self, service: PosService, backend: PosBackendClient,
        simulator: AndroidHceSimulator | None = None,
        offline_enabled: bool = False,
    ):
        super().__init__()
        self.service = service
        self.backend = backend
        self.simulator = simulator
        self.offline_enabled = offline_enabled
        self.pool = QThreadPool.globalInstance()
        self.operation_id: str | None = None
        self.access_token: str | None = None
        self.sync_service = PosSyncService(service.database, backend)
        self.setWindowTitle("POS Pagos Offline")
        self.resize(760, 520)
        self.stack = QStackedWidget()
        self.setCentralWidget(self.stack)
        self.access_page = self._access_page()
        self.amount_page = self._amount_page()
        self.wait_page = self._wait_page()
        self.history_page = self._history_page()
        for page in (self.access_page, self.amount_page, self.wait_page, self.history_page):
            self.stack.addWidget(page)

    def _access_page(self) -> QWidget:
        page = QWidget()
        layout = QFormLayout(page)
        self.username = QLineEdit()
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self.access_status = QLabel("Ingrese con una cuenta de comercio")
        button = QPushButton("Ingresar")
        button.clicked.connect(self._login)
        layout.addRow("Usuario", self.username)
        layout.addRow("Contraseña", self.password)
        layout.addRow(button)
        if self.simulator is not None:
            local = QPushButton("Entrar en simulador local")
            local.clicked.connect(lambda: self.stack.setCurrentWidget(self.amount_page))
            layout.addRow(local)
        elif self.offline_enabled:
            local = QPushButton("Abrir POS sin conexión")
            local.clicked.connect(lambda: self.stack.setCurrentWidget(self.amount_page))
            layout.addRow(local)
        layout.addRow(self.access_status)
        return page

    def _amount_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.addWidget(QLabel("Nuevo cobro en ARS"))
        self.amount = QLineEdit()
        self.amount.setPlaceholderText("Ej.: 125,50")
        layout.addWidget(self.amount)
        button = QPushButton("Crear solicitud y acercar teléfono")
        button.clicked.connect(self._start_payment)
        history = QPushButton("Historial y conciliación")
        history.clicked.connect(self._show_history)
        self.amount_status = QLabel()
        layout.addWidget(button)
        layout.addWidget(history)
        layout.addWidget(self.amount_status)
        return page

    def _wait_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        self.wait_status = QLabel("Esperando confirmación en Android")
        layout.addWidget(self.wait_status)
        if self.simulator is not None:
            confirm = QPushButton("Simular confirmación Android")
            confirm.clicked.connect(self._simulate_confirmation)
            layout.addWidget(confirm)
        collect = QPushButton("Segundo acercamiento: recibir comprobante")
        collect.clicked.connect(self._collect)
        layout.addWidget(collect)
        back = QPushButton("Volver")
        back.clicked.connect(lambda: self.stack.setCurrentWidget(self.amount_page))
        layout.addWidget(back)
        return page

    def _history_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.addWidget(QLabel("Historial local y conciliación remota por operación"))
        self.sync_status = QLabel("Conciliación pendiente")
        sync_button = QPushButton("Conciliar operaciones pendientes")
        sync_button.clicked.connect(self._sync)
        layout.addWidget(sync_button)
        layout.addWidget(self.sync_status)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Operación", "Importe", "Estado", "Actualizada"])
        layout.addWidget(self.table)
        resume = QPushButton("Reanudar operación seleccionada")
        resume.clicked.connect(self._resume_selected)
        layout.addWidget(resume)
        back = QPushButton("Volver")
        back.clicked.connect(lambda: self.stack.setCurrentWidget(self.amount_page))
        layout.addWidget(back)
        return page

    def _login(self) -> None:
        username, password = self.username.text().strip(), self.password.text()
        if not username or not password:
            self.access_status.setText("Complete usuario y contraseña")
            return
        def success(session):
            self.access_token = session.access_token
            if session.merchant_id and session.terminal_id and session.key_id:
                self.service.config = replace(
                    self.service.config,
                    merchant_id=session.merchant_id,
                    terminal_id=session.terminal_id,
                    pos_key_id=session.key_id,
                )
                self.offline_enabled = True
            self.stack.setCurrentWidget(self.amount_page)

        self._run(lambda: self.backend.login_and_register_key(username, password), success, self.access_status)

    def _start_payment(self) -> None:
        try:
            normalized = self.amount.text().strip().replace(",", ".")
            cents = int((Decimal(normalized) * 100).quantize(Decimal("1")))
        except (InvalidOperation, ValueError):
            self.amount_status.setText("Importe inválido")
            return

        def action():
            operation = self.service.create_payment(cents)
            self.service.deliver_request(operation.operation_id)
            return operation.operation_id

        def success(operation_id):
            self.operation_id = operation_id
            self.wait_status.setText(f"Solicitud {operation_id} recibida; confirme en Android")
            self.stack.setCurrentWidget(self.wait_page)

        self._run(action, success, self.amount_status)

    def _simulate_confirmation(self) -> None:
        if self.simulator is not None and self.operation_id:
            self.simulator.confirm(self.operation_id)
            self.wait_status.setText("Confirmado en simulador; ejecute el segundo acercamiento")

    def _collect(self) -> None:
        if not self.operation_id:
            return
        self._run(
            lambda: self.service.collect_receipt(self.operation_id),
            lambda state: self.wait_status.setText(
                "Aceptación local persistida; conciliación pendiente"
                if state == "LOCALLY_ACCEPTED" else f"Sin aceptación: {state}"
            ),
            self.wait_status,
        )

    def _show_history(self) -> None:
        self._run(self.service.database.list_operations, self._populate_history, self.amount_status)

    def _sync(self) -> None:
        if not self.access_token:
            self.sync_status.setText("Inicie sesión online para conciliar")
            return

        def success(summary):
            rendered = ", ".join(f"{key}: {value}" for key, value in sorted(summary.items()))
            self.sync_status.setText(rendered or "No hay operaciones pendientes")
            self._show_history()

        self._run(
            lambda: self.sync_service.sync_due(self.access_token),
            success,
            self.sync_status,
        )

    def _populate_history(self, operations) -> None:
        self.table.setRowCount(len(operations))
        for row, operation in enumerate(operations):
            values = (
                operation.operation_id,
                f"${operation.amount_cents / 100:.2f}",
                operation.state,
                operation.updated_at,
            )
            for column, value in enumerate(values):
                self.table.setItem(row, column, QTableWidgetItem(value))
        self.stack.setCurrentWidget(self.history_page)

    def _resume_selected(self) -> None:
        row = self.table.currentRow()
        item = self.table.item(row, 0) if row >= 0 else None
        if item is None:
            self.sync_status.setText("Seleccione una operación")
            return
        self.operation_id = item.text()
        operation = self.service.database.get_operation(self.operation_id)
        if operation is None:
            self.sync_status.setText("La operación ya no está disponible")
            return
        if operation.state == "REQUEST_CREATED":
            self._run(
                lambda: self.service.deliver_request(operation.operation_id),
                lambda state: self.wait_status.setText(f"Solicitud recuperada: {state}; confirme en Android"),
                self.wait_status,
            )
        elif operation.state in {"REQUEST_DELIVERED", "WAITING_CONFIRMATION"}:
            self.wait_status.setText("Solicitud recuperada; complete el segundo acercamiento")
        elif operation.ack_envelope is not None:
            self.wait_status.setText("Aceptación recuperada; acerque el teléfono para reenviar el acuse")
        else:
            self.wait_status.setText(f"Operación recuperada en estado {operation.state}")
        self.stack.setCurrentWidget(self.wait_page)

    def _run(self, action, on_success, status: QLabel) -> None:
        status.setText("Procesando…")
        worker = Worker(action)
        worker.signals.succeeded.connect(on_success)
        worker.signals.failed.connect(lambda message: status.setText(f"Error: {message}"))
        self.pool.start(worker)

