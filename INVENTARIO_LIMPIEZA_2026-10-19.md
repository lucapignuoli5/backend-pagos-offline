# Inventario de limpieza backend/POS — 19/10/2026

Unidad: TFG-C8-BE-09. Corte inicial `84bc5da5ed0f2db3081f0f5c7c2e9bc957a3071f`,
Git limpio. Inspección estática, referencias y metadatos de archivos; sin importar
la aplicación, ejecutar pruebas, servicios, herramientas administrativas o pagos.

## Resultado y límites

Inventario completo de nombres/tamaños del árbol, excluyendo `.git`, y análisis
de consumidores en fuentes propias sin buscar en entornos o bibliotecas de terceros.
No se leyó contenido de bases ni secretos. No se borraron scripts, código,
dependencias, cachés, datos ni entornos. No se encontraron APK en este repositorio.
El intento de borrar cuatro APK del Android/demo fue rechazado por la revisión
automática; siguen presentes y se detallan en el inventario general.

## Tamaños observados

Instantánea previa a crear informes: 13.775 archivos, 1.502.320.890 bytes sin `.git`.
La mayor parte son dependencias Python, no código del proyecto. No interpretar
estos tamaños lógicos como espacio físico liberado.

| Grupo | Archivos | Bytes | Tratamiento |
|---|---:|---:|---|
| `.venv313/`, incluido su bytecode | 5.669 | 729.450.950 | CONSERVAR, entorno actual |
| `venv/`, incluido su bytecode | 7.994 | 771.826.144 | CONSERVAR por decisión previa |
| Bytecode propio fuera de entornos | 24 | 304.615 | ELIMINAR PROPUESTO, no eliminado |
| `pos_desktop/`, sin bytecode | 13 | 72.484 | CONSERVAR |
| `tools/`, sin bytecode | 6 | 21.040 | CONSERVAR herramientas vigentes |
| `tests/` | 19 | 146.118 | CONSERVAR regresión pendiente |
| `benchmarks/`, `docs/`, `evidence/` | 7 | 24.169 | CONSERVAR / clasificar estado |
| `antecedentes/` | 4 | 13.115 | CONSERVAR procedencia |
| `.idea/` | 5 | 5.556 | CONSERVAR IDE |

El resto son 34 archivos de raíz, incluidas bases protegidas que no se abrieron.

## Candidatos y consumidores

Las rutas son relativas a este repositorio. **Eliminar propuesto** no significa
eliminado ni autorización de cambiar código en esta unidad.

| Decisión | Ruta y evidencia | Recomendación / riesgo |
|---|---|---|
| ELIMINAR PROPUESTO | `__pycache__/`, `pos_desktop/__pycache__/`, `tools/__pycache__/` | 24 archivos/304.615 bytes regenerables. No eliminados; procesos activos pueden recrearlos. No extender borrado a entornos conservados. |
| ELIMINAR CÓDIGO PROPUESTO | `main.py:263–278,284–297,306–360,643–694` | 137 líneas posteriores a `raise HTTPException(410)` incondicional en líneas 262,283,305,642. Retirar después en unidad propia conservando ruta, firma y respuesta 410. Revisar imports/consumidores. |
| ELIMINAR CÓDIGO PROPUESTO | `api_v2.py:185–249` | 65 líneas después del 410 en línea 184. `_AUTH_LOCK` en 175 solo se referencia dentro de ese bloque (195). Conservar stub y contratos compartidos/históricos. |
| INVESTIGAR CONJUNTAMENTE | Helpers `main.py:697,724,781,794,885,945` | Referencias encontradas en implementación heredada posterior al 410 y sus helpers; revisar grupo completo. No borrar modelos/tablas históricas ni dashboard activo en líneas 550/760. |
| INVESTIGAR | `main.py:815,824,915` y firma/Base64 en 858/869 | Helpers de transacciones/verificación sin consumidores actuales encontrados. La ausencia de llamadas estáticas no demuestra inexistencia de herramientas externas. |
| INVESTIGAR CONSOLIDACIÓN | `main.py:949–964` | Arranque/túnel alternativo al launcher; sigue activo si se ejecuta el archivo. No llamarlo código muerto ni ejecutarlo para comprobar uso. |
| INVESTIGAR UBICACIÓN | `REGISTRO_IMPLEMENTACION_CONSOLIDADO.md` | Archivo pequeño de decisión de proceso, distinto del consolidado académico completo. Renombrar/mover solo preservando contenido, referencias y trazabilidad. |
| ARCHIVAR / CONSERVAR YA ARCHIVADO | `antecedentes/github_2026-07-06/` | Ya fechado y separado en publicación. No borrar informes por contener afirmaciones antiguas. |
| CONSERVAR | `tools/run_demo.py`, `prepare_demo.py` | Consumidos por `GUIA_PRUEBA_MANUAL.md:40,53,66,78,159,211` y launcher demo externo. No son scripts desechables. |
| CONSERVAR | `tools/provision_user.py`, `revoke_key.py` | Administración y recuperación explícitas; alta pública retirada. Importantes para identidad y revocación. |
| CONSERVAR | `tools/safe_tests.py`, `verify_cross_language.py`, `tests/`, `benchmarks/`, `evidence/` | Referencias en `docs/safe_verification.md:3`, `docs/protocol_v3.md:57`, `test_safe_tests.py:3`, `test_protocol_v3.py:27`, `test_benchmark.py:3`. Que no se ejecuten ahora no los vuelve inútiles. |
| CONSERVAR | `api_v2.py`, `sync_v2.py`, `protocol_v2.py`, documentación y fixtures v2 | Claves/confianza/saldo compartidos y recuperación histórica; router montado en `main.py:159`, inventario en `sync_v2.py:201–205`, imports desde POS. |
| CONSERVAR / INVESTIGAR ROLES | `requirements*.txt`, `requirements-*.lock` | Locks para manual/verificación y requisitos POS cumplen roles diferentes. `ecdsa` puede ser transitiva de python-jose; `pyngrok` sí se usa en launcher (líneas 43–44,88,108 al corte). No quitar por ausencia de import directo. |
| CONSERVAR | `.venv313/`, `venv/`, `.idea/`, bases y configuración | Decisión expresa de preservar ambos entornos. No borrar bases por ser antiguas ni abrirlas como parte del inventario. |

Los candidatos más claros son cachés y 202 líneas de implementación posterior a
respuestas 410. La limpieza del código necesita una unidad posterior, análisis
de dependencias y verificación autorizada; no se implementó aquí.

## Continuación

No se encontraron scripts sueltos inequívocamente desechables entre los seis de
`tools/`. Mantener separado retirar código inalcanzable de corregir hallazgos
AUD-01–AUD-19 o cambiar la integración Mercado Pago. Sin push de esta unidad.
