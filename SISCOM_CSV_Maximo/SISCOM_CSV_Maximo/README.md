# SISCOM — guardado CSV de máxima continuidad sin alterar el resto

Esta actualización se limita al mecanismo de almacenamiento en Python.

## Qué cambia

- La lectura UART, el protocolo, la frecuencia de adquisición configurada en la FPGA,
  la interfaz, las gráficas y el análisis permanecen iguales.
- La cola de bloques seriales de la aplicación deja de tener un límite fijo de 20 000
  elementos, para evitar que el hilo lector se bloquee por saturación de esa cola.
- El CSV se escribe desde un hilo dedicado, no desde el hilo de la interfaz gráfica.
- Las filas se escriben por lotes de hasta 1 000 muestras o cada segundo, lo que ocurra
  primero. Al detener la grabación, se vacía la cola completa y se cierra el archivo.
- Se encola cada trama válida que el parser recibe; no se submuestrea ni se crean datos
  artificiales. El orden de las filas se conserva.

## Qué NO cambia

- No modificar ningún VHDL ni volver a compilar/programar la FPGA por esta actualización.
- No cambiar los baudios UART, el formato de trama, el CRC ni la frecuencia del sensor.
- No cambiar el diseño de la interfaz ni las gráficas ni las métricas del analizador.

## Instalación

1. Haz una copia de seguridad de tu carpeta `python` actual.
2. Sustituye `siscom.py` y `siscom_core.py` por los incluidos aquí.
3. Conserva `analizar_movimiento.py` y `requirements.txt` como estaban; se incluyen copias
   para que el paquete esté completo.
4. Ejecuta igual que antes:

```powershell
py siscom.py --port COM10
```

Conecta, presiona **Iniciar CSV**, realiza tu prueba y presiona **Detener CSV**.

## Importante: límite físico

Este cambio maximiza la continuidad del guardado en la computadora, pero no aumenta la
frecuencia a la que la FPGA produce muestras. El número máximo de filas disponibles sigue
limitado por las tramas que la FPGA transmite y que llegan con CRC válido. La tasa observada
se debe revisar con el contador de secuencia y el contador de paquetes perdidos de SISCOM.

La cola de escritura no tiene límite fijo para evitar descartar muestras por un pico temporal
de I/O; como contrapartida, si el disco permanece bloqueado durante mucho tiempo, el consumo
de memoria puede crecer. Al terminar la captura, el cierre espera a que todas las filas
encoladas queden escritas.
