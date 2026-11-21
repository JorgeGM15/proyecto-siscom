# SISCOM — Monitoreo de movimientos con FPGA DE10-Lite

**Entrega de referencia para implementar, compilar y probar en hardware.**

La tarjeta DE10-Lite mide aceleracion XYZ con su ADXL345. La FPGA no calcula
angulos, impactos ni tendencias: solo adquiere las lecturas y las transmite.
La computadora interpreta y guarda los datos mediante Python.

> **Transparencia:** Esta entrega es una implementacion autocontenida nueva,
> elaborada a partir del contexto del proyecto y las especificaciones de la
> DE10-Lite/ADXL345. Los ZIP y VHDL originales de la conversacion no pudieron
> reabrirse en esta sesion por un error de acceso. Por eso no se afirma que se
> haya editado o compilado el repositorio original. El UART incluido utiliza la
> misma interfaz de puertos mencionada antes; si quieres sustituirlo por tu
> `uart_top.vhd` original, solo hazlo si sus nombres/puertos/genericos coinciden.

## 1. Estructura

```text
SISCOM_Integrado/
  SISCOM.qpf                 Proyecto Quartus Prime
  SISCOM.qsf                 Pines de la DE10-Lite y archivos VHDL
  SISCOM.sdc                 Reloj de 50 MHz
  rtl/
    adxl345_reader.vhd       SPI mode 3, lectura burst XYZ, 50 Hz aprox.
    uart_top.vhd             UART 8N1 a 115200 baudios, TX y RX
    siscom_top.vhd           Paquetes binarios y comandos desde Python
    uart_smoke_top.vhd       Prueba OPCIONAL del UART sin acelerometro
  python/
    siscom_core.py           Parser CRC, calculos, deteccion de eventos, CSV
    siscom.py                GUI en vivo, modo terminal y simulador
    uart_raw_test.py         Lector de prueba UART sin protocolo
    requirements.txt         pyserial y matplotlib
    tests/test_siscom.py     Pruebas automaticas de protocolo y calculos
  prueba_simulada.csv        Ejemplo generado con datos sinteticos
```

## 2. Componentes fisicos

- Placa Terasic DE10-Lite con su ADXL345 integrado.
- Cable USB-Blaster (para programacion); no transporta por si solo las tramas UART.
- Convertidor **USB-UART de nivel logico 3.3 V** (CP2102, FT232 o similar).
- Cables Dupont para TX, RX y GND; una computadora con Quartus y Python.

### Cableado del USB-UART (JP1)

| DE10-Lite | FPGA | Convertidor USB-UART |
|---|---|---|
| GPIO[0] | PIN_V10 | RX del adaptador |
| GPIO[1] | PIN_W10 | TX del adaptador |
| GND del conector de expansion | — | GND del adaptador |

**No conectar VCC del adaptador a la DE10-Lite**, si la placa ya esta
alimentada por su USB. No conectar señales de 5 V directamente a GPIO.
Comprobar que el adaptador transmite y recibe a 3.3 V (no basta con que
su alimentacion diga 3.3 V). Consultar la numeracion del cabezal JP1
fisico y la tabla de conexiones en el manual de la placa.

Otros pines necesarios son **internos de la FPGA y el acelerometro integrado**:
MAX10_CLK1_50=P11, KEY0=B8 (reset activo bajo), GSENSOR_CS_N=AB16,
GSENSOR_SCLK=AB15, GSENSOR_SDI=V11 (MOSI), GSENSOR_SDO=V12 (MISO).
**F15 pertenece a SW9, no a KEY0.**

## 3. Instalacion en Quartus

1. **Conservar sin cambios una copia de la practica funcional original.**
2. Extraer este paquete en una ruta sin acentos ni espacios, por ejemplo
   `C:\\FPGA\\SISCOM_Integrado`.
3. Abrir `SISCOM.qpf` mediante **File > Open Project**.
4. En **Assignments > Settings > General** comprobar `TOP_LEVEL_ENTITY = siscom_top`
   y el dispositivo `10M50DAF484C7G`.
5. Confirmar los archivos de `rtl/` (estan registrados en `SISCOM.qsf`).
6. Ir a **Processing > Start Compilation**.
7. Solucionar cualquier error de compilacion antes de continuar.
8. Conectar la placa por USB-Blaster; abrir **Tools > Programmer**.
9. Elegir USB-Blaster y el `.sof` de `output_files/SISCOM.sof`,
   activar **Program/Configure** y presionar **Start**.
10. Presionar y soltar `KEY0` tras programar; la inicializacion del
    acelerometro tarda aproximadamente 40 ms antes de la primera muestra.

**Este entorno no dispone de Quartus ni de una DE10-Lite fisica. Por tanto
no se ha probado la compilacion del VHDL ni la lectura real de la placa.**
En caso de error, revisar la primera linea del reporte de compilacion y
comparar la entidad e interfaz con los archivos incluidos.

## 4. Prueba previa: UART sin sensor (opcional, recomendable)

1. En Quartus poner temporalmente `uart_smoke_top` como Top-level Entity
   (si usas GUI, aplica cambios a la revision).
2. Compilar y programar; abre en una terminal:

   ```bash
   cd python
   python -m pip install -r requirements.txt
   python uart_raw_test.py --port COM5
   ```

3. Se deben recibir periodicamente **55 AA 00**, cada 500 ms aprox.
4. Regresar la entidad principal a **siscom_top**, recompilar y reprogramar.

Este test envia bytes **sin** encabezado/CRC: se lee con `uart_raw_test.py`,
no con el parser de tramas de `siscom.py`.

## 5. Instalar Python y comprobar software ANTES de conectar la placa

Se recomienda Python 3.10 o superior. En Windows, abre PowerShell:

```powershell
cd C:\FPGA\SISCOM_Integrado\python
py -m pip install -r requirements.txt
py -m unittest discover -s tests -v
py siscom.py --simulate --headless --seconds 8 --csv prueba.csv
py siscom.py --simulate
```

En macOS/Linux usa `python3` en lugar de `py`. En Linux puede requerirse
el paquete de sistema `python3-tk` para la GUI.

Resultados esperados: seis pruebas correctas, 400 muestras simuladas a
50 Hz durante 8 segundos, y un CSV con eventos sinteticos. `--simulate`
no recibe nada de la FPGA: solo valida el software.

## 6. Recepcion de la FPGA en Python

**Modo grafico:**

```bash
python siscom.py --port COM5
```

O bien abre `python siscom.py`, escribe COM5, pulsa **Conectar** y luego
**Guardar CSV**. En Linux normalmente sera `/dev/ttyUSB0`; en macOS,
`/dev/cu.usbserial...`. Verificalo en el administrador de dispositivos o
el boton «Ver puertos».

**Modo terminal con CSV durante 30 segundos:**

```bash
python siscom.py --port COM5 --headless --seconds 30 --csv datos_reales.csv
```

Pueden aparecer primeros datos sin mover la placa: al estar horizontal,
Z deberia indicar cerca de +/-1 g y X/Y cerca de 0 g (segun orientacion).
Si X=Y=Z=0 de forma permanente, revisa la comunicacion SPI. Si no llega
ningun byte, primero realiza la prueba UART independiente.

### Comandos por RX

| Caracter enviado desde Python | Efecto FPGA |
|---|---|
| `S` (0x53) | Reanuda envio de muestras |
| `P` (0x50) | Pausa al finalizar la trama en curso |
| `R` (0x52) | Reinicia contador de secuencia |

Al presionar `KEY0` la FPGA se reinicia y queda enviando por defecto.

## 7. Especificacion exacta de comunicacion

- UART **115200 baudios, 8N1** (1 bit inicio, 8 datos, sin paridad, 1 stop).
- Trama **binaria de 12 bytes**, no cadena ASCII:

| Offset | Campo | Orden |
|---:|---|---|
| 0 | `0xAA` | Encabezado 1 |
| 1 | `0x55` | Encabezado 2 |
| 2-3 | sequence | uint16 little-endian |
| 4-5 | X | int16 complemento a dos, little-endian |
| 6-7 | Y | int16 complemento a dos, little-endian |
| 8-9 | Z | int16 complemento a dos, little-endian |
| 10-11 | CRC16 | uint16 little-endian |

**CRC-16/CCITT-FALSE**: polinomio `0x1021`, inicio `0xFFFF`,
RefIn/RefOut=False, XorOut=0; se calcula **solo sobre bytes 2 a 9**.
Cabecera no entra en CRC. Vector de prueba `123456789` -> `0x29B1`.
El contador de secuencia es modulo 65536; Python estima faltantes por
saltos de contador, pero no detecta directamente muestras descartadas
antes de que la FPGA les asigne contador.

El ADXL345 se inicializa mediante escrituras SPI de 4 cables:
- `BW_RATE[0x2C] = 0x0A` (ODR nominal 100 Hz).
- `DATA_FORMAT[0x31] = 0x0B` (FULL_RES, +/-16g, 4-wire SPI).
- `POWER_CTL[0x2D] = 0x08` (modo de medicion).

La FPGA realiza lectura multibyte de `0x32` a `0x37` (comando `0xF2`),
seguida de una pausa de aproximadamente 20 ms. La frecuencia real de
tramas es por ello **algo menor que 50 Hz** (~49.9 Hz).

## 8. Analisis y criterios iniciales en Python

- Conversion: **aceleracion_g = entero * 0.0039**, factor nominal que
  requiere calibracion si desean precision metrologica.
- Magnitud: `sqrt(ax² + ay² + az²)`. En reposo ~1 g.
- Angulos a partir de gravedad suavizada: roll y pitch, no yaw.
- Aceleracion dinamica = aceleracion medida menos gravedad filtrada.
- Eje predominante = max RMS de dinamica X/Y/Z en ventana de 2 segundos.
- Impacto preliminar = modulo de componente dinamica >= **0.75 g**,
  con tiempo de bloqueo de 0.35 segundos entre eventos.
- Inclinacion excesiva preliminar = roll o pitch >= **30 grados**,
  cuando los datos permiten una estimacion razonable.
- Vibracion preliminar = RMS dinamico >= **0.09 g**.

Todos los umbrales anteriores son **propuestas iniciales de laboratorio**,
no criterios certificados de integridad. Se deben ajustar mediante pruebas
controladas. Un acelerometro sin giroscopio no determina yaw ni puede
separar perfectamente gravedad de movimiento rapido.

## 9. Protocolo de validacion en hardware

1. **Reposo horizontal 20 s:** deben llegar ~50 paquetes/s,
   `|A|` proximo a 1g, sin CRC invalidos.
2. **Inclinacion conocida:** inclinar ~30 grados; observar roll/pitch.
3. **Rotacion de 90 grados:** verificar que se reasigne la gravedad entre ejes.
4. **Movimiento repetitivo:** agitar con suavidad sobre un eje y comparar RMS.
5. **Impacto suave y controlado:** registrar un pico sin golpear directamente
   la placa ni aplicar fuerzas peligrosas.
6. **Pausar y reanudar:** comprobar comandos RX `P` y `S`.
7. **Desconectar/reconectar:** verificar resincronizacion y conteo CRC.
8. **Guardar CSV:** revisar datos y tendencias con software de hoja de calculo.

Si los datos estan invertidos, comprobar orientacion y asignacion de
signos; si todos son ceros, primero evaluar SPI; si se ven bytes extraños
con `uart_raw_test.py`, verificar cruce TX/RX, tierra compartida y 115200 8N1.

## 10. Limites y pasos de mejora

Esta version es un prototipo funcional **por validar en hardware**.
En laboratorio conviene medir la tasa real, verificar con osciloscopio
el SPI, y contrastar con un instrumento de referencia o angulos
controlados. Para un sistema robusto de transporte se puede añadir
FIFO del sensor, marca de tiempo de la FPGA, calibracion de offset,
y memoria no volatil (la captura en vivo se pierde si se desconecta USB).

Fuentes de hardware:
- Manual DE10-Lite (Terasic): https://manuals.plus/m/8345cbb747f2627e17801ea81a0a85201d7792405f26310a068aa9b62be78501
- Datasheet ADXL345 (Analog Devices): https://www.analog.com/media/en/technical-documentation/data-sheets/adxl345.pdf
