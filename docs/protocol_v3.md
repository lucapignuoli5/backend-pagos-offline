# Contrato firmado v3 — TFG-C1-BE-01

Estado: contrato puro y vectores; todavía no integrado en API, Room ni POS. C1 no acredita pagos completos ni hardware. V2 conserva sus bytes y no se vuelve a firmar.

## Representación común

Cada sobre completo y cada mensaje independiente admite hasta **4096 bytes**, UTF-8 estricto. Fragmento inicial 160 bytes. Sobre exacto: `{"payload_b64":"...","signature_b64":"..."}` con nombres ordenados, sin espacios. Base64 estándar con padding canónico y sin saltos; se rechazan bits sobrantes y variantes. Payload JSON: claves ordenadas por orden de caracteres, UTF-8 literal, sin escape HTML, espacios, floats, booleanos, null, campos duplicados o desconocidos. Los campos firmados usan ASCII según su tipo, salvo la función genérica de serialización que admite Unicode válido. Enteros estrictos int64; `version=3` no admite `3.0`, `true` ni `"3"`.

Firma ECDSA P-256/SHA-256 sobre **bytes originales del payload**, DER mínimo con r/s positivos dentro del orden P-256 y Base64 estándar. No se exige low-S porque Kotlin/Python pueden producir cualquiera de las dos formas válidas. Clave pública SPKI DER P-256 en Base64; huella SHA-256 hexadecimal minúscula del DER. Digests SHA-256 hexadecimal de los **bytes originales del payload**, nunca del sobre ni de un objeto reconstruido. El sobre y payload recibidos se conservan literalmente.

IDs: `[A-Za-z0-9][A-Za-z0-9._:-]{0,119}`. `operation_id` y `closure_id`: UUID v4 canónico minúscula. Nonce: 16 bytes en Base64url canónico de 22 caracteres sin padding. Fechas: `YYYY-MM-DDTHH:mm:ssZ`, UTC, segundos completos; productores descartan microsegundos. Importes positivos en centavos ARS, hasta `2^63-1`; sumas/productos se comprueban antes de convertir. `final_issuance_index` y `emitted_total_cents` permiten cero. Límites monetarios efectivos provienen del grant firmado y de la política de emisión; el parser no fija $1000 como máximo estructural. Solicitud y límite de TTL soportado: 1–120 segundos.

## Campos exactos de los siete tipos

Comunes de solicitud, comprobante y acuse (`C`): `version,type,operation_id,merchant_id,terminal_id,amount_cents,currency,nonce,issued_at,expires_at`.

| type | Campos exactos |
|---|---|
| `payment_request` | C + `pos_key_id,pos_key_fingerprint` |
| `offline_authorization` | `version,type,authorization_id,wallet_id,wallet_key_id,wallet_key_fingerprint,wallet_public_key_b64,currency,max_payment_cents,max_payments,authorized_total_cents,max_request_lifetime_seconds,issued_at,spend_expires_at,issuer_key_id,issuer_key_fingerprint` |
| `payment_receipt` | C + `wallet_id,offline_authorization_id,wallet_key_id,wallet_key_fingerprint,request_digest,authorization_digest,issuance_index,confirmed_at` |
| `payment_ack` | C + `wallet_id,offline_authorization_id,pos_key_id,pos_key_fingerprint,receipt_digest,accepted_at,status` |
| `offline_authorization_close` | `version,type,closure_id,authorization_id,wallet_id,wallet_key_id,wallet_key_fingerprint,authorization_digest,final_issuance_index,emitted_total_cents,manifest_digest,issued_at` |
| `payment_resolution` | `version,type,operation_id,wallet_id,merchant_id,terminal_id,amount_cents,currency,offline_authorization_id,authorization_digest,request_digest,receipt_digest,operation_status,code,resolution_revision,resolved_at,issuer_key_id,issuer_key_fingerprint` |
| `key_registration` | `version,type,key_id,purpose,owner_user_id,scope_id,fingerprint,nonce,issued_at` |

`status=LOCALLY_ACCEPTED` para acuse; `operation_status=ACCEPTED|REJECTED` para resolución. `resolution_revision` y `owner_user_id` enteros positivos. `purpose=wallet|pos`. `code` es ID ASCII no vacío; el ejemplo aceptado usa `APPLIED`. Todos los campos son obligatorios, sin null ni defaults.

El grant tiene total positivo no mayor que `max_payment_cents * max_payments` y el producto cabe en int64; TTL 1–120; `spend_expires_at > issued_at`; DER/huella wallet coincidentes. No contiene fecha límite de conciliación: el backend validará emisión/confirmación, no la fecha actual de subida. La política inicial de emisión será saldo $10.000, pago $1.000, diez pagos, grant 24 h y solicitud 120 s; esa aplicación corresponde a C2.

## Vínculos y verificadores puros

`SignedEnvelope(payload_bytes,payload,signature_b64)` expone `verify(public_key_b64)`. Python exporta `canonical_bytes`, `canonical_json`, `parse_signed_envelope`, `encode_signed_envelope`, `sign_payload`, `payload_digest`, `verify_exact_signature`, `decode_public_key`, `encode_public_key`, `public_key_fingerprint`, `parse_timestamp`, `timestamp`.

- `verify_authorization(grant, issuer_public_b64, expected_issuer_key_id=None) -> bool`: valida tipo, huella issuer, ID opcional y firma. El llamador debe aportar una clave issuer previamente confiable; recibir una pública en el mensaje no establece confianza.
- `verify_pos_signer(envelope,public_key_b64,key_id,fingerprint,merchant_id,terminal_id) -> bool`: valida firma, huella DER y alcance exacto contra metadatos de catálogo confiable, para solicitud/acuse. No acepta los metadatos del propio mensaje como prueba de propiedad.
- `validate_receipt_binding(request,receipt,grant) -> None`: mismos campos C excepto type, digests exactos, ID grant y billetera/clave/moneda coincidentes, índice 1..max_payments, importe dentro del cupo, TTL dentro del límite firmado y `grant.issued_at <= request.issued_at <= confirmed_at <= request.expires_at <= grant.spend_expires_at`. También verifica firma wallet contra DER del grant. El llamador verifica adicionalmente firma/propiedad POS y firma/confianza issuer.
- `validate_ack_binding(request,receipt,ack) -> None`: C idénticos excepto type; billetera/grant coincidentes; digests request/receipt; **mismo POS key ID y huella que solicitud**; `confirmed_at <= accepted_at <= expires_at`. El llamador verifica firma POS con su clave confiable.
- `validate_close_manifest(close,grant,manifest_bytes) -> list[dict]`: mismo grant/billetera/clave; digests grant/manifest exactos, límites y firma wallet. El backend deberá acreditar existencia y bytes de cada recibo y que no haya recibos conocidos fuera del manifest antes de liberar cupo.

Manifest independiente: array JSON canónico de objetos exactos `{"amount_cents":...,"issuance_index":...,"operation_id":"...","receipt_digest":"..."}`. Orden de entradas por índices consecutivos 1..n, operaciones únicas, importe positivo dentro del límite por pago. Puede ser `[]`. Longitud <=4096, n igual a `final_issuance_index` y <=max_payments; suma igual a `emitted_total_cents` y <=authorized_total. `manifest_digest` firma los bytes originales del array. Cierre no precede emisión grant. Ningún validador puro demuestra que una billetera modificada no oculta un recibo: sigue siendo riesgo residual.

## Transporte previsto y compatibilidad

Grant separado mediante recuperación fragmentada `INS=0x50`, asociado al ID operación, evita anidarlo en comprobante. Cuerpo SELECT canónico, sin SW: `{"authorization_instruction":80,"chunk_bytes":160,"max_message_bytes":4096,"protocol_version":3}`. Campos exactos e enteros estrictos; versión 3, instrucción 80 y tamaño 4096 exactos, fragmento 1..160. `encode_select_capabilities` y `parse_select_capabilities` validan esos límites; negociar más de 160 requiere medición física posterior. SELECT no acepta pagos. Integración y ensayo de APDU corresponden a fases siguientes.

La API v3 separará fallo de presentación de evidencia de resolución final persistida. Este contrato no aplica contabilidad ni libera reservas. Resolución firmada final deberá coincidir con los digests del comprobante local. Revocación posterior no reescribe resultados finales existentes.

Compatibilidad v2 solo admite sobres exteriores canónicos Python (`=`) o históricos Kotlin (`\u003d`), preservando bytes originales, con versión estricta entera 2; no produce nueva evidencia v2. El inventario previo y el acceso a conciliación legacy se implementarán en C2/C3.

## Vectores y prueba cruzada

`tests/fixtures/protocol_v3_vectors.json` contiene únicamente claves públicas y siete evidencias coherentes, más manifest. Cada evidencia guarda `payload,payload_b64,signature_b64,envelope_b64,payload_sha256,signer`. `keys` tiene `pos,wallet,issuer`, cada una con `key_id,public_key_b64,fingerprint`. No se conserva ninguna clave privada.

Las pruebas negativas deben alterar cada campo firmado, verificar firmante ajeno, enteros/coerciones, límites, padding 0/1/2, duplicados, JSON incompleto, nonce no canónico, DER inválido, vencimientos y vínculos. Las pruebas cruzadas deben consumir sobres completos Python en Kotlin y Kotlin en Python; comparar solo payload o regenerar sobres en el receptor no acredita R01.

`tests/fixtures/protocol_v3_kotlin_vectors.json` archiva literalmente los siete sobres producidos por Kotlin/JCA y su manifest, sin claves privadas. La prueba Python los consume directamente sin volver a firmar ni construir los sobres. Verificación manual reproducible: `python -B tools/verify_cross_language.py tests/fixtures/protocol_v3_kotlin_vectors.json`. El origen JVM se identifica en `producer`; la contraparte Android consume los vectores Python originales de esta carpeta.
