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

## TFG-F3-BE-01 — Exponer la billetera asociada al inicio de sesión

- **Fecha:** 2026-10-13
- **Fase:** 3 — Persistencia y reservas Android
- **Estado:** COMPROBADO
- **Hallazgo o requisito:** Android necesita identificar de forma explícita la billetera cuyo saldo y autorizaciones persiste localmente.
- **Comportamiento anterior:** el login devolvía solamente el token y el tipo.
- **Comportamiento nuevo:** la respuesta incluye `wallet_id` derivado del usuario autenticado (`wallet-{id}`), sin exponer credenciales.
- **Archivos:** `schemas.py`, `main.py`, `REGISTRO_CAMBIOS.md`.
- **Pruebas:** suite backend completa de 21 pruebas correcta en base SQLite temporal; la prueba de login verifica token, rol y `wallet_id` sin usar la base existente ni servicios externos.
- **Limitaciones:** todavía no descarga autorizaciones ni registra claves; no se inicia el backend sobre bases existentes.
- **Commit:** `feat(auth): [TFG-F3-BE-01] devolver billetera del usuario`
- **Impacto académico:** hace explícita la identidad de la billetera para vincular saldo, reservas y conciliación.

## TFG-F3-BE-02 — Reintento idempotente de autorización inicial

- **Fecha:** 2026-10-13
- **Fase:** 3 — Persistencia y reservas Android
- **Estado:** COMPROBADO
- **Hallazgo o requisito:** una respuesta perdida durante el aprovisionamiento no debe consumir dos veces el cupo disponible.
- **Comportamiento anterior:** repetir una solicitud idéntica encontraba el saldo ya comprometido y devolvía conflicto.
- **Comportamiento nuevo:** una autorización activa e intacta con la misma billetera, clave y límites devuelve el mismo identificador sin crear otra fila.
- **Archivos:** `api_v2.py`, `tests/test_api_v2_keys.py`, `REGISTRO_CAMBIOS.md`.
- **Pruebas:** suite backend completa de 21 pruebas correcta en SQLite temporal; la repetición idéntica conserva el ID y una sola fila, mientras una solicitud diferente sigue respetando el saldo comprometido.
- **Limitaciones:** si una autorización ya fue parcialmente consumida, una solicitud posterior se evalúa como una nueva autorización contra el saldo aún disponible.
- **Commit:** `fix(auth): [TFG-F3-BE-02] hacer idempotente el aprovisionamiento`
- **Impacto académico:** documenta la tolerancia a pérdida de respuesta durante el alta inicial offline.

## TFG-F3-BE-03 — Revisión de cierre de persistencia y aprovisionamiento

- **Fecha:** 2026-10-13
- **Fase:** 3 — Persistencia y reservas Android
- **Estado:** COMPROBADO
- **Hallazgo o requisito:** antes de iniciar el POS debía comprobarse que los cambios de autenticación y autorización no rompieran el backend.
- **Comportamiento anterior:** las instrucciones del área todavía describían la API v2 como pendiente de demostración.
- **Comportamiento nuevo:** se registra el estado realmente verificado y sus límites sin atribuir pruebas físicas ni uso de datos reales.
- **Archivos:** `AGENTS.md`, `REGISTRO_CAMBIOS.md`.
- **Pruebas:** 21 pruebas backend correctas en SQLite temporal; estado Git y formato revisados.
- **Limitaciones:** no se abrió la base existente ni se inició el servidor; POS y ACR122U permanecen pendientes.
- **Commit:** `docs(review): [TFG-F3-BE-03] cerrar revision de fase 3`
- **Impacto académico:** separa evidencia automatizada del backend de la interoperabilidad física aún no demostrada.

## TFG-F4-POS-01 — Núcleo durable y simulador del POS de Windows

- **Fecha:** 2026-10-13
- **Fase:** 4 — POS de Windows
- **Estado:** PARCIAL
- **Hallazgo o requisito:** el flujo principal requiere una aplicación de escritorio que cree la solicitud, use PC/SC, verifique el comprobante y persista aceptación antes del acuse.
- **Comportamiento anterior:** no existía `pos_desktop/`; el POS era solamente una propuesta académica.
- **Comportamiento nuevo:** el POS crea y firma solicitudes, ejecuta dos acercamientos APDU, verifica la clave y todos los campos del comprobante, persiste comprobante/acuse antes de entregarlo y tolera reintentos. Incluye SQLite con migración, DPAPI, PC/SC, simulador y pantallas PySide6 con tareas fuera del hilo principal.
- **Decisión:** crear un núcleo Python independiente de PySide6, almacenamiento SQLite propio, claves privadas protegidas con DPAPI, adaptadores PC/SC/simulador y UI con trabajo fuera del hilo principal.
- **Archivos:** `pos_desktop/`, `requirements-pos.txt`, `tests/test_pos_desktop.py`, `REGISTRO_CAMBIOS.md`.
- **Contratos o datos afectados:** protocolo APDU v2, base local del POS, claves POS y evidencia para conciliación.
- **Pruebas:** siete pruebas POS correctas: flujo completo de dos acercamientos e idempotencia, espera sin falsa aceptación, alteración de evidencia, cambio de importe con firma válida, DPAPI real y construcción de las cuatro pantallas PySide6 en modo offscreen; análisis sintáctico correcto. La suite completa alcanza 28 pruebas.
- **Limitaciones:** PySide6 quedó instalado y validado. `pyscard` no ofrece wheel para el Python 3.14 presente y su compilación requiere Microsoft C++ Build Tools; el adaptador PC/SC conserva verificación sintáctica. La prueba ACR122U continúa pendiente hasta disponer del lector físico.
- **Commit:** `feat(pos): [TFG-F4-POS-01] implementar flujo local con simulador`
- **Impacto académico:** cambia el POS de propuesta a implementación demostrable mediante simulador, sin afirmar interoperabilidad física.

## TFG-F4-BE-01 — Distribuir claves públicas confiables

- **Fecha:** 2026-10-13
- **Fase:** 4 — POS de Windows
- **Estado:** COMPROBADO
- **Hallazgo o requisito:** Android y POS deben verificar firmantes registrados antes de quedar sin Internet; el registro existía, pero no había una ruta para obtener las claves públicas activas.
- **Comportamiento anterior:** las pruebas inyectaban claves directamente en las bases locales.
- **Comportamiento nuevo:** una ruta autenticada lista claves activas por propósito con ID, huella, alcance y clave pública; el POS almacena claves de billetera durante el acceso.
- **Archivos:** `schemas.py`, `api_v2.py`, `pos_desktop/backend_client.py`, pruebas y `REGISTRO_CAMBIOS.md`.
- **Contratos o datos afectados:** `GET /api/keys/trusted/{purpose}` y almacenes locales de confianza.
- **Pruebas:** suite backend completa de 26 pruebas correcta en SQLite temporal; se comprueba que la clave registrada aparece con el alcance esperado y que las cinco pruebas POS no afectan datos existentes.
- **Limitaciones:** la lista es adecuada para el prototipo; una instalación productiva requeriría paginación y política de revocación/actualización.
- **Commit:** `feat(keys): [TFG-F4-BE-01] distribuir claves publicas confiables`
- **Impacto académico:** demuestra cómo ambos actores obtienen material público previo a la operación offline.

## TFG-F4-BE-02 — Limitar la distribución de claves por rol

- **Fecha:** 2026-10-13
- **Fase:** 4 — POS de Windows
- **Estado:** COMPROBADO
- **Hallazgo o requisito:** la revisión de fase detectó que un usuario autenticado podía enumerar claves y alcances que no necesita para su rol.
- **Comportamiento anterior:** clientes y comercios podían pedir indistintamente claves de billetera o POS.
- **Comportamiento nuevo:** clientes reciben únicamente claves POS y comercios únicamente claves de billetera; otros propósitos o roles se rechazan.
- **Archivos:** `api_v2.py`, `tests/test_api_v2_keys.py`, `REGISTRO_CAMBIOS.md`.
- **Pruebas:** suite completa de 28 pruebas correcta; incluye acceso permitido del comercio a claves de billetera y rechazo del cliente para ese mismo directorio.
- **Limitaciones:** las claves siguen siendo públicas; la restricción reduce exposición de metadatos y no sustituye una política de directorio a gran escala.
- **Commit:** `fix(keys): [TFG-F4-BE-02] limitar directorio por rol`
- **Impacto académico:** documenta el mínimo material de confianza que necesita cada actor offline.

## TFG-F4-RV-01 — Revisión de cierre del POS simulado

- **Fecha:** 2026-10-13
- **Fase:** 4 — POS de Windows
- **Estado:** COMPROBADO
- **Hallazgo o requisito:** antes de iniciar conciliación debía comprobarse que POS, backend y aprovisionamiento Android siguieran compatibles y sin regresiones.
- **Comportamiento anterior:** el núcleo POS estaba probado, pero las instrucciones aún lo describían como no implementado y el directorio de claves exponía más propósitos de los necesarios.
- **Comportamiento nuevo:** la documentación distingue simulador de hardware; el acceso a claves se limita por rol y el árbol completo pasa sus verificaciones.
- **Archivos:** `AGENTS.md`, `REGISTRO_CAMBIOS.md`; registro consolidado e instrucciones generales fuera del repositorio.
- **Pruebas:** 28 pruebas Python correctas en bases temporales; siete son específicas del POS. PySide6 construye las cuatro pantallas offscreen, DPAPI real cifra/descifra y Android completa JVM, ensamblado, compilación instrumentada y lint.
- **Limitaciones:** no hay ACR122U; `pyscard` requiere un Python con wheel compatible o Microsoft C++ Build Tools. No se declara interoperabilidad física ni medición de latencia.
- **Commit:** `docs(review): [TFG-F4-RV-01] cerrar revision del POS simulado`
- **Impacto académico:** acredita implementación y simulación del POS sin convertirlas en evidencia de hardware.

## TFG-F5-POS-01 — Cola durable de conciliación del POS

- **Fecha:** 2026-10-13
- **Fase:** 5 — Conciliación independiente
- **Estado:** COMPROBADO
- **Hallazgo o requisito:** una aceptación local persistida debe sincronizarse sin depender del teléfono y sin marcar lotes completos por una respuesta HTTP exitosa.
- **Comportamiento anterior:** el POS conservaba evidencia, pero no la enviaba al backend ni registraba intentos/resultados individuales.
- **Comportamiento nuevo:** SQLite v2 conserva intentos, próxima ejecución y último código; el POS envía solicitud/comprobante/acuse, valida IDs y estados individuales, aplica solo cada resultado conocido y reintenta ausentes o transitorios con espera exponencial.
- **Decisión:** migrar la SQLite del POS, enviar evidencia v2 por operación, aplicar cada estado y usar reintentos progresivos solo para fallos transitorios.
- **Archivos:** `pos_desktop/database.py`, `pos_desktop/backend_client.py`, `pos_desktop/sync.py`, `pos_desktop/ui.py`, `pos_desktop/README.md`, `tests/test_pos_desktop.py`, `REGISTRO_CAMBIOS.md`.
- **Pruebas:** nueve pruebas POS correctas, incluidas migración v1→v2 con operación preservada y lote mixto donde solo faltantes se reintentan; la suite completa alcanza 30 pruebas.
- **Limitaciones:** la sesión del comercio se obtiene online y no se guarda en disco.
- **Commit:** `feat(sync): [TFG-F5-POS-01] conciliar cola durable del POS`
- **Impacto académico:** demuestra que la PC puede conciliar independientemente del teléfono.
