import logging
import time
from datetime import datetime, timedelta, timezone, time as dt_time
from flask import Flask, jsonify, request
import requests
from datetime import datetime, timedelta, timezone
from timezonefinder import TimezoneFinder
import pytz
import sys
from collections import OrderedDict
import json

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler("app.log"),
        logging.StreamHandler(sys.stdout)
    ]
)

def get_utc_shift_hours(lat, lng):
    tf = TimezoneFinder()
    tz_name = tf.timezone_at(lat=lat, lng=lng)
    if not tz_name:
        tz_name = 'Pacific/Auckland'
    local_tz = pytz.timezone(tz_name)
    now_utc = datetime.now(timezone.utc)
    local_dt = now_utc.astimezone(local_tz)
    offset = local_dt.utcoffset()
    return int(offset.total_seconds() // 3600)


def ensure_forecast_date(results, date_str):
    if date_str not in results['forecast']:
        results['forecast'][date_str] = {
            'high_tide': [],
            'low_tide': [],
            'sunrise': None,
            'sunset': None,
            'moon': {},
            'moon_phase': None,
            'swell_height': [],
            'wind': [],
            'airTemperature': [],
            'waterTemperature': [],
            'cloudCover': [],
            'precipitation': []
        }




API_KEY = 'a3c69958-b8fd-11f0-a148-0242ac130003-a3c69a3e-b8fd-11f0-a148-0242ac130003'
    #http://127.0.0.1:5050/weather-info?location=Pauanui,%20Coromandel,%20New%20Zealand&days=2
    #http://127.0.0.1:5050/weather-info?location=Ponza,%20Lazio,%20Italia&days=2
    # fcardinali'2c92f59a-bec1-11ed-a654-0242ac130002-2c92f644-bec1-11ed-a654-0242ac130002'
    #franco.cardinali:'a3c69958-b8fd-11f0-a148-0242ac130003-a3c69a3e-b8fd-11f0-a148-0242ac130003'

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

#This will get the Coordinates and the Display Name of the location
def get_coordinates(location_name):
    url = "https://nominatim.openstreetmap.org/search"
    params = {'q': location_name, 'format': 'json', 'limit': 1}
    response = requests.get(url, params=params, headers={
                            'User-Agent': 'weather-agent'})
    data = response.json()

    if data:
        lat = float(data[0]['lat'])
        lon = float(data[0]['lon'])
        display_name = data[0]['display_name']
        return lat, lon, display_name
    return None, None, None

app = Flask(__name__)

@app.route('/weather-info', methods=['GET'])
def get_weather_info():
    location = request.args.get('location', default='Huia', type=str)
    days = request.args.get('days', default=1, type=int)
    days = max(1, min(days, 7))

    logging.info(f"Incoming /weather-info request: location={location}, days={days}")

    lat, lng, display_name = get_coordinates(location)
    if lat is None or lng is None:
        return jsonify({'error': f'Could not resolve location: {location}'}), 400

    # Get today's date in local time
    tf = TimezoneFinder()
    tz_name = tf.timezone_at(lat=lat, lng=lng) or 'Pacific/Auckland'
    local_tz = pytz.timezone(tz_name)
    local_today = datetime.now(local_tz).date()

    if days == 1:
        start_dt = datetime.combine(local_today, dt_time.min, tzinfo=local_tz).astimezone(timezone.utc)
        end_dt = datetime.combine(local_today + timedelta(days=1), dt_time.min, tzinfo=local_tz).astimezone(
            timezone.utc)
    else:
        start_dt = datetime.combine(local_today, dt_time.min, tzinfo=local_tz).astimezone(timezone.utc)
        end_dt = datetime.combine(local_today + timedelta(days=days), dt_time.min, tzinfo=local_tz).astimezone(
            timezone.utc)

    # Convert to Unix timestamps for Stormglass API
    start = int(start_dt.timestamp())  # Start of today in UTC
    end = int(end_dt.timestamp())  # Start of day after last requested day in UTC

    # Used for caching results per location and date range
    cache_key = f"{lat}_{lng}_{start}_{end}"

    if cache_key in daily_cache_by_coords:
        logging.info(f"Using cached data for {cache_key}")
        return jsonify(daily_cache_by_coords[cache_key])

    headers = {'Authorization': API_KEY}
    results = {'coordinates': {'lat': lat, 'lng': lng},
        'location': display_name,
        'forecast': {}
    }

    requested_dates = [(local_today + timedelta(days=i)).isoformat() for i in range(days)]
    for date_str in requested_dates:
        results['forecast'][date_str] = {
            'high_tide': [],
            'low_tide': [],
            'sunrise': None,
            'sunset': None,
            'moon': {},
            'moon_phase': None,
            'swell_height': [],
            'wind': [],
            'airTemperature': [],
            'waterTemperature': [],
            'cloudCover': [],
            'precipitation': []
        }

        # Tide extremes
    tide_url = 'https://api.stormglass.io/v2/tide/extremes/point'
    tide_params = {'lat': lat, 'lng': lng,'datum': 'MLLW', 'start': start, 'end': end}

    start_time = time.time()
    logging.info(f"Calling Tide API: {tide_url} with params: {tide_params}")

    tide_response = requests.get(tide_url, headers=headers, params=tide_params)

    duration = time.time() - start_time
    logging.info(f"Response time: {duration:.2f}s")
    logging.info(f"Tide API status: {tide_response.status_code}")

    if tide_response.status_code != 200:
        logging.error(f"Tide API failed: {tide_response.text}")

    tide_data = tide_response.json()
    for entry in tide_data.get('data', []):
        local_dt = convert_to_local_time(entry['time'], lat, lng)
        date_str = local_dt.date().isoformat()

        if date_str not in results['forecast']:
            continue

        tide_info = {
            'time': local_dt.strftime('%Y-%m-%d %H:%M %Z'),
            'height': round(entry['height'], 2)
        }

        ensure_forecast_date(results, date_str)
        if entry['type'] == 'high':
            results['forecast'][date_str]['high_tide'].append(tide_info)
        elif entry['type'] == 'low':
            results['forecast'][date_str]['low_tide'].append(tide_info)

    shift_hours = get_utc_shift_hours(lat, lng)

    weather_start_dt = datetime.combine(local_today, dt_time.min, tzinfo=timezone.utc) - timedelta(hours=shift_hours)
    weather_end_dt = datetime.combine(local_today + timedelta(days=days), dt_time.min,tzinfo=timezone.utc) - timedelta(hours=shift_hours)

    weather_start = int(weather_start_dt.timestamp())
    weather_end = int(weather_end_dt.timestamp())

    # Wind data
    weather_url = 'https://api.stormglass.io/v2/weather/point'
    weather_params = {
        'lat': lat,
        'lng': lng,
        'params': 'windDirection,windSpeed,airTemperature,precipitation,cloudCover,waterTemperature',
        'source': 'noaa',
        'start': weather_start,
        'end': weather_end

    }
    logging.info(f"Calling Weather API: {weather_url} with params: {weather_params}")

    start_time = time.time()
    weather_response = requests.get(weather_url, headers=headers, params=weather_params)

    duration = time.time() - start_time
    logging.info(f"Response time: {duration:.2f}s")

    logging.info(f"Weather API status: {weather_response.status_code}")
    if weather_response.status_code != 200:
        logging.error(f"Weather API failed: {weather_response.text}")

    weather_data = weather_response.json()
    for entry in weather_data.get('hours', []):
        local_dt = convert_to_local_time(entry['time'], lat, lng)
        date_str = local_dt.date().isoformat()

        # Skip if outside requested local date range
        if date_str not in requested_dates:
            continue

        # ✅ Ensure all keys are initialized before appending anything
        ensure_forecast_date(results, date_str)

        # Wind
        wind_speed = entry.get('windSpeed', {}).get('noaa')
        wind_dir = entry.get('windDirection', {}).get('noaa')
        if wind_speed is not None and wind_dir is not None:
            results['forecast'][date_str]['wind'].append({
                'time': local_dt.strftime('%Y-%m-%d %H:%M %Z'),
                'speed_kmh': round(wind_speed * 3.6, 2),
                'direction_deg': wind_dir
            })

        # Air temperature
        air_temp = entry.get('airTemperature', {}).get('noaa')
        if air_temp is not None:
            results['forecast'][date_str]['airTemperature'].append({
                'time': local_dt.strftime('%Y-%m-%d %H:%M %Z'),
                'temperature_c': round(air_temp, 1)
            })

        # Water temperature
        water_temp = entry.get('waterTemperature', {}).get('noaa')
        if water_temp is not None:
            results['forecast'][date_str]['waterTemperature'].append({
                'time': local_dt.strftime('%Y-%m-%d %H:%M %Z'),
                'temperature_c': round(water_temp, 1)
            })

        # Cloud cover
        cloud_cover = entry.get('cloudCover', {}).get('noaa')
        if cloud_cover is not None:
            results['forecast'][date_str]['cloudCover'].append({
                'time': local_dt.strftime('%Y-%m-%d %H:%M %Z'),
                'coverage_percent': round(cloud_cover, 1)
            })

        # Precipitation
        precipitation = entry.get('precipitation', {}).get('noaa')
        if precipitation is not None:
            results['forecast'][date_str]['precipitation'].append({
                'time': local_dt.strftime('%Y-%m-%d %H:%M %Z'),
                'amount_mm': round(precipitation, 2)
            })



    # Astronomy: sunrise, sunset, moonrise, moonset, moon phase
    for i in range(days):
        date = local_today + timedelta(days=i)
        date_str = date.isoformat()
        astro_url = 'https://api.stormglass.io/v2/astronomy/point'
        astro_params = {'lat': lat, 'lng': lng, 'date': date_str}
        logging.info(f"Calling Astronomy API: {astro_url} with params: {astro_params}")
        start_time = time.time()

        astro_response = requests.get(
            astro_url, headers=headers, params=astro_params)

        duration = time.time() - start_time
        logging.info(f"Response time: {duration:.2f}s")

        logging.info(f"Astronomy API status ({date_str}): {astro_response.status_code}")
        if astro_response.status_code != 200:
            logging.error(f"Astronomy API failed: {astro_response.text}")

        astro_data = astro_response.json()
        if 'data' in astro_data and len(astro_data['data']) > 0:
            astro = astro_data['data'][0]
            if astro.get('sunrise'):
                results['forecast'][date_str]['sunrise'] = convert_to_local_time(
                    astro.get('sunrise'), lat, lng).strftime('%Y-%m-%d %H:%M %Z')
            if astro.get('sunset'):
                results['forecast'][date_str]['sunset'] = convert_to_local_time(
                    astro.get('sunset'), lat, lng).strftime('%Y-%m-%d %H:%M %Z')
            if astro.get('moonrise'):
                results['forecast'][date_str]['moon']['rise'] = convert_to_local_time(
                    astro.get('moonrise'), lat, lng).strftime('%Y-%m-%d %H:%M %Z')
            if astro.get('moonset'):
                results['forecast'][date_str]['moon']['set'] = convert_to_local_time(
                    astro.get('moonset'), lat, lng).strftime('%Y-%m-%d %H:%M %Z')
            if astro.get('moonPhase'):
                results['forecast'][date_str]['moon_phase'] = astro.get(
                    'moonPhase')

    # Swell height
    swell_params = {
        'lat': lat,
        'lng': lng,
        'params': 'swellHeight',
        'source': 'noaa',
        'start': weather_start,
        'end': weather_end

    }
    logging.info(f"Calling Swell API: { weather_url} with params: {swell_params}")

    start_time = time.time()

    swell_response = requests.get(
        weather_url, headers=headers, params=swell_params)

    duration = time.time() - start_time
    logging.info(f"Response time: {duration:.2f}s")

    logging.info(f"Swell API status: {swell_response.status_code}")
    if swell_response.status_code != 200:
        logging.error(f"Swell API failed: {swell_response.text}")

    swell_data = swell_response.json()
    for entry in swell_data.get('hours', []):
        local_dt = convert_to_local_time(entry['time'], lat, lng)
        date_str = local_dt.date().isoformat()

        if date_str not in results['forecast']:
            continue

        swell_height = entry.get('swellHeight', {}).get('noaa')
        if swell_height is not None:
            ensure_forecast_date(results, date_str)
            results['forecast'][date_str]['swell_height'].append({
                'time': local_dt.strftime('%Y-%m-%d %H:%M %Z'),
                'height_m': round(swell_height, 2)
            })


    # Add metadata and enhancements


    tf_meta = TimezoneFinder()
    tz_name_meta = tf_meta.timezone_at(lat=lat, lng=lng) or 'Pacific/Auckland'
    local_tz_meta = pytz.timezone(tz_name_meta)
    now_utc_meta = datetime.now(timezone.utc)
    local_dt_meta = now_utc_meta.astimezone(local_tz_meta)

    local_dt = convert_to_local_time(datetime.now(timezone.utc).isoformat(), lat, lng)
    results['meta'] = {
        'location': f"https://www.google.com/maps?q={lat},{lng}",
        'timezone_name': local_dt_meta.tzname(),
        'timezone_offset': f"UTC{int(local_dt_meta.utcoffset().total_seconds() // 3600):+}",
        'requested_days': days,
        'data_source': 'Stormglass',
        'data_status': 'complete' if any(results['forecast'].values()) else 'partial'
    }

    results['units'] = {
    'height': 'meters',
    'speed': 'km/h',
    'temperature': '°C',
    'precipitation': 'mm',
    'direction': 'degrees'
}

    for date_str, day_data in results['forecast'].items():
        high_tides = len(day_data.get('high_tide', []))
        low_tides = len(day_data.get('low_tide', []))
        wind_speeds = [w['speed_kmh'] for w in day_data.get('wind', []) if 'speed_kmh' in w]
        swell_heights = [s['height_m'] for s in day_data.get('swell_height', []) if 'height_m' in s]

        air_temps = [t['temperature_c'] for t in day_data.get('airTemperature', []) if 'temperature_c' in t]
        water_temps = [t['temperature_c'] for t in day_data.get('waterTemperature', []) if 'temperature_c' in t]
        cloud_covers = [c['coverage_percent'] for c in day_data.get('cloudCover', []) if 'coverage_percent' in c]

        summary = {
            'tide': f"{high_tides} high, {low_tides} low",
            'wind_peak_kmh': max(wind_speeds) if wind_speeds else None,
            'swell_peak_m': max(swell_heights) if swell_heights else None,
            'air_temp_max_c': max(air_temps) if air_temps else None,
            'air_temp_min_c': min(air_temps) if air_temps else None,
            'air_temp_avg_c': round(sum(air_temps) / len(air_temps), 1) if air_temps else None,
            'water_temp_max_c': max(water_temps) if water_temps else None,
            'water_temp_min_c': min(water_temps) if water_temps else None,
            'water_temp_avg_c': round(sum(water_temps) / len(water_temps), 1) if water_temps else None,
            'cloud_cover_avg_percent': round(sum(cloud_covers) / len(cloud_covers), 1) if cloud_covers else None,
            'sunrise': day_data.get('sunrise'),
            'sunset': day_data.get('sunset')
        }

        # Add summary to day_data
        day_data['summary'] = summary

        # Reorder keys
        ordered_keys = [
            "summary", "high_tide", "low_tide", "sunrise", "sunset", "moon", "moon_phase",
            "wind", "swell_height", "airTemperature", "waterTemperature", "precipitation", "cloudCover"
        ]

        ordered_day_data = OrderedDict()
        for key in ordered_keys:
            if key in day_data:
                ordered_day_data[key] = day_data[key]
        for key in day_data:
            if key not in ordered_day_data:
                ordered_day_data[key] = day_data[key]

        # Replace the original forecast entry
        results['forecast'][date_str] = ordered_day_data

    daily_cache_by_coords[cache_key] = results
    logging.info(f"Cached new data for {cache_key}")
    logging.info(json.dumps(results, indent=2))
    return jsonify(results)


if __name__ == '__main__':
    app.run(debug=True, host='127.0.0.1', port=5050)
