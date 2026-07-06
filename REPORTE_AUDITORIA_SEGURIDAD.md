# Reporte de Auditoría de Seguridad y Correcciones Aplicadas

## 1. Resumen Ejecutivo
Como parte del desarrollo del prototipo de Pagos Offline (arquitectura Zero-Trust), se llevó a cabo una auditoría de seguridad sobre el código fuente original (Backend y Android). El objetivo fue identificar vulnerabilidades criptográficas, riesgos en el almacenamiento de datos sensibles y fallos en el control de acceso.

A continuación se detallan los hallazgos (Findings) de la auditoría y las acciones correctivas (Remediations) implementadas en el sistema.

---

## 2. Hallazgo #1: Inconsistencia Criptográfica por Precisión de Punto Flotante
**Nivel de Severidad:** Alto
**Componente Afectado:** Algoritmo de Firmas ECDSA (Android / Backend)

### Descripción de la Vulnerabilidad
La arquitectura depende de firmas de Curva Elíptica (ECDSA) generadas offline por la aplicación de Android para validar la autenticidad de un pago en el backend. Sin embargo, el payload criptográfico estaba utilizando montos en formato de punto flotante (`Double/Float`).
Esto generaba un vector de error donde la configuración regional (Locale) del teléfono podía alterar la representación a formato de cadena de texto (ej. `10.50` vs `10,50`). Esta pequeña discrepancia rompía el determinismo criptográfico, causando que la verificación de la firma fallara silenciosamente en el backend (FastAPI), resultando en denegación de pagos válidos o inconsistencia en los estados.

### Acción Correctiva Implementada
Se refactorizó todo el modelo de datos y el proceso de firmado para utilizar **centavos absolutos en formato entero (`Long/Int`)**.
Al transmitir y firmar enteros (ej. `1050` en lugar de `10.5`), se elimina la ambigüedad de codificación y Locale, garantizando que el texto plano firmado en Android y el texto plano reconstruido en el Backend sean exactamente idénticos (bit a bit).

---

## 3. Hallazgo #2: Almacenamiento Inseguro de Base de Datos Local
**Nivel de Severidad:** Crítico
**Componente Afectado:** Almacenamiento Local (Android)

### Descripción de la Vulnerabilidad
La aplicación Android almacenaba la base de datos de operaciones offline utilizando `Room` (SQLite) en texto plano. Un atacante con acceso físico al dispositivo, o con privilegios de root (jailbreak/rooting) podía extraer la base de datos y alterar transacciones encoladas, modificar su saldo offline o inyectar operaciones falsas antes de que el sistema recobrara conexión para la sincronización con el backend.

### Acción Correctiva Implementada
Se implementó cifrado en reposo para la base de datos local utilizando **SQLCipher**.
- La base de datos ahora está cifrada completamente utilizando AES-256.
- La clave de cifrado se genera de manera dinámica en el dispositivo en la primera ejecución y se almacena de forma segura delegando al **Android Keystore System** a través de `EncryptedSharedPreferences`.
- Esto garantiza que incluso en un dispositivo comprometido, extraer la base de datos no sirva de nada sin comprometer también el chip de seguridad (TEE/StrongBox) del dispositivo para extraer la clave de desencriptación.

---

## 4. Hallazgo #3: Secretos JWT Predecibles y Hardcodeados
**Nivel de Severidad:** Crítico
**Componente Afectado:** Autenticación de API (Backend - FastAPI)

### Descripción de la Vulnerabilidad
El servicio de FastAPI contenía una vulnerabilidad potencial de "Broken Access Control" al depender de una clave secreta JWT con un valor por defecto o hardcodeado en el entorno de desarrollo (ej. `dev-change-me`). Si el sistema era desplegado a producción sin inyectar una variable de entorno segura, un atacante podía deducir el secreto y utilizar técnicas de *JWT Forgery* para fabricar tokens válidos, escalando privilegios y logrando control total sobre las cuentas de otros usuarios en el backend.

### Acción Correctiva Implementada
Se incluyó un mecanismo defensivo tipo *fail-safe* durante la inicialización de FastAPI.
- El servidor inspecciona de forma activa el valor de `JWT_SECRET_KEY` durante el arranque (`startup event`).
- Si detecta que la clave está vacía, o es el valor por defecto inseguro, lanza una excepción crítica (RuntimeError) y **detiene la ejecución del servidor** de forma inmediata.
- Esto fuerza la inyección segura de variables de entorno mediante archivos `.env` o gestores de secretos en despliegues productivos.

---

## 5. Conclusión
Con estas correcciones, la superficie de ataque primaria (Firmas Forjadas, Modificación Offline, y Evasión de Autenticación) ha sido mitigada satisfactoriamente. Se recomienda como trabajo futuro realizar pruebas de penetración (pentesting) específicamente enfocadas en los endpoints de sincronización y mitigación de ataques de repetición (Replay Attacks).
