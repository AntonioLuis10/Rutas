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
            
            # Petición a Google Maps (incluyendo la lógica de evitar peajes si la casilla existe)
            try:
                if 'evitar_peajes' in locals() and evitar_peajes:
                    directions = gmaps.directions(origen, destino, mode="driving", avoid="tolls")
                else:
                    directions = gmaps.directions(origen, destino, mode="driving")
            except Exception as e:
                st.error(f"Error con Google Maps: {e}")
                st.stop()

            if not directions:
                st.error("No se encontró una ruta entre esos puntos.")
            else:
                pasos = directions[0]['legs'][0]['steps']
                elevacion_total = 0
                
                st.subheader("Resultados de la Telemetría de Alta Resolución")
                
                # --- 1. PREPARACIÓN DE LA RUTA GEOMÉTRICA ---
                poly_str = directions[0]['overview_polyline']['points']
                ruta_coords = googlemaps.convert.decode_polyline(poly_str)
                lats = [punto['lat'] for punto in ruta_coords]
                lngs = [punto['lng'] for punto in ruta_coords]
                
                # --- 2. CÁLCULO CONTINUO PARA GRÁFICAS (150 Puntos) ---
                muestras = 150  # Un punto en la gráfica aprox. cada 2 km en rutas largas
                datos_elevacion = gmaps.elevation_along_path(poly_str, samples=muestras)
                
                distancia_total_km = directions[0]['legs'][0]['distance']['value'] / 1000.0
                dist_por_muestra = distancia_total_km / (muestras - 1)
                
                x_dist = []
                y_elev = []
                y_wind = []
                
                dist_clima_acumulada = 1000 # Forzamos la lectura de Open-Meteo en el punto 0
                FRECUENCIA_CLIMA_KM = 330  
                vel_viento_actual, dir_viento_actual = 0, 0
                elevacion_total = 0
                
                for i in range(muestras):
                    lat = datos_elevacion[i]['location']['lat']
                    lon = datos_elevacion[i]['location']['lng']
                    elev = datos_elevacion[i]['elevation']
                    
                    dist_acumulada = i * dist_por_muestra
                    x_dist.append(dist_acumulada)
                    y_elev.append(elev)
                    
                    # Sumar desnivel positivo continuo
                    if i > 0:
                        desnivel = max(0, elev - y_elev[i-1])
                        elevacion_total += desnivel
                        
                    # Rumbo (bearing) de alta resolución entre puntos cercanos
                    if i < muestras - 1:
                        next_lat = datos_elevacion[i+1]['location']['lat']
                        next_lon = datos_elevacion[i+1]['location']['lng']
                        bearing = calcular_bearing(lat, lon, next_lat, next_lon)
                    else:
                        prev_lat = datos_elevacion[i-1]['location']['lat']
                        prev_lon = datos_elevacion[i-1]['location']['lng']
                        bearing = calcular_bearing(prev_lat, prev_lon, lat, lon)
                    
                    # Caché meteorológica: consulta Open-Meteo solo cada 12 km
                    if dist_clima_acumulada >= FRECUENCIA_CLIMA_KM:
                        tiempo_horas = dist_acumulada / vel_media
                        hora_estimada = hora_actual_ruta + timedelta(hours=tiempo_horas)
                        vel_viento_actual, dir_viento_actual = obtener_datos_viento_futuro(lat, lon, hora_estimada)
                        dist_clima_acumulada = 0
                    
                    dist_clima_acumulada += dist_por_muestra
                    
                    # El ángulo relativo se calcula SIEMPRE, adaptándose a las curvas
                    angulo_relativo = math.radians(dir_viento_actual - bearing)
                    viento_en_contra = vel_viento_actual * math.cos(angulo_relativo)
                    y_wind.append(viento_en_contra)

                # --- 3. DIBUJAR LA GRÁFICA INTERACTIVA ---
                fig = make_subplots(specs=[[{"secondary_y": True}]])
                # shape='spline' suaviza las líneas para un acabado más profesional
                fig.add_trace(go.Scatter(x=x_dist, y=y_elev, name="Elevación (m)", fill='tozeroy', mode='lines', line=dict(color='rgba(150, 150, 150, 0.8)', shape='spline')), secondary_y=False)
                fig.add_trace(go.Scatter(x=x_dist, y=y_wind, name="Viento en contra (km/h)", mode='lines', line=dict(color='red', width=2, shape='spline')), secondary_y=True)
                
                fig.update_layout(title_text="Telemetría Continua: Elevación vs Viento", hovermode="x unified")
                fig.update_xaxes(title_text="Distancia recorrida (km)")
                fig.update_yaxes(title_text="Elevación (m)", secondary_y=False)
                fig.update_yaxes(title_text="Viento (km/h) [+ Contra / - A favor]", secondary_y=True)
                
                st.plotly_chart(fig, use_container_width=True)

                # --- 4. MAPA CON HOVER SINCRONIZADO ---
                hover_texts = []
                puntos_por_tramo = max(1, len(lats) // muestras)
                for i in range(len(lats)):
                    idx_aprox = min(i // puntos_por_tramo, muestras - 1)
                    viento_redondeado = round(y_wind[idx_aprox], 1)
                    tipo_viento_hover = "Viento en contra" if viento_redondeado > 0 else "Viento a favor"
                    
                    texto = (f"📍 Elevación: {round(y_elev[idx_aprox], 1)}m<br>"
                             f"💨 {tipo_viento_hover}: {abs(viento_redondeado)} km/h<br>"
                             f"📏 Km estimado: {round(x_dist[idx_aprox], 1)}")
                    hover_texts.append(texto)

                fig_mapa = go.Figure(go.Scattermap(
                    mode="lines+markers",
                    lon=lngs,
                    lat=lats,
                    line=dict(width=4, color='#E50914'),
                    marker=dict(size=4, opacity=0),
                    name="Ruta",
                    text=hover_texts,
                    hoverinfo="text"
                ))
                
                fig_mapa.update_layout(
                    title_text="Mapa Interactivo de la Ruta",
                    map_style="open-street-map",
                    map_zoom=6.5,
                    map_center={"lat": sum(lats)/len(lats), "lon": sum(lngs)/len(lngs)},
                    margin={"r":0, "t":40, "l":0, "b":0},
                    height=500
                )
                st.plotly_chart(fig_mapa, use_container_width=True)
                
                # --- 5. TEXTOS DESPLEGABLES (Navegación pura) ---
                st.markdown("### Detalles por tramo")
                hora_paso_actual = hora_actual_ruta
                for paso in pasos:
                    distancia_km = paso['distance']['value'] / 1000.0
                    tiempo_tramo_horas = distancia_km / vel_media
                    instruccion_limpia = re.sub(r'<[^>]+>', '', paso['html_instructions'])
                    
                    with st.expander(f"⏱️ {hora_paso_actual.strftime('%H:%M')} | {instruccion_limpia} ({paso['distance']['text']})"):
                        st.markdown(f"**Indicación GPS:** Continúa por esta vía durante {paso['distance']['text']}.")
                    
                    hora_paso_actual += timedelta(hours=tiempo_tramo_horas)
                
                st.success(f"**Desnivel positivo total:** {round(elevacion_total, 1)} m | **Hora estimada de llegada:** {hora_paso_actual.strftime('%H:%M')}")
