# Publicación del backend y POS — 19/10/2026

Esta publicación conserva el historial del desarrollo local y remoto. El usuario
informó pagos QR/NFC entre teléfonos con conciliación y actualización automática.
Ese resultado manual no constituye regresión completa ni validación del lector
ACR122U, del POS físico o de todos los escenarios contables y de seguridad.

## Cambios incluidos

- Contrato v3 para operaciones nuevas: JSON estricto, importes enteros en
  centavos, firmas sobre evidencia original y autorización separada del comprobante.
- Registro de claves con prueba de posesión, alcance de billetera/terminal,
  revocación efectiva e inventario externo fijado de emisores históricos.
- Autorizaciones offline con compromiso de presupuesto, índices de emisión,
  conciliación tardía, cierre firmado y resoluciones financieras firmadas.
- Conciliación independiente por operación, resultados individuales,
  deduplicación, conflictos y conservación de evidencia pendiente.
- Contabilidad y recargas simuladas v3 transaccionales e idempotentes;
  retirada explícita de rutas mutantes heredadas y recuperación v2 inventariada.
- POS Python/PySide6 con SQLite, migraciones, historial, recuperación, colas,
  DPAPI para claves privadas y adaptadores PC/SC/simulador. Hardware pendiente.
- Demostración en carpeta externa nueva con base y configuración propias;
  entorno adicional CPython 3.13 x64 y dependencias fijadas con pyscard 2.3.1.
- Acceso automático demo por instalación/rol, cuentas simuladas individuales y
  sesión renovable sin reiniciar saldo; endpoint deshabilitado en arranque normal.
- Launcher de backend/ngrok y configuración pública de Android Studio sin
  contraseñas embebidas; datos, secretos y claves privadas fuera del repositorio.
- Consola operativa con eventos seguros de login, autorizaciones, recargas y
  conciliación; distinción entre aplicación contable y reintento de envío.
- Mercado Pago opcional y deshabilitado; correcciones y casos de prueba escritos
  conservados, sin atribuir a la publicación una nueva ejecución de esas pruebas.

## Integración con GitHub

Antes de publicar, main tenía 52 commits locales y origin/main dos commits remotos
de julio. Se conservan todos mediante merge con estrategia ours, sin force-push.
Se mantiene el código local v3: el código remoto heredado activa integraciones y
rutas incompatibles con los controles posteriores. No se reintroducen secretos,
recargas sin los controles actuales ni sincronización antigua como flujo principal.

La bitácora, documentación general e informe remoto de auditoría se conservan
íntegros en `antecedentes/github_2026-07-06/`, identificados como antecedentes.
No se importan bibliotecas `.agents`, auxiliares `._*` ni herramientas ajenas al
runtime. Los commits previos mantienen sus IDs y registros de trabajo.

## Verificación y límites

- Antecedente C8: sintaxis Python revisada sin importar ni arrancar la aplicación;
  preparación demo separada y uso posterior del servidor por el usuario.
- En esta publicación: comparación de historial/árboles, revisión Git, inspección
  heurística de secretos y diff. Sin pruebas, compilaciones, migraciones,
  instalaciones, arranques ni pagos. Las bases y claves existentes no se alteran.
- No se incluyen bases demo, configuración DPAPI, tokens, claves privadas ni
  entornos Python. Seguir `GUIA_PRUEBA_MANUAL.md` para preparar otra instalación.
- Pendientes: regresión agrupada, migraciones ejecutadas, rollback, concurrencia,
  respuesta perdida, lotes mixtos, revocación y hardware POS/ACR122U.
- El historial remoto antiguo conserva información que debe tratarse como
  antecedente; retirar una credencial del árbol actual no la elimina de su historia.

Detalles de implementación y evidencia: `REGISTRO_CAMBIOS.md` y `AGENTS.md`.
