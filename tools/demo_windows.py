"""Windows containment and private writes for the explicit demo launcher.

Nothing in this module runs a service or reads demo material on import.
"""
import ctypes
from ctypes import wintypes
from contextlib import contextmanager
import os
from pathlib import Path
import signal
import sys
import threading
import uuid


class DemoError(RuntimeError):
    """An operator-facing message that contains no underlying exception data."""


_stderr_lock = threading.RLock()
_stderr_handles_until_exit = []


@contextmanager
def ngrok_native_stderr_to_null():
    """Discard native ngrok stderr without changing Python/Popen globally.

    Windows Popen(stderr=None) duplicates GetStdHandle(STD_ERROR_HANDLE).
    Only this launcher's standard-handle slot changes during agent startup;
    already-running backend pipes and the parent console are unaffected.
    """
    if sys.platform != "win32" or threading.current_thread() is not threading.main_thread():
        raise DemoError("El inicio seguro de ngrok requiere el hilo principal en Windows.")
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.GetStdHandle.argtypes = [wintypes.DWORD]
    kernel.GetStdHandle.restype = wintypes.HANDLE
    kernel.SetStdHandle.argtypes = [wintypes.DWORD, wintypes.HANDLE]
    kernel.SetStdHandle.restype = wintypes.BOOL
    kernel.CreateFileW.argtypes = [
        wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
        wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE,
    ]
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    stderr_slot = 0xFFFFFFF4  # STD_ERROR_HANDLE (-12 as DWORD)
    with _stderr_lock:
        original = kernel.GetStdHandle(stderr_slot)
        null_handle = kernel.CreateFileW("NUL", 0x40000000, 3, None, 3, 0x80, None)
        if null_handle == ctypes.c_void_p(-1).value:
            raise DemoError("No se pudo aislar la salida nativa de ngrok; no se inicio el agente.")
        attempted = False
        try:
            # Mark before the API call so interruption immediately after it
            # still restores the original handle in finally.
            attempted = True
            if not kernel.SetStdHandle(stderr_slot, null_handle):
                raise DemoError("No se pudo aislar la salida nativa de ngrok; no se inicio el agente.")
            yield
        finally:
            # A second Ctrl+C during this short restoration must not leave the
            # launcher's standard-handle slot pointing at a closed NUL handle.
            handlers = {}
            for name in ("SIGINT", "SIGBREAK"):
                event = getattr(signal, name, None)
                if event is not None:
                    handlers[event] = signal.signal(event, signal.SIG_IGN)
            try:
                restored = not attempted or bool(kernel.SetStdHandle(stderr_slot, original))
                if restored:
                    kernel.CloseHandle(null_handle)
                else:
                    # Do not close a handle still installed in the process table.
                    _stderr_handles_until_exit.append(null_handle)
            finally:
                for event, handler in handlers.items():
                    signal.signal(event, handler)
            if not restored:
                raise DemoError("No se pudo restaurar stderr nativo; se detendra esta demostracion.")


def require_console():
    if sys.platform != "win32":
        raise DemoError("Este iniciador requiere Windows.")
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.GetConsoleCP.restype = wintypes.UINT
    if not kernel.GetConsoleCP():
        raise DemoError("Abra el iniciador desde una ventana CMD o PowerShell con consola.")


# Raw, non-inheritable handles intentionally survive until process exit. Closing
# this job earlier would also terminate the launcher, which belongs to the job.
_jobs_until_exit = []


def contain_children_until_exit():
    """Join a kill-on-close job BEFORE spawning any child (including ngrok)."""
    require_console()
    if _jobs_until_exit:
        return

    class BasicLimits(ctypes.Structure):
        _fields_ = [
            ("process_time", ctypes.c_longlong), ("job_time", ctypes.c_longlong),
            ("flags", wintypes.DWORD), ("minimum_working_set", ctypes.c_size_t),
            ("maximum_working_set", ctypes.c_size_t), ("active_processes", wintypes.DWORD),
            ("affinity", ctypes.c_size_t), ("priority", wintypes.DWORD),
            ("scheduling", wintypes.DWORD),
        ]

    class IoCounters(ctypes.Structure):
        _fields_ = [(name, ctypes.c_ulonglong) for name in (
            "read_operations", "write_operations", "other_operations",
            "read_bytes", "write_bytes", "other_bytes",
        )]

    class ExtendedLimits(ctypes.Structure):
        _fields_ = [
            ("basic", BasicLimits), ("io", IoCounters),
            ("process_memory", ctypes.c_size_t), ("job_memory", ctypes.c_size_t),
            ("peak_process_memory", ctypes.c_size_t), ("peak_job_memory", ctypes.c_size_t),
        ]

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateJobObjectW.argtypes = [wintypes.LPVOID, wintypes.LPCWSTR]
    kernel.CreateJobObjectW.restype = wintypes.HANDLE
    kernel.SetInformationJobObject.argtypes = [
        wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD,
    ]
    kernel.SetInformationJobObject.restype = wintypes.BOOL
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    kernel.AssignProcessToJobObject.restype = wintypes.BOOL
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    job = kernel.CreateJobObjectW(None, None)
    if not job:
        raise DemoError("Windows no pudo crear la contencion de procesos; no se inicio la demo.")
    limits = ExtendedLimits()
    limits.basic.flags = 0x00002000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    if (not kernel.SetInformationJobObject(job, 9, ctypes.byref(limits), ctypes.sizeof(limits))
            or not kernel.AssignProcessToJobObject(job, kernel.GetCurrentProcess())):
        kernel.CloseHandle(job)  # The launcher was not assigned on this failure path.
        raise DemoError(
            "Windows no permite contener los procesos en esta consola. "
            "Abra un CMD normal; no se inicio ningun servicio."
        )
    _jobs_until_exit.append(job)


class FileLock:
    """A held Windows byte-range lock; file presence alone is not a lock."""

    def __init__(self, path, label):
        self.path = Path(path)
        self.label = label
        self.stream = None

    def __enter__(self):
        import msvcrt
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self.stream = self.path.open("a+b")
            os.set_inheritable(self.stream.fileno(), False)
            if self.path.stat().st_size == 0:
                self.stream.write(b"\0")
                self.stream.flush()
            self.stream.seek(0)
            msvcrt.locking(self.stream.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            if self.stream is not None:
                self.stream.close()
                self.stream = None
            raise DemoError(
                "No se obtuvo el bloqueo de " + self.label + ". "
                "Compruebe si ya hay una ventana activa y los permisos locales."
            ) from None
        return self

    def __exit__(self, *_):
        if self.stream is not None:
            # Closing the descriptor releases the lock even after abnormal exit.
            self.stream.close()
            self.stream = None


def endpoint_lock_path():
    local = os.environ.get("LOCALAPPDATA")
    if not local:
        raise DemoError("Windows no informo LOCALAPPDATA; no se pudo preparar el bloqueo local.")
    return Path(local) / "PagosOfflineDemo" / "runtime-locks" / "backend-127.0.0.1-8000.lock"


def _private_descriptor():
    """Return an allocated DACL for the current Windows SID and SYSTEM only."""
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    advapi = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.LocalFree.argtypes = [wintypes.LPVOID]
    kernel.LocalFree.restype = wintypes.LPVOID
    advapi.OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)]
    advapi.OpenProcessToken.restype = wintypes.BOOL
    advapi.GetTokenInformation.argtypes = [
        wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
    ]
    advapi.GetTokenInformation.restype = wintypes.BOOL
    advapi.ConvertSidToStringSidW.argtypes = [wintypes.LPVOID, ctypes.POINTER(wintypes.LPWSTR)]
    advapi.ConvertSidToStringSidW.restype = wintypes.BOOL
    advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = [
        wintypes.LPCWSTR, wintypes.DWORD, ctypes.POINTER(wintypes.LPVOID),
        ctypes.POINTER(wintypes.DWORD),
    ]
    advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW.restype = wintypes.BOOL
    token = wintypes.HANDLE()
    if not advapi.OpenProcessToken(kernel.GetCurrentProcess(), 0x0008, ctypes.byref(token)):
        raise DemoError("No se pudo obtener la identidad Windows para proteger la configuracion.")
    sid_text = wintypes.LPWSTR()
    try:
        needed = wintypes.DWORD()
        advapi.GetTokenInformation(token, 1, None, 0, ctypes.byref(needed))  # TokenUser
        if not needed.value or needed.value > 1024 * 1024:
            raise DemoError("Windows no pudo identificar al propietario de la configuracion.")
        user = ctypes.create_string_buffer(needed.value)
        if not advapi.GetTokenInformation(token, 1, user, needed.value, ctypes.byref(needed)):
            raise DemoError("Windows no pudo identificar al propietario de la configuracion.")
        # TOKEN_USER begins with SID_AND_ATTRIBUTES, whose first member is PSID.
        sid = ctypes.cast(user, ctypes.POINTER(wintypes.LPVOID)).contents.value
        if not advapi.ConvertSidToStringSidW(sid, ctypes.byref(sid_text)):
            raise DemoError("Windows no pudo proteger la configuracion del usuario actual.")
        sddl = "D:P(A;;FA;;;" + sid_text.value + ")(A;;FA;;;SY)"
    finally:
        if sid_text:
            kernel.LocalFree(ctypes.cast(sid_text, wintypes.LPVOID))
        kernel.CloseHandle(token)
    descriptor = wintypes.LPVOID()
    if not advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW(
            sddl, 1, ctypes.byref(descriptor), None):
        raise DemoError("Windows no pudo crear los permisos privados de la configuracion.")
    return descriptor


def write_private_atomic(path, data):
    """Create with a protected ACL BEFORE writing bytes, then replace atomically."""
    import msvcrt
    if sys.platform != "win32":
        raise DemoError("La configuracion privada requiere Windows.")
    path = Path(path)
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise DemoError("El destino de configuracion debe ser un archivo local normal.")
    temporary = path.with_name("." + path.name + "." + uuid.uuid4().hex + ".tmp")
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)

    class SecurityAttributes(ctypes.Structure):
        _fields_ = [
            ("length", wintypes.DWORD), ("descriptor", wintypes.LPVOID),
            ("inherit", wintypes.BOOL),
        ]

    kernel.CreateFileW.argtypes = [
        wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
        ctypes.POINTER(SecurityAttributes), wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE,
    ]
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.LocalFree.argtypes = [wintypes.LPVOID]
    kernel.LocalFree.restype = wintypes.LPVOID
    descriptor = _private_descriptor()
    attributes = SecurityAttributes(ctypes.sizeof(SecurityAttributes), descriptor, False)
    try:
        handle = kernel.CreateFileW(str(temporary), 0x40000000, 0, ctypes.byref(attributes), 1, 0x80, None)
    finally:
        kernel.LocalFree(descriptor)
    if handle == ctypes.c_void_p(-1).value:
        raise DemoError("No se pudo crear el archivo privado; la configuracion anterior se conserva.")
    try:
        try:
            descriptor_fd = msvcrt.open_osfhandle(
                handle, os.O_WRONLY | os.O_BINARY | os.O_NOINHERIT,
            )
        except Exception:
            kernel.CloseHandle(handle)
            raise
        with os.fdopen(descriptor_fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except Exception:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        raise DemoError("No se pudo guardar la configuracion privada de forma atomica.") from None
