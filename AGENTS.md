Leer `../../AGENTS.md` antes de actuar si el contexto general no está cargado; las rutas siguientes parten de esta carpeta.

# Backend de pagos

## Organización existente

- Aplicación Python/FastAPI con módulos planos; no imponer una nueva estructura por capas.
- `main.py`: rutas, autenticación, recargas, integración Mercado Pago, dashboard y sincronización.
- `schemas.py`: contratos Pydantic y validaciones de entrada y salida; mantenerlos coherentes con Android.
- `models.py`: modelos SQLAlchemy; `database.py`: conexión SQLite, sesiones y dependencia de acceso a datos.
- `crypto_utils.py`: verificación criptográfica de comprobantes; revisar también la verificación de firmas de `main.py`.
- `requirements.txt` declara dependencias; no asumir que reproduce todo lo instalado en `venv/`.
- Python/FastAPI es la base existente y documentada de la Entrega 4; consultar la raíz para decisiones sobre Go y sobre el POS de PC.

## Contratos y consistencia

- Antes de cambiar un DTO o ruta, revisar `../Prototipo Pagos Offline Android/app/src/main/java/com/example/prototipopagosoffline/network/`.
- `/sync-offline-payments` recibe importes enteros en centavos y devuelve contadores y resultados individuales.
- Una respuesta HTTP exitosa puede incluir operaciones fallidas; conservar la distinción entre aceptación del lote y de cada operación.
- La integración prevista debe admitir envíos independientes de billetera y POS con el mismo ID; revisar autenticación de cada actor, duplicados y efectos contables antes de ampliar el contrato.
- Revisar validación de importes positivos, límites, unidades y conversiones; hay caminos con Decimal y otros con float.
- Comprobar correspondencia entre datos firmados y campos usados para aplicar el pago; no confiar en afirmaciones independientes del cliente.
- Para firmas, contrastar identificador, payload original, UTF-8, representación Base64/DER y algoritmo con emisor y receptor Android.
- Para persistencia, revisar alcance de commit/rollback, cambios de saldos, registro contable y comportamiento ante reintentos o duplicados.
- Manejar errores conforme a los contratos existentes; no ocultar rechazos de una operación ni exponer detalles sensibles.
- Son criterios de revisión; no afirmar que el código ya garantiza atomicidad, idempotencia o prevención completa del doble gasto.
- Las rutas de Mercado Pago existentes no acreditan liquidación de pagos offline; la demostración acordada usa saldos y recargas simulados.

## Estado implementado verificado al 13/10/2026

- La API v2 dispone de login JWT, registro de claves con prueba de posesión, autorizaciones offline, consulta de saldo, sincronización por resultado y consulta por operación.
- La contabilidad v2 usa importes enteros en centavos, evidencia exacta, asientos únicos, actualización condicionada de saldo y estados idempotentes; las rutas heredadas no aplican movimientos v2.
- La suite actual ejecuta 21 pruebas sobre bases SQLite temporales, incluidas concurrencia, rollback, duplicados, conflicto, clave revocada, lote mixto y reintento del aprovisionamiento.
- Estas pruebas no usan la base existente ni servicios de pago. El POS de escritorio está implementado con SQLite, DPAPI, PySide6, adaptadores PC/SC/simulador y pruebas del flujo completo simulado; no existe todavía evidencia con ACR122U.

## Estado del POS verificado al 13/10/2026

- `pos_desktop/` implementa acceso, importe, solicitud, espera, aceptación local, historial, configuración externa y tareas fuera del hilo de interfaz.
- Siete pruebas específicas cubren el flujo de dos acercamientos, reintento, comprobante alterado, importe cambiado con firma válida, espera sin aceptación, DPAPI real y construcción de UI.
- PySide6 se validó en modo offscreen. `pyscard` no pudo compilarse con Python 3.14 por falta de un wheel y de Microsoft C++ Build Tools; el adaptador permanece verificado solo por sintaxis hasta disponer de un entorno compatible y del lector.

## Entorno y efectos de ejecución

- Usar el entorno virtual de esta carpeta; comprobar `venv/Scripts/python.exe` antes de ejecutar comandos.
- Instalación de dependencias, solo cuando la tarea lo requiera: `.\venv\Scripts\python.exe -m pip install -r requirements.txt`.
- Arranque intencional: `.\venv\Scripts\python.exe -m uvicorn main:app --host 127.0.0.1 --port 8000`.
- No arrancar ni importar `main.py` para una inspección estática: crea tablas al importar y su lifespan puede modificar datos.
- La base configurada en `database.py` es SQLite con ruta relativa al directorio de ejecución; verificar el destino antes de correr.
- Ejecutar `main.py` directamente puede activar un túnel; revisar integraciones y credenciales sin reproducir sus valores.
- Las pruebas que ejecuten la aplicación requieren un entorno de prueba aislado y no deben alcanzar bases históricas ni servicios de pagos reales.
- No considerar instalación, importación o arranque como operaciones inocuas de verificación.

## Verificación y cierre

- Para sintaxis, usar `ast.parse` sobre fuentes sin importarlas ni generar bytecode.
- En la inspección inicial se comprobó sintaxis Python; no se ejecutaron API, conciliación ni integraciones externas.
- No se encontró una suite de pruebas de pagos del backend; no presentar un comando pytest como prueba existente.
- Para cambios funcionales, verificar validación, firma inválida, duplicados, saldo insuficiente, fallos parciales y rollback en entorno aislado.
- Revisar que contratos y estados resultantes sean interpretados correctamente por Android; informar pruebas ejecutadas y limitaciones.
