# Documentación General del Proyecto: Sistema de Pagos Offline (Prototipo)

## 1. Resumen y Objetivos del Proyecto
Este proyecto es un **prototipo de sistema de pagos offline**, diseñado bajo el principio de *Zero-Trust* (Cero Confianza). Su objetivo principal es permitir la realización de transacciones financieras de manera segura sin necesidad de conexión a internet en el momento del pago, mediante la utilización de criptografía de curva elíptica (ECDSA) y sincronización posterior con el backend.

El sistema se compone de dos partes fundamentales:
1. **Backend (Python / FastAPI)**: Encargado de la validación final, administración de saldos, emisión de JWT y verificación criptográfica estricta de las firmas enviadas por los dispositivos.
2. **Aplicación Android (Kotlin / Jetpack Compose)**: Actúa como punto de venta (POS) y billetera del cliente (Pagar QR / HCE). Genera las firmas criptográficas de forma offline y almacena localmente el registro de operaciones hasta que exista conexión para sincronizarlas.

## 2. Estado Actual del Desarrollo
Se ha realizado una auditoría de seguridad y una refactorización de los componentes críticos para asegurar la robustez del sistema:

- **Payload Criptográfico Estable**: Se modificó la generación y verificación de las firmas ECDSA para utilizar el monto en centavos absolutos (`Long/Enteros`) en lugar de números decimales de coma flotante. Esto elimina fallos silenciosos derivados de la configuración regional (Locale) de los distintos dispositivos Android (por ejemplo, el uso de coma vs. punto para decimales).
- **Almacenamiento Local Cifrado (Android)**: Se integró `SQLCipher` junto a `Room`. La base de datos local ahora está completamente cifrada en reposo utilizando una clave dinámica de 256-bits gestionada de forma segura por el Keystore de Android (`EncryptedSharedPreferences`).
- **Seguridad en la Autenticación (Backend)**: Se implementó un validador tipo *fail-safe* para el `JWT_SECRET_KEY` en FastAPI, evitando el despliegue a producción con secretos _hardcodeados_ o valores por defecto vulnerables.

## 3. Arquitectura Tecnológica
- **Backend**: Python 3, FastAPI, SQLite (Bases de datos `offline_payments.db` y `transacciones.db`), PyJWT, ecdsa.
- **Frontend / Móvil**: Android Nativo, Kotlin, Jetpack Compose, Room (con SQLCipher), Retrofit, HCE (Host-based Card Emulation) / QR para la transmisión del pago.

## 4. Lista de Tareas y Mejoras Futuras (To-Do List)
Para poder continuar el proyecto en otro equipo, aquí tienes la lista de siguientes pasos recomendados:

### Backend
- [ ] **Manejo de Errores Avanzado**: Refinar los mensajes de error devueltos por la API para no exponer detalles internos durante fallos criptográficos.
- [ ] **Rate Limiting / Throttling**: Añadir límites de peticiones en los endpoints de sincronización para evitar ataques de denegación de servicio (DDoS).
- [ ] **Migración de Base de Datos**: Cambiar de SQLite a una base de datos más robusta para producción (como PostgreSQL) en el momento del despliegue final.
- [ ] **Rotación de Claves JWT**: Implementar una lógica para la expiración y refresco seguro de tokens (Refresh Tokens).

### Android
- [ ] **Manejo de Sincronización en Segundo Plano**: Implementar `WorkManager` para que las transacciones encoladas se sincronicen de manera silenciosa tan pronto como el dispositivo recupere conexión a internet.
- [ ] **Mejora de UX/UI**: Refinar las pantallas de Compose con feedback visual (snackbars/loading spinners) durante el proceso de pago y sincronización.
- [ ] **Protección Contra Root/Temper**: Incorporar mecanismos (ej. Play Integrity API o SafetyNet) para verificar que el dispositivo no esté comprometido antes de realizar operaciones de pago.
- [ ] **Autenticación Biométrica**: Requerir la huella dactilar o reconocimiento facial del usuario antes de firmar una transacción (en la pantalla `PagarQrScreen`).

---
> **Nota de Continuidad**: 
> Este documento te sirve como punto de partida. Para retomar el desarrollo en tu otra PC, clona ambos repositorios y asegúrate de instalar las dependencias (`pip install -r requirements.txt` para el backend, y sincronizar Gradle para Android). Revisa la bitácora (`BITACORA_PROYECTO_FINAL.md`) para el histórico detallado.
