# SISCOM Web — monitor local de la FPGA DE10-Lite

Interfaz web local para leer la UART por COM desde la misma PC, visualizar XYZ,
observar métricas RMS/dominancia y guardar CSV. El navegador no abre COM10:
lo hace el servidor Python local y publica los resultados a la página.

## Requisitos
- Windows 10/11, Python 3.10 o superior.
- Arduino UNO usado como puente USB-UART, manteniendo el conversor USB-serial.
- DE10-Lite programada con el diseño SISCOM que transmite tramas binarias de 12 bytes.
- Puerto correcto de Windows (por ejemplo COM10).

## Protocolo serial esperado
115200 baudios, 8N1. Cada trama son 12 bytes:
`AA 55 | seq uint16 LE | X int16 LE | Y int16 LE | Z int16 LE | CRC16 uint16 LE`.
CRC-16/CCITT-FALSE se calcula sobre bytes 2..9. El lector usa `FrameParser`,
`SequenceClock`, `MotionAnalyzer` y `CSVRecorder` de la versión estable SISCOM.

## Ejecutar en Windows
1. Cierra el SISCOM de escritorio u otro monitor serial: COM10 solo puede abrirse en una app a la vez.
2. Descomprime `SISCOM_Web.zip`.
3. Doble clic en `start_siscom_web.bat` (instala dependencias la primera vez y arranca servidor).
4. Abre `http://127.0.0.1:8000` en Chrome o Edge.
5. Selecciona COM10, usa la misma frecuencia nominal configurada en FPGA, y pulsa **Conectar FPGA**.
6. Pulsa **Iniciar CSV**, realiza tu prueba y luego **Detener y guardar**. Los archivos quedan en `captures/` y también aparecen como enlaces de descarga en la página.

El botón **Ver demostración** genera datos sintéticos para probar la interfaz sin hardware. No son mediciones de la FPGA.

## Características
- Lectura serial en un hilo dedicado, parser binario y CRC.
- Gráficas individuales X/Y/Z (aceleración dinámica m/s²).
- Valores actuales absolutos y dinámicos en m/s².
- RMS, promedio absoluto, pico y eje predominante en ventana móvil.
- Muestras válidas, tasa recibida, pérdidas de secuencia y errores CRC.
- Escritura asíncrona CSV por lotes (1000 filas o 1 s) sin submuestreo deliberado.
- Comandos FPGA `S` y `P` para iniciar/pausar transmisión.
- Descarga de las capturas generadas.

## Importante
- La frecuencia nominal de la interfaz debe coincidir con el `sample_rate_hz` usado para la temporización. No modifica la frecuencia de la FPGA.
- La página y el backend corren en `127.0.0.1`; el acceso serial ocurre en el PC local. No se suben datos a internet.
- Si el servidor no lista COM10, revisa `pyserial` y el Administrador de dispositivos.
- Si la página conecta pero no llegan muestras, verifica el protocolo binario, CRC, TX/RX y que el VHDL realmente transmita paquetes SISCOM, no la prueba `uart_smoke_top` (55 AA 00).
- El código es un prototipo de laboratorio. El hardware real debe comprobarse en la placa; la demostración sintética solo verifica la UI.

## Servidor web local vs. sitio público

La interfaz se abre en un navegador, pero el servidor debe ejecutarse en la misma
computadora física conectada al Arduino/FPGA porque es esa computadora la que tiene
el dispositivo COM. Para ver la página desde otro dispositivo de la red se puede
configurar el servidor en una IP LAN, pero eso requiere configurar firewall y
seguridad; no es necesario para la demostración de laboratorio.

## Prueba sin hardware

Pulsa **Ver demostración**. Se generan muestras sintéticas de 100 Hz y podrás
probar gráficas, métricas, CSV y análisis offline. La banda superior indica que es
una demostración; no debe confundirse con mediciones reales.

## Análisis de archivos guardados

En la sección Capturas guardadas, pulsa **Analizar** sobre un CSV. El servidor
calcula promedio absoluto, RMS y pico de aceleración dinámica en m/s² para cada eje,
y señala el predominante por RMS durante todo el archivo.

## Controles desde el navegador

- **Conectar FPGA:** abre el puerto seleccionado a 115200 8N1 y envía `S`.
- **Pausar transmisión / Reanudar transmisión:** envía `P` / `S` al UART RX de la FPGA.
- **Iniciar CSV / Detener y guardar:** inicia y cierra el registro por lotes.
- **Ver demostración:** usa datos sintéticos sin abrir ningún puerto COM.

## Análisis web de CSV guardados localmente

1. Conecta COM10 (o el puerto que corresponda) y presiona **Iniciar CSV**.
2. Al terminar, presiona **Detener y guardar**. El archivo completo se conserva
   automáticamente en `captures/` dentro de la carpeta del proyecto en tu PC.
3. En **Capturas guardadas en esta computadora**, presiona **Analizar**.
4. La página mostrará las barras de promedio absoluto de aceleración dinámica
   para X, Y y Z, los valores con cuatro decimales y tres gráficas independientes
   de aceleración dinámica (m/s²) frente al tiempo normalizado (0–100 %).
5. Puedes pulsar **Descargar** para guardar otra copia del CSV en Descargas.

El cálculo de estadísticas utiliza **todas las muestras** del archivo. Para que
la página siga siendo rápida con archivos largos, las gráficas temporales
representan un máximo de 2400 puntos por eje distribuidos sobre todo el
intervalo; el CSV original no se reduce ni se modifica. El tiempo normalizado
se obtiene de las marcas temporales originales. La aceleración dinámica
se calcula restando una estimación filtrada de la gravedad, no a partir
de la aceleración total.

**Nota:** los CSV se guardan en el disco del equipo que ejecuta el servidor
Python. Si abres la página desde otro equipo, la descarga permite copiarlo.
