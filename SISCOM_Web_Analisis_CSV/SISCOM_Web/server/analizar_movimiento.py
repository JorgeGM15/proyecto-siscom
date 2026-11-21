#!/usr/bin/env python3
"""Analiza un CSV generado por SISCOM y compara el movimiento en X, Y y Z.

Uso:
  py analizar_movimiento.py datos.csv
  py analizar_movimiento.py datos.csv --guardar-grafica comparacion.png
  py analizar_movimiento.py datos.csv --sin-grafica

La gravedad se estima con un filtro pasa-bajas exponencial. El movimiento
por eje es la componente dinámica (aceleración medida menos gravedad estimada).
"""
from __future__ import annotations
import argparse
import csv
import math
import sys
from pathlib import Path

AXES = ("x", "y", "z")
G0 = 9.80665  # aceleracion estandar de gravedad, m/s^2 por g


def number(row, key):
    value = row.get(key, "")
    if value is None or str(value).strip() == "":
        raise ValueError(f"Falta el campo '{key}' en una fila del CSV")
    return float(value)


def load_samples(filename: Path):
    with filename.open("r", newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames:
            raise ValueError("El CSV no tiene encabezados")
        fields = set(reader.fieldnames)
        # CSV de SISCOM: aceleraciones calibradas en g.
        if {"ax_g", "ay_g", "az_g"}.issubset(fields):
            columns = ("ax_g", "ay_g", "az_g")
        # Compatibilidad con un CSV que contenga muestras crudas del sensor.
        elif {"raw_x", "raw_y", "raw_z"}.issubset(fields):
            columns = ("raw_x", "raw_y", "raw_z")
        else:
            raise ValueError("No encuentro ax_g/ay_g/az_g ni raw_x/raw_y/raw_z. "
                             "Usa el CSV exportado por SISCOM.")
        rows = []
        for line, row in enumerate(reader, start=2):
            try:
                if row.get("t_rel_s", "").strip():
                    t = number(row, "t_rel_s")
                elif row.get("timestamp_s", "").strip():
                    t = number(row, "timestamp_s")
                else:
                    # Si no hay tiempo, se asume frecuencia aproximada de 50 Hz.
                    t = (len(rows)) / 50.0
                vals = [number(row, col) for col in columns]
                if columns[0] == "raw_x":
                    vals = [v * 0.0039 for v in vals]
                if not all(math.isfinite(v) for v in [t, *vals]):
                    raise ValueError("valor no finito")
                rows.append((t, *vals))
            except (ValueError, TypeError) as e:
                raise ValueError(f"Fila {line}: {e}") from e
    if len(rows) < 2:
        raise ValueError("Se necesitan al menos dos muestras para analizar el movimiento")
    rows.sort(key=lambda r: r[0])
    if any(rows[i][0] <= rows[i-1][0] for i in range(1, len(rows))):
        raise ValueError("Los tiempos deben ser estrictamente crecientes y no repetirse")
    return rows


def analyze(rows, gravity_alpha=0.03):
    # gravity_alpha=0.03 equivale a suavizado de gravedad 0.97 en el analizador vivo.
    gravity = list(rows[0][1:4])
    dynamic = []
    for t, *acc in rows:
        for i in range(3):
            gravity[i] = (1.0 - gravity_alpha) * gravity[i] + gravity_alpha * acc[i]
        dynamic.append((t, *(acc[i] - gravity[i] for i in range(3))))

    start, end = rows[0][0], rows[-1][0]
    duration = end - start
    metrics = {}
    for axis_i, axis in enumerate(AXES):
        # Integración trapezoidal para que muestras con intervalos distintos
        # se ponderen por el tiempo y no solo por su cantidad.
        abs_integral = 0.0
        sq_integral = 0.0
        peak = 0.0
        for j in range(1, len(dynamic)):
            dt = dynamic[j][0] - dynamic[j-1][0]
            a0 = dynamic[j-1][axis_i+1]
            a1 = dynamic[j][axis_i+1]
            abs_integral += 0.5 * (abs(a0) + abs(a1)) * dt
            sq_integral += 0.5 * (a0*a0 + a1*a1) * dt
            peak = max(peak, abs(a0), abs(a1))
        # La estadistica se calcula primero en g y luego se convierte a m/s^2.
        metrics[axis.upper()] = {
            "mean_abs_ms2": (abs_integral / duration) * G0,
            "rms_ms2": math.sqrt(sq_integral / duration) * G0,
            "peak_ms2": peak * G0,
        }
    # RMS dinamico por eje: criterio principal de intensidad del movimiento.
    ranking = sorted(metrics, key=lambda a: metrics[a]["rms_ms2"], reverse=True)
    strongest = ranking[0]
    second = ranking[1]
    ratio = (metrics[strongest]["rms_ms2"] / metrics[second]["rms_ms2"]
             if metrics[second]["rms_ms2"] > 1e-12 else float("inf"))
    # Tiempo normalizado: 0 % en la primera muestra y 100 % en la ultima.
    # Se calcula con el tiempo real de cada muestra, no con el indice de fila.
    dynamic_ms2 = [(row[0], *(value * G0 for value in row[1:4])) for row in dynamic]
    normalized_time_pct = [((row[0] - start) / duration) * 100.0 for row in dynamic_ms2]
    return {
        "samples": len(rows), "duration": duration, "metrics": metrics,
        "ranking": ranking, "strongest": strongest, "ratio": ratio,
        "dynamic": dynamic_ms2,
        "normalized_time_pct": normalized_time_pct,
    }


def print_report(result, filename):
    print("\n========== REPORTE DE MOVIMIENTO SISCOM ==========")
    print(f"Archivo: {filename}")
    print(f"Muestras: {result['samples']}   Duración: {result['duration']:.3f} s")
    print("\nPromedio y potencia del movimiento por eje")
    print("Eje   Promedio |a dinamica|   RMS dinamico    Pico dinamico")
    print("      (m/s²)                  (m/s²)          (m/s²)")
    for axis in ("X", "Y", "Z"):
        m = result["metrics"][axis]
        print(f"{axis:>3}   {m['mean_abs_ms2']:>12.4f}       {m['rms_ms2']:>10.4f}      {m['peak_ms2']:>10.4f}")
    print("\nComparacion:")
    for position, axis in enumerate(result["ranking"], start=1):
        print(f"{position}. Eje {axis}: RMS = {result['metrics'][axis]['rms_ms2']:.4f} m/s²")
    strongest = result["strongest"]
    print(f"\nMOVIMIENTO MÁS INTENSO: EJE {strongest}")
    if math.isfinite(result["ratio"]):
        print(f"Su RMS fue {result['ratio']:.2f} veces el del segundo eje.")
    else:
        print("Los otros ejes no registraron movimiento dinámico significativo.")
    print("Criterio: mayor RMS de aceleración dinámica durante todo el registro.")
    print("==================================================\n")


def make_plot(result, output=None, show=True):
    """Grafica comparaciones globales y series temporales independientes X/Y/Z.

    Las tres graficas temporales usan el mismo eje X normalizado de 0 a 100 %
    de la duracion del archivo, y muestran aceleracion dinamica en m/s².
    """
    try:
        import matplotlib.pyplot as plt
        from matplotlib.ticker import FuncFormatter, MaxNLocator
    except ImportError as e:
        raise RuntimeError("Para generar la gráfica instala matplotlib: py -m pip install matplotlib") from e

    metrics = result["metrics"]
    axes = ["X", "Y", "Z"]
    mean_values = [metrics[a]["mean_abs_ms2"] for a in axes]
    rms_values = [metrics[a]["rms_ms2"] for a in axes]
    dynamic = result["dynamic"]
    time_pct = result["normalized_time_pct"]
    ms2_formatter = FuncFormatter(lambda value, _position: f"{value:.4f}")

    # Dos comparaciones globales y tres graficas temporales separadas.
    fig = plt.figure(figsize=(13, 13.5), constrained_layout=True)
    grid = fig.add_gridspec(4, 2, height_ratios=[1.0, 0.9, 0.9, 0.9])
    left = fig.add_subplot(grid[0, 0])
    right = fig.add_subplot(grid[0, 1])

    left_bars = left.bar(axes, mean_values)
    left.bar_label(left_bars, labels=[f"{value:.4f}" for value in mean_values],
                   padding=4, fontsize=9)
    left.set_title("Promedio de movimiento por eje")
    left.set_ylabel("Aceleración dinámica promedio (m/s²)")
    left.set_ylim(bottom=0, top=max(mean_values) * 1.20 if max(mean_values) > 0 else 1.0)
    left.yaxis.set_major_locator(MaxNLocator(nbins=5))
    left.yaxis.set_major_formatter(ms2_formatter)
    left.grid(axis="y", alpha=.25)

    right_bars = right.bar(axes, rms_values)
    right.bar_label(right_bars, labels=[f"{value:.4f}" for value in rms_values],
                    padding=4, fontsize=9)
    right.set_title("Intensidad RMS por eje")
    right.set_ylabel("Aceleración dinámica RMS (m/s²)")
    right.set_ylim(bottom=0, top=max(rms_values) * 1.20 if max(rms_values) > 0 else 1.0)
    right.yaxis.set_major_locator(MaxNLocator(nbins=5))
    right.yaxis.set_major_formatter(ms2_formatter)
    right.grid(axis="y", alpha=.25)

    colors = {"X": "tab:blue", "Y": "tab:orange", "Z": "tab:green"}
    for index, axis in enumerate(axes, start=1):
        ax = fig.add_subplot(grid[index, :])
        values = [row[index] for row in dynamic]  # dynamic columns: t, X, Y, Z
        m = metrics[axis]
        ax.plot(time_pct, values, color=colors[axis], linewidth=1.15,
                label=f"Aceleración dinámica {axis}")
        ax.axhline(0, color="black", linewidth=.7, alpha=.55)
        ax.set_title(
            f"Movimiento del eje {axis} — promedio |a|: {m['mean_abs_ms2']:.4f} m/s²  "
            f"| RMS: {m['rms_ms2']:.4f} m/s²  | Pico: {m['peak_ms2']:.4f} m/s²"
        )
        ax.set_ylabel(f"Eje {axis} (m/s²)")
        ax.set_xlabel("Tiempo normalizado (% del inicio al final del archivo)")
        ax.set_xlim(0, 100)
        ax.set_xticks([0, 20, 40, 60, 80, 100])
        ax.yaxis.set_major_locator(MaxNLocator(nbins=5))
        ax.yaxis.set_major_formatter(ms2_formatter)
        ax.grid(alpha=.25)
        ax.legend(loc="upper right", fontsize=8)

    fig.suptitle(
        f"Comparación de movimiento — eje predominante: {result['strongest']}\n"
        f"Duración del registro: {result['duration']:.4f} s; tiempo normalizado de 0 a 100 %",
        fontsize=14,
    )
    if output:
        fig.savefig(output, dpi=170, bbox_inches="tight")
        print(f"Gráfica guardada en: {output}")
    if show:
        plt.show()
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser(description="Compara el movimiento promedio en X, Y y Z en m/s² a partir de un CSV SISCOM")
    parser.add_argument("csv", type=Path, help="CSV generado por SISCOM")
    parser.add_argument("--guardar-grafica", type=Path, help="Ruta PNG para guardar la gráfica")
    parser.add_argument("--sin-grafica", action="store_true", help="Solo mostrar el reporte en terminal")
    parser.add_argument("--alpha-gravedad", type=float, default=0.03,
                        help="Respuesta del filtro de gravedad entre 0 y 1 (predeterminado: 0.03)")
    args = parser.parse_args()
    if not 0 < args.alpha_gravedad <= 1:
        parser.error("--alpha-gravedad debe estar en el intervalo (0, 1]")
    try:
        rows = load_samples(args.csv)
        result = analyze(rows, args.alpha_gravedad)
        print_report(result, args.csv)
        if not args.sin_grafica:
            make_plot(result, args.guardar_grafica, show=not bool(args.guardar_grafica))
    except (OSError, ValueError, RuntimeError) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
