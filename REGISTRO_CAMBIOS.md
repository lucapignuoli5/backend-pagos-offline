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

## TFG-F5-BE-01 — Verificar ambos órdenes de conciliación

- **Fecha:** 2026-10-14
- **Fase:** 5 — Conciliación independiente
- **Estado:** COMPROBADO
- **Hallazgo o requisito:** la conciliación debe admitir que el POS o el teléfono llegue primero y debe mantener un único movimiento contable ante repeticiones.
- **Comportamiento anterior:** existía evidencia automatizada del orden teléfono→POS→teléfono, pero no una prueba explícita del orden POS→teléfono.
- **Comportamiento nuevo:** una prueba separada sincroniza primero la evidencia completa del POS, después la evidencia sin acuse del teléfono y finalmente repite el POS; los tres intentos obtienen el mismo resultado aceptado y solo existen dos asientos contables.
- **Decisión:** fijar ambos órdenes como comportamiento contractual del endpoint v2.
- **Archivos:** `tests/test_sync_v2.py`, `REGISTRO_CAMBIOS.md`.
- **Contratos o datos afectados:** idempotencia de `POST /api/offline-payments/sync` para evidencia parcial o completa de una operación ya aceptada.
- **Pruebas:** 31 pruebas `unittest` correctas en SQLite temporal; la nueva prueba acredita POS→teléfono→POS, y la existente teléfono→POS→teléfono. En ambos casos persisten exactamente dos asientos para una operación aceptada.
- **Limitaciones:** prueba el orden lógico del servidor; la entrega física sigue pendiente del ACR122U.
- **Commit:** `test(sync): [TFG-F5-BE-01] verificar ambos ordenes de conciliacion`
- **Impacto académico:** aporta evidencia reproducible de conciliación independiente sin doble aplicación.

## TFG-F5-RV-01 — Revisión de cierre de conciliación independiente

- **Fecha:** 2026-10-14
- **Fase:** 5 — Conciliación independiente
- **Estado:** COMPROBADO
- **Hallazgo o requisito:** antes de adaptar flujos secundarios debe comprobarse que backend, POS y Android conservan contratos, idempotencia, reservas y resultados individuales.
- **Comportamiento anterior:** las unidades de conciliación estaban implementadas, pero las instrucciones aún informaban conteos y estado anteriores.
- **Comportamiento nuevo:** las instrucciones reflejan 31 pruebas, nueve pruebas POS, colas independientes y ambos órdenes; los contratos y estados coinciden con Android.
- **Decisión:** repetir las suites aisladas, revisar estados Git y documentar por separado la evidencia automatizada y las pruebas físicas pendientes.
- **Archivos:** `AGENTS.md`, `REGISTRO_CAMBIOS.md`; registro consolidado e instrucciones generales fuera del repositorio.
- **Pruebas:** puerta final correcta: 31 pruebas `unittest` en bases temporales; Android completa 16 pruebas JVM, APK debug, compilación instrumentada y lint. Diffs y estados Git revisados.
- **Limitaciones:** no se inicia la API, no se usan bases existentes ni servicios externos; hardware pendiente.
- **Commit:** `docs(review): [TFG-F5-RV-01] cerrar conciliacion independiente`
- **Impacto académico:** fija la evidencia que habilita la adaptación de QR/TCP sin sobredimensionar el resultado.

## TFG-F6-BE-01 — Aislar e idempotentizar recargas externas

- **Fecha:** 2026-10-14
- **Fase:** 6 — Flujos secundarios e integraciones
- **Estado:** COMPROBADO
- **Hallazgo o requisito:** el webhook opcional podía acreditar repetidamente el mismo pago y el código heredado imprimía payloads, huellas y datos de operaciones.
- **Comportamiento anterior:** cada notificación aprobada sumaba saldo sin un identificador durable y se emitían trazas sensibles de firmas y comprobantes.
- **Comportamiento nuevo:** cada pago aprobado se registra por proveedor e identificador antes de acreditar; una repetición idéntica devuelve `duplicate`, un contenido distinto devuelve conflicto y usuario/billetera se actualizan en la misma transacción. Se eliminaron trazas heredadas de payloads, firmas, huellas y operaciones.
- **Decisión:** conservar Mercado Pago deshabilitado por defecto, registrar cada pago del proveedor con unicidad y probarlo solo con un SDK simulado.
- **Archivos:** `models.py`, `main.py`, `crypto_utils.py`, `tests/test_mercadopago.py`, `AGENTS.md`, `REGISTRO_CAMBIOS.md`.
- **Contratos o datos afectados:** webhook opcional, tabla `external_payment_events`, saldo heredado y saldo confirmado v2.
- **Pruebas:** 33 pruebas `unittest` correctas en bases temporales; el SDK simulado repite el mismo webhook y acredita una sola vez, y el mismo ID con otro importe devuelve conflicto sin una segunda acreditación.
- **Limitaciones:** no se usarán credenciales ni servicios reales.
- **Commit:** `fix(integration): [TFG-F6-BE-01] hacer idempotente el webhook simulado`
- **Impacto académico:** delimita la recarga externa como integración opcional y separada del pago offline.

## TFG-F6-RV-01 — Revisar integraciones y flujos secundarios

- **Fecha:** 2026-10-14
- **Fase:** 6 — Flujos secundarios e integraciones
- **Estado:** COMPROBADO
- **Hallazgo o requisito:** cerrar la fase solo después de revisar webhook, configuración, canales móviles, datos sensibles y regresiones en ambos repositorios.
- **Comportamiento anterior:** las unidades estaban probadas por separado, sin una evidencia consolidada posterior a todos los cambios de fase.
- **Comportamiento nuevo:** la integración externa permanece deshabilitada por defecto e idempotente en simulación; Android usa solicitud, comprobante y acuse v2 para QR/TCP y lector NFC móvil, sin registro HTTP sensible y con configuración externa efectiva.
- **Decisión:** conservar Mercado Pago como integración opcional, mantener los canales móviles como secundarios y habilitar la fase 7 únicamente después de repetir las suites completas y revisar los estados Git.
- **Archivos:** `AGENTS.md`, `REGISTRO_CAMBIOS.md`; las correcciones de revisión Android se registran en su repositorio con el mismo ID.
- **Contratos o datos afectados:** ninguno adicional; se confirmó el contrato v2 compartido y el aislamiento de la integración externa.
- **Pruebas:** 33 pruebas backend en SQLite temporal; 24 pruebas JVM Android, APK debug, compilación instrumentada y lint desde resolución limpia; búsquedas estáticas de secretos y trazas sensibles.
- **Limitaciones:** no se ejecutaron servicios de pago reales, dos teléfonos físicos, ACR122U ni mediciones de latencia.
- **Commit:** `docs(review): [TFG-F6-RV-01] cerrar flujos secundarios`
- **Impacto académico:** acredita código y simuladores, manteniendo explícita la evidencia física y experimental pendiente.

## TFG-F7-BE-01 — Generar evidencia temporal reproducible del simulador

- **Fecha:** 2026-10-14
- **Fase:** 7 — Evidencia final y documentación académica
- **Estado:** COMPROBADO
- **Hallazgo o requisito:** ejecutar al menos veinte repeticiones por configuración disponible, separar confirmación humana y reportar mediana y percentil 95 sin atribuir resultados al ACR122U.
- **Comportamiento anterior:** el flujo POS simulado tenía pruebas funcionales, pero no un ejecutor ni un resultado temporal reproducible.
- **Comportamiento nuevo:** un ejecutor aislado crea operaciones temporales, excluye tres calentamientos, mide veinte repeticiones de entrega de solicitud y comprobante/acuse con la confirmación fuera del cronómetro, y conserva muestras y resumen JSON.
- **Decisión:** medir por separado entrega electrónica de solicitud y recuperación de comprobante/acuse con `perf_counter_ns`; preparar la confirmación simulada fuera del intervalo y calcular p95 por rango más próximo.
- **Archivos:** `benchmarks/pos_simulator_latency.py`, `tests/test_benchmark.py`, `evidence/pos_simulator_latency_2026-10-14.json`, `evidence/README.md`, `AGENTS.md`, `REGISTRO_CAMBIOS.md`.
- **Contratos o datos afectados:** ninguno; se mide el flujo simulado existente con base SQLite temporal y sin red.
- **Pruebas:** 35 pruebas backend correctas. En 20 repeticiones, la entrega de solicitud obtuvo mediana 20,820600 ms y p95 33,827300 ms; comprobante y acuse, mediana 32,770000 ms y p95 37,663900 ms; total electrónico, mediana 55,199650 ms y p95 65,045300 ms.
- **Limitaciones:** el simulador en memoria no representa USB, PC/SC, RF, Android real ni confirmación humana; la cifra no valida el objetivo de p95 en hardware.
- **Commit:** `test(evidence): [TFG-F7-BE-01] medir flujo pos simulado`
- **Impacto académico:** aporta una línea base reproducible sin presentar la meta de 500 ms como validada físicamente.

## TFG-F7-RV-01 — Completar escenarios obligatorios de revisión final

- **Fecha:** 2026-10-14
- **Fase:** 7 — Evidencia final y documentación académica
- **Estado:** COMPROBADO
- **Hallazgo o requisito:** el mapeo final detectó que varias condiciones obligatorias estaban cubiertas solo de manera implícita y no tenían una prueba nominal independiente.
- **Comportamiento anterior:** clave revocada, duplicados y flujo idempotente estaban probados, pero no clave desconocida, firmante ajeno, terminal incorrecta, ventana vencida, nonce reutilizado, acuse perdido, segundo acercamiento interrumpido ni fallo posterior a actualizar ambos saldos.
- **Comportamiento nuevo:** cada escenario devuelve rechazo, conflicto o reintento según contrato; los cortes de transporte se recuperan sin duplicar y los fallos SQL revierten autorización, saldos, operación y asientos.
- **Decisión:** agregar evidencia específica sin cambiar la lógica que ya satisfacía los contratos.
- **Archivos:** `tests/test_sync_v2.py`, `tests/test_pos_desktop.py`, `AGENTS.md`, `REGISTRO_CAMBIOS.md`.
- **Contratos o datos afectados:** ninguno.
- **Pruebas:** suite completa de 41 pruebas correcta en bases temporales; seis casos nuevos cubren las condiciones enumeradas.
- **Limitaciones:** continúan pendientes las mismas pruebas físicas e instrumentadas; los cortes se simulan en el transporte en memoria.
- **Commit:** `test(review): [TFG-F7-RV-01] completar escenarios obligatorios`
- **Impacto académico:** hace trazable la matriz de pruebas mínimas y evita inferir cobertura a partir de casos más amplios.


## TFG-C0-BE-01 — Preparar correcciones de auditoría

- **Fecha:** 2026-10-14
- **Fase:** C0
- **Estado:** COMPROBADO
- **Hallazgos:** R31, R32; matriz de seguimiento R01–R34.
- **Anterior:** cierre previo con pruebas parciales y defectos de integración diagnosticados.
- **Nuevo previsto:** línea base explícita, verificaciones aisladas y contrato v3 planificado.
- **Decisión:** conservar datos y evidencia v2; commits locales, sin push ni pagos reales.
- **Base Git:** `9abecf0`, árbol limpio antes de la unidad.
- **Archivos:** AGENTS.md, REGISTRO_CAMBIOS.md, main.py (anotaciones diferidas), tools/safe_tests.py, tests/test_safe_tests.py, docs/safe_verification.md, requirements-verification.lock y evidence/c0_preserved_files.json.
- **Contratos/datos:** ninguna migración ejecutada; v3 todavía no implementado.
- **Pruebas:** revisión independiente C0 aprobada; estados Git y diff-check correctos; hashes de ambas bases y ambos Word conservados. Backend completa 43 pruebas con CPython 3.13.13 en base temporal y reloj histórico explícito; pyscard 2.3.1 importado sin acceder al lector. Android solo cambia guías/instrucciones y no requiere repetir el build de código.
- **Limitaciones:** ACR122U y Android físico no disponibles.
- **Commit:** `chore(audit): [TFG-C0-BE-01] preparar correcciones trazables`
- **Impacto académico:** separar auditoría, implementación y evidencia; no actualizar Entrega 4.

- **Incidencia de entorno:** el primer intento CPython 3.13 falló al evaluar una anotación legacy `ec`; se añadió evaluación diferida. No se corrigen aún esas funciones heredadas ni R19. El entorno anterior se conserva y el nuevo está fuera del repositorio.


## TFG-C1-BE-01 — Contrato firmado v3 interoperable

- **Fecha:** 2026-10-14
- **Fase:** C1
- **Estado:** COMPROBADO
- **Hallazgos:** R01, R02, R09, R16, R20, R33, R34.
- **Anterior:** sobres v2 incompatibles y ausencia de autorización verificable.
- **Nuevo previsto:** contrato v3 estricto y autorización/cierre/resolución firmados; compatibilidad v2 sin re-firmar; pruebas completas cruzadas.
- **Decisión:** bytes originales, digests de payload, mensajes independientes hasta 4096 bytes, UTC segundos y ECDSA P-256/DER canónico.
- **Archivos:** `protocol_v3.py`, `protocol_v2.py` (compatibilidad de sobres históricos y versión estricta), `tests/test_protocol_v3.py`, `tests/fixtures/protocol_v3_vectors.json`, `tests/fixtures/protocol_v3_kotlin_vectors.json` (bytes originales JVM públicos), `docs/protocol_v3.md`, `tools/verify_cross_language.py`, `REGISTRO_CAMBIOS.md`.
- **Contratos/datos:** v3 nuevo; compatibilidad exterior en v2 preservando bytes firmados; ningún blob v2 ni base existente se modifica.
- **Pruebas:** 16 pruebas puras Python aprobadas en `tests/test_protocol_v3.py` (siete sobres completos, alteración de campos, firmante ajeno, vínculos, cierre, tipos estrictos, overflow, padding 0/1/2, DER de curva desconocida con `ProtocolError`, JSON malformado, UTC, alcance POS y capacidades SELECT). Verificador cruzado `tools/verify_cross_language.py` valida 7 vectores originales Python, 7 vectores de la fixture Kotlin y los 7 vectores generados en tiempo de ejecución por Android JVM (`CROSS_LANGUAGE_VERIFIED=7`). Suite completa segura aislada (`python -B tools/safe_tests.py --legacy-clock`) completó 61 pruebas exitosas bajo CPython 3.13.13; `git diff --check` sin errores.
- **Limitaciones:** conexión a persistencia y transportes se completa en C2–C5.
- **Commit:** `feat(protocol): [TFG-C1-BE-01] definir mensajes v3 verificables`
- **Impacto académico:** contrato nuevo; no se atribuye flujo integrado ni hardware hasta sus pruebas.


## TFG-C1-BE-02 — Proteger la clave emisora fuera del repositorio

- **Fecha:** 2026-10-14
- **Fase:** C1
- **Estado:** COMPROBADO
- **Hallazgos:** R02, R09 y configuración R31.
- **Anterior:** no existe emisor de autorizaciones verificables.
- **Nuevo previsto:** identidad emisora P-256 cifrada mediante DPAPI, con huella fijada externamente y creación explícita sin sobrescritura.
- **Decisión:** leer ruta externa; nunca generar otra identidad silenciosamente ni almacenar claves privadas en Git.
- **Archivos:** `issuer_keys.py`, `tests/test_issuer_keys.py`, `REGISTRO_CAMBIOS.md`.
- **Contratos/datos:** firma de mensajes v3; sin bases existentes.
- **Pruebas:** 2 pruebas unitarias en `tests/test_issuer_keys.py` ejecutadas dentro de la suite segura aislada de 61 pruebas (`tools/safe_tests.py --legacy-clock`); verifican creación con DPAPI, prohibición de sobrescritura, pin de huella SHA-256 de 64 caracteres hex y rechazo explícito si la ruta de identidad privada está dentro de cualquier repositorio Git.
- **Limitaciones:** protección local por usuario Windows, no acredita hardware confiable ni gestión comercial de claves.
- **Commit:** `feat(keys): [TFG-C1-BE-02] proteger emisor externo v3`
- **Impacto académico:** explicitar confianza en el emisor y límites de protección local.


## TFG-C2-BE-01 — Consistencia contable atómica y corrección de rutas

- **Fecha:** 2026-10-14
- **Fase:** C2
- **Estado:** COMPROBADO
- **Hallazgos:** R05, R12, R16, R17, R18, R19, R30.
- **Anterior:** recargas y pagos actualizaban saldos sin sincronía entre `User.saldo_real` y `Wallet.confirmed_balance_cents`; recargas no usaban SQL atómico; emisión de autorizaciones permitía carreras de sobreasignación; ruta `/verify-signature` fallaba por nombres de parámetros incompatibles; login no reconocía alias de billetera y truncaba silenciosamente en bcrypt; timestamps no garantizaban formato canónico UTC en segundos.
- **Nuevo previsto:** sincronización bidireccional estricta de saldos; updates atómicos en SQL; exclusión mutua en emisión de autorizaciones; normalización de alias de login y manejo seguro de contraseñas largas; corrección de firma en `/verify-signature`; timestamps UTC estrictos en segundos.
- **Decisión:** actualizar simultáneamente `saldo_real` y `confirmed_balance_cents` con deltas atómicos; serializar emisión por billetera; admitir alias `wallet-*`, `terminal-*` y `merchant-*`; manejar contraseñas extensas con hash SHA-256 intermedio si superan el límite de bcrypt; corregir firma de `verify_payment_contract_signature` aceptando formato PEM y DER.
- **Archivos:** `main.py`, `api_v2.py`, `crypto_utils.py`, `sync_v2.py`, `tests/test_c2_accounting.py`, `REGISTRO_CAMBIOS.md`.
- **Contratos/datos:** cuentas y saldos en pesos y centavos; sin migraciones de esquema requeridas.
- **Pruebas:** 5 pruebas dedicadas en `tests/test_c2_accounting.py` integradas a la suite segura (`tools/safe_tests.py --legacy-clock`) para un total de 66 pruebas aprobadas: compatibilidad de `/verify-signature` con kwargs de schemas y PEM/DER; hashing y verificación segura de contraseñas de más de 72 bytes evitando colisión por truncamiento; login con alias `wallet-1`, `merchant-2` y `terminal-c2`; recargas concurrentes con 10 hilos sin pérdida de movimientos; y emisión concurrente de autorizaciones con límite atómico estricto impidiendo sobreasignación. `git diff --check` limpio.
- **Limitaciones:** sin bases de datos reales ni pagos monetarios externos.
- **Commit:** `feat(accounting): [TFG-C2-BE-01] garantizar consistencia contable y corregir rutas`
- **Impacto académico:** elimina discrepancias de saldo contable y defectos de integración en autenticación y verificación criptográfica legacy.


## TFG-C2-BE-02 — Conciliación tardía e idempotencia estricta

- **Fecha:** 2026-10-14
- **Fase:** C2
- **Estado:** COMPROBADO
- **Hallazgos:** R03, R04.
- **Anterior:** la conciliación offline rechazaba pagos válidos si la sincronización ocurría después del vencimiento de la autorización (`expires_at > now` evaluado en tiempo de sincronización); reenvíos de evidencia en estados finales podían recalcular transitoriamente o generar respuestas inestables.
- **Nuevo previsto:** admitir conciliación tardía de comprobantes emitidos válidamente dentro de la ventana de autorización; garantizar inmutabilidad e idempotencia estricta de resultados finales ante reenvíos sucesivos.
- **Decisión:** retirar la restricción de reloj en tiempo de sincronización dentro de `_apply_payment`, manteniendo la validación estricta de que la emisión del comprobante ocurrió dentro de la ventana de validez de la autorización; retornar el estado final persistido de forma determinista ante cualquier reintento con evidencia idéntica.
- **Archivos:** `sync_v2.py`, `tests/test_c2_reconciliation.py`, `tests/test_c2_accounting.py`, `REGISTRO_CAMBIOS.md`.
- **Contratos/datos:** conciliación de evidencia v2 y v3; sin cambios de esquema.
- **Pruebas:** 3 pruebas dedicadas en `tests/test_c2_reconciliation.py` integradas a la suite segura (`tools/safe_tests.py --legacy-clock`) para un total de 69 pruebas aprobadas: (1) conciliación tardía efectiva de pago emitido dentro de la autorización luego de vencida la ventana de sincronización sin pérdida de fondos; (2) idempotencia e inmutabilidad estricta de reenvío de pagos aceptados tanto por cliente como por comercio incluso tras la revocación posterior de la clave; (3) progresión y estabilidad de entregas parciales (PENDING_EVIDENCE -> ACCEPTED) sin conflictos de sobre. `git diff --check` limpio.
- **Limitaciones:** sin dispositivos móviles ni lectores físicos.
- **Commit:** `feat(sync): [TFG-C2-BE-02] admitir conciliacion tardia e idempotencia estricta`
- **Impacto académico:** demuestra la naturaleza desconectada del sistema, permitiendo que la evidencia offline sea acreditada al recuperar conectividad sin importar la demora de sincronización, siempre que el pago fuera válido al emitirse.

## TFG-C2-BE-03 — API v3, compromisos y cierre verificable

- **Fecha:** 2026-10-14
- **Fase:** C2
- **Estado:** PARCIAL
- **Hallazgos:** R02, R03, R04, R05, R09, R12, R18, R20.
- **Anterior:** C2 corregía rutas y conciliación v2, pero todavía no exponía el contrato v3 ni persistía el compromiso, cierre firmado y resolución final.
- **Nuevo previsto:** API v3 con autorización/cierre/resolución firmados, presupuesto por billetera, estados de envío separados y evidencia histórica controlada.
- **Decisión:** agregar tablas y migraciones aditivas; no modificar ni recalcular datos históricos existentes.
- **Archivos:** `models.py`, `schemas.py`, `api_v3.py`, `main.py`, `REGISTRO_CAMBIOS.md`.
- **Contratos/datos:** nuevas tablas v3; datos v2 conservados byte a byte.
- **Pruebas:** `py_compile`, `git diff --check`, persistencia temporal, unicidad de emisiones, consulta HTTP autenticada, resolución firmada idempotente y cierre firmado por billetera sobre bases temporales correctos.
- **Limitaciones:** no habilitar pagos reales ni integración Mercado Pago; queda pendiente repetir el flujo bajo concurrencia HTTP.
- **Commit:** `feat(api): [TFG-C2-BE-03] incorporar compromisos y cierre v3` (`ca23bac`).
- **Impacto académico:** demostrar contabilidad y recuperación v3, separadas de la compatibilidad histórica v2.
