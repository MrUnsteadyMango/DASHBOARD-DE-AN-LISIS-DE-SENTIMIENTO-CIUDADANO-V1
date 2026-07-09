"""
================================================================================
DASHBOARD DE ANÁLISIS DE SENTIMIENTO CIUDADANO - PROBLEMAS AMBIENTALES
Lima Metropolitana
================================================================================
App en Streamlit que muestra un mapa de calor de sentimiento negativo por
distrito según 4 temas ambientales, con filtros, KPIs y feed de tweets
simulados con paginación.

Cómo ejecutar:
    streamlit run app.py

IMPORTANTE: ajusta la variable GEOJSON_PATH más abajo a la ruta de tu archivo
lima_callao_distritos_simple.geojson en tu entorno (local, Drive montado, etc).
================================================================================
"""

import json
import math
import random
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

# ==============================================================================
# 0. CONFIGURACIÓN GENERAL DE LA PÁGINA
# ==============================================================================

st.set_page_config(
    page_title="Sentimiento Ambiental - Lima Metropolitana",
    page_icon="🌎",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Ruta al geojson. AJUSTAR según tu entorno (Drive, local, etc.)
GEOJSON_PATH = "/content/drive/MyDrive/Mapa LM/lima_callao_distritos_simple.geojson"

# Los 4 temas del dashboard
TEMAS = [
    "Olas de Calor y Efecto Isla de Calor Urbana",
    "Inundaciones y Gestión de Riesgos Climáticos",
    "Contaminación del Aire y Humo Urbano",
    "Escasez de Agua y Sequía Urbana",
]

# Emojis / iconos cortos para cada tema (uso en botones y UI)
TEMA_ICONOS = {
    TEMAS[0]: "🔥",
    TEMAS[1]: "🌊",
    TEMAS[2]: "🌫️",
    TEMAS[3]: "💧",
}

# ==============================================================================
# 1. ESTILOS (colores institucionales azul/verde + soporte modo oscuro/claro)
# ==============================================================================

if "modo_oscuro" not in st.session_state:
    st.session_state.modo_oscuro = False

def inyectar_css(modo_oscuro: bool):
    """Inyecta CSS institucional. Cambia paleta según modo oscuro/claro."""
    if modo_oscuro:
        bg = "#0E1A24"
        bg_card = "#132836"
        texto = "#EAF2F5"
        texto_sec = "#A9C0CB"
        borde = "#1E3A4C"
    else:
        bg = "#F4F8F9"
        bg_card = "#FFFFFF"
        texto = "#0E2A38"
        texto_sec = "#4C6A78"
        borde = "#DCE7EA"

    azul = "#0B5D7A"       # azul institucional
    azul_claro = "#1C8EB0"
    verde = "#2E8B57"      # verde institucional
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
            box-shadow: 0 2px 6px rgba(0,0,0,0.06);
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
        .badge-positivo {{ background-color: {verde}; }}

        .tema-activo {{
            border: 2px solid {verde_claro} !important;
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
        </style>
        """,
        unsafe_allow_html=True,
    )

inyectar_css(st.session_state.modo_oscuro)

# ==============================================================================
# 2. CARGA DE DATOS GEOGRÁFICOS
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
    # Normalizamos el nombre del distrito para hacer merges sin problemas
    # de mayúsculas/tildes/espacios
    gdf["distrito_norm"] = (
        gdf["distrito"]
        .astype(str)
        .str.upper()
        .str.strip()
        .str.normalize("NFKD")
        .str.encode("ascii", errors="ignore")
        .str.decode("utf-8")
    )
    return gdf

gdf = cargar_geojson(GEOJSON_PATH)
LISTA_DISTRITOS = sorted(gdf["distrito"].dropna().unique().tolist())

# ==============================================================================
# 3. GENERACIÓN DE DATOS SINTÉTICOS (cacheado para que sea estable en la sesión)
# ==============================================================================

@st.cache_data(show_spinner=False)
def generar_datos_sinteticos(distritos: list, temas: list, semilla: int = 42):
    """
    Genera un DataFrame distrito x tema con métricas sintéticas de sentimiento,
    y un DataFrame de tweets sintéticos asociado a cada combinación.
    """
    rng = np.random.default_rng(semilla)

    # --- 3.1 Perfil base por distrito (para que algunos temas "pesen" más
    # en ciertos distritos, y así no sea 100% aleatorio uniforme) ---
    perfiles = {}
    for d in distritos:
        perfiles[d] = {
            "calor": rng.uniform(0.3, 1.0),
            "inundacion": rng.uniform(0.2, 1.0),
            "aire": rng.uniform(0.3, 1.0),
            "agua": rng.uniform(0.2, 1.0),
        }
    mapa_tema_perfil = {
        temas[0]: "calor",
        temas[1]: "inundacion",
        temas[2]: "aire",
        temas[3]: "agua",
    }

    filas_resumen = []
    filas_tweets = []

    # Plantillas de texto sintético por tema (varias variantes para variedad)
    plantillas = {
        temas[0]: [
            "El calor en {distrito} está insoportable, no se puede dormir de noche.",
            "Otra vez récord de temperatura en {distrito}, esto ya no es normal.",
            "Las calles de {distrito} son un horno, falta más sombra y áreas verdes.",
            "Cortes de luz + ola de calor en {distrito}, situación crítica.",
            "En {distrito} el asfalto literalmente quema, isla de calor urbana real.",
        ],
        temas[1]: [
            "Se inundó de nuevo mi calle en {distrito}, el sistema de drenaje colapsó.",
            "Alerta en {distrito}: acumulación de agua tras las lluvias de esta madrugada.",
            "Las pistas de {distrito} parecen ríos cada vez que llueve fuerte.",
            "Vecinos de {distrito} piden con urgencia limpieza de canales y colectores.",
            "Tercer aniversario del huaico y {distrito} sigue sin obras de mitigación.",
        ],
        temas[2]: [
            "El aire en {distrito} huele a smog todas las mañanas, es preocupante.",
            "Índice de calidad del aire en {distrito} en niveles dañinos hoy.",
            "Demasiado tráfico y polución en {distrito}, mis hijos ya tosen seguido.",
            "En {distrito} el humo de los combis es insoportable en hora punta.",
            "Necesitamos más monitoreo de aire en {distrito}, la contaminación sube.",
        ],
        temas[3]: [
            "Llevamos días sin agua en {distrito}, esto ya es insostenible.",
            "El camión cisterna llegó tarde otra vez a {distrito}, la gente reclama.",
            "En {distrito} el racionamiento de agua afecta a miles de familias.",
            "Preocupa la escasez hídrica en {distrito} de cara al verano.",
            "Vecinos de {distrito} exigen soluciones urgentes por falta de agua potable.",
        ],
    }
    plantillas_positivas = [
        "Buena iniciativa municipal en {distrito} para enfrentar el problema, vamos bien.",
        "Se nota mejora en {distrito} gracias a las nuevas medidas implementadas.",
        "Felicito a la gestión de {distrito} por atender rápido el reclamo vecinal.",
    ]
    plantillas_neutrales = [
        "Reporte del día en {distrito}: situación estable, sin mayores incidentes.",
        "Autoridades de {distrito} monitorean la situación, se espera actualización.",
        "Comparto info oficial sobre el tema en {distrito}, revisen el comunicado.",
    ]

    hoy = datetime.now()

    for tema in temas:
        perfil_key = mapa_tema_perfil[tema]
        for d in distritos:
            base = perfiles[d][perfil_key]
            ruido = rng.normal(0, 8)
            sentimiento_negativo = float(np.clip(base * 80 + ruido + rng.uniform(-5, 15), 2, 98))
            num_tweets = int(rng.integers(40, 650))

            filas_resumen.append(
                {
                    "distrito": d,
                    "tema": tema,
                    "sentimiento_negativo": round(sentimiento_negativo, 1),
                    "num_tweets": num_tweets,
                }
            )

            # --- Tweets sintéticos para esta combinación distrito+tema ---
            n_tweets_generar = int(rng.integers(15, 40))
            for _ in range(n_tweets_generar):
                r = rng.random()
                if r < sentimiento_negativo / 100 * 0.85:
                    sentimiento = "negativo"
                    texto = rng.choice(plantillas[tema]).format(distrito=d)
                elif r < sentimiento_negativo / 100 * 0.85 + 0.10:
                    sentimiento = "neutral"
                    texto = rng.choice(plantillas_neutrales).format(distrito=d)
                else:
                    sentimiento = "positivo"
                    texto = rng.choice(plantillas_positivas).format(distrito=d)

                dias_atras = int(rng.integers(0, 30))
                fecha = hoy - timedelta(
                    days=dias_atras,
                    hours=int(rng.integers(0, 24)),
                    minutes=int(rng.integers(0, 60)),
                )
                filas_tweets.append(
                    {
                        "distrito": d,
                        "tema": tema,
                        "texto": texto,
                        "sentimiento": sentimiento,
                        "fecha": fecha,
                        "likes": int(rng.integers(0, 500)),
                        "usuario": f"@vecino_{rng.integers(1000, 9999)}",
                    }
                )

    df_resumen = pd.DataFrame(filas_resumen)
    df_tweets = pd.DataFrame(filas_tweets).sort_values("fecha", ascending=False).reset_index(drop=True)
    return df_resumen, df_tweets

df_resumen, df_tweets = generar_datos_sinteticos(LISTA_DISTRITOS, TEMAS)

# ==============================================================================
# 4. ESTADO DE SESIÓN (filtros persistentes entre reruns)
# ==============================================================================

if "tema_seleccionado" not in st.session_state:
    st.session_state.tema_seleccionado = TEMAS[0]
if "distrito_seleccionado" not in st.session_state:
    st.session_state.distrito_seleccionado = "Todos"
if "pagina_tweets" not in st.session_state:
    st.session_state.pagina_tweets = 0

# ==============================================================================
# 5. SIDEBAR: FILTROS
# ==============================================================================

with st.sidebar:
    st.markdown("## 🌎 Filtros")
    st.markdown("---")

    st.markdown("#### Tema ambiental")
    for tema in TEMAS:
        activo = st.session_state.tema_seleccionado == tema
        etiqueta = f"{TEMA_ICONOS[tema]}  {tema}"
        if st.button(etiqueta, key=f"btn_{tema}", width='stretch',
                     type="primary" if activo else "secondary"):
            st.session_state.tema_seleccionado = tema
            st.session_state.pagina_tweets = 0
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

    st.markdown("---")
    st.toggle("🌙 Modo oscuro", key="modo_oscuro", on_change=lambda: None)

tema_actual = st.session_state.tema_seleccionado
distrito_actual = st.session_state.distrito_seleccionado

# ==============================================================================
# 6. CABECERA
# ==============================================================================

st.markdown("# 🌎 Sentimiento Ciudadano sobre Problemas Ambientales")
st.markdown(f"#### Tema seleccionado: **{TEMA_ICONOS[tema_actual]} {tema_actual}**")

# ==============================================================================
# 7. FILTRADO DE DATOS SEGÚN TEMA / DISTRITO / FECHAS
# ==============================================================================

df_tema = df_resumen[df_resumen["tema"] == tema_actual].copy()

df_tweets_filtrado = df_tweets[
    (df_tweets["tema"] == tema_actual)
    & (df_tweets["fecha"].dt.date >= fecha_ini)
    & (df_tweets["fecha"].dt.date <= fecha_fin)
]
if distrito_actual != "Todos":
    df_tweets_filtrado = df_tweets_filtrado[df_tweets_filtrado["distrito"] == distrito_actual]

df_tweets_filtrado = df_tweets_filtrado.head(100)  # tope de 100 tweets

# ==============================================================================
# 8. KPIs SUPERIORES
# ==============================================================================

total_tweets_tema = int(df_tema["num_tweets"].sum())
promedio_negativo = df_tema["sentimiento_negativo"].mean()
distrito_mas_afectado = df_tema.loc[df_tema["sentimiento_negativo"].idxmax(), "distrito"]
valor_max = df_tema["sentimiento_negativo"].max()
distrito_menos_afectado = df_tema.loc[df_tema["sentimiento_negativo"].idxmin(), "distrito"]

k1, k2, k3, k4 = st.columns(4)
with k1:
    st.markdown(
        f"""<div class="kpi-card"><div class="kpi-valor">{total_tweets_tema:,}</div>
        <div class="kpi-etiqueta">Tweets totales (tema)</div></div>""",
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
        <div class="kpi-etiqueta">Distrito más afectado ({valor_max:.0f}%)</div></div>""",
        unsafe_allow_html=True,
    )
with k4:
    st.markdown(
        f"""<div class="kpi-card"><div class="kpi-valor">{distrito_menos_afectado}</div>
        <div class="kpi-etiqueta">Distrito menos afectado</div></div>""",
        unsafe_allow_html=True,
    )

st.markdown("<br>", unsafe_allow_html=True)

# ==============================================================================
# 9. MAPA DE CALOR POR DISTRITO
# ==============================================================================

col_mapa, col_resumen = st.columns([2, 1])

def color_por_sentimiento(valor: float) -> str:
    """rojo = muy negativo, naranja = medio, azul = poco afectado."""
    if valor >= 67:
        return "#D64550"   # rojo
    elif valor >= 34:
        return "#E1A63A"   # naranja
    else:
        return "#1C8EB0"   # azul

# --- Merge del gdf con los datos del tema actual ---
df_tema["distrito_norm"] = (
    df_tema["distrito"]
    .astype(str)
    .str.upper()
    .str.strip()
    .str.normalize("NFKD")
    .str.encode("ascii", errors="ignore")
    .str.decode("utf-8")
)
gdf_tema = gdf.merge(df_tema, on="distrito_norm", suffixes=("", "_datos"), how="left")
gdf_tema["sentimiento_negativo"] = gdf_tema["sentimiento_negativo"].fillna(0)
gdf_tema["num_tweets"] = gdf_tema["num_tweets"].fillna(0).astype(int)
gdf_tema["color_calor"] = gdf_tema["sentimiento_negativo"].apply(color_por_sentimiento)

with col_mapa:
    st.markdown("### 🗺️ Mapa de calor por distrito")

    # --- Bounding box cuadrado (misma lógica ya validada previamente) ---
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
        tiles="CartoDB positron",
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

    # Resaltar distrito seleccionado en sidebar con borde más grueso
    def estilo(feature):
        d = feature["properties"].get("distrito")
        seleccionado = distrito_actual != "Todos" and d == distrito_actual
        return {
            "fillColor": feature["properties"]["color_calor"],
            "color": "#0E2A38" if seleccionado else "#333333",
            "weight": 3.5 if seleccionado else 1.2,
            "fillOpacity": 0.85 if seleccionado else 0.7,
        }

    folium.GeoJson(
        json.loads(gdf_tema.to_json()),
        style_function=estilo,
        highlight_function=lambda x: {"weight": 3, "fillOpacity": 0.9},
        tooltip=folium.GeoJsonTooltip(
            fields=["distrito", "sentimiento_negativo", "num_tweets"],
            aliases=["Distrito:", "Sentimiento negativo (%):", "N° tweets:"],
            localize=True,
            sticky=True,
        ),
        popup=folium.GeoJsonPopup(
            fields=["distrito", "sentimiento_negativo", "num_tweets"],
            aliases=["Distrito:", "Sentimiento negativo (%):", "N° tweets:"],
        ),
    ).add_to(m)

    m.fit_bounds([sw, ne])

    # --- Botón de reinicio de vista ---
    class ResetViewButton(MacroElement):
        _template = Template(
            """
            {% macro script(this, kwargs) %}
            var resetBtn = L.control({position: 'topleft'});
            resetBtn.onAdd = function(map) {
                var div = L.DomUtil.create('div', 'leaflet-bar leaflet-control');
                div.innerHTML = '<a href="#" title="Reiniciar vista" style="font-size:18px; text-align:center; line-height:30px; width:30px; height:30px; display:block;">⟳</a>';
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

    # --- Leyenda simple del mapa de calor ---
    leyenda_html = """
    <div style="position: fixed; bottom: 20px; left: 20px; z-index: 9999;
                background: white; padding: 8px 12px; border-radius: 8px;
                box-shadow: 0 1px 4px rgba(0,0,0,0.3); font-size: 12px;">
        <b>Sentimiento negativo</b><br>
        <span style="color:#D64550;">●</span> Muy negativo (67-100%)<br>
        <span style="color:#E1A63A;">●</span> Medio (34-66%)<br>
        <span style="color:#1C8EB0;">●</span> Poco afectado (0-33%)
    </div>
    """
    m.get_root().html.add_child(folium.Element(leyenda_html))

    salida_mapa = st_folium(fig, width=TAMANO, height=TAMANO, returned_objects=["last_active_drawing"])

    # Si el usuario hace click en un distrito, sincronizamos el filtro de sidebar
    if salida_mapa and salida_mapa.get("last_active_drawing"):
        props = salida_mapa["last_active_drawing"].get("properties", {})
        distrito_click = props.get("distrito")
        if distrito_click and distrito_click != st.session_state.distrito_seleccionado:
            st.session_state.distrito_seleccionado = distrito_click
            st.session_state.pagina_tweets = 0
            st.rerun()

with col_resumen:
    st.markdown("### 📍 Resumen del distrito")
    if distrito_actual == "Todos":
        st.info("Selecciona un distrito en el mapa o en el sidebar para ver su detalle.")
        # Top 10 distritos más afectados para el tema actual
        top10 = df_tema.sort_values("sentimiento_negativo", ascending=False).head(10)
        fig_bar = px.bar(
            top10.sort_values("sentimiento_negativo"),
            x="sentimiento_negativo",
            y="distrito",
            orientation="h",
            color="sentimiento_negativo",
            color_continuous_scale=["#1C8EB0", "#E1A63A", "#D64550"],
            labels={"sentimiento_negativo": "% Negativo", "distrito": ""},
            title="Top 10 distritos más afectados",
        )
        fig_bar.update_layout(height=380, margin=dict(l=10, r=10, t=40, b=10), coloraxis_showscale=False)
        st.plotly_chart(fig_bar, width='stretch')
    else:
        fila = df_tema[df_tema["distrito"] == distrito_actual].iloc[0]
        color_badge = color_por_sentimiento(fila["sentimiento_negativo"])
        st.markdown(
            f"""
            <div class="kpi-card" style="text-align:left;">
                <h4 style="margin-top:0;">{distrito_actual}</h4>
                <p style="margin:4px 0;">Tema: <b>{tema_actual}</b></p>
                <p style="margin:4px 0;">
                    Sentimiento negativo:
                    <span class="badge" style="background-color:{color_badge};">
                        {fila['sentimiento_negativo']:.1f}%
                    </span>
                </p>
                <p style="margin:4px 0;">N° de tweets: <b>{int(fila['num_tweets']):,}</b></p>
            </div>
            """,
            unsafe_allow_html=True,
        )

        # Comparativo del distrito en los 4 temas
        comp = df_resumen[df_resumen["distrito"] == distrito_actual]
        fig_comp = px.bar(
            comp,
            x="tema",
            y="sentimiento_negativo",
            color="sentimiento_negativo",
            color_continuous_scale=["#1C8EB0", "#E1A63A", "#D64550"],
            labels={"sentimiento_negativo": "% Negativo", "tema": ""},
            title=f"{distrito_actual}: comparativo por tema",
        )
        fig_comp.update_xaxes(tickangle=25)
        fig_comp.update_layout(height=340, margin=dict(l=10, r=10, t=40, b=10), coloraxis_showscale=False)
        st.plotly_chart(fig_comp, width='stretch')

        if st.button("✖ Quitar selección de distrito", width='stretch'):
            st.session_state.distrito_seleccionado = "Todos"
            st.session_state.pagina_tweets = 0
            st.rerun()

# ==============================================================================
# 10. SECCIÓN DE TWEETS CON PAGINACIÓN
# ==============================================================================

st.markdown("---")
titulo_tweets = f"### 💬 Tweets — {tema_actual}"
if distrito_actual != "Todos":
    titulo_tweets += f" en {distrito_actual}"
st.markdown(titulo_tweets)
st.caption(f"Mostrando hasta 100 tweets más recientes según los filtros aplicados ({len(df_tweets_filtrado)} encontrados).")

TWEETS_POR_PAGINA = 10
total_tweets_filtrados = len(df_tweets_filtrado)
total_paginas = max(1, math.ceil(total_tweets_filtrados / TWEETS_POR_PAGINA))

# Aseguramos que la página actual sea válida tras cambios de filtro
if st.session_state.pagina_tweets >= total_paginas:
    st.session_state.pagina_tweets = total_paginas - 1
if st.session_state.pagina_tweets < 0:
    st.session_state.pagina_tweets = 0

inicio = st.session_state.pagina_tweets * TWEETS_POR_PAGINA
fin = inicio + TWEETS_POR_PAGINA
pagina_actual_df = df_tweets_filtrado.iloc[inicio:fin]

badge_clase = {
    "negativo": "badge-negativo",
    "neutral": "badge-neutral",
    "positivo": "badge-positivo",
}

if total_tweets_filtrados == 0:
    st.warning("No hay tweets para esta combinación de filtros.")
else:
    for _, tw in pagina_actual_df.iterrows():
        st.markdown(
            f"""
            <div class="tweet-card">
                <div>{tw['texto']}</div>
                <div class="tweet-meta">
                    <span class="badge {badge_clase[tw['sentimiento']]}">{tw['sentimiento'].capitalize()}</span>
                    &nbsp;·&nbsp; {tw['usuario']} &nbsp;·&nbsp; {tw['distrito']}
                    &nbsp;·&nbsp; {tw['fecha'].strftime('%d/%m/%Y %H:%M')}
                    &nbsp;·&nbsp; ❤ {tw['likes']}
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    # --- Controles de paginación ---
    c_prev, c_info, c_next = st.columns([1, 2, 1])
    with c_prev:
        if st.button("⬅ Anterior", disabled=st.session_state.pagina_tweets == 0, width='stretch'):
            st.session_state.pagina_tweets -= 1
            st.rerun()
    with c_info:
        st.markdown(
            f"<div style='text-align:center; padding-top:8px;'>Página "
            f"<b>{st.session_state.pagina_tweets + 1}</b> de <b>{total_paginas}</b></div>",
            unsafe_allow_html=True,
        )
    with c_next:
        if st.button("Siguiente ➡", disabled=st.session_state.pagina_tweets >= total_paginas - 1, width='stretch'):
            st.session_state.pagina_tweets += 1
            st.rerun()

# ==============================================================================
# 11. PIE DE PÁGINA
# ==============================================================================

st.markdown("---")
st.caption(
    "Datos sintéticos generados con fines de demostración. "
    "Dashboard de análisis de sentimiento ciudadano — problemas ambientales en Lima Metropolitana."
)
