# Dashboard de Sentimiento Ciudadano - Problemas Ambientales (Lima Metropolitana)

Dashboard en Streamlit que muestra un mapa de calor de sentimiento negativo por
distrito segun 4 categorias ambientales (ola de calor, escasez de agua,
contaminacion del aire, residuos solidos), con filtros, KPIs, tendencias
mensuales, feed de tweets sinteticos y un modulo de "Plan de Accion" para
generar posts/campanas municipales (con plantilla fija o, opcionalmente, con
IA via Gemini).

> Datos 100% sinteticos, generados con fines de demostracion academica
> (Universidad Nacional Mayor de San Marcos - UNMSM).

## Archivos necesarios

- `imagenes/`: carpeta con las imagenes del dashboard (hero, galerias por
  categoria, imagenes de campana). Los nombres de archivo esperados estan
  listados en `IMAGENES_TEMA`, `IMAGENES_CAMPANA` e `IMAGEN_HERO` dentro de
  `app.py`. Si clonas el repo, la app las busca ahi automaticamente (no hace
  falta configurar nada).
- `lima_callao_distritos_simple.geojson`: poligonos de distritos de Lima y
  Callao (no incluido en este repo; ver `GEOJSON_PATH` mas abajo).

## Configuracion

La app lee estas rutas desde variables de entorno. Si no las defines, usa
`imagenes/` (junto a `app.py`) para las imagenes, y la ruta de Drive del
notebook de Colab para el geojson:

| Variable         | Descripcion                                  |
|------------------|-----------------------------------------------|
| `GEOJSON_PATH`   | Ruta al archivo `.geojson` de distritos       |
| `IMAGENES_DIR`   | Carpeta donde estan las imagenes del dashboard (por defecto: `imagenes/` junto a `app.py`) |
| `GEMINI_API_KEY` | (Opcional) API key de Gemini para generar posts con IA. Sin esto, la app usa plantillas fijas automaticamente. |

**Nunca subas tu API key a este repo.** Configúrala como variable de entorno
en tu propia maquina/notebook, nunca dentro de `app.py`.

## Instalacion local

```bash
git clone https://github.com/MrUnsteadyMango/DASHBOARD-DE-ANALISIS-DE-SENTIMIENTO-CIUDADANO.git
cd DASHBOARD-DE-ANALISIS-DE-SENTIMIENTO-CIUDADANO
pip install -r requirements.txt
```

```bash
export GEOJSON_PATH="/ruta/a/lima_callao_distritos_simple.geojson"
export GEMINI_API_KEY="tu_clave_aqui"   # opcional

streamlit run app.py
```
(`IMAGENES_DIR` no hace falta definirla si clonaste el repo con la carpeta
`imagenes/` incluida — la app la encuentra sola.)

## Ejecucion en Google Colab

1. Monta Drive y coloca `app.py` y el `.geojson` en una carpeta (por ejemplo
   `MyDrive/Mapa LM/`). Las imagenes puedes dejarlas ahi tambien o usar las
   del repo clonado.
2. Antes de levantar Streamlit, fija las rutas de Drive por variable de
   entorno (reemplaza el checkbox de Gemini API key de tus notebooks
   anteriores por este bloque, que ahora incluye tambien las rutas):
   ```python
   import os
   os.environ["GEOJSON_PATH"] = "/content/drive/MyDrive/Mapa LM/lima_callao_distritos_simple.geojson"
   os.environ["IMAGENES_DIR"] = "/content/drive/MyDrive/Mapa LM/"
   os.environ["GEMINI_API_KEY"] = "tu_clave_aqui"   # opcional
   ```
3. Instala dependencias con version fija:
   ```python
   !pip install -q streamlit==1.38.0 streamlit-folium==0.21.0 folium==0.17.0 \
       plotly==5.24.0 geopandas pandas numpy google-genai pillow-avif-plugin
   ```
4. Levanta Streamlit y expon el puerto (recomendado: `cloudflared`, mas
   estable que `localtunnel` para este caso de uso).
5. Abre la URL en una pestana nueva de incognito (evita reutilizar pestanas
   de corridas anteriores).

## Estructura del proyecto

```
app.py              # Dashboard completo (Streamlit)
requirements.txt     # Dependencias con version fija
imagenes/            # Imagenes usadas en el dashboard
```
