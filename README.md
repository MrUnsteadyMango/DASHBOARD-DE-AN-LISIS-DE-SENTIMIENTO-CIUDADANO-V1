# Dashboard de Sentimiento Ciudadano - Problemas Ambientales (Lima Metropolitana)

Dashboard en Streamlit que muestra un mapa de calor de sentimiento negativo por
distrito segun 4 categorias ambientales (ola de calor, escasez de agua,
contaminacion del aire, residuos solidos), con filtros, KPIs, tendencias
mensuales, feed de tweets sinteticos y un modulo de "Plan de Accion" para
generar posts/campanas municipales (con plantilla fija o, opcionalmente, con
IA via Gemini).

> Datos 100% sinteticos, generados con fines de demostracion academica
> (Universidad Nacional Mayor de San Marcos - UNMSM).

## Archivos necesarios (no incluidos en este repo)

- `lima_callao_distritos_simple.geojson`: poligonos de distritos de Lima y Callao.
- Carpeta de imagenes usadas en el dashboard (hero, galerias por categoria,
  imagenes de campana). Los nombres de archivo esperados estan listados en
  `IMAGENES_TEMA`, `IMAGENES_CAMPANA` e `IMAGEN_HERO` dentro de `app.py`.

## Configuracion

La app lee estas rutas desde variables de entorno (si no las defines, usa por
defecto las rutas de Google Drive que se usan en el notebook de Colab del
proyecto):

| Variable         | Descripcion                                  |
|------------------|-----------------------------------------------|
| `GEOJSON_PATH`   | Ruta al archivo `.geojson` de distritos       |
| `IMAGENES_DIR`   | Carpeta donde estan las imagenes del dashboard|
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
export IMAGENES_DIR="/ruta/a/tu/carpeta/de/imagenes/"
export GEMINI_API_KEY="tu_clave_aqui"   # opcional

streamlit run app.py
```

## Ejecucion en Google Colab

1. Monta Drive y coloca `app.py`, el `.geojson` y las imagenes en una misma
   carpeta (por ejemplo `MyDrive/Mapa LM/`).
2. Instala dependencias con version fija:
   ```python
   !pip install -q streamlit==1.38.0 streamlit-folium==0.21.0 folium==0.17.0 \
       plotly==5.24.0 geopandas pandas numpy google-genai pillow-avif-plugin
   ```
3. Levanta Streamlit y expon el puerto (recomendado: `cloudflared`, mas
   estable que `localtunnel` para este caso de uso).
4. Abre la URL en una pestana nueva de incognito (evita reutilizar pestanas
   de corridas anteriores).

## Estructura del proyecto

```
app.py              # Dashboard completo (Streamlit)
requirements.txt     # Dependencias con version fija
```
