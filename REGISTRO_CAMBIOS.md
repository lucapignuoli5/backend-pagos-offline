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
