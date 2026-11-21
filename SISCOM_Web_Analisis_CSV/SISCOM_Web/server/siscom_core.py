"""Parser de tramas SISCOM, analisis dinamico y escritura CSV robusta."""
from __future__ import annotations

import csv
import math
import struct
import time
import queue
import threading
from dataclasses import dataclass
from pathlib import Path

SYNC = b"\xAA\x55"
FRAME_SIZE = 12
LSB_TO_G = 0.0039
G0 = 9.80665
CSV_FIELDS = [
    "timestamp_s", "t_rel_s", "sequence", "raw_x", "raw_y", "raw_z",
    "ax_g", "ay_g", "az_g", "ax_ms2", "ay_ms2", "az_ms2",
    "total_ms2", "dynamic_x_ms2", "dynamic_y_ms2", "dynamic_z_ms2",
    "dynamic_total_ms2", "roll_deg", "pitch_deg", "tilt_reliable",
    "lost_packets_total", "sample_rate_hz",
]


def crc16_ccitt_false(data: bytes) -> int:
    crc = 0xFFFF
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            crc = (((crc << 1) ^ 0x1021) & 0xFFFF) if crc & 0x8000 else ((crc << 1) & 0xFFFF)
    return crc


@dataclass(frozen=True)
class Frame:
    sequence: int
    x: int
    y: int
    z: int


class FrameParser:
    """Reensambla las tramas aunque los bloques seriales lleguen fragmentados."""
    def __init__(self):
        self.buffer = bytearray()
        self.crc_errors = 0
        self.valid_frames = 0
        self.discarded_bytes = 0

    def feed(self, chunk: bytes) -> list[Frame]:
        if chunk:
            self.buffer.extend(chunk)
        frames: list[Frame] = []
        while True:
            pos = self.buffer.find(SYNC)
            if pos < 0:
                keep = 1 if self.buffer.endswith(SYNC[:1]) else 0
                self.discarded_bytes += len(self.buffer) - keep
                self.buffer[:] = self.buffer[-1:] if keep else b""
                break
            if pos:
                del self.buffer[:pos]
                self.discarded_bytes += pos
            if len(self.buffer) < FRAME_SIZE:
                break
            candidate = bytes(self.buffer[:FRAME_SIZE])
            payload = candidate[2:10]
            expected = struct.unpack("<H", candidate[10:12])[0]
            if crc16_ccitt_false(payload) != expected:
                self.crc_errors += 1
                del self.buffer[0]
                self.discarded_bytes += 1
                continue
            seq, x, y, z = struct.unpack("<Hhhh", payload)
            frames.append(Frame(seq, x, y, z))
            del self.buffer[:FRAME_SIZE]
            self.valid_frames += 1
        return frames


class SequenceClock:
    """Reloj temporal de muestras basado en sequence y frecuencia objetivo.

    Evita asignar el mismo timestamp a varias tramas que llegan juntas en un
    bloque serial. Los huecos de sequence conservan su tiempo y se cuentan.
    """
    def __init__(self, sample_rate_hz: float = 100.0):
        if sample_rate_hz <= 0:
            raise ValueError("sample_rate_hz debe ser positivo")
        self.period = 1.0 / sample_rate_hz
        self.first_seq: int | None = None
        self.last_seq: int | None = None
        self.unwrapped = 0
        self.epoch_wall = 0.0
        self.lost_packets = 0
        self.duplicates = 0

    def reset(self):
        self.first_seq = None
        self.last_seq = None
        self.unwrapped = 0
        self.epoch_wall = 0.0
        self.lost_packets = 0
        self.duplicates = 0

    def timestamp(self, seq: int, receive_wall_time: float | None = None) -> tuple[float | None, int]:
        now = time.time() if receive_wall_time is None else receive_wall_time
        if self.first_seq is None:
            self.first_seq = seq
            self.last_seq = seq
            self.unwrapped = 0
            self.epoch_wall = now
            return self.epoch_wall, 0
        delta = (seq - self.last_seq) & 0xFFFF
        if delta == 0:
            self.duplicates += 1
            return None, 0
        # Si se reinicia la FPGA durante la conexion, un salto inverso grande
        # inicia una nueva epoca en lugar de atribuir miles de paquetes perdidos.
        if delta > 0x8000:
            self.first_seq = seq
            self.last_seq = seq
            self.unwrapped = 0
            self.epoch_wall = now
            return self.epoch_wall, 0
        missing = max(0, delta - 1)
        self.lost_packets += missing
        self.unwrapped += delta
        self.last_seq = seq
        return self.epoch_wall + self.unwrapped * self.period, missing


class MotionAnalyzer:
    """Calcula aceleracion absoluta y componente dinamica, con gravedad filtrada."""
    def __init__(self, alpha_gravity: float = 0.015):
        if not 0 < alpha_gravity <= 1:
            raise ValueError("alpha_gravity debe estar en (0, 1]")
        self.alpha = alpha_gravity
        self.gravity: list[float] | None = None
        self.first_t: float | None = None
        self.count = 0

    def reset(self):
        self.gravity = None
        self.first_t = None
        self.count = 0

    def analyze(self, frame: Frame, timestamp: float, lost_total: int,
                sample_rate_hz: float) -> dict:
        raw_g = [frame.x * LSB_TO_G, frame.y * LSB_TO_G, frame.z * LSB_TO_G]
        absolute_ms2 = [v * G0 for v in raw_g]
        if self.gravity is None:
            self.gravity = raw_g[:]
        else:
            for i in range(3):
                self.gravity[i] = (1.0 - self.alpha) * self.gravity[i] + self.alpha * raw_g[i]
        dynamic_g = [raw_g[i] - self.gravity[i] for i in range(3)]
        dynamic_ms2 = [v * G0 for v in dynamic_g]
        total_ms2 = math.sqrt(sum(v * v for v in absolute_ms2))
        dynamic_total_ms2 = math.sqrt(sum(v * v for v in dynamic_ms2))
        roll = math.degrees(math.atan2(self.gravity[1], self.gravity[2]))
        pitch = math.degrees(math.atan2(-self.gravity[0], math.hypot(self.gravity[1], self.gravity[2])))
        mag_g = math.sqrt(sum(v * v for v in raw_g))
        reliable = abs(mag_g - 1.0) < 0.20 and dynamic_total_ms2 < 0.25 * G0
        if self.first_t is None:
            self.first_t = timestamp
        self.count += 1
        return {
            "timestamp_s": f"{timestamp:.6f}",
            "t_rel_s": f"{timestamp - self.first_t:.6f}",
            "sequence": frame.sequence,
            "raw_x": frame.x, "raw_y": frame.y, "raw_z": frame.z,
            "ax_g": f"{raw_g[0]:.6f}", "ay_g": f"{raw_g[1]:.6f}", "az_g": f"{raw_g[2]:.6f}",
            "ax_ms2": f"{absolute_ms2[0]:.6f}", "ay_ms2": f"{absolute_ms2[1]:.6f}",
            "az_ms2": f"{absolute_ms2[2]:.6f}", "total_ms2": f"{total_ms2:.6f}",
            "dynamic_x_ms2": f"{dynamic_ms2[0]:.6f}", "dynamic_y_ms2": f"{dynamic_ms2[1]:.6f}",
            "dynamic_z_ms2": f"{dynamic_ms2[2]:.6f}",
            "dynamic_total_ms2": f"{dynamic_total_ms2:.6f}",
            "roll_deg": f"{roll:.4f}", "pitch_deg": f"{pitch:.4f}",
            "tilt_reliable": int(reliable), "lost_packets_total": lost_total,
            "sample_rate_hz": f"{sample_rate_hz:.3f}",
        }


class CSVRecorder:
    """Escritura CSV asíncrona: el hilo de la GUI no espera al disco.

    Cada fila válida recibida se encola en memoria y un hilo dedicado la escribe
    en orden. No se submuestrea ni se descartan filas intencionalmente.
    """
    _STOP = object()

    def __init__(self, filename: str | Path, flush_every: int = 1000,
                 flush_interval_s: float = 1.0):
        path = Path(filename)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.file = path.open("w", newline="", encoding="utf-8", buffering=1024 * 1024)
        self.writer = csv.DictWriter(self.file, fieldnames=CSV_FIELDS)
        self.writer.writeheader()
        self.flush_every = max(1, flush_every)
        self.flush_interval_s = max(0.1, flush_interval_s)
        self.count = 0
        self.written = 0
        self.closed = False
        self.error: Exception | None = None
        self.queue: queue.Queue = queue.Queue()  # sin límite: no descartar muestras por saturación
        self.thread = threading.Thread(target=self._writer_loop, name="SISCOM-CSV", daemon=True)
        self.thread.start()

    def add(self, row: dict):
        if self.closed:
            raise RuntimeError("El grabador CSV ya está cerrado")
        if self.error:
            raise RuntimeError(f"Error escribiendo CSV: {self.error}") from self.error
        # Copia defensiva: el productor puede reutilizar/modificar su diccionario.
        self.queue.put(dict(row))
        self.count += 1

    def _writer_loop(self):
        pending = []
        last_flush = time.monotonic()
        try:
            while True:
                timeout = max(0.05, self.flush_interval_s - (time.monotonic() - last_flush))
                try:
                    item = self.queue.get(timeout=timeout)
                except queue.Empty:
                    item = None

                if item is self._STOP:
                    if pending:
                        self.writer.writerows(pending)
                        self.written += len(pending)
                        pending.clear()
                    self.file.flush()
                    return
                if item is not None:
                    pending.append(item)

                # Escritura por lotes para reducir llamadas de I/O.
                if len(pending) >= self.flush_every or (
                    pending and time.monotonic() - last_flush >= self.flush_interval_s
                ):
                    self.writer.writerows(pending)
                    self.written += len(pending)
                    pending.clear()
                    self.file.flush()
                    last_flush = time.monotonic()
        except Exception as exc:
            self.error = exc

    def close(self):
        if self.closed:
            return
        self.closed = True
        self.queue.put(self._STOP)
        self.thread.join()  # espera a que se escriban todas las filas pendientes
        try:
            self.file.flush()
        finally:
            self.file.close()
        if self.error:
            raise RuntimeError(f"No se pudo completar el CSV: {self.error}") from self.error
        if self.written != self.count:
            raise RuntimeError(
                f"CSV incompleto: se encolaron {self.count} filas y se escribieron {self.written}"
            )
