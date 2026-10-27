"""Supervise only subprocesses created by the explicit demo launcher."""
import re
import signal
import socket
import subprocess
import sys
import threading
import time

from tools.demo_windows import DemoError


def require_free_backend_port():
    # This is an early diagnostic, not proof of ownership: the child's own
    # readiness and exit status below also have to succeed after this socket closes.
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            probe.bind(("127.0.0.1", 8000))
    except OSError:
        raise DemoError(
            "El puerto 127.0.0.1:8000 esta ocupado o no esta disponible. "
            "Cierre la otra ventana del servidor; no se detuvo ningun proceso ajeno."
        ) from None


def require_backend_listener():
    try:
        with socket.create_connection(("127.0.0.1", 8000), timeout=2):
            pass
    except OSError:
        raise DemoError("No hay un backend accesible en 127.0.0.1:8000 para abrir el tunel.") from None


class OwnedBackend:
    _READY = re.compile(
        r"^\d{2}:\d{2}:\d{2} INFO Uvicorn running on http://127\.0\.0\.1:8000(?: |$)"
    )

    def __init__(self, command, source, environment, directory):
        self.process = None
        self.relay = None
        self.log = None
        self.ready = threading.Event()
        self.relay_failed = threading.Event()
        self.stopped = False
        try:
            self.log = (directory / "backend.log").open("a", encoding="utf-8")
            self.process = subprocess.Popen(
                command, cwd=source, env=environment,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="replace", bufsize=1,
                stdin=subprocess.DEVNULL,
                # Same console, separate group: CTRL_BREAK targets this backend
                # and is handled by Uvicorn's graceful Windows SIGBREAK handler.
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
            )
            self.relay = threading.Thread(target=self._show_events, daemon=True)
            self.relay.start()
        except BaseException:
            self.stop()
            raise

    def _show_events(self):
        try:
            for line in self.process.stdout:
                self.log.write(line)
                self.log.flush()
                sys.stdout.write(line)
                sys.stdout.flush()
                if self._READY.match(line):
                    self.ready.set()
        except (OSError, ValueError):
            self.relay_failed.set()

    def check(self):
        if self.relay_failed.is_set():
            raise DemoError("No se pudo mantener la consola o backend.log; se detendra esta demo.")
        if self.process.poll() is not None:
            raise DemoError("El backend de esta ventana termino; consulte los eventos de backend.log.")

    def wait_ready(self, timeout=30):
        deadline = time.monotonic() + timeout
        while not self.ready.wait(0.1):
            self.check()
            if time.monotonic() >= deadline:
                raise DemoError("El backend propio no confirmo el arranque dentro del plazo.")
        self.check()

    def stop(self):
        """Normal close is graceful; forced termination is a bounded last resort."""
        if self.stopped:
            return
        self.stopped = True
        process = self.process
        forced = False
        try:
            if process is not None and process.poll() is None:
                try:
                    process.send_signal(signal.CTRL_BREAK_EVENT)
                    process.wait(timeout=15)
                except (OSError, subprocess.TimeoutExpired):
                    forced = True
                    process.terminate()
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=5)
        finally:
            if self.relay is not None:
                self.relay.join(timeout=5)
            # Close the pipe only after the child exited. A still-blocked relay
            # must not contend with close(); containment finishes on process exit.
            if process is not None and process.poll() is not None:
                process.stdout.close()
            if self.log is not None and (self.relay is None or not self.relay.is_alive()):
                self.log.close()
            if forced:
                print("El backend requirio cierre forzado; revise su estado antes de continuar.")


def stop_owned_process(process):
    """Bounded cleanup for a known ngrok Popen, never a process-name search."""
    if process is None or process.poll() is not None:
        return
    try:
        process.terminate()
        process.wait(timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)


def watch(backend=None, ngrok_process=None, enter_to_close=True):
    import msvcrt
    extended_key = False
    # Poll the existing Windows console rather than leaving an input() daemon
    # blocked on stdin while Python and the logging pipe are shutting down.
    while True:
        if backend is not None:
            backend.check()
        if ngrok_process is not None and ngrok_process.poll() is not None:
            raise DemoError("El tunel de esta ventana termino; se detendra esta demo.")
        if enter_to_close and msvcrt.kbhit():
            key = msvcrt.getwch()
            if extended_key:
                extended_key = False
            elif key in ("\x00", "\xe0"):
                extended_key = True
            elif key in ("\r", "\n"):
                return
        time.sleep(0.2)
