# Contrato de pagos locales v2

## Estado y alcance

Esta especificación define el intercambio implementable entre POS de Windows, Android HCE y backend. No acredita interoperabilidad con ACR122U hasta ejecutar pruebas con el lector físico.

## Codificación y firmas

- Todo mensaje firmado es un objeto JSON UTF-8 de hasta 4096 bytes.
- Se ordenan las claves en orden lexicográfico, sin espacios entre elementos, con escapes JSON estándar y sin campos adicionales.
- Se prohíben números de punto flotante. `amount_cents` es un entero entre 1 y 100000 y `currency` es `ARS`.
- Los tiempos usan UTC con forma `YYYY-MM-DDTHH:MM:SSZ`.
- El nonce contiene exactamente 128 bits y usa Base64url sin relleno.
- La firma es ECDSA P-256 con SHA-256, codificación DER y luego Base64 estándar sin saltos.
- Las claves públicas usan SubjectPublicKeyInfo DER en Base64. Su huella es SHA-256 hexadecimal en minúsculas sobre esos bytes DER.
- El `operation_id` es un UUID v4 canónico generado por el POS y permanece igual en solicitud, comprobante, acuse y sincronizaciones.

## Mensajes

`payment_request` vincula versión, tipo, operación, comercio, terminal, centavos, moneda, nonce, emisión, vencimiento —máximo dos minutos—, ID y huella de clave POS.

`payment_receipt` repite los campos económicos y de identidad de la solicitud, agrega billetera, autorización offline, ID y huella de clave de billetera, y `request_digest`, el SHA-256 del JSON canónico de la solicitud. Android firma este mensaje.

`payment_ack` repite los campos económicos y de identidad, agrega billetera, autorización offline, ID y huella de clave POS, `receipt_digest`, `accepted_at` y el estado único `LOCALLY_ACCEPTED`. El POS lo firma después de verificar y persistir el comprobante.

Las firmas se transportan en un sobre JSON canónico con exactamente dos campos: `payload_b64`, que contiene los bytes canónicos firmados en Base64 estándar, y `signature_b64`, que contiene la firma DER en Base64 estándar. Las claves públicas no viajan en el sobre: se resuelven desde el registro previo mediante el ID y la huella incluidos en el payload. El receptor decodifica y verifica los bytes de `payload_b64` antes de usar sus campos, sin reconstruir el JSON.

## APDU v2

Se conserva el AID `F222222222`. `SELECT` devuelve únicamente versión y capacidades; nunca crea, confirma ni entrega un pago.

Los comandos propietarios usan CLA `80`, número de fragmento en P1, y P2 `00` para más fragmentos o `01` para el último. El Lc corto precede los datos. Las instrucciones son:

| INS | Nombre | Sentido |
|---|---|---|
| `10` | `PUT_REQUEST` | POS a Android, solicitud firmada fragmentada |
| `20` | `GET_STATUS` | POS consulta el estado de una operación |
| `30` | `GET_RECEIPT` | POS obtiene un fragmento del comprobante |
| `40` | `PUT_ACK` | POS entrega el acuse firmado fragmentado |

El tamaño inicial de fragmento es 160 bytes. El receptor admite como máximo 4096 bytes por mensaje, exige secuencias desde cero sin huecos y conserva la respuesta de cada comando para que una repetición exacta sea idempotente. Un fragmento distinto para la misma operación y secuencia es conflicto.

Primer acercamiento: el POS transmite y firma la solicitud; Android valida versión, firma, clave registrada, campos, nonce y vencimiento, persiste `REQUEST_RECEIVED` y muestra comercio e importe para confirmación humana.

Segundo acercamiento: el POS consulta estado y obtiene el comprobante ya persistido; verifica firma, campos, digest, vencimiento, ID y duplicados; persiste la aceptación local y devuelve el acuse. Android verifica y persiste el acuse antes de considerar completada la entrega.

Los vectores de `tests/fixtures/protocol_v2_vectors.json` fijan la serialización común. Las pruebas con simulador no sustituyen la medición con ACR122U.
