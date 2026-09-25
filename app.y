from flask import Flask, render_template, request, jsonify
import googlemaps
import requests
import math

app = Flask(__name__)

# Configura tu clave de API de Google Maps aquí
GMAPS_API_KEY = 'TU_API_KEY_DE_GOOGLE_MAPS'
gmaps = googlemaps.Client(key=GMAPS_API_KEY)

def calcular_bearing(lat1, lon1, lat2, lon2):
    """Calcula el rumbo (bearing) de un punto a otro en grados."""
    lat1, lon1, lat2, lon2 = map(math.radians, [lat1, lon1, lat2, lon2])
    dlon = lon2 - lon1
    x = math.sin(dlon) * math.cos(lat2)
    y = math.cos(lat1) * math.sin(lat2) - (math.sin(lat1) * math.cos(lat2) * math.cos(dlon))
    initial_bearing = math.atan2(x, y)
    return (math.degrees(initial_bearing) + 360) % 360

def obtener_datos_viento(lat, lon):
    """Obtiene la velocidad y dirección del viento actual usando Open-Meteo."""
    url = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&current_weather=true"
    response = requests.get(url).json()
    if 'current_weather' in response:
        return (response['current_weather']['windspeed'], 
                response['current_weather']['winddirection'])
    return 0, 0

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/analizar_ruta', methods=['POST'])
def analizar_ruta():
    datos = request.json
    origen = datos['origen']
    destino = datos['destino']

    # 1. Obtener la ruta de Google Maps
    directions = gmaps.directions(origen, destino, mode="bicycling")
    if not directions:
        return jsonify({"error": "No se encontró la ruta"}), 400

    pasos = directions[0]['legs'][0]['steps']
    tramos_analizados = []
    elevacion_total = 0

    for paso in pasos:
        lat1, lon1 = paso['start_location']['lat'], paso['start_location']['lng']
        lat2, lon2 = paso['end_location']['lat'], paso['end_location']['lng']
        
        # 2. Calcular Rumbo (Bearing) del tramo
        bearing = calcular_bearing(lat1, lon1, lat2, lon2)
        
        # 3. Obtener el viento en el punto medio del tramo
        lat_media, lon_media = (lat1 + lat2) / 2, (lon1 + lon2) / 2
        vel_viento, dir_viento = obtener_datos_viento(lat_media, lon_media)
        
        # 4. Cálculo Vectorial del Viento
        # En meteorología, la dirección es de dónde VIENE el viento. 
        # Si el bearing y la dirección del viento coinciden, el ángulo es 0 = Viento en contra puro.
        angulo_relativo = math.radians(dir_viento - bearing)
        
        viento_en_contra = vel_viento * math.cos(angulo_relativo)
        viento_lateral = vel_viento * math.sin(angulo_relativo)

        # 5. Obtener desnivel del tramo (Elevación)
        coords = [(lat1, lon1), (lat2, lon2)]
        elevation_data = gmaps.elevation(coords)
        desnivel_tramo = elevation_data[1]['elevation'] - elevation_data[0]['elevation']
        elevacion_total += max(0, desnivel_tramo) # Sumar solo subidas

        # Clasificación del tramo para el consumo
        estado_terreno = "Subida" if desnivel_tramo > 2 else "Bajada" if desnivel_tramo < -2 else "Llano"
        
        tramos_analizados.append({
            "instruccion": paso['html_instructions'],
            "distancia": paso['distance']['text'],
            "estado_terreno": estado_terreno,
            "desnivel_metros": round(desnivel_tramo, 1),
            "viento_en_contra_kmh": round(viento_en_contra, 1), # Positivo: en contra, Negativo: a favor
            "viento_lateral_kmh": round(abs(viento_lateral), 1)
        })

    return jsonify({
        "desnivel_acumulado": round(elevacion_total, 1),
        "tramos": tramos_analizados
    })

if __name__ == '__main__':
    app.run(debug=True)
