"""Prueba UART independiente: recibe bytes hexadecimales de uart_smoke_top.vhd."""
import argparse
import serial

ap = argparse.ArgumentParser()
ap.add_argument('--port', required=True, help='COM5 o /dev/ttyUSB0')
args = ap.parse_args()
with serial.Serial(args.port, 115200, timeout=1) as s:
    print('Esperado: 55 AA 00, repetido. Ctrl+C para salir.')
    while True:
        data = s.read(s.in_waiting or 1)
        if data:
            print(data.hex(' ').upper(), flush=True)
