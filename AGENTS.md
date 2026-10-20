Leer `../../AGENTS.md` y este archivo antes de trabajar. Backend/POS y Android son repositorios Git independientes.

# Backend y POS — contexto vigente al 15/10/2026

## Mapa y alcance

- Python/FastAPI, Pydantic, SQLAlchemy y SQLite. Mantener convenciones de módulos existentes; no imponer una reestructuración general.
- `main.py`: aplicación, login común, rutas históricas, integración opcional y consola. `api_v3.py`/`sync_v3.py`: autorizaciones, cierres, recargas simuladas, conciliación y resoluciones v3.
- `api_v2.py`/`sync_v2.py`: registro/confianza/saldo compartidos y compatibilidad histórica. La presencia de rutas sin v3 no significa que un pago nuevo sea v2.
- `schemas.py`, `models.py`, `database.py`, `migrations.py` y módulos criptográficos definen contratos, persistencia, evolución y confianza. Revisar productores y consumidores Android/POS antes de cambiarlos.
- `pos_desktop/`: Python/PySide6, SQLite, DPAPI, adaptadores PC/SC y simulador. Persistencia en `pos_desktop/database.py`, versión 5; no confundir versión de esquema con versión de contrato.
- El POS principal requiere Windows y ACR122U. El lector todavía no está disponible; la implementación y las simulaciones no acreditan interoperabilidad física.
- Saldos y recargas simulados; no liquidación real ni certificación comercial. Mercado Pago opcional y deshabilitado por defecto.

## Contratos y contabilidad a preservar

- Pagos nuevos v3; evidencia v2 solo por inventario histórico controlado, cerrado por defecto. Conservar bytes, firmas, IDs, claves y movimientos antiguos.
- `/sync-offline-payments` y otras rutas mutantes heredadas responden retirada explícita; no recomendarlas para operaciones nuevas. Conciliación actual: `/api/v3/offline-payments/sync`.
- Revisar importes enteros en centavos, límites configurados, claves registradas, alcance, tiempos, nonce, índices, firmas sobre bytes originales y digests. No usar reconstrucciones para validar evidencia histórica.
- Una respuesta HTTP 200 no acepta todo un lote. Distinguir submission_status, operation_status, final y resolución firmada por operación.
- Reservas/compromisos se mantienen ante evidencia pendiente, contradictoria o entrega incierta. Vencimiento limita emisión, no libera automáticamente fondos pendientes ni impide conciliación tardía válida.
- Preservar resultados finales e idempotencia; revisar transacciones, rollback, concurrencia y SQL condicionado antes de afirmar ausencia de doble contabilización.
- Revocación con fecha efectiva y emisores públicos históricos fijados están implementados; eso no acredita todos los casos de seguridad. Identidad privada emisora externa protegida por DPAPI; nunca copiarla a Git ni logs.
- Prevención completa del doble gasto entre comercios aislados sigue como riesgo residual del alcance académico.

## Demostración y ejecución local

- Entorno adicional `.venv313`: CPython 3.13.13 x64; `requirements-manual.lock`, incluido pyscard 2.3.1. Se conserva el entorno `venv`; no borrarlo ni instalar dependencias incidentalmente.
- `tools.prepare_demo` crea exclusivamente un directorio externo nuevo. Demo existente: `C:\Users\anita\TFG-Demo-Manual`. No recrear base, cuentas, emisor ni configuración para solucionar fallos de conexión.
- `tools.run_demo` carga configuración DPAPI por acción explícita. `INICIAR_DEMO.cmd` de la carpeta externa abre backend/ngrok; Enter los detiene. Dominio: `https://unfailing-bless-thrift.ngrok-free.dev/`.
- `demo_access.py`: `/api/demo/device-login`, deshabilitado salvo DEMO_DEVICE_LOGIN_ENABLED=true. El launcher demo lo habilita; crea cuenta/billetera simulada por instalación/rol, o renueva sesión verificando secreto. Reingresar no reinicia saldo.
- Límites por defecto: cliente 10.000 ARS, comercio cero, pago 1.000 ARS, diez pagos por autorización, 24 horas de autorización y 120 segundos de solicitud; contrastar configuración efectiva. Máximo predeterminado de 100 cuentas automáticas demo.
- No compartir identidad entre teléfonos. Nuevas cuentas demo no heredan saldo/historial anterior; cuentas históricas y su evidencia deben conservarse.
- `tools.run_demo android-config` genera `demo.local.properties` ignorado de Android: solo URL, emisor público y opción de instalación aislada. No incrustar contraseñas/JWT. Android Studio y launcher deben producir la misma URL efectiva.
- `demo_events.py`, `demo_log_config.json` y launcher retransmiten eventos permitidos a consola y backend.log. Prohibidos cuerpos, headers, contraseñas, tokens, claves, datos personales y excepciones SQL parametrizadas.
- Los pagos offline aparecen en el servidor al sincronizar. Distinguir aplicación contable tras commit de envío repetido o consulta de resultado.
- Guía operativa: `GUIA_PRUEBA_MANUAL.md`. Android mantiene su guía `SINCRONIZACION_AUTOMATICA.md`; revisar ambos extremos si cambia conciliación.

## Seguridad del entorno

- `database.py` usa DATABASE_URL y conserva fallback relativo `sqlite:///./offline_payments.db`. Seleccionar y comprobar explícitamente el destino antes de cualquier ejecución; no asumir que arrancar el backend sea inocuo.
- `main.py` ejecuta migraciones y create_all en lifespan. No arrancar sobre bases originales como verificación. Importar tampoco es una técnica de revisión de sintaxis ni garantía de ausencia de efectos.
- No ejecutar herramientas administrativas, migraciones, POS, servidor, túnel o integraciones para validar cambios sin autorización. No usar servicios de pagos reales.
- No leer/imprimir secretos cuando alcance inspeccionar su configuración y consumidores. No reproducir valores en instrucciones, registros, comandos visibles o respuestas.
- Sintaxis permitida cuando corresponda: ast.parse sin importar la aplicación ni generar bytecode. Las futuras pruebas ejecutadas deben seleccionar bases temporales y proveedores simulados antes de importar módulos.

## Evidencia actual y límites

- Corte de programación previo a esta edición: `cbc9780`. C8 verificó sintaxis Python; Android compiló APK e instrumentadas. No se ejecutaron suites, simuladores, benchmarks ni instrumentadas durante estas correcciones.
- Los antecedentes de 41 pruebas backend, 24 JVM, once POS y mediciones simuladas pertenecen a cortes anteriores. La auditoría R01–R34 invalidó el cierre integral: no presentarlos como regresión aprobada del código actual.
- Usuario informó pagos físicos QR y NFC entre dos teléfonos, conciliación y actualización automática al recuperar Internet. Evidencia manual informada, sin ensayo controlado ni garantía de todos los escenarios.
- Se observaron logs de login, registro, autorizaciones y ACCEPTED v3; una lectura diagnóstica mode=ro del 14/10 mostró saldo confirmado del comercio aunque la UI antigua mostraba cero. La pantalla fue corregida en Android, sin repetir ni alterar pagos.
- La diferencia de reloj produjo un fallo de reserva y el usuario informó resolverlo sincronizando horas. No eliminar controles temporales para ocultarlo.
- Pendientes de validación agrupada: migraciones reales, rollback, concurrencia, duplicados, pérdida de respuestas, estados mixtos, cuenta/sesión y revocación. ACR122U, PC/SC y POS físico siguen pendientes.
- El arranque del servidor/túnel y los pagos recientes fueron realizados por el usuario. No atribuirlos a pruebas ejecutadas por el agente ni afirmar que esta edición documental los verificó.

## Trabajo y cierre

- Registrar Git inicial/final y conservar cambios previos. Cada unidad: ID, entrada EN PROGRESO en REGISTRO_CAMBIOS.md, revisión y commit local junto con documentación real. Sin push.
- Última autorización: no pruebas, lint, simuladores, benchmarks, pagos ni arranques. Únicamente sintaxis Python y compilación Android cuando la tarea lo requiera. Edición documental: solo lectura y diff, sin volver a compilar.
- Antes de contratos HTTP revisar Android `network/ApiService.kt`, `SyncItem.kt`, protocolos y sincronizadores, además de `pos_desktop/backend_client.py`, servicio y cola. Evaluar recorridos completos, no módulos aislados.
- Actualizar registro consolidado y decisiones/instrucciones afectadas. No reescribir Entrega 4 ni fuentes originales.
- Informar implementación, evidencia estática, compilación, ejecución real, informe manual y pendientes por separado. No declarar resuelto un hallazgo por existir un commit, una prueba escrita o una entrada de registro.

## Publicación autorizada — 19/10/2026

El usuario autorizó explícitamente subir los commits actuales a origin/main con
explicaciones específicas en español. Esta autorización prevalece sobre la regla
anterior Sin push para esta publicación; no implica permiso general para publicar
cambios futuros. No reescribir historia ni usar force-push. Ver
PUBLICACION_GITHUB_2026-10-19.md; documentos remotos antiguos se preservan como
antecedentes y no revierten el contrato v3 ni habilitan integraciones reales.

## Inventario de limpieza — 19/10/2026

Ver INVENTARIO_LIMPIEZA_2026-10-19.md del área y el inventario general en la raíz.
Esta unidad clasifica candidatos; no retira código, scripts, cachés, bases o claves.
El usuario autorizó borrar APK generados, pero la revisión automática rechazó
ambos comandos antes de ejecutar. Los cuatro APK Android/demo siguen presentes;
no afirmar que se borraron ni que se liberó espacio. No ejecutar las propuestas
de código de forma incidental. Sin pruebas, compilación, instalación ni push.

## Recuperación de autorizaciones C9 — 20/10/2026

- El backend implementa campos `held_cents`, liberación no emitida/rechazada y fase OPEN/SEALED/SETTLED; `offline_commitment_claims` registra comprobantes v3 validados aunque falte el acuse.
- El cierre requiere coincidencia del manifiesto firmado con todas las operaciones y evidencias conocidas, verifica alcance/firmas/revocación efectiva, conserva los bytes para reintento y libera solo el presupuesto no emitido.
- Un pago pendiente incluido conserva su compromiso tras el cierre; un acuse tardío exacto puede conciliarse. Evidencia omitida o contradictoria bloquea nuevas autorizaciones.
- La emisión reserva hasta el saldo libre real; el reintento de un request_id valida el cuerpo original y devuelve el grant existente. El balance incluye compromisos de todas las fases e historial de autorizaciones.
- C9-BE-01 está IMPLEMENTADA / VALIDACIÓN PENDIENTE: únicamente análisis AST y revisión estática. Migración, HTTP, transacciones concurrentes y recuperación real no fueron ejecutados ni comprobados.
