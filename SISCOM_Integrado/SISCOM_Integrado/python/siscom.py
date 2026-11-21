"""Captura SISCOM a 100 Hz aprox. con hilo serial y CSV de alta densidad.

Uso: py siscom.py --port COM10
     py siscom.py --port COM10 --sample-rate 100
"""
from __future__ import annotations
import argparse
import queue
import threading
import time
from collections import deque
from datetime import datetime
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from siscom_core import FrameParser, SequenceClock, MotionAnalyzer, CSVRecorder


class SerialWorker(threading.Thread):
    def __init__(self, port_name: str, out_queue: queue.Queue, stop_event: threading.Event):
        super().__init__(daemon=True)
        self.port_name = port_name
        self.out_queue = out_queue
        self.stop_event = stop_event
        self.serial = None
        self.error = None

    def run(self):
        try:
            import serial
            self.serial = serial.Serial(self.port_name, 115200, timeout=0.02)
            # Arrancar stream. La FPGA reconoce 'S'.
            self.serial.write(b"S")
            while not self.stop_event.is_set():
                waiting = self.serial.in_waiting
                data = self.serial.read(max(1, min(waiting, 4096)))
                if data:
                    # Se registra la hora de llegada del bloque; el timestamp de
                    # muestra se reconstruye después usando el contador FPGA.
                    self.out_queue.put((data, time.time()))
        except Exception as exc:
            self.error = str(exc)
        finally:
            if self.serial:
                try:
                    self.serial.write(b"P")
                    self.serial.close()
                except Exception:
                    pass


class App:
    def __init__(self, port: str | None, sample_rate: float, csv_path: str | None = None):
        self.sample_rate = sample_rate
        self.root = tk.Tk()
        self.root.title("SISCOM | Captura de alta frecuencia")
        self.root.geometry("1100x760")
        self.port_var = tk.StringVar(value=port or "COM10")
        self.status = tk.StringVar(value="Desconectado")
        self.stats = tk.StringVar(value="Muestras: 0 | Perdidas: 0 | CRC: 0 | Tasa: -- Hz")
        self.values = tk.StringVar(value="X: -- | Y: -- | Z: -- m/s²")
        self.q: queue.Queue = queue.Queue()  # sin límite para no bloquear la lectura serial
        self.stop_event = threading.Event()
        self.worker: SerialWorker | None = None
        self.parser = FrameParser()
        self.clock = SequenceClock(sample_rate)
        self.analyzer = MotionAnalyzer()
        self.recorder: CSVRecorder | None = None
        self.recorder_path: Path | None = None
        self.total_frames = 0
        self.rate_window = deque(maxlen=500)
        self.history = deque(maxlen=2000)
        self._build()
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.root.after(10, self.poll)
        self.root.after(200, self.refresh_plot)
        if port:
            self.root.after(200, self.connect)
        if csv_path:
            self.root.after(700, lambda: self.start_csv_path(csv_path))

    def _build(self):
        top = ttk.Frame(self.root, padding=10); top.pack(fill="x")
        ttk.Label(top, text="Puerto:").pack(side="left")
        ttk.Entry(top, textvariable=self.port_var, width=12).pack(side="left", padx=5)
        ttk.Button(top, text="Conectar", command=self.connect).pack(side="left", padx=3)
        ttk.Button(top, text="Desconectar", command=self.disconnect).pack(side="left", padx=3)
        ttk.Button(top, text="Iniciar CSV", command=self.start_csv).pack(side="left", padx=3)
        ttk.Button(top, text="Detener CSV", command=self.stop_csv).pack(side="left", padx=3)
        ttk.Label(top, textvariable=self.status).pack(side="right")
        ttk.Label(self.root, textvariable=self.values, font=("Arial", 13), padding=10).pack(anchor="w")
        ttk.Label(self.root, textvariable=self.stats, font=("Arial", 11), padding=(10, 0)).pack(anchor="w")
        self.plot_frame = ttk.Frame(self.root); self.plot_frame.pack(fill="both", expand=True, padx=10, pady=10)
        try:
            import matplotlib
            matplotlib.use("TkAgg")
            from matplotlib.figure import Figure
            from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
            self.fig = Figure(figsize=(10, 6), dpi=100)
            self.ax = self.fig.add_subplot(111)
            self.ax.set_title("Aceleración dinámica XYZ — últimas muestras")
            self.ax.set_xlabel("Tiempo relativo (s)"); self.ax.set_ylabel("m/s²")
            self.ax.grid(alpha=.25)
            self.canvas = FigureCanvasTkAgg(self.fig, master=self.plot_frame)
            self.canvas.get_tk_widget().pack(fill="both", expand=True)
        except ImportError:
            ttk.Label(self.plot_frame, text="Instala matplotlib para visualizar: py -m pip install matplotlib").pack()
            self.canvas = None

    def connect(self):
        if self.worker and self.worker.is_alive():
            return
        self.disconnect()
        self.stop_event.clear()
        self.q = queue.Queue()  # sin límite para no descartar bloques seriales
        self.parser = FrameParser(); self.clock = SequenceClock(self.sample_rate)
        self.analyzer = MotionAnalyzer(); self.total_frames = 0
        self.history.clear(); self.rate_window.clear()
        self.worker = SerialWorker(self.port_var.get().strip(), self.q, self.stop_event)
        self.worker.start()
        self.status.set("Conectando a " + self.port_var.get().strip())
        self.root.after(300, self.check_worker)

    def check_worker(self):
        if self.worker and self.worker.error:
            self.status.set("Error: " + self.worker.error)
            messagebox.showerror("Error serial", self.worker.error)
        elif self.worker and self.worker.is_alive():
            self.status.set("Conectado: " + self.port_var.get().strip())
        else:
            self.status.set("Desconectado")

    def disconnect(self):
        if self.worker:
            self.stop_event.set()
            self.worker.join(timeout=0.5)
            self.worker = None
        self.stop_csv()
        self.status.set("Desconectado")

    def start_csv_path(self, filename: str):
        if self.recorder:
            return
        self.recorder = CSVRecorder(filename, flush_every=1000, flush_interval_s=1.0)
        self.recorder_path = Path(filename)
        self.status.set("Grabando: " + self.recorder_path.name)

    def start_csv(self):
        if self.recorder:
            return
        default = f"SISCOM_100Hz_{datetime.now():%Y%m%d_%H%M%S}.csv"
        filename = filedialog.asksaveasfilename(defaultextension=".csv", initialfile=default,
                                                 filetypes=[("CSV", "*.csv")])
        if filename:
            self.start_csv_path(filename)

    def stop_csv(self):
        if self.recorder:
            count = self.recorder.count
            name = self.recorder_path.name if self.recorder_path else "CSV"
            self.recorder.close(); self.recorder = None
            self.status.set(f"CSV guardado: {name} ({count} muestras)")

    def process(self, chunk: bytes, arrival: float):
        for frame in self.parser.feed(chunk):
            timestamp, _missing = self.clock.timestamp(frame.sequence, arrival)
            if timestamp is None:
                continue
            row = self.analyzer.analyze(frame, timestamp, self.clock.lost_packets, self.sample_rate)
            self.total_frames += 1
            self.rate_window.append((time.monotonic(), self.total_frames))
            self.history.append(row)
            if self.recorder:
                self.recorder.add(row)
            self.values.set(
                f"X: {float(row['ax_ms2']):+.4f} | Y: {float(row['ay_ms2']):+.4f} | "
                f"Z: {float(row['az_ms2']):+.4f} m/s² | Dinámica: {float(row['dynamic_total_ms2']):.4f} m/s²")

    def poll(self):
        # Vacía toda la cola pendiente en cada ciclo: la GUI no bloquea el hilo serial.
        processed = 0
        while processed < 10000:
            try:
                chunk, arrival = self.q.get_nowait()
            except queue.Empty:
                break
            self.process(chunk, arrival)
            processed += 1
        measured_rate = 0.0
        if len(self.rate_window) >= 2:
            t0, n0 = self.rate_window[0]; t1, n1 = self.rate_window[-1]
            if t1 > t0:
                measured_rate = (n1 - n0) / (t1 - t0)
        self.stats.set(
            f"Muestras recibidas: {self.total_frames} | Perdidas (contador): {self.clock.lost_packets} | "
            f"CRC incorrectos: {self.parser.crc_errors} | Tasa recepción: {measured_rate:.1f} Hz")
        self.root.after(10, self.poll)

    def refresh_plot(self):
        if self.canvas and self.history:
            rows = list(self.history)[-500:]
            times = [float(r["t_rel_s"]) for r in rows]
            self.ax.clear()
            for key, label in [("dynamic_x_ms2", "X"), ("dynamic_y_ms2", "Y"), ("dynamic_z_ms2", "Z")]:
                self.ax.plot(times, [float(r[key]) for r in rows], label=label, linewidth=0.9)
            self.ax.set_title("Aceleración dinámica XYZ — últimas muestras")
            self.ax.set_xlabel("Tiempo relativo (s)"); self.ax.set_ylabel("m/s²")
            self.ax.grid(alpha=.25); self.ax.legend(loc="upper right")
            self.canvas.draw_idle()
        self.root.after(200, self.refresh_plot)

    def close(self):
        self.disconnect()
        self.root.destroy()

    def run(self):
        self.root.mainloop()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", help="Puerto serie, por ejemplo COM10")
    ap.add_argument("--sample-rate", type=float, default=100.0,
                    help="Frecuencia configurada de muestras de la FPGA (predeterminado 100 Hz)")
    ap.add_argument("--csv", help="Ruta CSV; si se indica, la grabacion comienza automaticamente")
    args = ap.parse_args()
    if args.sample_rate <= 0:
        ap.error("--sample-rate debe ser mayor que cero")
    App(args.port, args.sample_rate, args.csv).run()

if __name__ == "__main__":
    main()
