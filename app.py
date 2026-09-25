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
                
                st.subheader("Resultados de la Telemetría (Mapa Interactivo)")
                
                # --- 1. PREPARACIÓN DE VARIABLES GLOBALES ---
                ruta_coords = googlemaps.convert.decode_polyline(directions[0]['overview_polyline']['points'])
                lats = [punto['lat'] for punto in ruta_coords]
                lngs = [punto['lng'] for punto in ruta_coords]
                
                x_dist = [0]
                y_elev = []
                y_wind = [0]
                dist_acumulada = 0
                
                coord_inicio = (pasos[0]['start_location']['lat'], pasos[0]['start_location']['lng'])
                elev_inicio = gmaps.elevation([coord_inicio])[0]['elevation']
                y_elev.append(elev_inicio)
                
                distancia_desde_ultimo_clima = 0
                FRECUENCIA_CLIMA_KM = 12.0  
                vel_viento_actual = 0
                dir_viento_actual = 0
                tramos_ui = []
                
                # --- 2. PROCESAMIENTO TRAMO A TRAMO ---
                for i, paso in enumerate(pasos):
                    lat1, lon1 = paso['start_location']['lat'], paso['start_location']['lng']
                    lat2, lon2 = paso['end_location']['lat'], paso['end_location']['lng']
                    
                    distancia_km = paso['distance']['value'] / 1000.0
                    tiempo_tramo_horas = distancia_km / vel_media
                    hora_mitad_tramo = hora_actual_ruta + timedelta(hours=tiempo_tramo_horas / 2)
                    
                    if i == 0 or distancia_desde_ultimo_clima >= FRECUENCIA_CLIMA_KM:
                        vel_viento_actual, dir_viento_actual = obtener_datos_viento_futuro(
                            (lat1+lat2)/2, (lon1+lon2)/2, hora_mitad_tramo
                        )
                        distancia_desde_ultimo_clima = 0
                    
                    distancia_desde_ultimo_clima += distancia_km
                    
                    bearing = calcular_bearing(lat1, lon1, lat2, lon2)
                    angulo_relativo = math.radians(dir_viento_actual - bearing)
                    
                    viento_en_contra = vel_viento_actual * math.cos(angulo_relativo)
                    viento_lateral = vel_viento_actual * math.sin(angulo_relativo)
                    
                    coords = [(lat1, lon1), (lat2, lon2)]
                    elevation_data = gmaps.elevation(coords)
                    elevacion_final_tramo = elevation_data[1]['elevation']
                    desnivel_tramo = elevacion_final_tramo - elevation_data[0]['elevation']
                    elevacion_total += max(0, desnivel_tramo)
                    
                    # Guardar datos para la gráfica
                    dist_acumulada += distancia_km
                    x_dist.append(dist_acumulada)
                    y_elev.append(elevacion_final_tramo)
                    y_wind.append(viento_en_contra)
                    
                    # Formatear el texto de la interfaz
                    estado_terreno = "Subida 📈" if desnivel_tramo > 2 else "Bajada 📉" if desnivel_tramo < -2 else "Llano ➖"
                    instruccion_limpia = re.sub(r'<[^>]+>', '', paso['html_instructions'])
                    color_viento = "red" if viento_en_contra > 0 else "green"
                    tipo_viento = "en contra" if viento_en_contra > 0 else "a favor"
                    
                    tramo_html = {
                        "titulo": f"⏱️ {hora_actual_ruta.strftime('%H:%M')} | {instruccion_limpia} ({paso['distance']['text']})",
                        "terreno": f"**🚗 Terreno:** {estado_terreno} (Desnivel: {round(desnivel_tramo, 1)}m)",
                        "viento": f"**🌬️ Aerodinámica:** <span style='color:{color_viento}'>Viento {tipo_viento}: {round(abs(viento_en_contra), 1)} km/h</span> | Viento lateral: {round(abs(viento_lateral), 1)} km/h"
                    }
                    tramos_ui.append(tramo_html)
                    
                    hora_actual_ruta += timedelta(hours=tiempo_tramo_horas)
                
                # --- 3. DIBUJAR LA GRÁFICA INTERACTIVA ---
                fig = make_subplots(specs=[[{"secondary_y": True}]])
                fig.add_trace(go.Scatter(x=x_dist, y=y_elev, name="Elevación (m)", fill='tozeroy', mode='lines', line=dict(color='rgba(150, 150, 150, 0.8)')), secondary_y=False)
                fig.add_trace(go.Scatter(x=x_dist, y=y_wind, name="Viento en contra (km/h)", mode='lines', line=dict(color='red', width=2)), secondary_y=True)
                
                fig.update_layout(title_text="Telemetría: Elevación vs Resistencia Aerodinámica", hovermode="x unified")
                fig.update_xaxes(title_text="Distancia recorrida (km)")
                fig.update_yaxes(title_text="Elevación (m)", secondary_y=False)
                fig.update_yaxes(title_text="Viento (km/h) [+ Contra / - A favor]", secondary_y=True)
                
                st.plotly_chart(fig, use_container_width=True)

                # --- 4. MAPA CON HOVER DE DATOS EN LA RUTA ---
                # Alinear los datos interpolando (simplificado) para que coincidan con la ruta geométrica completa
                hover_texts = []
                # Distribuimos los datos a lo largo de los puntos del mapa de forma aproximada
                puntos_por_tramo = max(1, len(lats) // len(y_elev))
                for i in range(len(lats)):
                    idx_aprox = min(i // puntos_por_tramo, len(y_elev) - 1)
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
                    marker=dict(size=4, opacity=0), # Marcadores invisibles, solo sirven para captar el ratón
                    name="Ruta",
                    text=hover_texts,
                    hoverinfo="text"
                ))
                
                fig_mapa.update_layout(
                    title_text="Mapa de la Ruta (Pasa el cursor por encima de la línea)",
                    map_style="open-street-map",
                    map_zoom=6.5,
                    map_center={"lat": sum(lats)/len(lats), "lon": sum(lngs)/len(lngs)},
                    margin={"r":0, "t":40, "l":0, "b":0},
                    height=500
                )
                
                st.plotly_chart(fig_mapa, use_container_width=True)
                
                # --- 5. MOSTRAR LOS DESPLEGABLES DE LOS TRAMOS ---
                st.markdown("### Detalles por tramo")
                for tramo in tramos_ui:
                    with st.expander(tramo["titulo"]):
                        st.markdown(tramo["terreno"])
                        st.markdown(tramo["viento"], unsafe_allow_html=True)
                
                st.success(f"**Desnivel positivo total:** {round(elevacion_total, 1)} m | **Hora estimada de llegada:** {hora_actual_ruta.strftime('%H:%M')}")
