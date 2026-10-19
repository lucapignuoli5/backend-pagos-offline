# Bitácora de Cambios - Proyecto Final: Pagos Offline

Este documento registra todas las modificaciones realizadas en la arquitectura, código y seguridad del proyecto, documentando el "qué" y el "por qué" de cada cambio. Será utilizado como base para la documentación de la tesis/proyecto final.

## 📅 2026-07-06 - Auditoría Inicial y Refactorización de Seguridad

### Estado Inicial del Sistema
Se realizó una auditoría de seguridad del código fuente original. Se detectaron oportunidades de mejora en el manejo de JWT, validación de firmas ECDSA (problemas potenciales de Locale/Punto Flotante) y almacenamiento local.

### Cambios Realizados
*(Aquí iremos documentando cada archivo que toquemos y la justificación técnica)*

- **[COMPLETADO] Refactorización del Payload Criptográfico (main.py, PaymentHCEService.kt, PosScreen.kt, PagarQrScreen.kt)**: Se modificó la lógica para que las firmas criptográficas se realicen usando el monto en formato de centavos absolutos (enteros) en vez de decimales flotantes (`Locale.US`, `%.1f`). 
  - *Justificación Técnica:* Al depender de representaciones de coma flotante, la validación de la firma en el Backend podía fallar silenciosamente dependiendo de la configuración regional (Locale) del teléfono Android (ya que algunos países usan coma `,` y otros punto `.`). Al firmar y transmitir el monto en centavos enteros como un `Long/String` (ej. `1050` en lugar de `10.5` o `10,5`), se elimina la ambigüedad y se garantiza exactitud determinista en la firma ECDSA, lo cual es obligatorio en arquitecturas de pagos offline zero-trust.
- **[COMPLETADO] Base de datos cifrada con SQLCipher (Android)**: Se integró la librería `net.zetetic:android-database-sqlcipher` y se configuró Room para utilizar una clave de 256-bits dinámica, generada de forma segura en tiempo de ejecución y almacenada en `EncryptedSharedPreferences` mediante `TokenManager.kt`.
  - *Justificación Técnica:* Almacenar bases de datos SQLite en texto plano en Android permite a atacantes que obtengan privilegios root o extraigan los archivos del dispositivo alterar transacciones locales o saldos antes de la sincronización. El uso de SQLCipher con claves gestionadas por el Keystore subyacente de Android (mediante EncryptedSharedPreferences) mitiga la manipulación de datos en reposo y garantiza la inmutabilidad local del registro de pagos.
- **[COMPLETADO] Validación robusta del JWT Secret (main.py)**: Se agregó un mecanismo de validación tipo _fail-safe_ / log crítico durante el arranque del backend en FastAPI, que detecta si la clave de sesión secreta está utilizando el valor por defecto de desarrollo (`dev-change-me`).
  - *Justificación Técnica:* Un secreto JWT _hardcodeado_ o predecible en el código es una vulnerabilidad crítica (Broken Access Control) que permite a un atacante falsificar firmas JWT (JWT Forgery) y escalar privilegios tomando control de cualquier cuenta. Validarlo en el arranque asegura que el despliegue a producción requiera forzosamente el paso seguro de inyectar la variable de entorno `JWT_SECRET_KEY`.

---
*Nota: Este archivo se actualizará automáticamente a medida que avancemos con la implementación.*
