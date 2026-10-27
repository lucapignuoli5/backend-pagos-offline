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
- **Pruebas:** `py_compile`, `git diff --check`, persistencia temporal, unicidad de emisiones, consulta HTTP autenticada, resolución firmada idempotente concurrente y cierre firmado por billetera sobre bases temporales correctos; tres pruebas HTTP v3 pasan.
- **Limitaciones:** no habilitar pagos reales ni integración Mercado Pago.
- **Commit:** `feat(api): [TFG-C2-BE-03] incorporar compromisos y cierre v3` (`ca23bac`).
- **Impacto académico:** demostrar contabilidad y recuperación v3, separadas de la compatibilidad histórica v2.

## TFG-C2-BE-04 — Separación del procesador v3

- **Fecha:** 2026-10-14
- **Fase:** C2
- **Estado:** PARCIAL
- **Hallazgo:** R03/R04; la ruta HTTP v3 invocaba directamente el adaptador v2.
- **Anterior:** `api_v3.py` importaba `process_evidence` desde `sync_v2.py`.
- **Nuevo:** el núcleo de procesamiento quedó explicitado como `process_evidence_core`; v2 conserva su adaptador y v3 utiliza `sync_v3.py` con una entrada propia.
- **Archivos:** `api_v3.py`, `sync_v2.py`, `sync_v3.py`, `REGISTRO_CAMBIOS.md`.
- **Pruebas:** no ejecutadas por instrucción del usuario; se verificó únicamente el diff.
- **Limitación:** el núcleo aún comparte reglas de persistencia con compatibilidad histórica; requiere pruebas HTTP y de concurrencia antes de declarar C2 comprobada.
- **Commit:** `refactor(sync): [TFG-C2-BE-04] separar entrada de procesamiento v3`
- **Impacto académico:** deja explícita la frontera de API v3 y evita que la ruta HTTP dependa directamente del adaptador v2.

## Decisión de proceso vigente
Las fases pueden cerrarse por implementación y revisión estática sin ejecutar pruebas al finalizar. El estado debe indicar `VALIDACIÓN PENDIENTE`; no se declara `COMPROBADO` ni se atribuyen resultados experimentales hasta ejecutar las verificaciones correspondientes.

## TFG-C4-POS-01 — Perfil recuperable, migración 2→3 y conciliación exclusiva

- **Fecha:** 2026-10-14
- **Fase:** C4
- **Estado:** IMPLEMENTADA / VALIDACIÓN PENDIENTE
- **Cambio:** el POS migra antes de leer identidad, conserva el perfil devuelto por el backend, puede abrir offline después del aprovisionamiento, permite reanudar operaciones desde historial y usa un lease SQLite para impedir dos conciliadores simultáneos. El backend devuelve el comercio asociado al terminal. Se fijan PySide6 6.12.0 y `pyscard` 2.3.1 para CPython anterior a 3.14.
- **Archivos:** `schemas.py`, `api_v2.py`, `pos_desktop/database.py`, `app.py`, `backend_client.py`, `ui.py`, `sync.py`, `requirements-pos.txt`.
- **Pruebas:** no ejecutadas por decisión del usuario.
- **Limitaciones:** DPAPI, Qt, PC/SC y ACR122U quedan con validación pendiente; el entorno Python 3.14 actual no instala `pyscard`.
- **Commit:** `feat(pos): [TFG-C4-POS-01] completar recuperacion y perfil offline`
## TFG-C6-BE-01 — Reloj controlable y entorno reproducible

- **Fecha:** 2026-10-14
- **Fase:** C6
- **Estado:** IMPLEMENTADA / VALIDACIÓN PENDIENTE
- **Cambio:** autenticación, autorizaciones y conciliación usan una fuente UTC única sustituible; el ejecutor aislado congela el símbolo correcto y mantiene SQLite temporal, integraciones deshabilitadas y red externa bloqueada. Las dependencias verificables permanecen fijadas en el lock existente.
- **Archivos:** `clock.py`, `auth.py`, `api_v2.py`, `api_v3.py`, `sync_v2.py`, `tools/safe_tests.py`, `docs/safe_verification.md`.
- **Pruebas:** no ejecutadas por decisión del usuario.
- **Limitaciones:** compilación, suites, lint, instrumentadas y hardware quedan agrupados para validación posterior.
- **Commit:** `refactor(env): [TFG-C6-BE-01] centralizar reloj verificable`
## TFG-C7-DOC-01 — Consolidación sin atribuir pruebas nuevas

- **Fecha:** 2026-10-14
- **Fase:** C7
- **Estado:** IMPLEMENTADA / VALIDACIÓN PENDIENTE
- **Cambio:** el informe académico independiente y el registro consolidado distinguen implementación C2–C6 de evidencia ejecutada; se actualizan instrucciones sin modificar entregas históricas.
- **Archivos:** registros académicos, `AGENTS.md` general y de las áreas.
- **Pruebas:** no ejecutadas por decisión del usuario.
- **Limitaciones:** matriz de validación, benchmark completo, instrumentadas y hardware quedan para la ejecución agrupada posterior.
- **Commit:** `docs(plan): [TFG-C7-DOC-01] consolidar implementacion pendiente de validar`
## TFG-C5-BE-01 — Conciliación v3 nativa y cierre verificable

- **Fecha:** 2026-10-14
- **Fase:** C5
- **Estado:** IMPLEMENTADA / VALIDACIÓN PENDIENTE
- **Cambio:** `/api/v3/offline-payments/sync` recibe autorización separada, valida solicitud/autorización/comprobante/acuse v3, distingue estado de envío y operación, aplica contabilidad y compromiso en una transacción e impide reutilizar índices. La emisión toma un bloqueo de escritura y el cierre comprueba cada evidencia del manifiesto; el reintento idéntico de cierre es idempotente.
- **Archivos:** `schemas.py`, `models.py`, `migrations.py`, `api_v3.py`, `sync_v3.py` y POS v3.
- **Pruebas:** no ejecutadas por decisión del usuario.
- **Limitaciones:** validación HTTP, concurrencia y rollback permanecen pendientes.
- **Commit:** `feat(v3): [TFG-C5-BE-01] integrar conciliacion y POS v3`

## TFG-C2-BE-05 — Cerrar contabilidad, idempotencia y resoluciones v3

- **Fecha:** 2026-10-14
- **Fase:** C2
- **Estado:** IMPLEMENTADA / VALIDACIÓN PENDIENTE
- **Hallazgos:** R03, R04, R05, R10, R12, R18, R29 y reglas de cierre verificable.
- **Anterior:** la emisión v3 no tenía clave idempotente durable, el saldo no exponía compromisos vencidos sin resolver, un cierre concurrente podía competir y Android/POS confiaban en el estado HTTP sin una resolución final firmada. Persistían rutas públicas capaces de crear usuarios, recargar o aplicar el formato heredado.
- **Nuevo:** la autorización usa `request_id` único, bloquea cuentas en revisión y reserva con escritura serializada; el saldo resta compromisos abiertos aunque estén vencidos. El cierre verifica cada evidencia y se aplica de forma condicionada, mientras evidencia omitida queda persistida en revisión y bloquea nuevas autorizaciones. Cada aceptación v3 crea una resolución firmada por el emisor dentro de la misma transacción; Android y POS la verifican antes de tratar el resultado como final. Se retiran explícitamente las rutas mutantes heredadas y se incorpora recarga simulada v3 autenticada, idempotente y expresada en centavos. Mercado Pago exige secreto de webhook, orden propia, cuenta, moneda e importe esperados.
- **Archivos:** `.env.example`, `models.py`, `migrations.py`, `schemas.py`, `api_v2.py`, `api_v3.py`, `sync_v3.py`, `main.py`, `settings.py`, `pos_desktop/backend_client.py` y `REGISTRO_CAMBIOS.md`.
- **Contratos/datos:** columnas aditivas `issuance_request_id` y `offline_review_required`; tablas nuevas de recargas simuladas y órdenes externas; resultado v3 incluye `resolution_envelope_b64`.
- **Pruebas:** no ejecutadas por decisión del usuario.
- **Limitaciones:** API, migraciones, concurrencia, rollback y simulador de webhook quedan para validación agrupada; no se contactó Mercado Pago.
- **Commit:** `fix(accounting): [TFG-C2-BE-05] cerrar resoluciones y recargas v3`
- **Impacto académico:** completa la programación de C2 sin atribuir atomicidad ni interoperabilidad comprobadas hasta ejecutar la matriz posterior.

## TFG-C2-BE-06 — Cerrar bypasses de acceso y fallos transitorios externos

- **Fecha:** 2026-10-14
- **Fase:** C2
- **Estado:** IMPLEMENTADA / VALIDACIÓN PENDIENTE
- **Hallazgos:** R29 y R30.
- **Anterior:** distintos alias del mismo usuario tenían contadores de login separados, y contraseñas heredadas largas podían aceptarse por truncamiento bcrypt. Una respuesta fallida del proveedor podía terminar como webhook ignorado.
- **Nuevo:** el bloqueo combina IP e identidad resuelta para todos los alias, las contraseñas de más de 72 bytes usan únicamente el esquema SHA-256 previo a bcrypt y no aceptan el truncamiento histórico, y los fallos del proveedor se informan como reintentables mediante HTTP 502.
- **Archivos:** `main.py`, `tools/provision_user.py` y `REGISTRO_CAMBIOS.md`.
- **Pruebas:** no ejecutadas por decisión del usuario.
- **Limitaciones:** usuarios heredados con hashes truncados requieren ejecutar intencionalmente la herramienta administrativa con la base elegida; rate limiting distribuido queda fuera del prototipo local.
- **Commit:** `fix(auth): [TFG-C2-BE-06] cerrar aliases y fallos externos`
- **Impacto académico:** evita presentar como resueltos los controles de acceso mediante comportamientos heredados ambiguos.

## TFG-C7-DOC-02 — Cerrar programación backend/POS sin atribuir ejecución

- **Fecha:** 2026-10-14
- **Fase:** C7
- **Estado:** IMPLEMENTADA / VALIDACIÓN PENDIENTE
- **Cambio:** instrucciones y registros reflejan compromisos, cierres, resoluciones firmadas, recarga simulada, webhook aislado y POS v3, conservando la evidencia anterior como antecedente.
- **Archivos:** `AGENTS.md`, registros consolidados y `REGISTRO_CAMBIOS.md`.
- **Pruebas:** no ejecutadas por decisión del usuario.
- **Limitaciones:** no se afirma arranque, migración, HTTP, concurrencia, Qt, PC/SC ni hardware.
- **Commit:** `docs(corrections): [TFG-C7-DOC-02] cerrar programacion backend pendiente`
- **Impacto académico:** deja trazabilidad vigente sin modificar la Entrega 4 presentada.

## TFG-C2-BE-07 — Limitar v2 a evidencia histórica

- **Fecha:** 2026-10-14
- **Fase:** C2
- **Estado:** IMPLEMENTADA / VALIDACIÓN PENDIENTE
- **Requisito:** v3 es obligatorio para pagos nuevos y v2 se conserva solo para recuperación controlada.
- **Cambio:** la emisión v2 responde retirada explícita, el procesador v2 rechaza autorizaciones que tengan compromiso v3 y la emisión v3 refresca el saldo después de adquirir el bloqueo de escritura.
- **Archivos:** `api_v2.py`, `api_v3.py`, `sync_v2.py` y `REGISTRO_CAMBIOS.md`.
- **Pruebas:** no ejecutadas por decisión del usuario.
- **Limitaciones:** el inventario y la conciliación de evidencia histórica real requieren una migración operativa sobre copias controladas antes de habilitar producción.
- **Commit:** `fix(compat): [TFG-C2-BE-07] limitar v2 a evidencia historica`
- **Impacto académico:** evita que un cliente nuevo degrade una autorización v3 al contrato heredado.

## TFG-C2-BE-08 — Inventariar evidencia histórica v2

- **Fecha:** 2026-10-14
- **Fase:** C2
- **Estado:** IMPLEMENTADA / VALIDACIÓN PENDIENTE
- **Requisito:** permitir conciliación v2 únicamente para evidencia histórica conocida antes de habilitar v3.
- **Anterior:** cualquier evidencia v2 compatible con una autorización heredada podía intentar conciliación, sin un inventario previo por cuenta.
- **Nuevo:** una ventana administrativa deshabilitada por defecto permite que el cliente autenticado registre UUID, autorización y digest de sus comprobantes heredados; la conciliación v2 exige una coincidencia exacta y rechaza autorizaciones con compromiso v3.
- **Archivos:** `.env.example`, `settings.py`, `models.py`, `migrations.py`, `schemas.py`, `api_v3.py`, `sync_v2.py` y `REGISTRO_CAMBIOS.md`.
- **Contratos/datos:** tabla aditiva `legacy_evidence_inventory`; ruta autenticada `/api/v3/legacy-inventory`; variable `LEGACY_INVENTORY_OPEN=false`.
- **Pruebas:** no ejecutadas por decisión del usuario.
- **Limitaciones:** la apertura de la ventana y la migración deben hacerse sobre copias controladas; evidencia ausente o contradictoria requiere revisión y no se concilia automáticamente.
- **Commit:** `feat(compat): [TFG-C2-BE-08] inventariar evidencia v2`
- **Impacto académico:** hace explícito el límite entre recuperación histórica v2 y pagos nuevos v3.

## TFG-C7-DOC-03 — Registrar compatibilidad histórica controlada

- **Fecha:** 2026-10-14
- **Fase:** C7
- **Estado:** IMPLEMENTADA / VALIDACIÓN PENDIENTE
- **Cambio:** instrucciones y registro consolidado reflejan que v2 requiere inventario previo y que la ventana de importación permanece cerrada por defecto.
- **Archivos:** `AGENTS.md`, registros académicos y `REGISTRO_CAMBIOS.md`.
- **Pruebas:** no ejecutadas por decisión del usuario.
- **Limitaciones:** la migración y conciliación de datos históricos no se consideran comprobadas.
- **Commit:** `docs(corrections): [TFG-C7-DOC-03] registrar compatibilidad historica`
- **Impacto académico:** distingue la compatibilidad programada de una migración ya validada.
## TFG-C8-BE-01 — Preparación para prueba manual

- Fecha: 2026-10-14. Estado: IMPLEMENTADA / VALIDACIÓN FUNCIONAL PENDIENTE.
- Requisito: corregir bloqueos de compilación, APDU v3, aprovisionamiento y recuperación.
- Validación autorizada: solo compilación Android y sintaxis Python; sin pruebas ni arranque.
- Datos existentes: conservar; configuración y demostración nuevas fuera de Git.
- Comportamiento anterior: APDU 0x50 rechazado; reloj del simulador mezclado; verificación solo con emisor activo; revocación sin fecha; mensajes de aceptación durante espera y consultas POS v2.
- Comportamiento nuevo: APDU compartido acepta autorización v3; simulador recibe reloj y conserva índices/comprobantes; backend verifica inventarios externos históricos; POS persiste confianza emisora en SQLite 5; revocaciones con fecha y evidencia posterior en revisión; recuperación y estados finales conservados.
- Archivos: `protocol_v2.py`, `api_v3.py`, `sync_v2.py`, `sync_v3.py`, `models.py`, `migrations.py`, `issuer_trust.py`, `revocation.py`, módulos `pos_desktop/`, herramientas `tools/prepare_demo.py`, `tools/run_demo.py`, `tools/revoke_key.py`, configuración, lock y guía manual.
- Contratos/datos: `registered_keys.revoked_at` aditivo; POS 4→5; emisores públicos fijados por ID/huella; sin cambio de bytes históricos ni generación de evidencia v2.
- Entorno: CPython 3.13.13 x64 adicional en `.venv313`; 33 paquetes instalados desde lock, incluido pyscard 2.3.1. No se acredita funcionamiento por instalación.
- Verificación: sintaxis Python mediante AST correcta en 53 archivos, sin importar aplicación. No pruebas, simulador, pagos, migraciones ni servicios ejecutados.
- Limitaciones: herramientas de preparación/arranque no ejecutadas; URL HTTPS real y hardware pendientes; suites heredadas de la auditoría siguen sin revalidarse.
- Aclaración del equipo: conservar el dominio fijo ngrok anterior. El launcher admite `--domain` y reutiliza el hostname guardado; no se abrió túnel durante esta entrega.
- Commit: `fix(manual): [TFG-C8-BE-01] preparar ejecucion controlada`.
- Impacto académico: preparación reproducible para prueba manual; no acredita atomicidad, migración ni interoperabilidad.
## TFG-C8-BE-02 — Demostración configurada para dos teléfonos

- Fecha: 2026-10-14. Estado: PREPARADA / FUNCIONAMIENTO PENDIENTE DE PRUEBA MANUAL.
- Requisito: dejar demostración nueva y launcher preparados con dominio fijo del equipo.
- Preparación autorizada: base nueva externa, identidad DPAPI, cuentas demo y APK configurado. Sin pagos ni suites.
- Datos históricos: conservar; no migrar bases originales.
- Commit: `feat(demo): [TFG-C8-BE-02] configurar demostracion de dos telefonos`.
- Datos creados: exclusivamente `C:\Users\anita\TFG-Demo-Manual`; base demo nueva, usuarios cliente/comercio, emisor DPAPI, inventario público y configuración DPAPI. El prepare_demo terminó correctamente; no se arrancó backend ni se emitieron pagos.
- Dominio configurado: unfailing-bless-thrift.ngrok-free.dev; launcher reutiliza authtoken de configuración local sin imprimir ni registrar valores.
- Archivos: tools/run_demo.py, GUIA_PRUEBA_MANUAL.md, este registro y launcher/LEEME externos. El binario ngrok instalado se copió a la nueva carpeta sin modificar el original.
- Estado demostrado: preparación de datos nueva y sintaxis de herramientas; funcionamiento en dispositivos pendiente.
- Impacto académico: ejecución comprobada de preparación nueva, sin atribuir pagos ni conciliación comprobados; instrucciones y consolidado actualizados.
## TFG-C8-BE-03 — Corregir lectura de identidad emisora desde entorno

- Fecha: 2026-10-14. Estado: CORREGIDO / VALIDACIÓN MANUAL PENDIENTE.
- Disparador real: usuario intenta login desde el APK demo; login/registro/balance responden 200 y emisión v3 responde 503 en backend.log.
- Causa comprobada estáticamente: os.getenv devuelve str y _external invoca expanduser directamente sobre ese str.
- Corrección implementada: normalizar Path en el límite de identidad; preservar archivo DPAPI, huella y configuración. Consumidores API, conciliación y confianza histórica comparten el mismo límite.
- Verificación autorizada: sintaxis Python; sin solicitudes de pago ni suites.
- Archivos: issuer_keys.py, AGENTS.md, este registro e informe/consolidado académico.
- Verificación: AST correcto; sin importación de aplicación, suites ni solicitudes HTTP ejecutadas por el agente.
- Despliegue: reiniciar la demostración para cargar el módulo corregido; APK y claves no se regeneran.
- Commit: `fix(issuer): [TFG-C8-BE-03] aceptar rutas de configuracion externas`.
## TFG-C8-BE-04 — Consola de eventos en vivo

- Fecha: 2026-10-14. Estado: IMPLEMENTADA / VALIDACIÓN MANUAL PENDIENTE.
- Requisito: mostrar login, autorizaciones y conciliación en la ventana del launcher.
- Límite: un servidor desconectado no observa pagos entre dispositivos hasta recibir sincronización.
- Datos excluidos: contraseñas, JWT, cabeceras, cuerpos firmados, claves y nombres personales.
- Implementación: stdout del backend se retransmite en vivo al CMD y se conserva en backend.log; logger con campos permitidos y formato seguro sin traza/parametrización SQL; rutas HTTP sin cuerpos/cabeceras ni direcciones personales.
- Eventos: LOGIN_OK/LOGIN_RECHAZADO, autorización emitida/reutilizada/cerrada, recarga simulada/repetida, pago aplicado tras commit y resultado individual de conciliación. Un reintento no se anuncia como otro débito.
- Archivos: demo_events.py, demo_log_config.json, main.py, api_v3.py, sync_v3.py, tools/run_demo.py, guía, instrucciones y registro.
- Verificación: AST Python y JSON correctos; diff revisado. No pruebas, pagos ni reinicio de servicios ejecutados.
- Uso: Enter y reabrir INICIAR_DEMO.cmd para cargar la consola nueva; no requiere otro APK.
- Commit: `feat(console): [TFG-C8-BE-04] mostrar eventos seguros en vivo`.
## TFG-C8-BE-05 — Limpieza recuperable de auxiliares y cachés

- Fecha: 2026-10-14. Estado: COMPLETADA / RECUPERABLE.
- Requisito: retirar temporales y archivos sin uso de la carpeta del proyecto.
- Alcance: bytecode Python reproducible, mensaje auxiliar de commit, copia binaria ngrok sin consumidor actual y launcher antiguo reemplazado por la demo externa.
- Protección: mover a archivo externo con manifiesto; conservar bases, Git, ambos entornos, herramientas, documentos y evidencia.
- Resultado: cinco carpetas bytecode archivadas, commitmsg.txt y copia binaria ngrok.exe retirados del checkout; launcher antiguo ignorado archivado. Nueva regla Git evita rastrear esos auxiliares otra vez.
- Archivo externo: `C:\Users\anita\TFG-Archivo-Limpieza\2026-10-14-limpieza-01`; manifiesto con rutas exactas. Herramientas actuales, ambos entornos, bases, fuentes y evidencia conservados.
- Verificación: clasificación, rutas, estado Git y diff; sin pruebas ni arranque. El ngrok operativo está en TFG-Demo-Manual y no se modificó.
- Commit: `chore(cleanup): [TFG-C8-BE-05] archivar auxiliares obsoletos`.

## TFG-C8-BE-06 — Acceso automático por dispositivo de demostración
- Fecha: 2026-10-14. Estado: IMPLEMENTADA / VALIDACIÓN MANUAL PENDIENTE.
- Requisito: acceso con un toque, identidad aleatoria durable por instalación/rol, sin credenciales compartidas embebidas.
- Alcance: endpoint demo deshabilitado por defecto; launcher explícito lo habilita en demostración. Configuración pública local para Android Studio. Sin pruebas ni arranque.
- Commit: feat(demo): [TFG-C8-BE-06] aprovisionar acceso automático por dispositivo.
- Archivos: demo_access.py, main.py, tools/run_demo.py, GUIA_PRUEBA_MANUAL.md, AGENTS y registros.
- Contrato: UUID, rol cliente/comercio y secreto aleatorio de 256 bits; hash bcrypt en servidor. Creación cuenta/billetera SQL serializada; reintentos verifican secreto, nunca reinician saldo. Máximo 100 cuentas demo.
- Verificación: AST correcto sin importar backend. No arranque, migraciones, peticiones HTTP ni pagos ejecutados. Reiniciar launcher requerido; datos anteriores intactos.

## TFG-C8-BE-07 — Instrucciones backend actualizadas
- Fecha: 2026-10-15. Estado: COMPROBADO DOCUMENTAL / SIN NUEVA VALIDACIÓN FUNCIONAL.
- Requisito: preparar contexto fiel para auditoría nueva, sin garantías heredadas. Retirar contradicciones v2/v3, rutas retiradas, entorno y evidencia histórica; conservar reglas de seguridad y trazabilidad.
- Verificación: lectura de código, estado Git y diff, sin ejecutar backend ni pruebas.
- Commit: docs(agents): [TFG-C8-BE-07] actualizar contexto backend y evidencia.
- Resultado: AGENTS del área consolidado, sin instrucciones contradictorias de versiones ni garantías heredadas; evidencia manual y pendientes separados. Se ajustó contexto compartido general y registro consolidado.
- Archivos del commit: AGENTS.md y REGISTRO_CAMBIOS.md. No código, configuración, datos ni entregas históricas. Revisados fuentes seleccionadas y diff; ninguna prueba ni compilación ejecutada.

## TFG-C8-BE-08 — Publicación autorizada en GitHub

- Fecha: 2026-10-19. Estado: COMPROBADO LOCAL / PUBLICACIÓN AUTORIZADA.
- Requisito: subir commits locales con descripciones específicas en español. La autorización actual reemplaza la restricción previa Sin push solo para esta publicación.
- Estado inicial: main limpio; origin/main actualizado mediante fetch diverge en dos commits remotos de julio. No modificar datos, código funcional ni historial publicado.
- Integración prevista: conservar árbol funcional local mediante merge ours sin reescritura; preservar commits remotos como ancestros y archivar sus documentos como antecedentes no vigentes. No importar código heredado incompatible, ._* ni herramientas .agents ajenas al runtime.
- Verificación: inspección de cambios y secretos sin reproducir valores, diff y comprobación de referencias Git. Sin pruebas, compilación, instalaciones, arranques ni pagos.
- Asunto exacto: `docs(publicacion): [TFG-C8-BE-08] publicar backend v3, POS y demostración`.
- Corte preservado: d60c294; remoto integrado: c12a374. Revisión independiente de compatibilidad e inspección heurística de secretos sin valores. No se detectaron secretos nuevos por los patrones revisados; no equivale a garantía absoluta.
- Archivos: PUBLICACION_GITHUB_2026-10-19.md, antecedentes/github_2026-07-06/*.md, AGENTS.md y este registro. Todos los cambios del árbol de esta unidad son Markdown; código funcional y datos conservados.
- Resultado: merge con historia completa preparado, referencias remotas verificables y mensajes de commit detallados en español. Confirmación de subida a origin/main se comunicará tras git push y contraste de hash remoto.
- Antecedentes copiados byte a byte: conservan espacios finales históricos señalados por diff --check. Se verifica limpieza del resto del diff; no se reescriben originales para eliminar esos avisos.

## TFG-C8-BE-09 — Inventario de limpieza y retirada de APK

- Fecha: 2026-10-19. Estado: COMPROBADO DOCUMENTAL / INVENTARIO COMPLETO.
- Solicitud: inventariar ambas carpetas, clasificar eliminar/archivar/conservar/investigar y borrar APK porque el usuario instala desde Android Studio.
- Alcance: medir archivos y referencias estáticas; borrar únicamente APK generados identificados, incluido APK externo preparado en TFG-Demo-Manual. No borrar código, datos, claves, entornos, migraciones, pruebas ni cachés en esta unidad.
- Preservación: registrar estados Git y rutas/tamaños antes de borrar; sin tests, compilación, instalación, servicios, migraciones o pagos. La publicación anterior no autoriza push de estos cambios nuevos.
- Resultado: inventario por área y general con tamaños, candidatos y consumidores. Código y scripts solo clasificados. Revisión automática bloqueó borrado de los cuatro APK en dos comandos; todos siguen presentes, sin espacio liberado ni eliminación alternativa.
- Archivos del commit: INVENTARIO_LIMPIEZA_2026-10-19.md, AGENTS.md y REGISTRO_CAMBIOS.md; informes/registro general y académico fuera de estos repos. Solo documentación; sin pruebas, compilación ni instalación.
- Asunto exacto: docs(limpieza): [TFG-C8-BE-09] inventariar scripts, cachés y código heredado.

## TFG-C9-BE-01 — Compromisos retenidos y cierre parcial de autorizaciones
- Fecha: 2026-10-20. Fase: C9 — Recuperación de autorizaciones y cupo.
- Estado: IMPLEMENTADA / VALIDACIÓN PENDIENTE.
- Hallazgos: AUD-01, AUD-04, AUD-06, AUD-12.
- Requisito: cerrar una autorización vencida con manifiesto completo, liberar solo el importe nunca emitido y conservar comprometidos los pagos pendientes de acuse.
- Comportamiento: cada comprobante autenticado queda registrado aunque todavía no tenga acuse; los índices duplicados y la evidencia contradictoria se conservan en revisión. El saldo retenido incluye todas las fases del compromiso. El cierre exige el conjunto completo de pagos y evidencia, se reintenta con los mismos bytes y libera solamente el presupuesto no emitido. La emisión nueva reserva hasta el saldo libre real y una repetición devuelve el grant original.
- Datos y contrato: migración aditiva de compromisos y tabla `offline_commitment_claims`; campos `held_cents`, `released_unissued_cents`, `released_rejected_cents`, `phase` (OPEN/SEALED/SETTLED), sobre/manifiesto de cierre. `/api/wallets/{id}/balance` informa historial de autorizaciones. No se cambia el formato firmado v3 ni se modifica base alguna en esta entrega.
- Archivos: `models.py`, `migrations.py`, `schemas.py`, `api_v2.py`, `api_v3.py`, `sync_v3.py`, `AGENTS.md`, `REGISTRO_CAMBIOS.md`.
- Verificación: análisis AST con Python 3.13 aislado de seis módulos y `git diff --check`; ambos correctos. Revisión estática del flujo de emisión, serialización por billetera, sincronización sin acuse, cierre, acuse tardío y saldo. No se ejecutaron pruebas, migraciones, importaciones, servidor, POS ni pagos.
- Límites: la migración de datos, transacciones concurrentes, firma/conciliación y la recuperación de la autorización demo permanecen sin validación ejecutada. Evidencia histórica cerrada sin sobre de cierre queda retenida y en revisión. El rechazo firmado aún no tiene un mecanismo de resolución administrativa; no libera fondos.
- Commit: `fix(contabilidad): [TFG-C9-BE-01] conservar compromisos pendientes al renovar`.
- Impacto académico: explicar vencimiento de emisión separado de conciliación; el saldo reservado por pagos pendientes sigue siendo propiedad del cliente, pero no gastable.

## TFG-C11-BE-01 — Persistir resoluciones firmadas en POS
- Fecha: 2026-10-20. Fase: C11 — Recuperación POS.
- Estado: IMPLEMENTADA / VALIDACIÓN PENDIENTE.
- Hallazgos: AUD-04, AUD-12, AUD-15.
- Requisito: conservar localmente la resolución v3 verificada para recuperar estado después de reinicios.
- Cambio: backend client valida firma y vínculos; conserva los bytes exactos del sobre; servicio de sincronización los pasa a SQLite en la misma actualización que el estado final. La migración aditiva 5→6 agrega `operations.resolution_envelope`; no altera operaciones ni evidencia existentes.
- Archivos: `pos_desktop/database.py`, `pos_desktop/backend_client.py`, `pos_desktop/sync.py`, `AGENTS.md`, `REGISTRO_CAMBIOS.md`.
- Verificación: Python 3.13 `ast.parse` en los tres módulos y `git diff --check`; correctos. No se importó ni inició el POS, no se ejecutaron migraciones ni pruebas.
- Límites: persistencia tras reinicio, migración histórica y reintentos pendientes de ejecución manual/agrupada; sintaxis no valida el contrato en ejecución.
- Commit: `fix(pos): [TFG-C11-BE-01] persistir resoluciones firmadas`.
- Impacto académico: una resolución final queda conservada con la evidencia POS; no se declara interoperabilidad física ni resultado de hardware.

## TFG-C12-BE-01 — Detectar índices históricos duplicados y preparar recuperación
- Fecha: 2026-10-20. Estado: IMPLEMENTADA / VALIDACIÓN MANUAL PENDIENTE.
- Hallazgo: el backfill conservaba claims contradictorios sin marcar la billetera; resultados finales degradados requieren reparación conservadora.
- Alcance: detección idempotente y herramienta administrativa explícita de diagnóstico/reparación, sin ejecutar sobre bases existentes.
- Commit: `fix(migracion): [TFG-C12-BE-01] detectar conflictos históricos sin alterar asientos`.
- Antes: claims previos duplicados no marcaban revisión. Ahora: backfill escanea todos los índices; la herramienta administrativa exige base explícita, inventario público fijado, diagnóstico por defecto y copia antes de reparar bajo transacción. Solo restaura un ACCEPTED degradado si firmas, alcance, digests, emisión, fecha y exactamente dos asientos coinciden. Conserva saldos/compromisos/clave y no limpia revisión de billetera.
- Archivos: `migrations.py`, `tools/recover_final_payments.py`, `tools/backup_sqlite.py`, este registro. Verificación: AST Python; ninguna herramienta ni migración fue ejecutada sobre bases existentes. Interrupción de migración requiere diagnóstico desde copia coherente, nunca downgrade automático.

## TFG-C12-CO-01 — Inmutabilidad de resultados financieros finales
- Fecha: 2026-10-20. Estado: IMPLEMENTADA / VALIDACIÓN MANUAL PENDIENTE.
- Hallazgo: una presentación contradictoria podía degradar un pago final y bloquear la billetera; clientes descartaban una resolución firmada si el envío indicaba conflicto.
- Alcance: preservar resultado financiero y resolución original; procesar conflicto de envío por separado en backend, Android y POS.
- Commit: `fix(conciliacion): [TFG-C12-CO-01] preservar resoluciones finales ante conflictos`.
- Antes: un envío alterado degradaba ACCEPTED/REJECTED. Ahora: devuelve conflicto del envío junto con estado financiero y resolución original; no cambia fila final, asientos ni marca de revisión. El POS valida esa resolución primero y usa el código firmado.
- Archivos: `sync_v3.py`, `pos_desktop/backend_client.py`, este registro. Verificación: AST Python y revisión estática; solicitudes HTTP pendientes.

## TFG-C12-CO-02 — Recuperar evidencia final POS
- Fecha: 2026-10-20. Estado: IMPLEMENTADA / VALIDACIÓN MANUAL PENDIENTE.
- Hallazgo: operaciones POS históricas finales carecen de resolución local.
- Alcance: migración aditiva 6→7 y recuperación por consulta de estado sin volver a contabilizar.
- Commit: `fix(pos): [TFG-C12-CO-02] recuperar resoluciones históricas sin mover saldos`.
- Antes: filas finales previas podían carecer de resolución local. Ahora: SQLite 6→7 conserva estado de recuperación; GET v3 verifica firma y vínculos antes de adjuntar bytes en la fila final. Errores de red se reintentan, 404/prueba inválida se aíslan como atención; acción manual permite reintentar. No se reenvía el pago ni se mueven fondos.
- Archivos: `pos_desktop/database.py`, `pos_desktop/backend_client.py`, `pos_desktop/sync.py`, `pos_desktop/ui.py`, `AGENTS.md`, `GUIA_PRUEBA_MANUAL.md`, este registro. Verificación: AST Python y diff; POS y migración real no ejecutados.

## TFG-C13-BE-01 — Cierre de autorizaciones con rechazos definitivos
- Fecha: 2026-10-20. Estado: IMPLEMENTADA / VALIDACIÓN MANUAL PENDIENTE.
- Requisito: la preparación automática no debe quedar bloqueada por una operación rechazada cuyo índice sigue consumido y cuya reserva ya fue resuelta.
- Alcance: admitir en el manifiesto únicamente rechazos finales respaldados y comprobar su total contra la liberación contable registrada; conservar el índice emitido y excluir ese importe del presupuesto no emitido.
- Antes/ahora: el cierre excluía cualquier REJECTED; ahora admite un rechazo final solo con resolución emisora confiable vinculada a la evidencia y sin aplicación, asientos o emisión ACCEPTED contradictoria. El total rechazado debe igualar la liberación registrada, antes de liberar exclusivamente lo no emitido.
- Decisión: conservar el índice consumido y los rechazos en el manifiesto; no reabrir pagos ni reparar historia ambigua automáticamente. Necesario para la renovación automática solicitada en C13.
- Archivos: `api_v3.py`, `AGENTS.md`, este registro; consumidor Android `sync/OfflineAuthorizationCloser.kt` (TFG-C13-AN-02). Sin cambio de esquema, rutas ni campos firmados.
- Verificación: revisión estática independiente y AST de `api_v3.py` correctos; diff sin errores. Sin pruebas, arranque, apertura de bases ni migraciones ejecutadas.
- Límite: migración/historia y rechazo real con cierre permanecen pendientes de verificación manual; no se agrega un productor nuevo de rechazos ni se alteran contadores existentes.
- Impacto académico: describe cierre automático conservador con índices permanentes y resolución final; no acredita corrección contable en ejecución.
- Commit: `fix(cierre): [TFG-C13-BE-01] conservar rechazos definitivos en el manifiesto`.

## TFG-C14-BE-01 — Contexto de continuidad entre computadoras
- Fecha: 2026-10-25. Estado: DOCUMENTADA / ESTADO LOCAL REVISADO.
- Requisito: indicar en backend qué evidencia C14 afecta al cliente y cómo preparar una nueva estación sin asumir acceso a secretos locales.
- Hallazgo: la excepción S24 pertenece a `WifiNetworkSpecifier` Android; no se halló causa ni requiere cambio backend. Las cuentas y claves demo externas están ligadas a la máquina donde se prepararon.
- Decisión: dejar claro que backend no cambia en C14, que sus datos de demostración externos no son portables por defecto, y que la rama Android con commits C14 está solo local/no publicada.
- Archivos: `AGENTS.md` y este registro.
- Verificación: releídos estado backend `main`/`origin/main`, registro existente y alcance C14. No se arrancaron servicios ni se abrieron bases.
- Asunto de commit: `docs(backend): [TFG-C14-BE-01] preparar continuidad del entorno de demostracion`.

## TFG-C14-BE-02 — Centralizar contexto de continuidad fuera de AGENTS
- Fecha: 2026-10-25. Estado: DOCUMENTADA / REVISIÓN ESTÁTICA.
- Requisito: guardar el estado operativo móvil/backend y el siguiente ensayo en un archivo de contexto común, manteniendo AGENTS como instrucciones estables.
- Decisión: crear `CONTEXTO_CONTINUACION_C14_WIFI_LOCAL.md` en la carpeta general y retirar de AGENTS el resumen temporal C14.
- Archivos: `AGENTS.md`, registro backend y el contexto compartido fuera de los repositorios.
- Verificación: el contexto documenta que C14 no altera backend y advierte sobre el entorno demo externo ligado a la máquina; diff sin errores. No se abrieron bases ni arrancaron servicios.
- Asunto exacto: `docs(backend): [TFG-C14-BE-02] separar contexto de continuidad`.

## TFG-C14-BE-03 — Arranque controlado de la demo
- Fecha: 2026-10-27. Estado: IMPLEMENTADA / SINTAXIS REVISADA / VALIDACIÓN MANUAL PENDIENTE.
- Alcance: launcher, dominio, autenticación local y procesos; conservar base y configuración existentes. No cambia contratos HTTP, esquema de datos ni contabilidad.
- El dominio explícito, el dominio guardado o el hostname heredado se intentan exactamente, sin inferencia por sufijo ni reemplazo aleatorio si fallan. La URL y metadatos DPAPI solo se reemplazan tras abrir un túnel válido.
- El token se mantiene en YAML externo con permisos Windows; se excluye de argumentos y entorno del backend. La salida nativa ngrok se descarta y se muestran errores sanitizados. `--configure-token` admite reemplazo mediante entrada oculta.
- Bloqueos por backend/túnel, comprobación del proceso propio, supervisión y contención Job Object están diseñados para no detener instancias ajenas. Enter/Ctrl+C solicitan cierre ordenado; X y fallback forzado no garantizan cierre contable ordenado y requieren ensayo físico.
- Se cerró el servidor que el agente había iniciado y se creó una copia SQLite coherente en un destino nuevo externo antes de usar el launcher actualizado; se conservaron base e identidades. No se inició ni probó el launcher nuevo.
- Verificación: revisión estática independiente de la unidad y análisis AST de cuatro archivos sin importar la aplicación. Sin pruebas, simuladores ni pagos. El usuario ejecutará la guía manual.
- Límite: bloqueo, ACL, manejo de consola y cierre del Job Object no están validados en ejecución Windows. La base existente no fue abierta por el backend actualizado.
- Punto inicial: main en 6707089, dos commits sobre origin/main, registro y tools/run_demo.py previamente modificados, conservados.
