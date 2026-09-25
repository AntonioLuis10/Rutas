import streamlit as st
import googlemaps
import requests
import math
import re
from datetime import datetime, timedelta

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

# --- BOTÓN Y LÓGICA DE CÁLCULO ---
if st.button("Analizar Ruta Dinámica", type="primary"):
    if not origen or not destino:
        st.warning("Por favor, introduce origen y destino.")
    else:
        with st.spinner('Calculando tiempos, elevación y vectores aerodinámicos...'):
            hora_actual_ruta = datetime.combine(fecha_salida, hora_salida_input)
            
            try:
                directions = gmaps.directions(origen, destino, mode="bicycling")
            except Exception as e:
                st.error(f"Error con Google Maps: {e}")
                st.stop()

            if not directions:
                st.error("No se encontró una ruta ciclista entre esos puntos.")
            else:
                pasos = directions[0]['legs'][0]['steps']
                elevacion_total = 0
                
                st.subheader("Resultados de la Telemetría")
                
                for i, paso in enumerate(pasos):
                    lat1, lon1 = paso['start_location']['lat'], paso['start_location']['lng']
                    lat2, lon2 = paso['end_location']['lat'], paso['end_location']['lng']
                    
                    # Cálculo de tiempos
                    distancia_km = paso['distance']['value'] / 1000.0
                    tiempo_tramo_horas = distancia_km / vel_media
                    hora_mitad_tramo = hora_actual_ruta + timedelta(hours=tiempo_tramo_horas / 2)
                    
                    # Cálculos físicos y meteorológicos
                    bearing = calcular_bearing(lat1, lon1, lat2, lon2)
                    vel_viento, dir_viento = obtener_datos_viento_futuro((lat1+lat2)/2, (lon1+lon2)/2, hora_mitad_tramo)
                    
                    angulo_relativo = math.radians(dir_viento - bearing)
                    viento_en_contra = vel_viento * math.cos(angulo_relativo)
                    viento_lateral = vel_viento * math.sin(angulo_relativo)
                    
                    # Elevación
                    coords = [(lat1, lon1), (lat2, lon2)]
                    elevation_data = gmaps.elevation(coords)
                    desnivel_tramo = elevation_data[1]['elevation'] - elevation_data[0]['elevation']
                    elevacion_total += max(0, desnivel_tramo)
                    
                    estado_terreno = "Subida 📈" if desnivel_tramo > 2 else "Bajada 📉" if desnivel_tramo < -2 else "Llano ➖"
                    
                    # Limpiar etiquetas HTML que devuelve Google Maps
                    instruccion_limpia = re.sub(r'<[^>]+>', '', paso['html_instructions'])
                    
                    color_viento = "red" if viento_en_contra > 0 else "green"
                    tipo_viento = "en contra" if viento_en_contra > 0 else "a favor"
                    
                    # Mostrar tramo desplegable
                    with st.expander(f"⏱️ {hora_actual_ruta.strftime('%H:%M')} | {instruccion_limpia} ({paso['distance']['text']})"):
                        st.markdown(f"**🚵 Terreno:** {estado_terreno} (Desnivel: {round(desnivel_tramo, 1)}m)")
                        st.markdown(f"**🌬️ Aerodinámica:** <span style='color:{color_viento}'>Viento {tipo_viento}: {round(abs(viento_en_contra), 1)} km/h</span> | Viento lateral: {round(abs(viento_lateral), 1)} km/h", unsafe_allow_html=True)
                    
                    hora_actual_ruta += timedelta(hours=tiempo_tramo_horas)
                
                # Resumen final
                st.success(f"**Desnivel positivo total:** {round(elevacion_total, 1)} m | **Hora estimada de llegada:** {hora_actual_ruta.strftime('%H:%M')}")
