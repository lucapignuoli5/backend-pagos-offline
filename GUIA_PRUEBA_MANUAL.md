# Preparar y probar la demostración v3

Estado: correcciones programadas; funcionamiento pendiente de prueba manual.
Durante esta entrega solo se permite compilar Android y revisar sintaxis Python.
Los comandos de preparación y arranque siguientes los ejecuta el usuario.

## Preparación única

Desde este repositorio, usar el entorno nuevo `.venv313` (CPython 3.13 x64).
El entorno anterior `venv` se conserva. Las dependencias están fijadas en
`requirements-manual.lock`, incluido `pyscard==2.3.1`.
Para reinstalar: `uv pip sync requirements-manual.lock --python .venv313/Scripts/python.exe`.

Si todavía no se dispone de URL, preparar primero la demostración sin URL y
generarla mediante el túnel explicado abajo. Si ya existe un backend HTTPS propio,
agregar `--backend-url https://tu-direccion/` a la preparación.
La carpeta de demostración debe ser nueva y externa a cualquier repositorio Git:

```powershell
.\.venv313\Scripts\python.exe -m tools.prepare_demo --directory C:\Users\anita\TFG-Demo-Manual
```

La herramienta se niega a sobrescribir carpetas existentes. Crea exclusivamente allí:
base nueva, cliente con $10.000, comercio con $0, identidad emisora DPAPI,
inventario público fijado y configuración DPAPI para el usuario Windows actual.
No utiliza bases históricas, no abre servicios y no contacta pagos externos.
Si falla, conservar la carpeta parcial y elegir otra nueva; no repetir sobre datos existentes.

Después de obtener la URL HTTPS con el túnel o configurar el dominio propio,
compilar el APK con esa configuración:

```powershell
.\.venv313\Scripts\python.exe -m tools.run_demo android --directory C:\Users\anita\TFG-Demo-Manual
```

El APK resultante está en el repositorio Android:
`app/build/outputs/apk/debug/app-debug.apk`.
El APK sin configurar usa una URL inerte y credenciales vacías: compilarlo no lo conecta al servidor.
Las credenciales incluidas son únicamente las de esta demostración simulada.

## Servidor HTTPS

Iniciar el backend sobre la base nueva:

```powershell
.\.venv313\Scripts\python.exe -m tools.run_demo backend --directory C:\Users\anita\TFG-Demo-Manual
```

Escucha solo en `127.0.0.1:8000`. Publicarlo mediante un proxy HTTPS.
La opción preparada para quien no tiene dominio es ngrok: crea una dirección
pública HTTPS que envía las solicitudes a este backend local. Requiere una cuenta
propia y su authtoken, disponible en el panel de ngrok. Nunca pegar el token en
este chat ni en el repositorio.

Con el backend abierto, ejecutar en otra terminal:

```powershell
.\.venv313\Scripts\python.exe -m tools.run_demo tunnel --directory C:\Users\anita\TFG-Demo-Manual
```

Ingresar el authtoken cuando se solicite (entrada oculta). La herramienta muestra
la URL pública y la guarda en la configuración DPAPI. Mantener esa ventana abierta.
Si ya se usaba un dominio fijo, copiarlo desde https://dashboard.ngrok.com/domains
y agregar `--domain tu-dominio.ngrok-free.app` al comando del túnel.
En las siguientes aperturas se reutiliza el dominio guardado en la configuración;
no hace falta cambiar el código ni recompilar mientras dominio e identidad sigan iguales.
Compilar Android en una tercera terminal con el comando anterior. El túnel solo
está disponible mientras permanezca activo; si cambia la URL, repetir la compilación.
Instrucciones oficiales: https://ngrok.com/docs/start

Este túnel no se inició durante la implementación. La cuenta y su configuración
se preparan por el usuario; no se acredita conectividad por escribir esta herramienta.

Como alternativa con dominio propio:
Ejemplo de Caddyfile para un dominio que ya apunte a esta PC, con puertos 80/443
accesibles desde Internet:

```text
pagos.tu-dominio {
    reverse_proxy 127.0.0.1:8000
}
```

Después de instalar Caddy y guardar ese archivo fuera del repositorio:
`caddy run --config C:\ruta\Caddyfile`.
La disponibilidad del dominio, certificado, DNS, router y firewall debe prepararse
por el operador; no se inicia ni verifica automáticamente aquí.
No conectar directamente el APK a HTTP: la configuración exige HTTPS.
DPAPI vincula el emisor y la configuración a esta cuenta Windows; no copiar la
identidad privada a otro servidor como si fuera portable.

## Dos teléfonos por QR/TCP

Requisitos: Android 8 o posterior, cámara y soporte NFC/HCE requerido por el
manifest; bloqueo de pantalla configurado para confirmar con biometría/PIN.
Usar dispositivos o perfiles de demostración separados de instalaciones con pagos
pendientes. La migración Room histórica no fue ejecutada en esta entrega; no
borrar ni reinstalar la aplicación original para hacer esta prueba.

1. Instalar el APK configurado en ambos teléfonos. Activar Internet.
2. Ingresar como cliente en el teléfono pagador; registra su clave.
3. Ingresar como comercio en el teléfono cobrador; descarga la clave del cliente.
4. Cerrar sesión y volver a ingresar como cliente para descargar la clave del comercio.
   Este orden es necesario: las claves se descargan durante el aprovisionamiento.
5. Conectar ambos a la misma Wi-Fi sin aislamiento de clientes. Para demostrar ausencia
   de Internet, apagar datos móviles y desconectar la salida a Internet del router,
   manteniendo la red local. El QR no crea hotspot ni Wi-Fi Direct.
6. En comercio, abrir cobro QR, ingresar $10 y generar la solicitud.
7. En cliente, escanear el QR, verificar comercio/importe y confirmar con biometría/PIN.
   Completar dentro de los 120 segundos de vigencia.
8. Comercio debe indicar aceptación local persistida; cliente debe indicar acuse
   verificado. Esto todavía no es conciliación del servidor.
9. Recuperar Internet y usar la acción de sincronización de cada rol. Puede sincronizar
   cualquiera primero. Esperar resultado por operación y actualizar saldo.
   En este ejemplo, saldo confirmado esperado: cliente $9.990 y comercio $10.
10. La acción Cargar del cliente agrega $1.000 simulados, online y con ID persistido.
    Ante respuesta perdida, reintentar conserva el mismo ID. No usa Mercado Pago.

## Interrupciones y duplicados: comprobación del usuario

- Antes de emitir: cancelar no debe crear comprobante ni reserva.
- Después de emitir: cortar comunicación conserva reserva y operación pendiente;
  no mostrar pago conciliado ni devolver automáticamente el importe.
- Si el comercio persistió el acuse pero el cliente no lo recibió, escanear la misma
  solicitud y reintentar dentro de la ventana. Debe conservar ID y comprobante.
  Después del vencimiento, conservar la evidencia y conciliar; no crear una operación
  nueva para sustituir la anterior.
- Repetir sincronización de una operación aceptada no debe volver a mover saldos.
- Evidencia inválida, conflicto, revocación posterior a emisión o revocación sin fecha
  conocida requiere atención y mantiene reservas hasta resolución verificable.
- Registrar ID, estados y saldos observados; no copiar JWT, claves privadas o contraseñas
  en el informe académico.

## POS de Windows y ACR122U

Para abrir el POS configurado:

```powershell
.\.venv313\Scripts\python.exe -m tools.run_demo pos --directory C:\Users\anita\TFG-Demo-Manual
```

Para copiar las credenciales demo del comercio al portapapeles, sin imprimirlas:
`python -m tools.run_demo credentials --directory C:\Users\anita\TFG-Demo-Manual`,
usando siempre `.venv313\Scripts\python.exe`.
Ingresar online una vez; el perfil devuelto por el servidor y las claves públicas
emisoras quedan persistidos. Volver a ingresar al cliente después para que descargue
la clave de este POS, distinta de la del comercio móvil.

Con ACR122U y driver PC/SC instalados: crear cobro, primer acercamiento para solicitud,
retirar teléfono y confirmar en Android, segundo acercamiento para autorización,
comprobante y acuse. El historial permite reanudar solicitud y entrega del acuse.
Después del aprovisionamiento puede abrirse offline con el mismo usuario Windows.
La conciliación requiere volver a ingresar online.

El simulador usa identidades propias y únicamente transporte local; sus operaciones
no son evidencia emitida por el backend demo. No enviarlas al backend como pagos reales
de la demostración. No se ejecutó simulador en esta entrega.

## Compatibilidad y límites

- Room permanece en 16; migraciones 5→16 se conservan, pero no fueron ejecutadas.
- POS agrega migración 4→5 para inventario público del emisor; no se abrió ninguna
  base POS existente durante la implementación.
- V2 solo concilia evidencia previamente inventariada. La ventana sigue cerrada;
  los datos heredados requieren un procedimiento separado sobre copias.
- Antes de rotar emisor, conservar las claves públicas antiguas en el inventario
  externo y volver a distribuir la configuración fijada a Android/POS.
- Revocar claves exige herramienta administrativa con base y fecha UTC explícitas;
  nunca inventar fechas para revocaciones anteriores.
- Hardware, migraciones, concurrencia, contabilidad, restauración e interacción entre
  teléfonos siguen pendientes. Una compilación correcta no acredita estos resultados.
