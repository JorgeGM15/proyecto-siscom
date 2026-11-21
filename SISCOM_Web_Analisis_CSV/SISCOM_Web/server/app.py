from __future__ import annotations

import argparse
import math
import threading
import time
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from siscom_core import CSVRecorder, Frame, FrameParser, MotionAnalyzer, SequenceClock
from analizar_movimiento import analyze as analyze_csv_rows, load_samples

ROOT = Path(__file__).resolve().parents[1]
WEB_DIR = ROOT / "web"
CAPTURE_DIR = ROOT / "captures"
CAPTURE_DIR.mkdir(exist_ok=True)

app = FastAPI(title="SISCOM Web", version="1.0.0")
app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")


class ConnectRequest(BaseModel):
    port: str = Field(min_length=1, max_length=64)
    sample_rate_hz: float = Field(default=100.0, gt=0, le=2000)


class RecordRequest(BaseModel):
    filename: str = Field(default="", max_length=180)


class Runtime:
    """Serial reader, frame parser, online metrics and asynchronous CSV capture."""
    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.serial_obj = None
        self.serial_thread: threading.Thread | None = None
        self.stop_event = threading.Event()
        self.connected = False
        self.demo = False
        self.port = ""
        self.sample_rate_hz = 100.0
        self.parser = FrameParser()
        self.clock = SequenceClock(100.0)
        self.analyzer = MotionAnalyzer()
        self.recorder: CSVRecorder | None = None
        self.recording_filename = ""
        self.last_saved_path: Path | None = None
        self.sample_id = 0
        self.total_valid = 0
        self.rate_events: deque[tuple[float, int]] = deque(maxlen=1000)
        self.samples: deque[dict[str, Any]] = deque(maxlen=12000)
        self.metrics_window: deque[dict[str, float]] = deque(maxlen=2000)
        self.last_sample: dict[str, Any] | None = None
        self.last_error = ""
        self.recording_count = 0
        self.io_lock = threading.Lock()
        self.demo_thread: threading.Thread | None = None

    def reset_session(self, rate: float) -> None:
        self.sample_rate_hz = rate
        self.parser = FrameParser()
        self.clock = SequenceClock(rate)
        self.analyzer = MotionAnalyzer()
        self.sample_id = 0
        self.total_valid = 0
        self.rate_events.clear()
        self.samples.clear()
        self.metrics_window.clear()
        self.last_sample = None
        self.last_error = ""
        self.recording_count = 0

    def connect(self, port: str, rate: float) -> None:
        self.disconnect()
        try:
            import serial
        except ImportError as exc:
            raise RuntimeError("Falta PySerial. Instala requirements.txt con: py -m pip install -r requirements.txt") from exc
        try:
            ser = serial.Serial(port=port, baudrate=115200, bytesize=8,
                                parity="N", stopbits=1, timeout=0.03)
        except Exception as exc:
            raise RuntimeError(f"No se pudo abrir {port}: {exc}") from exc
        with self.lock:
            self.reset_session(rate)
            self.serial_obj = ser
            self.connected = True
            self.demo = False
            self.port = port
            self.stop_event.clear()
            ser.reset_input_buffer()
            ser.write(b"S")
            self.serial_thread = threading.Thread(target=self._serial_loop,
                                                  name="SISCOM-serial", daemon=True)
            self.serial_thread.start()

    def _serial_loop(self) -> None:
        while not self.stop_event.is_set():
            try:
                with self.lock:
                    ser = self.serial_obj
                if ser is None:
                    break
                waiting = ser.in_waiting
                chunk = ser.read(max(1, min(waiting, 8192)))
                arrival = time.time()
                if chunk:
                    for frame in self.parser.feed(chunk):
                        self._accept_frame(frame, arrival)
            except Exception as exc:
                with self.lock:
                    self.last_error = str(exc)
                break
        with self.lock:
            self.connected = False

    def _accept_frame(self, frame: Frame, arrival: float) -> None:
        timestamp, _missing = self.clock.timestamp(frame.sequence, arrival)
        if timestamp is None:
            return
        row = self.analyzer.analyze(frame, timestamp, self.clock.lost_packets,
                                    self.sample_rate_hz)
        with self.lock:
            self.sample_id += 1
            self.total_valid += 1
            now_mono = time.monotonic()
            self.rate_events.append((now_mono, self.total_valid))
            row = {k: (float(v) if isinstance(v, str) and k not in ("tilt_reliable",) else v)
                   for k, v in row.items()}
            row["id"] = self.sample_id
            self.samples.append(row)
            self.metrics_window.append({
                "x": float(row["dynamic_x_ms2"]),
                "y": float(row["dynamic_y_ms2"]),
                "z": float(row["dynamic_z_ms2"]),
            })
            self.last_sample = row
            recorder = self.recorder
            if recorder:
                try:
                    recorder.add({k: v for k, v in row.items() if k != "id"})
                    self.recording_count += 1
                except Exception as exc:
                    self.last_error = f"Error CSV: {exc}"

    def start_record(self, requested: str) -> str:
        with self.lock:
            if self.recorder is not None:
                raise RuntimeError("Ya hay una grabación CSV activa.")
            if not self.connected and not self.demo:
                raise RuntimeError("Conecta la FPGA antes de iniciar la grabación.")
            clean = Path(requested).name if requested.strip() else ""
            if not clean:
                clean = f"SISCOM_{datetime.now():%Y%m%d_%H%M%S}.csv"
            if not clean.lower().endswith(".csv"):
                clean += ".csv"
            path = CAPTURE_DIR / clean
            if path.exists():
                stem, suffix = path.stem, path.suffix
                path = CAPTURE_DIR / f"{stem}_{datetime.now():%H%M%S}{suffix}"
            self.recorder = CSVRecorder(path, flush_every=1000, flush_interval_s=1.0)
            self.recording_filename = path.name
            self.last_saved_path = path
            self.recording_count = 0
            return path.name

    def stop_record(self) -> dict:
        with self.lock:
            recorder = self.recorder
            if recorder is None:
                return {"recording": False, "saved": self.recording_filename,
                        "samples": self.recording_count}
            self.recorder = None
            name = self.recording_filename
            count = recorder.count
        recorder.close()
        with self.lock:
            self.recording_count = count
        return {"recording": False, "saved": name, "samples": count}

    def send_command(self, command: bytes) -> None:
        with self.lock:
            ser = self.serial_obj
            active = self.connected and ser is not None
        if not active:
            raise RuntimeError("No hay una conexión UART activa.")
        with self.io_lock:
            ser.write(command)

    def disconnect(self) -> None:
        self.stop_event.set()
        with self.lock:
            ser = self.serial_obj
            thread = self.serial_thread
            self.serial_obj = None
            self.serial_thread = None
        if ser is not None:
            try:
                with self.io_lock:
                    ser.write(b"P")
                ser.close()
            except Exception:
                pass
        if thread and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=1.0)
        try:
            self.stop_record()
        except Exception as exc:
            with self.lock:
                self.last_error = str(exc)
        with self.lock:
            self.connected = False
            self.demo = False
            self.port = ""

    def start_demo(self) -> None:
        self.disconnect()
        with self.lock:
            self.reset_session(100.0)
            self.connected = True
            self.demo = True
            self.port = "DEMO (datos sintéticos)"
            self.stop_event.clear()
        self.demo_thread = threading.Thread(target=self._demo_loop, daemon=True)
        self.demo_thread.start()

    def _demo_loop(self) -> None:
        import random
        seq = 0
        start = time.monotonic()
        while not self.stop_event.is_set():
            t = time.monotonic() - start
            noise = lambda: random.uniform(-0.006, 0.006)
            x, y, z = noise(), noise(), 1.0 + noise()
            if 2 < t < 4:
                x += 0.22 * math.sin(2 * math.pi * 3 * t)
            if 5 < t < 7:
                y += 0.35 * math.sin(2 * math.pi * 2 * t)
            if 8 < t < 8.08:
                z += 0.8
            to_raw = lambda a: max(-32768, min(32767, round(a / 0.0039)))
            frame = Frame(seq & 0xFFFF, to_raw(x), to_raw(y), to_raw(z))
            self._accept_frame(frame, time.time())
            seq += 1
            self.stop_event.wait(0.01)

    def status(self) -> dict:
        with self.lock:
            measured_rate = 0.0
            if len(self.rate_events) >= 2:
                t0, n0 = self.rate_events[0]
                t1, n1 = self.rate_events[-1]
                if t1 > t0:
                    measured_rate = (n1 - n0) / (t1 - t0)
            rms = {}
            mean_abs = {}
            peak = {}
            for axis in "xyz":
                values = [r[axis] for r in self.metrics_window]
                rms[axis.upper()] = math.sqrt(sum(v*v for v in values) / len(values)) if values else 0.0
                mean_abs[axis.upper()] = sum(abs(v) for v in values) / len(values) if values else 0.0
                peak[axis.upper()] = max((abs(v) for v in values), default=0.0)
            dominant = max(rms, key=rms.get) if self.metrics_window else "—"
            return {
                "connected": self.connected, "demo": self.demo, "port": self.port,
                "sample_rate_hz_configured": self.sample_rate_hz,
                "sample_rate_hz_measured": measured_rate,
                "samples_received": self.total_valid,
                "lost_packets": self.clock.lost_packets,
                "crc_errors": self.parser.crc_errors,
                "discarded_bytes": self.parser.discarded_bytes,
                "recording": self.recorder is not None,
                "recording_filename": self.recording_filename,
                "recording_samples": self.recorder.count if self.recorder else self.recording_count,
                "csv_written": self.recorder.written if self.recorder else self.recording_count,
                "last_error": self.last_error,
                "current": self.last_sample,
                "rms_ms2": rms, "mean_abs_ms2": mean_abs, "peak_ms2": peak,
                "dominant_axis": dominant,
            }

    def get_samples(self, after: int, limit: int) -> dict:
        with self.lock:
            rows = [row for row in self.samples if row["id"] > after][:limit]
            oldest = self.samples[0]["id"] if self.samples else self.sample_id + 1
            newest = self.sample_id
        return {"samples": rows, "oldest_id": oldest, "newest_id": newest,
                "history_truncated": bool(after and after < oldest - 1)}


runtime = Runtime()


@app.get("/", response_class=HTMLResponse)
def index():
    return FileResponse(WEB_DIR / "index.html")


@app.get("/api/ports")
def ports():
    try:
        from serial.tools import list_ports
        return {"ports": [{"device": p.device, "description": p.description}
                           for p in list_ports.comports()]}
    except ImportError:
        return {"ports": [], "error": "PySerial no está instalado."}


@app.post("/api/connect")
def connect(req: ConnectRequest):
    try:
        runtime.connect(req.port, req.sample_rate_hz)
        return {"ok": True, "status": runtime.status()}
    except Exception as exc:
        raise HTTPException(400, str(exc))


@app.post("/api/disconnect")
def disconnect():
    runtime.disconnect()
    return {"ok": True, "status": runtime.status()}


@app.post("/api/command/{cmd}")
def command(cmd: str):
    commands = {"start": b"S", "pause": b"P", "reset": b"R"}
    if cmd not in commands:
        raise HTTPException(404, "Comando desconocido")
    try:
        runtime.send_command(commands[cmd])
        return {"ok": True, "command": cmd}
    except Exception as exc:
        raise HTTPException(400, str(exc))


@app.post("/api/record/start")
def record_start(req: RecordRequest):
    try:
        filename = runtime.start_record(req.filename)
        return {"ok": True, "filename": filename}
    except Exception as exc:
        raise HTTPException(400, str(exc))


@app.post("/api/record/stop")
def record_stop():
    try:
        result = runtime.stop_record()
        if result.get("saved"):
            result["download_url"] = "/api/download/" + result["saved"]
        return result
    except Exception as exc:
        raise HTTPException(500, str(exc))


@app.get("/api/download/{filename}")
def download(filename: str):
    safe = Path(filename).name
    path = CAPTURE_DIR / safe
    if not path.exists() or not path.is_file():
        raise HTTPException(404, "CSV no encontrado")
    return FileResponse(path, filename=safe, media_type="text/csv")


@app.get("/api/captures")
def captures():
    files = sorted(CAPTURE_DIR.glob("*.csv"), key=lambda p: p.stat().st_mtime, reverse=True)
    return {"files": [{"name": p.name, "bytes": p.stat().st_size,
                       "modified": p.stat().st_mtime,
                       "url": f"/api/download/{p.name}"} for p in files[:50]]}




def compress_timeseries(result: dict, max_points: int = 2400) -> dict:
    """Keep original CSV intact; reduce only browser plot payload.

    Uniformly sample across the full recording, retaining both endpoints.
    """
    rows = result["dynamic"]
    normalized = result["normalized_time_pct"]
    n = len(rows)
    if n <= max_points:
        indices = range(n)
    else:
        indices = sorted(set(round(i * (n - 1) / (max_points - 1))
                             for i in range(max_points)))
    return {
        "time_pct": [round(normalized[i], 6) for i in indices],
        "x_ms2": [round(rows[i][1], 6) for i in indices],
        "y_ms2": [round(rows[i][2], 6) for i in indices],
        "z_ms2": [round(rows[i][3], 6) for i in indices],
        "original_points": n,
        "plotted_points": len(indices),
    }

@app.get("/api/analyze/{filename}")
def analyze_capture(filename: str):
    safe = Path(filename).name
    path = CAPTURE_DIR / safe
    if not path.exists() or not path.is_file():
        raise HTTPException(404, "CSV no encontrado")
    try:
        rows = load_samples(path)
        result = analyze_csv_rows(rows)
        return {
            "filename": safe,
            "samples": result["samples"],
            "duration_s": result["duration"],
            "strongest_axis": result["strongest"],
            "ratio_vs_second": result["ratio"] if math.isfinite(result["ratio"]) else None,
            "ranking": result["ranking"],
            "metrics": result["metrics"],
            "timeseries": compress_timeseries(result),
        }
    except Exception as exc:
        raise HTTPException(400, f"No se pudo analizar el CSV: {exc}") from exc


@app.get("/api/status")
def status():
    return runtime.status()


@app.get("/api/samples")
def samples(after: int = Query(default=0, ge=0), limit: int = Query(default=1200, ge=1, le=5000)):
    return runtime.get_samples(after, limit)


@app.post("/api/demo/start")
def demo_start():
    runtime.start_demo()
    return {"ok": True, "status": runtime.status()}


@app.post("/api/demo/stop")
def demo_stop():
    runtime.disconnect()
    return {"ok": True}


@app.on_event("shutdown")
def shutdown():
    runtime.disconnect()


if __name__ == "__main__":
    import uvicorn
    parser = argparse.ArgumentParser(description="Servidor web local SISCOM")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    uvicorn.run("app:app", host=args.host, port=args.port, reload=False)
