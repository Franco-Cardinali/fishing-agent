import logging
from flask import Flask, jsonify, request
import requests
from datetime import datetime, timedelta, timezone
from timezonefinder import TimezoneFinder
import pytz


# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler("app.log"),
        logging.StreamHandler()
    ]
)


app = Flask(__name__)

API_KEY = '2c92f59a-bec1-11ed-a654-0242ac130002-2c92f644-bec1-11ed-a654-0242ac130002'

# In-memory cache by lat/lng per day range
daily_cache_by_coords = {}

def convert_to_local_time(utc_time_str, lat, lng):
    tf = TimezoneFinder()
    tz_name = tf.timezone_at(lat=lat, lng=lng)
    if not tz_name:
        tz_name = 'Pacific/Auckland'  # fallback
    local_tz = pytz.timezone(tz_name)
    utc_dt = datetime.fromisoformat(utc_time_str.replace("Z", "+00:00"))
    local_dt = utc_dt.astimezone(local_tz)
    return local_dt

def get_coordinates(location_name):
    url = "https://nominatim.openstreetmap.org/search"
    params = {'q': location_name, 'format': 'json', 'limit': 1}
    response = requests.get(url, params=params, headers={'User-Agent': 'weather-agent'})
    data = response.json()
    if data:
        return float(data[0]['lat']), float(data[0]['lon'])
    return None, None

@app.route('/weather-info', methods=['GET'])
def get_weather_info():
    location = request.args.get('location', default='Huia', type=str)
    days = request.args.get('days', default=1, type=int)
    days = max(1, min(days, 7))

    lat, lng = get_coordinates(location)
    if lat is None or lng is None:
        return jsonify({'error': f'Could not resolve location: {location}'}), 400
    today = datetime.now(timezone.utc).date()
    start = today.isoformat()
    end_date = today + timedelta(days=days)
    end = end_date.isoformat()
    cache_key = f"{lat}_{lng}_{start}_{end}"

    if cache_key in daily_cache_by_coords:
        print(f"Using cached data for {cache_key}")
        return jsonify(daily_cache_by_coords[cache_key])

    headers = {'Authorization': API_KEY}
    results = {
        'coordinates': {'lat': lat, 'lng': lng},
        'location': location,
        'forecast': {}
    }

    #Initialize forecast dictionary for each day
    for i in range(days):
        date = today + timedelta(days=i)
        date_str = date.isoformat()
        results['forecast'][date_str] = {
            'high_tide': [],
            'low_tide': [],
            'sunrise': None,
            'sunset': None,
            'moon': {},
            'moon_phase': None,
            'swell_height': [],
            'wind': []
        }

    # Tide extremes
    tide_url = 'https://api.stormglass.io/v2/tide/extremes/point'
    tide_params = {'lat': lat, 'lng': lng, 'datum': 'MLLW', 'start': start, 'end': end}
    tide_response = requests.get(tide_url, headers=headers, params=tide_params)
    logging.info(f"Tide API status: {tide_response.status_code}")

    if tide_response.status_code != 200:
        logging.error(f"Tide API failed: {tide_response.text}")

    tide_data = tide_response.json()
    for entry in tide_data.get('data', []):
        local_dt = convert_to_local_time(entry['time'], lat, lng)
        date_str = local_dt.date().isoformat()
        tide_info = {
            'time': local_dt.strftime('%Y-%m-%d %H:%M %Z'),
            'height': round(entry['height'], 2)
        }
        if entry['type'] == 'high':
            results['forecast'][date_str]['high_tide'].append(tide_info)
        elif entry['type'] == 'low':
            results['forecast'][date_str]['low_tide'].append(tide_info)

    #Wind data
    weather_url = 'https://api.stormglass.io/v2/weather/point'
    weather_params = {
        'lat': lat,
        'lng': lng,
        'params': 'windDirection,windSpeed',
        'source': 'noaa',
        'start': start,
        'end': end
    }
    weather_response = requests.get(weather_url, headers=headers, params=weather_params)

    logging.info(f"Weather API status: {weather_response.status_code}")
    if weather_response.status_code != 200:
        logging.error(f"Weather API failed: {weather_response.text}")

    weather_data = weather_response.json()
    for entry in weather_data.get('hours', []):
        local_dt = convert_to_local_time(entry['time'], lat, lng)
        date_str = local_dt.date().isoformat()
        wind_speed = entry.get('windSpeed', {}).get('noaa')
        wind_dir = entry.get('windDirection', {}).get('noaa')
        if wind_speed is not None and wind_dir is not None:
            results['forecast'][date_str]['wind'].append({
                'time': local_dt.strftime('%Y-%m-%d %H:%M %Z'),
                'speed_kmh': round(wind_speed * 3.6, 2),
                'direction_deg': wind_dir
            })

    #Astronomy: sunrise, sunset, moonrise, moonset, moon phase
    for i in range(days):
        date = today + timedelta(days=i)
        date_str = date.isoformat()
        astro_url = 'https://api.stormglass.io/v2/astronomy/point'
        astro_params = {'lat': lat, 'lng': lng, 'date': date_str}
        astro_response = requests.get(astro_url, headers=headers, params=astro_params)

        logging.info(f"Astronomy API status ({date_str}): {astro_response.status_code}")
        if astro_response.status_code != 200:
            logging.error(f"Astronomy API failed: {astro_response.text}")

        astro_data = astro_response.json()
        if 'data' in astro_data and len(astro_data['data']) > 0:
            astro = astro_data['data'][0]
            if astro.get('sunrise'):
                results['forecast'][date_str]['sunrise'] = convert_to_local_time(astro.get('sunrise'), lat, lng).strftime('%Y-%m-%d %H:%M %Z')
            if astro.get('sunset'):
                results['forecast'][date_str]['sunset'] = convert_to_local_time(astro.get('sunset'), lat, lng).strftime('%Y-%m-%d %H:%M %Z')
            if astro.get('moonrise'):
                results['forecast'][date_str]['moon']['rise'] = convert_to_local_time(astro.get('moonrise'), lat, lng).strftime('%Y-%m-%d %H:%M %Z')
            if astro.get('moonset'):
                results['forecast'][date_str]['moon']['set'] = convert_to_local_time(astro.get('moonset'), lat, lng).strftime('%Y-%m-%d %H:%M %Z')
            if astro.get('moonPhase'):
                results['forecast'][date_str]['moon_phase'] = astro.get('moonPhase')

    #Swell height
    swell_params = {
        'lat': lat,
        'lng': lng,
        'params': 'swellHeight',
        'source': 'noaa',
        'start': start,
        'end': end
    }
    swell_response = requests.get(weather_url, headers=headers, params=swell_params)

    logging.info(f"Swell API status: {swell_response.status_code}")
    if swell_response.status_code != 200:
        logging.error(f"Swell API failed: {swell_response.text}")

    swell_data = swell_response.json()
    for entry in swell_data.get('hours', []):
        local_dt = convert_to_local_time(entry['time'], lat, lng)
        date_str = local_dt.date().isoformat()
        swell_height = entry.get('swellHeight', {}).get('noaa')
        if swell_height is not None:
            results['forecast'][date_str]['swell_height'].append({
                'time': local_dt.strftime('%Y-%m-%d %H:%M %Z'),
                'height_m': round(swell_height, 2)
            })

    daily_cache_by_coords[cache_key] = results
    print(f"Cached new data for {cache_key}")
    return jsonify(results)

if __name__ == '__main__':
    app.run(debug=True, host='127.0.0.1', port=5050)
