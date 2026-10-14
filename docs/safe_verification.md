# Verificación aislada de las correcciones

Ejecutar `python -B tools/safe_tests.py --legacy-clock` desde la raíz del repositorio con el entorno autorizado. El ejecutor fija SQLite temporal, secretos efímeros, servicios externos desactivados y red limitada a loopback antes de importar la aplicación. No inicia el lifespan sobre datos existentes.

`--legacy-clock` congela exclusivamente el reloj de sincronización v2 para reproducir su fixture histórica. No demuestra conciliación tardía ni corrige el defecto R04. Las pruebas nuevas deben usar reloj inyectado y escenarios temporales independientes.

El perfil PC/SC será CPython 3.13 x64 y pyscard 2.3.1 en un entorno separado; el entorno anterior se conserva. Instalar dependencias nunca implica abrir la base ni iniciar integraciones. Los resultados concretos y la versión instalada se registran en REGISTRO_CAMBIOS.md.

Hardware ACR122U, HCE físico y pruebas instrumentadas requieren evidencia separada. Las bases históricas y los DOCX/PDF académicos no son destinos de las verificaciones.

Las guardas cubren las APIs Python socket TCP/UDP y los resolutores usados por la suite; no son un firewall del sistema. Además de las guardas, cada integración externa debe inyectar un doble local sin credenciales reales.
