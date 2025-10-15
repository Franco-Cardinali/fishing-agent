from flask import Flask, jsonify, request
import requests
from datetime import datetime, timezone

app = Flask(__name__)

API_KEY = '2c92f59a-bec1-11ed-a654-0242ac130002-2c92f644-bec1-11ed-a654-0242ac130002'

def is_today(timestamp):
    today = datetime.now(timezone.utc).date()
    entry_date = datetime.fromisoformat(timestamp.replace("Z", "+00:00")).date()
    return entry_date == today

def get_coordinates(location_name):
    url = "https://nominatim.openstreetmap.org/search"
    params = {
        'q': location_name,
        'format': 'json',
        'limit': 1
    }
    response = requests.get(url, params=params, headers={'User-Agent': 'weather-agent'})
    data = response.json()
    if data:
        return float(data[0]['lat']), float(data[0]['lon'])
    return None, None

@app.route('/weather-info', methods=['GET'])
def get_weather_info():
    location = request.args.get('location', default='Huia', type=str)
    lat, lng = get_coordinates(location)
    if lat is None or lng is None:
        return jsonify({'error': f'Could not resolve location: {location}'}), 400

    headers = {'Authorization': API_KEY}
    results = {
        'location': location,
        'coordinates': {'lat': lat, 'lng': lng},
        'high_tide': [],
        'low_tide': [],
        'wind': [],
        'sunrise': None,
        'sunset': None,
        'swell_height_today': []
    }

    # 🌊 Tide extremes
    tide_url = 'https://api.stormglass.io/v2/tide/extremes/point'
    tide_params = {'lat': lat, 'lng': lng, 'datum': 'MLLW'}
    tide_response = requests.get(tide_url, headers=headers, params=tide_params)
    tide_data = tide_response.json()

    for entry in tide_data.get('data', []):
        if is_today(entry['time']):
            tide_info = {'time': entry['time'], 'height': round(entry['height'], 2)}
            if entry['type'] == 'high':
                results['high_tide'].append(tide_info)
            elif entry['type'] == 'low':
                results['low_tide'].append(tide_info)

    # 🌬️ Wind data
    weather_url = 'https://api.stormglass.io/v2/weather/point'
    weather_params = {
        'lat': lat,
        'lng': lng,
        'params': 'windDirection,windSpeed',
        'source': 'noaa'
    }
    weather_response = requests.get(weather_url, headers=headers, params=weather_params)
    weather_data = weather_response.json()

    for entry in weather_data.get('hours', []):
        if is_today(entry['time']):
            wind_speed = entry.get('windSpeed', {}).get('noaa')
            wind_dir = entry.get('windDirection', {}).get('noaa')
            if wind_speed is not None and wind_dir is not None:
                results['wind'].append({
                    'time': entry['time'],
                    'speed_kmh': round(wind_speed * 3.6, 2),
                    'direction_deg': wind_dir
                })

    # 🌅 Sunrise/sunset
    astro_url = 'https://api.stormglass.io/v2/astronomy/point'
    astro_params = {
        'lat': lat,
        'lng': lng,
        'date': datetime.now(timezone.utc).date().isoformat()
    }
    astro_response = requests.get(astro_url, headers=headers, params=astro_params)
    astro_data = astro_response.json()

    if 'data' in astro_data and len(astro_data['data']) > 0:
        astro = astro_data['data'][0]
        results['sunrise'] = astro.get('sunrise')
        results['sunset'] = astro.get('sunset')

    # 🌊 Swell height (using same location)
    swell_params = {
        'lat': lat,
        'lng': lng,
        'params': 'swellHeight',
        'source': 'sg'
    }
    swell_response = requests.get(weather_url, headers=headers, params=swell_params)
    swell_data = swell_response.json()

    for entry in swell_data.get('hours', []):
        if is_today(entry['time']):
            swell_height = entry.get('swellHeight', {}).get('sg')
            if swell_height is not None:
                results['swell_height_today'].append({
                    'time': entry['time'],
                    'height_m': round(swell_height, 2)
                })

    return jsonify(results)

if __name__ == '__main__':
    app.run(debug=True, host='127.0.0.1', port=5050)
