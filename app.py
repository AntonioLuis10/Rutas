import streamlit as st
import googlemaps
import requests
import math
import re
from datetime import datetime, timedelta
import plotly.graph_objects as go
from plotly.subplots import make_subplots

# 1. Configuración de la página
st.set_page_config(page_title="Telemetría de Ruta", page_icon="🚴")
st.title("Estimador de Consumo y Viento por Tramos")

# 2. Cargar API Key de forma segura desde los secretos de Streamlit
try:
    GMAPS_API_KEY = st.secrets["GMAPS_API_KEY"]
except KeyError:
    st.error("Falta configurar la GMAPS_API_KEY en los Secrets de Streamlit.")
    st.stop()

gmaps = googlemaps.Client(key=GMAPS_API_KEY)

# --- FUNCIONES AUXILIARES ---
def calcular_bearing(lat1, lon1, lat2, lon2):
    lat1, lon1, lat2, lon2 = map(math.radians, [lat1, lon1, lat2, lon2])
    dlon = lon2 - lon1
    x = math.sin(dlon) * math.cos(lat2)
    y = math.cos(lat1) * math.sin(lat2) - (math.sin(lat1) * math.cos(lat2) * math.cos(dlon))
    initial_bearing = math.atan2(x, y)
    return (math.degrees(initial_bearing) + 360) % 360

def redondear_hora(dt):
    if dt.minute >= 30:
        dt += timedelta(hours=1)
    return dt.replace(minute=0, second=0, microsecond=0)

def obtener_datos_viento_futuro(lat, lon, hora_estimada):
    url = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&hourly=windspeed_10m,winddirection_10m&timezone=auto"
    response = requests.get(url).json()
    if 'hourly' in response:
        tiempos = response['hourly']['time']
        hora_redondeada = redondear_hora(hora_estimada)
        hora_str = hora_redondeada.strftime('%Y-%m-%dT%H:00')
        try:
            indice = tiempos.index(hora_str)
            return response['hourly']['windspeed_10m'][indice], response['hourly']['winddirection_10m'][indice]
        except ValueError:
            return 0, 0
    return 0, 0

# --- INTERFAZ DE USUARIO ---
col1, col2 = st.columns(2)
with col1:
    origen = st.text_input("Origen", placeholder="Ej. València")
    fecha_salida = st.date_input("Fecha de salida", datetime.today())
with col2:
    destino = st.text_input("Destino", placeholder="Ej. Cullera")
    hora_salida_input = st.time_input("Hora de salida", datetime.now().time())

vel_media = st.number_input("Velocidad media estimada (km/h)", min_value=1.0, value=25.0, step=1.0)
evitar_peajes = st.checkbox("Evitar peajes de pago", value=False)

# --- BOTÓN Y LÓGICA DE CÁLCULO ---
if st.button("Analizar Ruta Dinámica", type="primary"):
    if not origen or not destino:
        st.warning("Por favor, introduce origen y destino.")
    else:
        with st.spinner('Calculando tiempos, elevación y vectores aerodinámicos...'):
            hora_actual_ruta = datetime.combine(fecha_salida, hora_salida_input)
            
            try:
                if evitar_peajes:
                    directions = gmaps.directions(origen, destino, mode="driving", avoid="tolls")
                else:
                    directions = gmaps.directions(origen, destino, mode="driving")
            except Exception as e:
                st.error(f"Error con Google Maps: {e}")
                st.stop()

            if not directions:
                st.error("No se encontró una ruta ciclista entre esos puntos.")
            else:
                pasos = directions[0]['legs'][0]['steps']
                elevacion_total = 0
                
                st.subheader("Resultados de la Telemetría")
                
                # --- DIBUJAR EL MAPA DE LA RUTA ---
                # Extraer y decodificar la línea geométrica de la ruta
                ruta_coords = googlemaps.convert.decode_polyline(directions[0]['overview_polyline']['points'])
                lats = [punto['lat'] for punto in ruta_coords]
                lngs = [punto['lng'] for punto in ruta_coords]
                
                # Crear el mapa con Plotly usando el nuevo motor Scattermap
                fig_mapa = go.Figure(go.Scattermap(
                    mode="lines",
                    lon=lngs,
                    lat=lats,
                    line=dict(width=5, color='#E50914'),
                    name="Ruta"
                ))
                
                # Configurar la vista del mapa con los nuevos parámetros
                fig_mapa.update_layout(
                    map_style="open-street-map",
                    map_zoom=6.5,
                    map_center={"lat": sum(lats)/len(lats), "lon": sum(lngs)/len(lngs)},
                    margin={"r":0, "t":0, "l":0, "b":0},
                    height=450
                )
                
                
                # --- VARIABLES PARA LA GRÁFICA ---
                # (Aquí continúa el código que ya tenías: x_dist = [0], y_elev = [], etc.)
                
                # Resumen final
                st.success(f"**Desnivel positivo total:** {round(elevacion_total, 1)} m | **Hora estimada de llegada:** {hora_actual_ruta.strftime('%H:%M')}")
