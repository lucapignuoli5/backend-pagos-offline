# Evidencia reproducible

`pos_simulator_latency_2026-10-14.json` conserva las veinte muestras usadas para calcular mediana y percentil 95 del flujo POS simulado.

La medición se reproduce desde la raíz del repositorio con:

```powershell
.\venv\Scripts\python.exe benchmarks\pos_simulator_latency.py --iterations 20 --warmups 3 --output evidence\pos_simulator_latency_2026-10-14.json
```

El intervalo `request_delivery` mide el primer intercambio electrónico. La confirmación simulada se ejecuta fuera del cronómetro. `receipt_and_ack` mide el segundo intercambio. `electronic_total` suma ambos intervalos por repetición y excluye la confirmación humana y la espera entre acercamientos.

El transporte está íntegramente en memoria. Los resultados no incluyen USB, PC/SC, radiofrecuencia, ACR122U, Android físico, red ni conciliación y no acreditan la meta experimental sobre hardware.
