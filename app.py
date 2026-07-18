"""
================================================================================
DASHBOARD DE ANALISIS DE SENTIMIENTO CIUDADANO - PROBLEMAS AMBIENTALES
Lima Metropolitana
================================================================================
App en Streamlit que muestra un mapa de calor de sentimiento negativo por
distrito segun 4 categorias ambientales (residuos solidos, escasez de agua,
contaminacion del aire, ola de calor), con filtros, KPIs, feed de tweets
simulados con paginacion, y una pagina de Plan de Accion para generar
posts/campanas municipales a partir de los registros filtrados.

Como ejecutar en Colab (evita el error "Failed to fetch dynamically imported
module" / "trouble loading the streamlit_folium component"):

    1) Reinicia el entorno de ejecucion (Entorno de ejecucion > Reiniciar
       entorno de ejecucion). Esto es clave: si vienes de una sesion donde
       ya corriste streamlit antes, versiones viejas de los paquetes JS
       quedan cacheadas y el navegador pide un archivo que ya no existe.

    2) Instala TODO con version fija, una sola vez por sesion (las versiones
       sueltas -q sin pin son la causa mas comun de este error, porque cada
       vez que reinstalas puede cambiar el build del frontend):
           !pip install -q streamlit==1.38.0 streamlit-folium==0.21.0 \
               folium==0.17.0 plotly==5.24.0 geopandas pandas numpy \
               google-genai

    3) Antes de levantar la app, mata cualquier proceso viejo:
           !pkill -f streamlit; !pkill -f localtunnel

    4) Escribe el archivo con %%writefile (no con files.upload) y levanta:
           !streamlit run app.py --server.headless true &>/content/logs.txt &

    5) Genera un tunel NUEVO (no reuses una URL de localtunnel vieja):
           !npx localtunnel --port 8501

    6) Abre la URL nueva en una pestana de incognito / recien abierta, no en
       una pestana que ya tenias abierta de una corrida anterior -- esa
       pestana puede tener el index.html viejo apuntando a un archivo JS que
       ya no existe en el nuevo build, que es exactamente el error que viste.

IMPORTANTE: ajusta la variable GEOJSON_PATH mas abajo a la ruta de tu archivo
lima_callao_distritos_simple.geojson en tu entorno (local, Drive montado, etc).
================================================================================
"""

import base64
import json
import math
import os
from datetime import datetime, timedelta

import folium
import geopandas as gpd
import numpy as np
import pandas as pd
import plotly.express as px
import streamlit as st
from folium import Figure, MacroElement
from jinja2 import Template
from streamlit_folium import st_folium

# SDK de Gemini (opcional, google-genai). Si no esta instalado o no hay
# API key configurada, la generacion de posts cae de vuelta a las plantillas
# fijas sin romper la app. Para habilitarlo: !pip install -q google-genai
# y luego, en tu propia sesion (NUNCA pegado dentro de este archivo):
#     import os
#     os.environ["GEMINI_API_KEY"] = "tu_clave_aqui"
# Consigue/gestiona tu clave en https://aistudio.google.com/apikey
try:
    from google import genai as genai_sdk
    GEMINI_DISPONIBLE = True
except ImportError:
    GEMINI_DISPONIBLE = False



# ==============================================================================
# 0. CONFIGURACION GENERAL DE LA PAGINA
# ==============================================================================

st.set_page_config(
    page_title="Sentimiento Ambiental - Lima Metropolitana",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Ruta al geojson. AJUSTAR segun tu entorno (Drive, local, etc.)
GEOJSON_PATH = os.environ.get(
    "GEOJSON_PATH", "/content/drive/MyDrive/Mapa LM/lima_callao_distritos_simple.geojson"
)

# Las 4 categorias del dashboard (criterio solicitado por la profesora)
TEMAS = [
    "Ola de Calor",
    "Escasez de Agua",
    "Contaminacion del Aire",
    "Residuos Solidos",
]

# Nombres de distrito que llegan con problemas de codificacion/tilde desde el
# geojson y que se reemplazan por su version correcta en mayusculas. Se usa
# como respaldo ademas de reparar_mojibake() / distrito_norm mas abajo.
FIX_DISPLAY_DISTRITO = {
    "MI PERU": "MI PERU",
}

# Distritos con mayor poblacion/relevancia: reciben un volumen mas alto de
# tweets sinteticos. El resto recibe un volumen mas bajo para no saturar el
# feed con distritos poco relevantes. Lista aproximada, solo para la demo.
DISTRITOS_RELEVANTES = [
    "SAN JUAN DE LURIGANCHO", "SAN MARTIN DE PORRES", "ATE", "COMAS",
    "VILLA MARIA DEL TRIUNFO", "SAN JUAN DE MIRAFLORES", "VILLA EL SALVADOR",
    "PUENTE PIEDRA", "CHORRILLOS", "SANTIAGO DE SURCO", "SURCO", "LOS OLIVOS",
    "CALLAO", "CARABAYLLO", "INDEPENDENCIA", "EL AGUSTINO",
]

# Correos institucionales que se muestran en el pie de pagina del Dashboard.
# Agrega/quita los que necesites.
EMAILS_CONTACTO = [
    "jean.cardenas5@unmsm.edu.pe",
    "martin.bellido@unmsm.edu.pe",
    "stefano.gutierrez@unmsm.edu.pe",
    "luis.ruiz21@unmsm.edu.pe",
]

# ==============================================================================
# 1B. IMAGENES (subelas a tu Drive y ajusta IMAGENES_DIR a esa carpeta)
# ==============================================================================
# AJUSTAR: carpeta en Drive donde subiras las imagenes. Mismo criterio que
# GEOJSON_PATH: usa la ruta real de tu Drive montado.
IMAGENES_DIR = os.environ.get("IMAGENES_DIR", "/content/drive/MyDrive/Mapa LM/")

# Banner/hero general (cabecera de la app, estilo institucional).
IMAGEN_HERO = "concientizacionareaverde.avif"

# Imagenes de apoyo por categoria, mostradas como cabecera/galeria del tema
# seleccionado en el Dashboard. Puedes dejar una lista vacia si no tienes
# imagen para esa categoria todavia.
IMAGENES_TEMA = {
    TEMAS[0]: ["olacalor.avif", "calorpersonassombrilla.avif", "sombrillapersonas.avif"],  # Ola de Calor
    TEMAS[1]: [],  # Escasez de Agua (agrega aqui cuando tengas una propia)
    TEMAS[2]: ["humolima.jpg", "incendiofabrica.avif"],  # Contaminacion del Aire
    TEMAS[3]: ["basuracentro.webp"],  # Residuos Solidos
}

# Imagenes de campana, mostradas al pie de la pestana "Plan de Accion".
IMAGENES_CAMPANA = [
    ("peruanossinaccesoagua.png", "Acceso al agua en Lima Metropolitana"),
    ("menosplastico.jpg", "Campana municipal: menos plastico"),
    ("areasverdessjl.jpg", "Areas verdes en San Juan de Lurigancho"),
]

def _ruta_imagen(nombre_archivo: str) -> str:
    return os.path.join(IMAGENES_DIR, nombre_archivo)

def mostrar_imagen(nombre_archivo: str, alto_px: int = 220, leyenda: str = None, contenedor=st) -> bool:
    """Muestra una imagen con una altura razonable y recorte uniforme (estilo
    tarjeta institucional). Si el archivo no existe todavia (por ejemplo,
    porque aun no la subiste al Drive) o el formato no se puede decodificar
    (AVIF requiere el plugin pillow-avif-plugin), no rompe la app: solo
    muestra un aviso discreto y sigue de largo. Devuelve True si se pudo
    mostrar la imagen."""
    ruta = _ruta_imagen(nombre_archivo)
    if not os.path.exists(ruta):
        contenedor.caption(f"(Imagen pendiente de subir: {nombre_archivo})")
        return False
    try:
        contenedor.markdown(
            f'<div style="height:{alto_px}px; border-radius:12px; overflow:hidden; '
            f'border:1px solid #1E3A4C;">'
            f'<img src="data:image/{nombre_archivo.split(".")[-1]};base64,'
            f'{_imagen_base64(ruta)}" style="width:100%; height:100%; object-fit:cover;" />'
            f'</div>',
            unsafe_allow_html=True,
        )
        if leyenda:
            contenedor.caption(leyenda)
        return True
    except Exception:
        contenedor.caption(
            f"(No se pudo cargar {nombre_archivo} -- si es .avif instala "
            f"`!pip install -q pillow-avif-plugin` y agrega `import pillow_avif` "
            f"al inicio del script)"
        )
        return False

@st.cache_data(show_spinner=False)
def _imagen_base64_cache(ruta: str, mtime: float) -> str:
    # mtime forma parte de la key de cache: si reemplazas el archivo en Drive
    # (mtime nuevo), Streamlit lo vuelve a codificar; si no cambio, usa cache
    # en vez de releer el archivo de disco en cada rerun.
    with open(ruta, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")

def _imagen_base64(ruta: str) -> str:
    return _imagen_base64_cache(ruta, os.path.getmtime(ruta))

# ==============================================================================
# 1. ESTILOS (tema oscuro fijo, sin alternancia claro/oscuro)
# ==============================================================================

def inyectar_css():
    """Inyecta CSS institucional en tema oscuro fijo."""
    bg = "#0E1A24"
    bg_card = "#132836"
    texto = "#EAF2F5"
    texto_sec = "#A9C0CB"
    borde = "#1E3A4C"

    azul = "#1C8EB0"
    azul_claro = "#2FA8CC"
    verde_claro = "#4CAF7D"

    st.markdown(
        f"""
        <style>
        .stApp {{
            background-color: {bg};
            color: {texto};
        }}
        section[data-testid="stSidebar"] {{
            background-color: {bg_card};
            border-right: 1px solid {borde};
        }}
        h1, h2, h3, h4 {{
            color: {azul} !important;
            font-weight: 700 !important;
        }}
        .kpi-card {{
            background-color: {bg_card};
            border: 1px solid {borde};
            border-radius: 14px;
            padding: 18px 16px;
            text-align: center;
            box-shadow: 0 2px 6px rgba(0,0,0,0.25);
        }}
        .kpi-valor {{
            font-size: 28px;
            font-weight: 800;
            color: {azul};
        }}
        .kpi-etiqueta {{
            font-size: 13px;
            color: {texto_sec};
            text-transform: uppercase;
            letter-spacing: .04em;
        }}
        .tweet-card {{
            background-color: {bg_card};
            border: 1px solid {borde};
            border-left: 5px solid {azul_claro};
            border-radius: 10px;
            padding: 12px 16px;
            margin-bottom: 10px;
        }}
        .tweet-meta {{
            font-size: 12px;
            color: {texto_sec};
            margin-top: 6px;
        }}
        .badge {{
            display: inline-block;
            padding: 2px 10px;
            border-radius: 20px;
            font-size: 11px;
            font-weight: 700;
            color: white;
        }}
        .badge-negativo {{ background-color: #D64550; }}
        .badge-neutral  {{ background-color: #E1A63A; }}
        .badge-positivo {{ background-color: {verde_claro}; }}
        .badge-prioridad {{
            display: inline-block;
            padding: 4px 14px;
            border-radius: 20px;
            font-size: 13px;
            font-weight: 800;
            color: white;
        }}
        .accion-card {{
            background-color: {bg_card};
            border: 1px solid {borde};
            border-radius: 12px;
            padding: 16px 18px;
            margin-bottom: 14px;
        }}
        .post-preview {{
            background-color: {bg};
            border: 1px dashed {borde};
            border-radius: 10px;
            padding: 14px 16px;
            white-space: pre-wrap;
            font-family: monospace;
            font-size: 13px;
            margin-bottom: 10px;
        }}

        div.stButton > button {{
            border-radius: 10px;
            border: 1px solid {borde};
            background-color: {bg_card};
            color: {texto};
        }}
        div.stButton > button:hover {{
            border-color: {azul_claro};
            color: {azul_claro};
        }}
        .chip-accion {{
            display: inline-block;
            padding: 5px 12px;
            border-radius: 20px;
            font-size: 12.5px;
            font-weight: 700;
            color: white;
            background-color: {verde_claro};
            margin: 3px 6px 3px 0;
        }}
        .ia-badge {{
            display: inline-block;
            padding: 2px 9px;
            border-radius: 20px;
            font-size: 10.5px;
            font-weight: 800;
            letter-spacing: .03em;
            color: {bg};
            background-color: {azul_claro};
            margin-left: 8px;
            vertical-align: middle;
        }}
        .hero-banner {{
            position: relative;
            border-radius: 16px;
            overflow: hidden;
            height: 200px;
            margin-bottom: 18px;
            border: 1px solid {borde};
        }}
        .hero-banner img {{
            width: 100%;
            height: 100%;
            object-fit: cover;
            filter: brightness(0.55) saturate(1.05);
        }}
        .hero-banner .hero-texto {{
            position: absolute;
            left: 0; right: 0; bottom: 0;
            padding: 18px 24px;
            background: linear-gradient(180deg, rgba(14,26,36,0) 0%, rgba(14,26,36,0.92) 85%);
        }}
        .hero-banner .hero-texto h1 {{
            margin: 0 0 4px 0 !important;
            color: #FFFFFF !important;
            font-size: 26px !important;
        }}
        .hero-banner .hero-texto p {{
            margin: 0;
            color: {texto_sec};
            font-size: 14px;
        }}
        .footer-institucional {{
            border-top: 1px solid {borde};
            padding-top: 14px;
            margin-top: 6px;
            font-size: 12.5px;
            color: {texto_sec};
            text-align: center;
            line-height: 1.9;
        }}
        .footer-institucional b {{
            color: {texto};
        }}
        .campana-img-caption {{
            font-size: 11.5px;
            color: {texto_sec};
            text-align: center;
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )

inyectar_css()

# ==============================================================================
# 2. UTILIDADES DE TEXTO
# ==============================================================================

def normalizar_texto(serie: pd.Series) -> pd.Series:
    """Pasa una columna de texto a mayusculas sin tildes, para hacer merges
    y comparaciones sin problemas de acentos/espacios."""
    return (
        serie.astype(str)
        .str.upper()
        .str.strip()
        .str.normalize("NFKD")
        .str.encode("ascii", errors="ignore")
        .str.decode("utf-8")
    )

def reparar_mojibake(texto: str) -> str:
    """Repara texto que se leyo con la codificacion equivocada (tipico caso:
    un archivo guardado en UTF-8 pero leido/reescrito como Latin-1 o
    Windows-1252 en algun punto de la cadena Colab/Drive/geojson), que
    produce cosas como 'PERÃº' o 'PERÃz' en vez de 'PERU'. Si el texto ya
    esta bien, lo devuelve sin cambios."""
    if not isinstance(texto, str):
        return texto
    for codificacion in ("latin-1", "cp1252"):
        try:
            candidato = texto.encode(codificacion).decode("utf-8")
            # Si el candidato ya no tiene los caracteres tipicos de mojibake
            # (Ã, Â, etc.) asumimos que la reparacion funciono.
            if "Ã" not in candidato and "Â" not in candidato:
                return candidato
        except (UnicodeDecodeError, UnicodeEncodeError):
            continue
    return texto

# ==============================================================================
# 3. CARGA DE DATOS GEOGRAFICOS
# ==============================================================================

@st.cache_data(show_spinner="Cargando distritos...")
def cargar_geojson(path: str):
    try:
        gdf = gpd.read_file(path, driver="GeoJSON")
    except Exception as e:
        st.error(
            f"No se pudo cargar el geojson en la ruta configurada:\n\n`{path}`\n\n"
            f"Ajusta la variable GEOJSON_PATH al inicio de app.py. Error original: {e}"
        )
        st.stop()
    # 1) Repara mojibake (tildes rotas tipo "PERÃz") antes de normalizar.
    gdf["distrito"] = gdf["distrito"].astype(str).apply(reparar_mojibake)
    gdf["distrito_norm"] = normalizar_texto(gdf["distrito"])

    # 2) Corrige el nombre a mostrar. startswith("MI PER") es una regla
    #    robusta: funciona incluso si quedara algun byte raro pegado al
    #    final del nombre, que es justo lo que fallaba antes.
    def _display_distrito(row):
        if row["distrito_norm"].startswith("MI PER"):
            return "MI PERU"
        return FIX_DISPLAY_DISTRITO.get(row["distrito_norm"], row["distrito"])

    gdf["distrito"] = gdf.apply(_display_distrito, axis=1)
    gdf["distrito_norm"] = normalizar_texto(gdf["distrito"])
    return gdf

gdf = cargar_geojson(GEOJSON_PATH)
LISTA_DISTRITOS = sorted(gdf["distrito"].dropna().unique().tolist())

# ==============================================================================
# 4. ZONAS DE LIMA (para dar un sesgo mas realista a los datos sinteticos
#    por categoria; es una agrupacion aproximada solo para fines de demo)
# ==============================================================================

ZONAS_DISTRITOS = {
    "lima_norte": ["LOS OLIVOS", "SAN MARTIN DE PORRES", "COMAS", "INDEPENDENCIA",
                   "PUENTE PIEDRA", "CARABAYLLO", "ANCON", "SANTA ROSA"],
    "lima_este": ["SAN JUAN DE LURIGANCHO", "EL AGUSTINO", "SANTA ANITA", "ATE",
                  "LA MOLINA", "CIENEGUILLA", "CHACLACAYO", "LURIGANCHO"],
    "lima_centro": ["LIMA", "BRENA", "LA VICTORIA", "RIMAC", "SAN LUIS",
                     "JESUS MARIA", "LINCE", "PUEBLO LIBRE", "MAGDALENA DEL MAR",
                     "SAN MIGUEL", "SURQUILLO"],
    "lima_moderna": ["MIRAFLORES", "SAN ISIDRO", "BARRANCO", "SANTIAGO DE SURCO",
                      "SURCO", "SAN BORJA"],
    "lima_sur": ["CHORRILLOS", "SAN JUAN DE MIRAFLORES", "VILLA MARIA DEL TRIUNFO",
                 "VILLA EL SALVADOR", "LURIN", "PACHACAMAC", "PUNTA HERMOSA",
                 "PUNTA NEGRA", "SAN BARTOLO", "SANTA MARIA DEL MAR", "PUCUSANA"],
    "callao": ["CALLAO", "BELLAVISTA", "LA PERLA", "LA PUNTA",
               "CARMEN DE LA LEGUA REYNOSO", "VENTANILLA", "MI PERU"],
}

def obtener_zona(distrito_norm: str) -> str:
    for zona, lista in ZONAS_DISTRITOS.items():
        if distrito_norm in lista:
            return zona
    return "otro"

# Sesgo (suma sobre el % negativo base) por zona y categoria. Aproximado,
# solo para que el dataset sintetico tenga patrones plausibles por distrito.
BIAS_ZONA_CATEGORIA = {
    "calor":     {"lima_este": 15, "lima_norte": 10, "lima_centro": 0,
                  "lima_sur": -5, "lima_moderna": -15, "callao": -10, "otro": 0},
    "agua":      {"lima_norte": 15, "lima_sur": 15, "lima_este": 10,
                  "lima_centro": -5, "lima_moderna": -15, "callao": 5, "otro": 0},
    "aire":      {"callao": 15, "lima_centro": 15, "lima_este": 10,
                  "lima_norte": 5, "lima_sur": 0, "lima_moderna": -15, "otro": 0},
    "residuos":  {"lima_norte": 10, "lima_este": 10, "lima_sur": 10,
                  "lima_centro": 5, "callao": 5, "lima_moderna": -15, "otro": 0},
}

# ==============================================================================
# 5. GENERACION DE DATOS SINTETICOS (cacheado para que sea estable en la sesion)
# ==============================================================================

@st.cache_data(show_spinner="Generando datos sinteticos...")
def generar_datos_sinteticos(distritos: list, temas: list, semilla: int = 42):
    """
    Genera un DataFrame distrito x tema con metricas sinteticas de sentimiento,
    y un DataFrame de tweets sinteticos asociado a cada combinacion.
    Los distritos considerados mas relevantes (mayor poblacion) reciben entre
    150 y 300 tweets por categoria; el resto recibe entre 50 y 70 para no
    saturar el feed con distritos menos relevantes.

    Vectorizado con numpy/pandas (arrays completos por categoria, en vez de
    un loop de Python que arma un dict por cada tweet individual) para que
    la primera carga sea rapida incluso con miles de tweets sinteticos.
    """
    rng = np.random.default_rng(semilla)
    distritos_arr = np.array(distritos)
    n_distritos = len(distritos_arr)

    mapa_tema_perfil = {
        temas[0]: "calor",
        temas[1]: "agua",
        temas[2]: "aire",
        temas[3]: "residuos",
    }

    distritos_norm = normalizar_texto(pd.Series(distritos)).to_numpy()
    zonas_arr = np.array([obtener_zona(dn) for dn in distritos_norm])
    relevante_arr = np.isin(distritos_norm, DISTRITOS_RELEVANTES)

    perfiles = {
        "calor": rng.uniform(0.3, 1.0, size=n_distritos),
        "residuos": rng.uniform(0.2, 1.0, size=n_distritos),
        "aire": rng.uniform(0.3, 1.0, size=n_distritos),
        "agua": rng.uniform(0.2, 1.0, size=n_distritos),
    }

    filas_resumen = []
    partes_tweets = []

    plantillas = {
        temas[0]: [  # Ola de Calor
            "El calor en {distrito} esta insoportable, no se puede dormir de noche.",
            "Otra vez record de temperatura en {distrito}, esto ya no es normal.",
            "Las calles de {distrito} son un horno, falta mas sombra y areas verdes.",
            "Cortes de luz mas ola de calor en {distrito}, situacion critica.",
            "En {distrito} el asfalto literalmente quema, isla de calor urbana real.",
        ],
        temas[1]: [  # Escasez de Agua
            "Llevamos dias sin agua en {distrito}, esto ya es insostenible.",
            "El camion cisterna llego tarde otra vez a {distrito}, la gente reclama.",
            "En {distrito} el racionamiento de agua afecta a miles de familias.",
            "Preocupa la escasez hidrica en {distrito} de cara al verano.",
            "Vecinos de {distrito} exigen soluciones urgentes por falta de agua potable.",
        ],
        temas[2]: [  # Contaminacion del Aire
            "El aire en {distrito} huele a smog todas las mananas, es preocupante.",
            "Indice de calidad del aire en {distrito} en niveles daninos hoy.",
            "Demasiado trafico y polucion en {distrito}, mis hijos ya tosen seguido.",
            "En {distrito} el humo de los combis es insoportable en hora punta.",
            "Necesitamos mas monitoreo de aire en {distrito}, la contaminacion sube.",
        ],
        temas[3]: [  # Residuos Solidos
            "La basura se acumula en las calles de {distrito}, el camion recolector no pasa hace dias.",
            "En {distrito} el relleno sanitario esta colapsado, urge un plan de segregacion.",
            "Vecinos de {distrito} piden mas contenedores de reciclaje, todo se mezcla igual.",
            "Otra vez puntos criticos de basura en {distrito}, esto atrae plagas.",
            "La recoleccion de residuos en {distrito} es irregular, necesitamos mejor gestion municipal.",
        ],
    }
    plantillas_positivas = [
        "Buena iniciativa municipal en {distrito} para enfrentar el problema, vamos bien.",
        "Se nota mejora en {distrito} gracias a las nuevas medidas implementadas.",
        "Felicito a la gestion de {distrito} por atender rapido el reclamo vecinal.",
    ]
    plantillas_neutrales = [
        "Reporte del dia en {distrito}: situacion estable, sin mayores incidentes.",
        "Autoridades de {distrito} monitorean la situacion, se espera actualizacion.",
        "Comparto info oficial sobre el tema en {distrito}, revisen el comunicado.",
    ]

    hoy = pd.Timestamp(datetime.now())

    for tema in temas:
        perfil_key = mapa_tema_perfil[tema]
        base = perfiles[perfil_key]
        sesgo_zona = np.array([BIAS_ZONA_CATEGORIA[perfil_key][z] for z in zonas_arr])
        ruido = rng.normal(0, 8, size=n_distritos)
        extra = rng.uniform(-5, 10, size=n_distritos)
        sentimiento_negativo = np.round(np.clip(base * 70 + sesgo_zona + ruido + extra, 2, 98), 1)

        num_tweets_rel = rng.integers(150, 301, size=n_distritos)
        num_tweets_norel = rng.integers(50, 71, size=n_distritos)
        num_tweets = np.where(relevante_arr, num_tweets_rel, num_tweets_norel)

        for d, zona, sn, nt in zip(distritos_arr, zonas_arr, sentimiento_negativo, num_tweets):
            filas_resumen.append(
                {
                    "distrito": d,
                    "tema": tema,
                    "zona": zona,
                    "sentimiento_negativo": float(sn),
                    "num_tweets": int(nt),
                }
            )

        # --- Arma todos los tweets de esta categoria de una sola vez ---
        total_tema = int(num_tweets.sum())
        distrito_rep = np.repeat(distritos_arr, num_tweets)
        sent_neg_rep = np.repeat(sentimiento_negativo, num_tweets)

        r = rng.random(total_tema)
        umbral1 = sent_neg_rep / 100 * 0.85
        umbral2 = umbral1 + 0.10
        sentimiento_arr = np.where(
            r < umbral1, "negativo", np.where(r < umbral2, "neutral", "positivo")
        )

        textos_neg = plantillas[tema]
        idx_neg = rng.integers(0, len(textos_neg), size=total_tema)
        idx_pos = rng.integers(0, len(plantillas_positivas), size=total_tema)
        idx_neu = rng.integers(0, len(plantillas_neutrales), size=total_tema)

        mask_neg = sentimiento_arr == "negativo"
        mask_neu = sentimiento_arr == "neutral"
        mask_pos = sentimiento_arr == "positivo"

        textos_base = np.empty(total_tema, dtype=object)
        textos_base[mask_neg] = [textos_neg[i] for i in idx_neg[mask_neg]]
        textos_base[mask_neu] = [plantillas_neutrales[i] for i in idx_neu[mask_neu]]
        textos_base[mask_pos] = [plantillas_positivas[i] for i in idx_pos[mask_pos]]
        textos = [t.format(distrito=d) for t, d in zip(textos_base, distrito_rep)]

        # Hasta 6 meses hacia atras, para poder armar graficas de evolucion
        # mensual ademas del feed reciente.
        dias_atras = rng.integers(0, 182, size=total_tema)
        horas = rng.integers(0, 24, size=total_tema)
        minutos = rng.integers(0, 60, size=total_tema)
        fechas = (
            hoy
            - pd.to_timedelta(dias_atras, unit="D")
            - pd.to_timedelta(horas, unit="h")
            - pd.to_timedelta(minutos, unit="m")
        )
        likes = rng.integers(0, 500, size=total_tema)
        usuarios = "@vecino_" + rng.integers(1000, 9999, size=total_tema).astype(str)

        partes_tweets.append(
            pd.DataFrame(
                {
                    "distrito": distrito_rep,
                    "tema": tema,
                    "texto": textos,
                    "sentimiento": sentimiento_arr,
                    "fecha": fechas,
                    "likes": likes,
                    "usuario": usuarios,
                }
            )
        )

    df_resumen = pd.DataFrame(filas_resumen)
    df_tweets = pd.concat(partes_tweets, ignore_index=True).sort_values(
        "fecha", ascending=False
    ).reset_index(drop=True)
    df_tweets["mes"] = df_tweets["fecha"].dt.to_period("M").dt.to_timestamp()
    return df_resumen, df_tweets

df_resumen, df_tweets = generar_datos_sinteticos(LISTA_DISTRITOS, TEMAS)

# ==============================================================================
# 6. ACCIONES SUGERIDAS Y PLANTILLAS DE POST POR CATEGORIA
# ==============================================================================

# Acciones alineadas a medidas que efectivamente toman (o pueden tomar) las
# municipalidades en Lima/Callao, evitando propuestas poco realistas para el
# contexto peruano (ej. "refugios climatizados").
ACCIONES_SUGERIDAS = {
    TEMAS[0]: [  # Ola de Calor
        "Ampliar arborizacion y areas verdes en calles y parques",
        "Instalar y dar mantenimiento a paraderos con techado y sombra",
        "Distribuir agua a adultos mayores y zonas vulnerables",
        "Coordinar con el SENAMHI la difusion de alertas de calor",
    ],
    TEMAS[1]: [  # Escasez de Agua
        "Coordinar con Sedapal el envio de cisternas",
        "Habilitar puntos de acopio de agua potable",
        "Publicar y difundir el plan de racionamiento vigente",
        "Fiscalizar conexiones clandestinas que agravan el desabastecimiento",
    ],
    TEMAS[2]: [  # Contaminacion del Aire
        "Coordinar operativos de revision tecnica vehicular con la PNP",
        "Reforzar el barrido y riego de vias para reducir el polvo",
        "Restringir transito de vehiculos pesados en horas punta",
        "Ampliar arborizacion urbana como barrera de contaminacion",
    ],
    TEMAS[3]: [  # Residuos Solidos
        "Reforzar frecuencia de recojo con la empresa concesionaria",
        "Habilitar puntos de acopio y segregacion en origen (reciclaje)",
        "Fiscalizar con serenazgo los puntos criticos de arrojo informal",
        "Difundir campana vecinal sobre horarios de saca de basura",
    ],
}

def color_por_sentimiento(valor: float) -> str:
    if valor >= 67:
        return "#D64550"
    elif valor >= 34:
        return "#E1A63A"
    else:
        return "#1C8EB0"

@st.cache_data(show_spinner=False)
def geojson_por_tema(tema: str, _gdf, df_resumen_tema: pd.DataFrame):
    """Fusiona el geojson con los datos de la categoria seleccionada y lo
    serializa a dict listo para folium. Cacheado por tema: el mapa entero se
    volvia a mergear y a serializar (gdf_tema.to_json()) en cada rerun --
    incluso al pasar de pagina en el feed de tweets, que no cambia el mapa."""
    df_t = df_resumen_tema.copy()
    df_t["distrito_norm"] = normalizar_texto(df_t["distrito"])
    gdf_t = _gdf.merge(df_t, on="distrito_norm", suffixes=("", "_datos"), how="left")
    gdf_t["sentimiento_negativo"] = gdf_t["sentimiento_negativo"].fillna(0)
    gdf_t["num_tweets"] = gdf_t["num_tweets"].fillna(0).astype(int)
    gdf_t["color_calor"] = gdf_t["sentimiento_negativo"].apply(color_por_sentimiento)
    return json.loads(gdf_t.to_json())

def clasificar_prioridad(valor: float):
    """Devuelve (etiqueta, color) segun el % de sentimiento negativo."""
    if valor >= 67:
        return "Alta", "#D64550"
    elif valor >= 34:
        return "Media", "#E1A63A"
    else:
        return "Baja", "#1C8EB0"

def armar_lista_acciones(acciones: list) -> str:
    if not acciones:
        return "- (sin acciones seleccionadas todavia)"
    return "\n".join(f"- {a}" for a in acciones)

def generar_post(distrito: str, categoria: str, prioridad: str, porcentaje: float,
                  acciones: list, tipo: str) -> str:
    """Genera el texto de un post segun el tipo (alerta, en_curso, seguimiento,
    informe)."""
    cat_lower = categoria.lower()
    lista_acciones = armar_lista_acciones(acciones)

    if tipo == "alerta":
        return (
            f"ALERTA - {categoria.upper()} EN {distrito.upper()}\n\n"
            f"Vecinos de {distrito} vienen reportando un incremento de casos "
            f"relacionados a {cat_lower}. El {porcentaje:.0f}% de los comentarios "
            f"registrados en los ultimos dias es negativo.\n\n"
            f"La Municipalidad esta evaluando las siguientes acciones:\n{lista_acciones}\n\n"
            f"Seguiremos informando a la comunidad."
        )
    if tipo == "en_curso":
        return (
            f"ACCION EN CURSO - {categoria.upper()} EN {distrito.upper()}\n\n"
            f"Como parte de la respuesta a los reportes de {cat_lower} en {distrito}, "
            f"la Municipalidad viene ejecutando:\n{lista_acciones}\n\n"
            f"Agradecemos la paciencia de los vecinos mientras se normaliza la situacion."
        )
    if tipo == "seguimiento":
        return (
            f"SEGUIMIENTO - {categoria.upper()} EN {distrito.upper()}\n\n"
            f"Actualizacion sobre la situacion de {cat_lower} en {distrito} "
            f"({porcentaje:.0f}% de comentarios negativos registrados). "
            f"Acciones en evaluacion o en curso:\n{lista_acciones}"
        )
    # informe (prioridad baja)
    return (
        f"INFORME - {categoria.upper()} EN {distrito.upper()}\n\n"
        f"La situacion de {cat_lower} en {distrito} se mantiene bajo control "
        f"({porcentaje:.0f}% de comentarios negativos). Continuamos con las labores "
        f"habituales de prevencion:\n{lista_acciones}"
    )

def generar_campana(distrito: str, categoria: str, prioridad: str, porcentaje: float,
                     acciones: list) -> list:
    """Devuelve una lista de posts (campana escalonada) segun la prioridad."""
    if prioridad == "Alta":
        tipos = ["alerta", "en_curso", "seguimiento"]
    elif prioridad == "Media":
        tipos = ["alerta", "seguimiento"]
    else:
        tipos = ["informe"]
    return [generar_post(distrito, categoria, prioridad, porcentaje, acciones, t) for t in tipos]

# ------------------------------------------------------------------------
# Generacion con IA (opcional, Gemini). Requiere el paquete "google-genai"
# instalado y la variable de entorno GEMINI_API_KEY configurada en tu propia
# sesion (nunca hardcodeada en este archivo). Si algo falla, siempre cae de
# vuelta a la plantilla fija -- la app nunca se rompe por esto.
# ------------------------------------------------------------------------

MODELO_IA = "gemini-2.5-flash-lite"

def _cliente_ia():
    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not (GEMINI_DISPONIBLE and api_key):
        return None
    try:
        return genai_sdk.Client(api_key=api_key)
    except Exception:
        return None

TIPO_A_DESCRIPCION = {
    "alerta": "un primer aviso a la comunidad de que la municipalidad detecto el problema y ya esta evaluando acciones",
    "en_curso": "una actualizacion de que las acciones ya se estan ejecutando en campo",
    "seguimiento": "un seguimiento/cierre informando el avance a los vecinos",
    "informe": "un informe breve indicando que la situacion esta controlada y se mantienen labores preventivas",
}

def _prompt_post(distrito, categoria, prioridad, porcentaje, acciones, tipo, evidencia_textos):
    lista_acciones = armar_lista_acciones(acciones)
    ejemplos = "\n".join(f"- \"{t}\"" for t in evidencia_textos[:3]) or "- (sin ejemplos disponibles)"
    return (
        "Eres el equipo de comunicaciones de una municipalidad de Lima Metropolitana, Peru. "
        "Redacta UN post breve para redes sociales (estilo institucional, cercano, sin exagerar, "
        "en espanol de Peru, sin emojis, maximo 700 caracteres), que sea " + TIPO_A_DESCRIPCION[tipo] + ".\n\n"
        f"Distrito: {distrito}, Lima, Peru.\n"
        f"Categoria del problema: {categoria}.\n"
        f"Prioridad de intervencion: {prioridad}.\n"
        f"Porcentaje de comentarios ciudadanos negativos: {porcentaje:.0f}%.\n"
        f"Ejemplos de quejas reales de vecinos:\n{ejemplos}\n\n"
        f"Acciones que la municipalidad va a comunicar:\n{lista_acciones}\n\n"
        "Devuelve SOLO el texto del post (con un titulo corto en mayusculas en la primera linea "
        "y el cuerpo despues), sin explicaciones adicionales ni comillas envolventes."
    )

def generar_post_ia(distrito, categoria, prioridad, porcentaje, acciones, tipo, evidencia_textos):
    """Intenta generar el post con la API de Gemini. Devuelve
    (texto, uso_ia: bool)."""
    cliente = _cliente_ia()
    if cliente is None:
        return generar_post(distrito, categoria, prioridad, porcentaje, acciones, tipo), False
    try:
        respuesta = cliente.models.generate_content(
            model=MODELO_IA,
            contents=_prompt_post(distrito, categoria, prioridad, porcentaje, acciones, tipo, evidencia_textos),
        )
        texto = (respuesta.text or "").strip()
        if texto:
            return texto, True
        return generar_post(distrito, categoria, prioridad, porcentaje, acciones, tipo), False
    except Exception:
        return generar_post(distrito, categoria, prioridad, porcentaje, acciones, tipo), False

def generar_campana_ia(distrito, categoria, prioridad, porcentaje, acciones, evidencia_textos):
    if prioridad == "Alta":
        tipos = ["alerta", "en_curso", "seguimiento"]
    elif prioridad == "Media":
        tipos = ["alerta", "seguimiento"]
    else:
        tipos = ["informe"]
    posts, algun_ia = [], False
    for t in tipos:
        texto, uso_ia = generar_post_ia(distrito, categoria, prioridad, porcentaje, acciones, t, evidencia_textos)
        posts.append(texto)
        algun_ia = algun_ia or uso_ia
    return posts, algun_ia

# ==============================================================================
# 7. ESTADO DE SESION (filtros persistentes entre reruns)
# ==============================================================================

if "tema_seleccionado" not in st.session_state:
    st.session_state.tema_seleccionado = TEMAS[0]
if "distrito_seleccionado" not in st.session_state:
    st.session_state.distrito_seleccionado = "Todos"
if "pagina_tweets" not in st.session_state:
    st.session_state.pagina_tweets = 0
if "acciones_plan" not in st.session_state:
    st.session_state.acciones_plan = []
if "validado_comunicaciones" not in st.session_state:
    st.session_state.validado_comunicaciones = False

# ==============================================================================
# 8. SIDEBAR: FILTROS
# ==============================================================================

with st.sidebar:
    st.markdown("## Filtros")
    st.markdown("---")

    st.markdown("#### Categoria ambiental")
    for tema in TEMAS:
        activo = st.session_state.tema_seleccionado == tema
        if st.button(tema, key=f"btn_{tema}", use_container_width=True,
                     type="primary" if activo else "secondary"):
            st.session_state.tema_seleccionado = tema
            st.session_state.pagina_tweets = 0
            st.session_state.acciones_plan = []
            st.session_state.validado_comunicaciones = False
            st.rerun()

    st.markdown("---")
    st.markdown("#### Distrito")
    opciones_distrito = ["Todos"] + LISTA_DISTRITOS
    idx_actual = opciones_distrito.index(st.session_state.distrito_seleccionado) \
        if st.session_state.distrito_seleccionado in opciones_distrito else 0
    distrito_elegido = st.selectbox(
        "Selecciona un distrito", opciones_distrito, index=idx_actual
    )
    if distrito_elegido != st.session_state.distrito_seleccionado:
        st.session_state.distrito_seleccionado = distrito_elegido
        st.session_state.pagina_tweets = 0
        st.session_state.acciones_plan = []
        st.session_state.validado_comunicaciones = False

    st.markdown("---")
    st.markdown("#### Rango de fechas")
    fecha_min = df_tweets["fecha"].min().date()
    fecha_max = df_tweets["fecha"].max().date()
    rango_fechas = st.date_input(
        "Selecciona un rango",
        value=(fecha_min, fecha_max),
        min_value=fecha_min,
        max_value=fecha_max,
    )
    if isinstance(rango_fechas, tuple) and len(rango_fechas) == 2:
        fecha_ini, fecha_fin = rango_fechas
    else:
        fecha_ini, fecha_fin = fecha_min, fecha_max

tema_actual = st.session_state.tema_seleccionado
distrito_actual = st.session_state.distrito_seleccionado

# ==============================================================================
# 9. CABECERA
# ==============================================================================

ruta_hero = _ruta_imagen(IMAGEN_HERO)
if os.path.exists(ruta_hero):
    try:
        st.markdown(
            f"""
            <div class="hero-banner">
                <img src="data:image/{IMAGEN_HERO.split('.')[-1]};base64,{_imagen_base64(ruta_hero)}" />
                <div class="hero-texto">
                    <h1>Sentimiento Ciudadano sobre Problemas Ambientales</h1>
                    <p>Categoria seleccionada: <b>{tema_actual}</b> &nbsp;|&nbsp; Lima Metropolitana</p>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    except Exception:
        st.markdown("# Sentimiento Ciudadano sobre Problemas Ambientales")
        st.markdown(f"#### Categoria seleccionada: **{tema_actual}**")
else:
    st.markdown("# Sentimiento Ciudadano sobre Problemas Ambientales")
    st.markdown(f"#### Categoria seleccionada: **{tema_actual}**")

# ==============================================================================
# 10. FILTRADO DE DATOS SEGUN TEMA / DISTRITO / FECHAS
# ==============================================================================

df_tema = df_resumen[df_resumen["tema"] == tema_actual].copy()

df_tweets_filtrado = df_tweets[
    (df_tweets["tema"] == tema_actual)
    & (df_tweets["fecha"].dt.date >= fecha_ini)
    & (df_tweets["fecha"].dt.date <= fecha_fin)
]
if distrito_actual != "Todos":
    df_tweets_filtrado = df_tweets_filtrado[df_tweets_filtrado["distrito"] == distrito_actual]

df_tweets_filtrado_display = df_tweets_filtrado.head(100)  # tope de 100 en pantalla

tab_dashboard, tab_accion = st.tabs(["Dashboard", "Plan de Accion"])

# ==============================================================================
# 11. TAB: DASHBOARD
# ==============================================================================

with tab_dashboard:
    imagenes_tema_actual = IMAGENES_TEMA.get(tema_actual, [])
    if imagenes_tema_actual:
        cols_galeria = st.columns(len(imagenes_tema_actual))
        for col, nombre_img in zip(cols_galeria, imagenes_tema_actual):
            with col:
                mostrar_imagen(nombre_img, alto_px=140)
        st.markdown("<br>", unsafe_allow_html=True)

    total_tweets_tema = int(df_tema["num_tweets"].sum())
    promedio_negativo = df_tema["sentimiento_negativo"].mean()
    distrito_mas_afectado = df_tema.loc[df_tema["sentimiento_negativo"].idxmax(), "distrito"]
    valor_max = df_tema["sentimiento_negativo"].max()
    distrito_menos_afectado = df_tema.loc[df_tema["sentimiento_negativo"].idxmin(), "distrito"]

    k1, k2, k3, k4 = st.columns(4)
    with k1:
        st.markdown(
            f"""<div class="kpi-card"><div class="kpi-valor">{total_tweets_tema:,}</div>
            <div class="kpi-etiqueta">Tweets totales (categoria)</div></div>""",
            unsafe_allow_html=True,
        )
    with k2:
        st.markdown(
            f"""<div class="kpi-card"><div class="kpi-valor">{promedio_negativo:.1f}%</div>
            <div class="kpi-etiqueta">Sentimiento negativo promedio</div></div>""",
            unsafe_allow_html=True,
        )
    with k3:
        st.markdown(
            f"""<div class="kpi-card"><div class="kpi-valor">{distrito_mas_afectado}</div>
            <div class="kpi-etiqueta">Distrito mas afectado ({valor_max:.0f}%)</div></div>""",
            unsafe_allow_html=True,
        )
    with k4:
        st.markdown(
            f"""<div class="kpi-card"><div class="kpi-valor">{distrito_menos_afectado}</div>
            <div class="kpi-etiqueta">Distrito menos afectado</div></div>""",
            unsafe_allow_html=True,
        )

    st.markdown("<br>", unsafe_allow_html=True)

    col_mapa, col_resumen = st.columns([2, 1])

    geojson_tema_actual = geojson_por_tema(tema_actual, gdf, df_tema)

    with col_mapa:
        st.markdown("### Mapa de calor por distrito")

        minx, miny, maxx, maxy = gdf.total_bounds
        padding_geo = 0.05
        minx -= padding_geo; maxx += padding_geo
        miny -= padding_geo; maxy += padding_geo

        lat_center = (miny + maxy) / 2
        factor_lon = math.cos(math.radians(lat_center))
        width_deg = maxx - minx
        height_deg = maxy - miny
        ancho_real = width_deg * factor_lon
        alto_real = height_deg

        if ancho_real > alto_real:
            extra = (ancho_real - alto_real) / 2
            miny -= extra; maxy += extra
        else:
            nuevo_ancho_deg = (alto_real) / factor_lon
            extra = (nuevo_ancho_deg - width_deg) / 2
            minx -= extra; maxx += extra

        sw = [miny, minx]
        ne = [maxy, maxx]
        centro = [(sw[0] + ne[0]) / 2, (sw[1] + ne[1]) / 2]

        TAMANO = 620
        fig = Figure(width=TAMANO, height=TAMANO)
        m = folium.Map(
            location=centro,
            tiles="CartoDB dark_matter",
            max_zoom=12,
            min_zoom=10,
            scrollWheelZoom=True,
            dragging=True,
            zoom_control=True,
            attribution_control=False,
            width="100%",
            height="100%",
        )
        fig.add_child(m)
        m.options["maxBounds"] = [sw, ne]
        m.options["maxBoundsViscosity"] = 1.0

        def estilo(feature):
            d = feature["properties"].get("distrito")
            seleccionado = distrito_actual != "Todos" and d == distrito_actual
            return {
                "fillColor": feature["properties"]["color_calor"],
                "color": "#EAF2F5" if seleccionado else "#66808C",
                "weight": 3.5 if seleccionado else 1.2,
                "fillOpacity": 0.85 if seleccionado else 0.7,
            }

        folium.GeoJson(
            geojson_tema_actual,
            style_function=estilo,
            highlight_function=lambda x: {"weight": 3, "fillOpacity": 0.9},
            tooltip=folium.GeoJsonTooltip(
                fields=["distrito", "sentimiento_negativo", "num_tweets"],
                aliases=["Distrito:", "Sentimiento negativo (%):", "N. tweets:"],
                localize=True,
                sticky=True,
            ),
            popup=folium.GeoJsonPopup(
                fields=["distrito", "sentimiento_negativo", "num_tweets"],
                aliases=["Distrito:", "Sentimiento negativo (%):", "N. tweets:"],
            ),
        ).add_to(m)

        m.fit_bounds([sw, ne])

        class ResetViewButton(MacroElement):
            _template = Template(
                """
                {% macro script(this, kwargs) %}
                var resetBtn = L.control({position: 'topleft'});
                resetBtn.onAdd = function(map) {
                    var div = L.DomUtil.create('div', 'leaflet-bar leaflet-control');
                    div.innerHTML = '<a href="#" title="Reiniciar vista" style="font-size:14px; text-align:center; line-height:30px; width:30px; height:30px; display:block;">Reset</a>';
                    div.onclick = function(e) {
                        e.preventDefault();
                        {{ this._parent.get_name() }}.fitBounds({{ this.bounds_json }});
                    };
                    L.DomEvent.disableClickPropagation(div);
                    return div;
                };
                resetBtn.addTo({{ this._parent.get_name() }});
                {% endmacro %}
                """
            )

            def __init__(self, bounds):
                super().__init__()
                self.bounds_json = json.dumps(bounds)

        m.add_child(ResetViewButton([sw, ne]))

        leyenda_html = """
        <div style="position: fixed; bottom: 20px; left: 20px; z-index: 9999;
                    background: #132836; color: #EAF2F5; padding: 8px 12px; border-radius: 8px;
                    box-shadow: 0 1px 4px rgba(0,0,0,0.5); font-size: 12px; border: 1px solid #1E3A4C;">
            <b>Sentimiento negativo</b><br>
            <span style="color:#D64550;">&#9679;</span> Muy negativo (67-100%)<br>
            <span style="color:#E1A63A;">&#9679;</span> Medio (34-66%)<br>
            <span style="color:#1C8EB0;">&#9679;</span> Poco afectado (0-33%)
        </div>
        """
        m.get_root().html.add_child(folium.Element(leyenda_html))

        salida_mapa = st_folium(fig, width=TAMANO, height=TAMANO, returned_objects=["last_active_drawing"])

        if salida_mapa and salida_mapa.get("last_active_drawing"):
            props = salida_mapa["last_active_drawing"].get("properties", {})
            distrito_click = props.get("distrito")
            if distrito_click and distrito_click != st.session_state.distrito_seleccionado:
                st.session_state.distrito_seleccionado = distrito_click
                st.session_state.pagina_tweets = 0
                st.session_state.acciones_plan = []
                st.session_state.validado_comunicaciones = False
                st.rerun()

    with col_resumen:
        st.markdown("### Resumen del distrito")
        if distrito_actual == "Todos":
            st.info("Selecciona un distrito en el mapa o en el sidebar para ver su detalle.")
            top10 = df_tema.sort_values("sentimiento_negativo", ascending=False).head(10)
            fig_bar = px.bar(
                top10.sort_values("sentimiento_negativo"),
                x="sentimiento_negativo",
                y="distrito",
                orientation="h",
                color="sentimiento_negativo",
                color_continuous_scale=["#1C8EB0", "#E1A63A", "#D64550"],
                labels={"sentimiento_negativo": "% Negativo", "distrito": ""},
                title="Top 10 distritos mas afectados",
            )
            fig_bar.update_layout(
                height=380, margin=dict(l=10, r=10, t=40, b=10), coloraxis_showscale=False,
                paper_bgcolor="#132836", plot_bgcolor="#132836", font_color="#EAF2F5",
            )
            st.plotly_chart(fig_bar, use_container_width=True)
        else:
            fila = df_tema[df_tema["distrito"] == distrito_actual].iloc[0]
            color_badge = color_por_sentimiento(fila["sentimiento_negativo"])
            st.markdown(
                f"""
                <div class="kpi-card" style="text-align:left;">
                    <h4 style="margin-top:0;">{distrito_actual}</h4>
                    <p style="margin:4px 0;">Categoria: <b>{tema_actual}</b></p>
                    <p style="margin:4px 0;">
                        Sentimiento negativo:
                        <span class="badge" style="background-color:{color_badge};">
                            {fila['sentimiento_negativo']:.1f}%
                        </span>
                    </p>
                    <p style="margin:4px 0;">N. de tweets: <b>{int(fila['num_tweets']):,}</b></p>
                </div>
                """,
                unsafe_allow_html=True,
            )

            comp = df_resumen[df_resumen["distrito"] == distrito_actual]
            fig_comp = px.bar(
                comp,
                x="tema",
                y="sentimiento_negativo",
                color="sentimiento_negativo",
                color_continuous_scale=["#1C8EB0", "#E1A63A", "#D64550"],
                labels={"sentimiento_negativo": "% Negativo", "tema": ""},
                title=f"{distrito_actual}: comparativo por categoria",
            )
            fig_comp.update_xaxes(tickangle=25)
            fig_comp.update_layout(
                height=340, margin=dict(l=10, r=10, t=40, b=10), coloraxis_showscale=False,
                paper_bgcolor="#132836", plot_bgcolor="#132836", font_color="#EAF2F5",
            )
            st.plotly_chart(fig_comp, use_container_width=True)

            if st.button("Quitar seleccion de distrito", use_container_width=True):
                st.session_state.distrito_seleccionado = "Todos"
                st.session_state.pagina_tweets = 0
                st.session_state.acciones_plan = []
                st.session_state.validado_comunicaciones = False
                st.rerun()

    st.markdown("---")
    st.markdown("### Tendencias")

    @st.cache_data(show_spinner=False)
    def _agregados_tendencia(_df_tweets: pd.DataFrame, tema: str, distrito: str):
        df_t = _df_tweets[_df_tweets["tema"] == tema]
        if distrito != "Todos":
            df_t = df_t[df_t["distrito"] == distrito]

        evol = (
            df_t.groupby("mes")
            .agg(
                total=("sentimiento", "size"),
                negativos=("sentimiento", lambda s: (s == "negativo").sum()),
            )
            .reset_index()
        )
        evol["pct_negativo"] = (evol["negativos"] / evol["total"] * 100).round(1)
        evol = evol.sort_values("mes")

        conteo = df_t["sentimiento"].value_counts().reindex(
            ["negativo", "neutral", "positivo"]
        ).fillna(0).reset_index()
        conteo.columns = ["sentimiento", "cantidad"]
        return evol, conteo

    evol_mensual, conteo_sent = _agregados_tendencia(df_tweets, tema_actual, distrito_actual)

    col_mensual, col_dona = st.columns([2, 1])

    with col_mensual:
        titulo_mensual = f"Evolucion mensual del sentimiento negativo - {tema_actual}"
        if distrito_actual != "Todos":
            titulo_mensual += f" ({distrito_actual})"

        fig_mensual = px.line(
            evol_mensual, x="mes", y="pct_negativo", markers=True,
            labels={"mes": "Mes", "pct_negativo": "% Negativo"},
            title=titulo_mensual,
        )
        fig_mensual.update_traces(line_color="#D64550", marker=dict(size=9, color="#2FA8CC"))
        fig_mensual.update_layout(
            height=320, margin=dict(l=10, r=10, t=40, b=10),
            paper_bgcolor="#132836", plot_bgcolor="#132836", font_color="#EAF2F5",
            yaxis=dict(range=[0, 100]),
        )
        st.plotly_chart(fig_mensual, use_container_width=True)

    with col_dona:
        fig_dona = px.pie(
            conteo_sent, names="sentimiento", values="cantidad", hole=0.55,
            color="sentimiento",
            color_discrete_map={"negativo": "#D64550", "neutral": "#E1A63A", "positivo": "#4CAF7D"},
            title="Distribucion de sentimiento",
        )
        fig_dona.update_traces(textinfo="percent+label", textfont_color="#EAF2F5")
        fig_dona.update_layout(
            height=320, margin=dict(l=10, r=10, t=40, b=10), showlegend=False,
            paper_bgcolor="#132836", plot_bgcolor="#132836", font_color="#EAF2F5",
        )
        st.plotly_chart(fig_dona, use_container_width=True)

    st.markdown("---")
    titulo_tweets = f"### Tweets - {tema_actual}"
    if distrito_actual != "Todos":
        titulo_tweets += f" en {distrito_actual}"
    st.markdown(titulo_tweets)
    st.caption(
        f"Mostrando hasta 100 tweets mas recientes en pantalla, de un total de "
        f"{len(df_tweets_filtrado)} encontrados segun los filtros aplicados."
    )

    TWEETS_POR_PAGINA = 10
    total_tweets_filtrados = len(df_tweets_filtrado_display)
    total_paginas = max(1, math.ceil(total_tweets_filtrados / TWEETS_POR_PAGINA))

    if st.session_state.pagina_tweets >= total_paginas:
        st.session_state.pagina_tweets = total_paginas - 1
    if st.session_state.pagina_tweets < 0:
        st.session_state.pagina_tweets = 0

    inicio = st.session_state.pagina_tweets * TWEETS_POR_PAGINA
    fin = inicio + TWEETS_POR_PAGINA
    pagina_actual_df = df_tweets_filtrado_display.iloc[inicio:fin]

    badge_clase = {
        "negativo": "badge-negativo",
        "neutral": "badge-neutral",
        "positivo": "badge-positivo",
    }

    if total_tweets_filtrados == 0:
        st.warning("No hay tweets para esta combinacion de filtros.")
    else:
        for _, tw in pagina_actual_df.iterrows():
            st.markdown(
                f"""
                <div class="tweet-card">
                    <div>{tw['texto']}</div>
                    <div class="tweet-meta">
                        <span class="badge {badge_clase[tw['sentimiento']]}">{tw['sentimiento'].capitalize()}</span>
                        &nbsp;-&nbsp; {tw['usuario']} &nbsp;-&nbsp; {tw['distrito']}
                        &nbsp;-&nbsp; {tw['fecha'].strftime('%d/%m/%Y %H:%M')}
                        &nbsp;-&nbsp; {tw['likes']} likes
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )

        c_prev, c_info, c_next = st.columns([1, 2, 1])
        with c_prev:
            if st.button("Anterior", disabled=st.session_state.pagina_tweets == 0, use_container_width=True):
                st.session_state.pagina_tweets -= 1
                st.rerun()
        with c_info:
            st.markdown(
                f"<div style='text-align:center; padding-top:8px;'>Pagina "
                f"<b>{st.session_state.pagina_tweets + 1}</b> de <b>{total_paginas}</b></div>",
                unsafe_allow_html=True,
            )
        with c_next:
            if st.button("Siguiente", disabled=st.session_state.pagina_tweets >= total_paginas - 1, use_container_width=True):
                st.session_state.pagina_tweets += 1
                st.rerun()

    st.markdown("---")
    lista_correos = " &nbsp;|&nbsp; ".join(f'<a href="mailto:{c}" style="color:inherit;">{c}</a>' for c in EMAILS_CONTACTO)
    st.markdown(
        f"""
        <div class="footer-institucional">
            <b>Dashboard de Sentimiento Ciudadano - Problemas Ambientales en Lima Metropolitana</b><br>
            Elaborado por el equipo de la Universidad Nacional Mayor de San Marcos (UNMSM)<br>
            Contacto: {lista_correos}
        </div>
        """,
        unsafe_allow_html=True,
    )

# ==============================================================================
# 12. TAB: PLAN DE ACCION
# ==============================================================================

with tab_accion:
    st.markdown("### Plan de Accion")

    distrito_accion = distrito_actual
    if distrito_accion == "Todos":
        st.info(
            "No hay un distrito especifico seleccionado. Se usara automaticamente "
            "el distrito mas afectado en esta categoria como punto de partida; "
            "puedes cambiarlo en el sidebar para trabajar sobre otro."
        )
        distrito_accion = df_tema.loc[df_tema["sentimiento_negativo"].idxmax(), "distrito"]

    fila_accion = df_tema[df_tema["distrito"] == distrito_accion].iloc[0]
    porcentaje_accion = fila_accion["sentimiento_negativo"]
    num_tweets_accion = int(fila_accion["num_tweets"])
    prioridad, color_prioridad = clasificar_prioridad(porcentaje_accion)

    st.markdown(
        f"""
        <div class="accion-card">
            <h4 style="margin-top:0;">{distrito_accion} - {tema_actual}</h4>
            <p style="margin:4px 0;">Prioridad de intervencion:
                <span class="badge-prioridad" style="background-color:{color_prioridad};">{prioridad}</span>
            </p>
            <p style="margin:4px 0;">Sentimiento negativo: <b>{porcentaje_accion:.1f}%</b>
               &nbsp;|&nbsp; Registros analizados: <b>{num_tweets_accion:,}</b></p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.markdown("##### Registros de respaldo (tweets negativos mas relevantes)")
    evidencia = df_tweets[
        (df_tweets["tema"] == tema_actual)
        & (df_tweets["distrito"] == distrito_accion)
        & (df_tweets["sentimiento"] == "negativo")
    ].sort_values("likes", ascending=False).head(3)

    if evidencia.empty:
        st.caption("No hay registros negativos para esta combinacion.")
    else:
        for _, tw in evidencia.iterrows():
            st.markdown(
                f"""<div class="tweet-card">
                    <div>{tw['texto']}</div>
                    <div class="tweet-meta">{tw['usuario']} &nbsp;-&nbsp; {tw['likes']} likes</div>
                </div>""",
                unsafe_allow_html=True,
            )

    st.markdown("---")
    st.markdown("##### Acciones sugeridas (segun categoria)")
    st.caption("Selecciona las acciones que la municipalidad va a tomar; se incluiran en el post.")

    cols_acciones = st.columns(len(ACCIONES_SUGERIDAS[tema_actual]))
    for i, accion in enumerate(ACCIONES_SUGERIDAS[tema_actual]):
        with cols_acciones[i]:
            ya_seleccionada = accion in st.session_state.acciones_plan
            if st.button(
                ("Quitar: " if ya_seleccionada else "Agregar: ") + accion,
                key=f"accion_{tema_actual}_{i}",
                use_container_width=True,
                type="primary" if ya_seleccionada else "secondary",
            ):
                if ya_seleccionada:
                    st.session_state.acciones_plan.remove(accion)
                else:
                    st.session_state.acciones_plan.append(accion)
                st.rerun()

    if st.session_state.acciones_plan:
        chips = "".join(f'<span class="chip-accion">{a}</span>' for a in st.session_state.acciones_plan)
        st.markdown("Acciones en el plan actual:<br>" + chips, unsafe_allow_html=True)
    else:
        st.caption("Todavia no seleccionas ninguna accion.")

    st.markdown("---")
    st.markdown("##### Generar comunicacion")

    usar_ia = st.checkbox(
        "Generar texto con IA (Gemini) en vez de la plantilla fija",
        key="usar_ia_generacion",
        help=(
            "Requiere el paquete 'google-genai' instalado y la variable de entorno "
            "GEMINI_API_KEY configurada en tu sesion (no en este archivo). Si no "
            "esta disponible, se usa la plantilla fija automaticamente."
        ),
    )
    if usar_ia and not GEMINI_DISPONIBLE:
        st.caption("El paquete 'google-genai' no esta instalado en este entorno (`!pip install -q google-genai`). Se usara la plantilla fija.")
    elif usar_ia and not (os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")):
        st.caption("No se encontro GEMINI_API_KEY en el entorno. Se usara la plantilla fija.")

    evidencia_textos = evidencia["texto"].tolist() if not evidencia.empty else []

    col_post, col_campana = st.columns(2)

    with col_post:
        st.markdown("**Post individual**")
        tipo_post = "alerta" if prioridad == "Alta" else ("seguimiento" if prioridad == "Media" else "informe")
        if st.button("Generar post", use_container_width=True):
            if usar_ia:
                texto, uso_ia = generar_post_ia(
                    distrito_accion, tema_actual, prioridad, porcentaje_accion,
                    st.session_state.acciones_plan, tipo_post, evidencia_textos,
                )
            else:
                texto, uso_ia = generar_post(
                    distrito_accion, tema_actual, prioridad, porcentaje_accion,
                    st.session_state.acciones_plan, tipo_post,
                ), False
            st.session_state["post_generado"] = texto
            st.session_state["post_generado_con_ia"] = uso_ia
        if "post_generado" in st.session_state:
            etiqueta_ia = '<span class="ia-badge">IA</span>' if st.session_state.get("post_generado_con_ia") else ""
            st.markdown(f'<div class="post-preview">{st.session_state["post_generado"]}</div>{etiqueta_ia}', unsafe_allow_html=True)

    with col_campana:
        n_posts_sugeridos = {"Alta": 3, "Media": 2, "Baja": 1}[prioridad]
        st.markdown(f"**Campana sugerida ({n_posts_sugeridos} posts, segun prioridad {prioridad.lower()})**")
        if st.button("Generar campana", use_container_width=True):
            if usar_ia:
                posts, uso_ia = generar_campana_ia(
                    distrito_accion, tema_actual, prioridad, porcentaje_accion,
                    st.session_state.acciones_plan, evidencia_textos,
                )
            else:
                posts, uso_ia = generar_campana(
                    distrito_accion, tema_actual, prioridad, porcentaje_accion,
                    st.session_state.acciones_plan,
                ), False
            st.session_state["campana_generada"] = posts
            st.session_state["campana_generada_con_ia"] = uso_ia
        if "campana_generada" in st.session_state:
            etiqueta_ia = '<span class="ia-badge">IA</span>' if st.session_state.get("campana_generada_con_ia") else ""
            for i, post in enumerate(st.session_state["campana_generada"], start=1):
                st.markdown(f"Post {i} de {len(st.session_state['campana_generada'])}" + (etiqueta_ia if i == 1 else ""), unsafe_allow_html=True)
                st.markdown(f'<div class="post-preview">{post}</div>', unsafe_allow_html=True)

    st.markdown("---")
    st.markdown("##### Validacion y exportacion")
    st.checkbox(
        "Validado por el equipo de comunicaciones de la Municipalidad antes de publicar",
        key="validado_comunicaciones",
    )

    contenido_exportar = None
    if "campana_generada" in st.session_state:
        contenido_exportar = "\n\n---\n\n".join(st.session_state["campana_generada"])
    elif "post_generado" in st.session_state:
        contenido_exportar = st.session_state["post_generado"]

    if contenido_exportar:
        st.download_button(
            "Descargar borrador (.txt)",
            data=contenido_exportar,
            file_name=f"plan_accion_{distrito_accion}_{tema_actual}.txt".replace(" ", "_"),
            mime="text/plain",
            disabled=not st.session_state.validado_comunicaciones,
            use_container_width=True,
        )
        if not st.session_state.validado_comunicaciones:
            st.caption("Marca la casilla de validacion para habilitar la descarga.")
    else:
        st.caption("Genera un post o una campana para poder exportarla.")

    st.markdown("---")
    st.markdown("##### Campana visual")
    st.caption("Imagenes de apoyo para acompanar la difusion de la campana.")
    cols_campana_img = st.columns(len(IMAGENES_CAMPANA))
    for col, (nombre_img, leyenda_img) in zip(cols_campana_img, IMAGENES_CAMPANA):
        with col:
            mostrar_imagen(nombre_img, alto_px=160, leyenda=leyenda_img)
