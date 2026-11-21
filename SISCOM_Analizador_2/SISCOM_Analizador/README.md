# Analizador de movimiento SISCOM

Programa independiente que lee el CSV exportado por la aplicación SISCOM y genera un reporte del movimiento promedio por eje X, Y y Z, además de una comparación del eje con mayor movimiento.

## Ejecución

Coloca `analizar_movimiento.py` junto al CSV que generaste, o ejecuta desde la carpeta donde guardaste el archivo:

```powershell
py analizar_movimiento.py datos.csv
```

Para guardar la gráfica como PNG:

```powershell
py analizar_movimiento.py datos.csv --guardar-grafica comparacion.png
```

Solo reporte de texto:

```powershell
py analizar_movimiento.py datos.csv --sin-grafica
```

Necesita Python 3.10 o superior. Para la gráfica requiere Matplotlib:

```powershell
py -m pip install matplotlib
```

## Qué calcula

El acelerómetro mide gravedad además del movimiento. Por eso no se comparan directamente los valores ax, ay y az: en reposo un eje puede marcar aproximadamente 1 g por la gravedad y parecer falsamente el eje con más movimiento.

El programa estima la componente lenta de gravedad de cada eje con un filtro exponencial y la resta de la aceleración medida. Sobre esa aceleración dinámica calcula:

- **Promedio |a dinámica| (g):** promedio temporal de la magnitud absoluta del movimiento en cada eje. Indica cuánto se movió, en promedio, cada eje.
- **RMS dinámico (g):** raíz del promedio temporal del cuadrado de la aceleración dinámica. Se usa como criterio principal para comparar intensidad y da mayor peso a picos.
- **Pico dinámico (g):** mayor valor absoluto observado en el eje.

La comparación de “movimiento más intenso” se decide por el mayor RMS dinámico durante todo el registro. También se informa cuánto supera al segundo eje. La integración es trapezoidal y ponderada por tiempo.

El filtro de gravedad es una estimación; durante movimientos lentos o prolongados puede confundir parte del movimiento con gravedad. Los resultados son indicadores experimentales, no una medición certificada de vibración o daño.

## CSV compatible

El CSV normal de SISCOM debe incluir `t_rel_s` (o `timestamp_s`) y `ax_g`, `ay_g`, `az_g`. También acepta `raw_x`, `raw_y`, `raw_z` (se convierten con sensibilidad nominal 0.0039 g/LSB). Se necesitan al menos dos muestras y tiempos crecientes.
