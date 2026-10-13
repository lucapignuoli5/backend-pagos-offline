# POS de escritorio

Implementación Windows del comercio para Android HCE y ACR122U mediante PC/SC. El modo simulador prueba el contrato y la persistencia, pero no acredita interoperabilidad física.

## Configuración

La configuración se recibe por variables de entorno; no se guardan secretos en el repositorio:

- `TFG_POS_DATABASE`: ruta de la SQLite propia del POS.
- `TFG_POS_MERCHANT_ID`, `TFG_POS_TERMINAL_ID`, `TFG_POS_KEY_ID`.
- `TFG_POS_READER`: parte del nombre PC/SC del lector.
- `TFG_BACKEND_URL`: backend de conciliación.
- `TFG_POS_SIMULATOR=1`: usa el doble HCE local.

En Windows, la clave privada se cifra con DPAPI para el usuario actual. Instalar las dependencias con `requirements-pos.txt` y ejecutar `python -m pos_desktop.app`. Las operaciones de lector y base se realizan fuera del hilo de interfaz.

El simulador permite demostrar los dos acercamientos: enviar solicitud, confirmar en el doble Android, recuperar/verificar el comprobante, persistir la aceptación y entregar el acuse. La pantalla de historial envía la cola durable al backend y conserva por operación los rechazos, conflictos y reintentos progresivos.

