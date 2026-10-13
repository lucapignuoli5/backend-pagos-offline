# Registro de cambios de backend y POS

Este archivo acompaña los cambios del repositorio. Cada entrada identifica el motivo, la evidencia y el commit asociado sin incluir secretos ni datos personales.

## TFG-F0-BE-01 — Línea base segura del backend

- **Fecha:** 2026-10-13
- **Fase:** 0 — Línea base segura
- **Estado:** COMPROBADO
- **Hallazgo o requisito:** preservar los cambios locales previos sin incorporar credenciales al historial nuevo y evitar efectos incidentales al importar el backend.
- **Comportamiento anterior:** la copia de trabajo contenía configuración sensible literal, habilitaba integraciones externas directamente y creaba tablas al importar `main.py`.
- **Comportamiento nuevo:** configuración mediante variables de entorno, integraciones externas y semillas deshabilitadas por defecto, y creación de tablas limitada al arranque intencional.
- **Decisión:** el estado local previo se conserva como línea base después del saneamiento mínimo obligatorio.
- **Archivos:** `.env.example`, `.gitignore`, `AGENTS.md`, `database.py`, `main.py`, `settings.py`, `crypto_utils.py`, `schemas.py`, `REGISTRO_CAMBIOS.md`.
- **Contratos o datos afectados:** configuración de arranque; no se migran ni abren bases existentes.
- **Pruebas:** análisis sintáctico de todos los módulos Python; búsqueda de patrones de secretos conocidos; importación aislada con SQLite en memoria, semillas e integraciones desactivadas, sin creación de tablas ni acceso externo; `git diff --check` sin errores.
- **Limitaciones:** este commit todavía no implementa autenticación v2, contabilidad atómica ni el POS.
- **Commit:** `chore(baseline): [TFG-F0-BE-01] registrar linea base segura`
- **Impacto académico:** permite distinguir el código heredado auditado de las correcciones posteriores.

## TFG-F1-BE-01 — Contrato criptográfico y transporte NFC v2

- **Fecha:** 2026-10-13
- **Fase:** 1 — Contrato criptográfico y protocolo NFC v2
- **Estado:** COMPROBADO
- **Hallazgo o requisito:** Android, POS y backend necesitan una representación firmada única, sin flotantes ni reconstrucciones ambiguas, y un transporte APDU repetible.
- **Comportamiento anterior:** el backend verificaba cadenas heredadas sin una especificación versionada compartida ni reglas completas de validación y fragmentación.
- **Comportamiento nuevo:** una especificación v2 única define campos exactos, JSON canónico, firmas ECDSA P-256/SHA-256, huellas de claves, límites, mensajes y framing APDU de 160 bytes hasta 4 KiB.
- **Decisión:** definir primero el contrato canónico y sus vectores en Python para que Android y el futuro POS consuman la misma especificación.
- **Archivos:** `protocol_v2.py`, `docs/protocol_v2.md`, `tests/test_protocol_v2.py`, `tests/fixtures/protocol_v2_vectors.json`, `REGISTRO_CAMBIOS.md`.
- **Contratos o datos afectados:** contrato de solicitud, comprobante y acuse v2; framing APDU v2.
- **Pruebas:** 6 pruebas unitarias cubren vector canónico y firma fija, alteración de cada campo, importes inválidos, campos extra, JSON no canónico, fragmentación y exceso de 4 KiB; análisis sintáctico y `git diff --check` correctos.
- **Limitaciones:** la interoperabilidad con Kotlin y hardware se registra por separado; el registro y autorización de claves se implementan en la Fase 2.
- **Commit:** `feat(protocol): [TFG-F1-BE-01] definir contrato criptografico v2`
- **Impacto académico:** formaliza qué datos se autentican y cómo se intercambian en los dos acercamientos NFC.

## TFG-F1-BE-02 — Sobre firmado sin reconstrucción de payload

- **Fecha:** 2026-10-13
- **Fase:** 1 — Contrato criptográfico y protocolo NFC v2
- **Estado:** COMPROBADO
- **Hallazgo o requisito:** el transporte debe preservar exactamente los bytes firmados; enviar un objeto JSON deserializado obligaría a reconstruirlo antes de verificar.
- **Comportamiento anterior:** la especificación indicaba transportar firma y JSON juntos, pero no fijaba una representación inequívoca del sobre.
- **Comportamiento nuevo:** cada mensaje viaja en un sobre canónico con los bytes firmados en `payload_b64` y la firma DER en `signature_b64`; las claves se resuelven desde el registro previo.
- **Decisión:** encapsular los bytes canónicos en Base64 estándar junto con la firma DER/Base64, sin incluir claves públicas no confiables.
- **Archivos:** `protocol_v2.py`, `docs/protocol_v2.md`, `tests/test_protocol_v2.py`, `REGISTRO_CAMBIOS.md`.
- **Contratos o datos afectados:** representación de solicitud, comprobante y acuse sobre APDU y sincronización.
- **Pruebas:** 7 pruebas Python, incluida conservación byte a byte, verificación de firma sobre los bytes recibidos y rechazo de campos de sobre incompatibles.
- **Limitaciones:** la resolución de claves registradas pertenece a las fases de autorización y backend.
- **Commit:** `feat(protocol): [TFG-F1-BE-02] preservar bytes firmados en transporte`
- **Impacto académico:** elimina una fuente de ambigüedad entre la firma producida y la verificada.

## TFG-F2-BE-01 — Esquema v2 y migración preservando datos

- **Fecha:** 2026-10-13
- **Fase:** 2 — Backend seguro y contabilidad atómica
- **Estado:** COMPROBADO
- **Hallazgo o requisito:** el esquema heredado usa importes decimales y no representa roles, billeteras, claves, autorizaciones, evidencia ni libro contable v2.
- **Comportamiento anterior:** `create_all` solo creaba tablas faltantes y no ofrecía una ruta verificable desde bases actuales.
- **Comportamiento nuevo:** el backend agrega roles, billeteras en centavos, terminales, claves, autorizaciones, pagos v2 y asientos; la migración añade el rol y crea una billetera estable por usuario conservando el saldo heredado.
- **Decisión:** incorporar tablas v2 con centavos enteros y una migración incremental que preserve usuarios y saldos heredados.
- **Archivos:** `models.py`, `migrations.py`, `main.py`, `settings.py`, `.env.example`, `tests/test_migrations.py`, `REGISTRO_CAMBIOS.md`.
- **Contratos o datos afectados:** SQLite, usuarios, billeteras, claves, autorizaciones, operaciones y asientos.
- **Pruebas:** 8 pruebas backend correctas; una crea una base SQLite heredada temporal, migra, conserva usuario y saldo, convierte a centavos y comprueba que el backfill sea idempotente.
- **Limitaciones:** los endpoints y la aplicación contable se implementan en unidades posteriores.
- **Commit:** `feat(db): [TFG-F2-BE-01] agregar esquema contable v2`
- **Impacto académico:** establece la representación persistente usada para demostrar idempotencia y atomicidad.

## TFG-F2-BE-02 — Autenticación, claves y autorizaciones v2

- **Fecha:** 2026-10-13
- **Fase:** 2 — Backend seguro y contabilidad atómica
- **Estado:** COMPROBADO
- **Hallazgo o requisito:** las rutas v2 requieren identidad, rol, propiedad de billetera/terminal y claves registradas con prueba de posesión.
- **Comportamiento anterior:** el JWT no incluía rol, el bloqueo podía afectar a todos los usuarios de una IP y las rutas heredadas no aplicaban autorización consistente.
- **Comportamiento nuevo:** JWT incluye identidad y rol; las dependencias Bearer comprueban que el rol siga vigente; las claves P-256 se registran con prueba canónica de posesión, huella y nonce únicos; autorizaciones y saldos exigen propiedad y límites configurados.
- **Decisión:** centralizar autenticación Bearer, registrar claves P-256 mediante prueba firmada exacta y emitir autorizaciones acotadas por los límites configurados.
- **Archivos:** `auth.py`, `api_v2.py`, `schemas.py`, `main.py`, `tests/test_api_v2_keys.py`, `REGISTRO_CAMBIOS.md`.
- **Contratos o datos afectados:** JWT, registro de claves, terminales, autorizaciones y consulta de saldo.
- **Pruebas:** 10 pruebas backend correctas, incluidas prueba de posesión e idempotencia de clave, límites y propiedad de autorización, reserva del cupo autorizado y migración; importación aislada confirma rutas v2 sin crear tablas.
- **Limitaciones:** la sincronización contable se implementa en la siguiente unidad.
- **Commit:** `feat(api): [TFG-F2-BE-02] proteger claves y autorizaciones v2`
- **Impacto académico:** documenta el requisito previo de claves conocidas antes de operar sin conexión.

## TFG-F2-BE-03 — Sincronización idempotente y contabilidad atómica

- **Fecha:** 2026-10-13
- **Fase:** 2 — Backend seguro y contabilidad atómica
- **Estado:** COMPROBADO
- **Hallazgo o requisito:** teléfono y POS pueden sincronizar en cualquier orden; un comprobante sin acuse no debe mover saldos y una operación no puede aplicarse dos veces.
- **Comportamiento anterior:** la ruta heredada reconstruía datos firmados, procesaba estados globales y no modelaba evidencia parcial ni conflictos de contenido.
- **Comportamiento nuevo:** la API conserva evidencia exacta por operación, devuelve resultados individuales, deja comprobantes sin acuse en `PENDING_EVIDENCE`, detecta conflictos y aplica débito, crédito, autorización y dos asientos de forma atómica e idempotente.
- **Decisión:** procesar cada elemento en su propia transacción, conservar sobres exactos y aplicar actualizaciones SQL condicionadas con asientos únicos.
- **Archivos:** `sync_v2.py`, `schemas.py`, `models.py`, `migrations.py`, `api_v2.py`, `main.py`, `protocol_v2.py`, `tests/test_sync_v2.py`, `tests/test_protocol_v2.py`, `REGISTRO_CAMBIOS.md`.
- **Contratos o datos afectados:** `POST /api/offline-payments/sync`, consulta por operación, saldos, autorizaciones y libro contable.
- **Pruebas:** 16 pruebas backend correctas; cubren evidencia parcial, acuse posterior, duplicado idéntico, conflicto de contenido, usuario ajeno, dos pagos concurrentes contra saldo insuficiente, fallo simulado entre actualizaciones y vencimiento previo al acuse.
- **Limitaciones:** SQLite serializa escritores y puede devolver `RETRYABLE_ERROR` bajo contención; los clientes deben reintentar ese resultado. Las pruebas usan bases temporales, no datos existentes.
- **Commit:** `feat(sync): [TFG-F2-BE-03] aplicar pagos v2 atomicamente`
- **Impacto académico:** aporta evidencia de conciliación posterior, duplicados y resultados individuales.

## TFG-F2-BE-04 — Endurecimiento de errores de conciliación

- **Fecha:** 2026-10-13
- **Fase:** 2 — Backend seguro y contabilidad atómica
- **Estado:** COMPROBADO
- **Hallazgo o requisito:** la revisión de cierre distinguió conflictos permanentes de fallos transitorios de base y exigió conservar la evidencia usada para rechazar.
- **Comportamiento anterior:** cualquier `IntegrityError` sin operación concurrente se informaba como conflicto y un rollback por saldo podía descartar el acuse recién recibido.
- **Comportamiento nuevo:** nonce reutilizado conserva semántica de conflicto; fallos internos sin evidencia conflictiva devuelven `RETRYABLE_ERROR`; los rechazos contables conservan el acuse recibido.
- **Decisión:** clasificar nonce reutilizado como conflicto y otros fallos internos como reintentables; restaurar el acuse al persistir un rechazo contable.
- **Archivos:** `sync_v2.py`, `tests/test_sync_v2.py`, `REGISTRO_CAMBIOS.md`.
- **Contratos o datos afectados:** resultados individuales y evidencia persistida.
- **Pruebas:** 17 pruebas backend correctas, incluida clave revocada sin movimiento y trigger SQLite que interrumpe el crédito, revierte todo y produce resultado reintentable.
- **Limitaciones:** se valida con inyección controlada sobre SQLite temporal.
- **Commit:** `fix(sync): [TFG-F2-BE-04] clasificar fallos transitorios`
- **Impacto académico:** permite explicar por qué el cliente reintenta fallos internos sin confundirlos con duplicados maliciosos.

## TFG-F2-BE-05 — Cierre de autenticación y errores seguros

- **Fecha:** 2026-10-13
- **Fase:** 2 — Backend seguro y contabilidad atómica
- **Estado:** COMPROBADO
- **Hallazgo o requisito:** el cierre de fase debe comprobar el bloqueo de login, los claims de rol y que Pydantic no refleje credenciales recibidas.
- **Comportamiento anterior:** el usuario inexistente evitaba la verificación costosa de contraseña y faltaban pruebas específicas de bloqueo y respuesta segura.
- **Comportamiento nuevo:** el login usa `bcrypt` directamente, iguala el costo del usuario inexistente, limita por combinación IP/identificador, emite rol vigente en JWT y devuelve errores 422 sin los valores recibidos.
- **Decisión:** usar la verificación ficticia de Passlib y probar las fronteras de autenticación sin iniciar el backend ni tocar su base configurada.
- **Archivos:** `main.py`, pruebas de autenticación y `REGISTRO_CAMBIOS.md`.
- **Contratos o datos afectados:** `/api/login`, JWT y errores 422.
- **Pruebas:** 21 pruebas backend correctas; incluyen JWT con rol, alcance y expiración del bloqueo, ausencia de contraseña en la respuesta de validación, lote mixto y compatibilidad limpia de hash/verificación.
- **Limitaciones:** el bloqueo sigue siendo memoria local del proceso y no sustituye un limitador distribuido.
- **Commit:** `fix(auth): [TFG-F2-BE-05] cerrar autenticacion segura`
- **Impacto académico:** documenta las propiedades realmente probadas del acceso al prototipo.
