from flask import Flask, jsonify
import requests
from datetime import datetime, timezone

app = Flask(__name__)

API_KEY = '2c92f59a-bec1-11ed-a654-0242ac130002-2c92f644-bec1-11ed-a654-0242ac130002'

# Huia / Manukau Harbour
LAT1, LNG1 = -36.691489, 174.973523
# Marine location (offshore)
LAT2, LNG2 = -36.421667, 175.333

def is_today(timestamp):
    today = datetime.now(timezone.utc).date()
    entry_date = datetime.fromisoformat(timestamp.replace("Z", "+00:00")).date()
    return entry_date == today

@app.route('/weather-info', methods=['GET'])
def get_weather_info():
    headers = {'Authorization': API_KEY}
    results = {
        'high_tide': [],
        'low_tide': [],
        'wind': [],
        'sunrise': None,
        'sunset': None,
        'swell_height_today': []
    }

    # 🌊 Tide extremes
    tide_url = 'https://api.stormglass.io/v2/tide/extremes/point'
    tide_params = {'lat': LAT1, 'lng': LNG1, 'datum': 'MLLW'}
    tide_response = requests.get(tide_url, headers=headers, params=tide_params)
    tide_data = tide_response.json()

    for entry in tide_data.get('data', []):
        if is_today(entry['time']):
            tide_info = {'time': entry['time'], 'height': round(entry['height'], 2)}
            if entry['type'] == 'high':
                results['high_tide'].append(tide_info)
            elif entry['type'] == 'low':
                results['low_tide'].append(tide_info)

    # 🌬️ Wind data (Huia)
    weather_url = 'https://api.stormglass.io/v2/weather/point'
    weather_params = {
        'lat': LAT1,
        'lng': LNG1,
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
        'lat': LAT1,
        'lng': LNG1,
        'date': datetime.now(timezone.utc).date().isoformat()
    }
    astro_response = requests.get(astro_url, headers=headers, params=astro_params)
    astro_data = astro_response.json()

    if 'data' in astro_data and len(astro_data['data']) > 0:
        astro = astro_data['data'][0]
        results['sunrise'] = astro.get('sunrise')
        results['sunset'] = astro.get('sunset')

    # 🌊 Swell height (offshore)
    marine_params = {
        'lat': LAT2,
        'lng': LNG2,
        'params': 'swellHeight',
        'source': 'sg'
    }
    marine_response = requests.get(weather_url, headers=headers, params=marine_params)
    marine_data = marine_response.json()

    for entry in marine_data.get('hours', []):
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