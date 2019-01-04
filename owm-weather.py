# -*- coding: utf-8 -*-
import sopel
import argparse
from pyowm import OWM

def format_weather_message(location, weather):
    cover = get_cover(weather)
    temp = get_temperature(weather)
    humidity = get_humidity(weather)
    wind = get_wind(weather)
   
    return "{}: {} {} {} {}".format(location, cover, temp, humidity, wind) 

def get_cover(w):
    return w.get_detailed_status()

def get_temperature(w):
    temp_c = w.get_temperature('celsius')
    temp_f = w.get_temperature('fahrenheit')

    # Format is:
    # {'temp': 293.4, 'temp_kf': None, 'temp_max': 297.5, 'temp_min': 290.9}

    return "{}\u00B0C ({}\u00B0F)".format(round(temp_c['temp'], 1), round(temp_f['temp'], 1))

def get_humidity(w):
    return "Humidity: {}%".format(w.get_humidity())

def get_wind(w):
    wind = w.get_wind()
    # Format is:
    # {'deg': 59, 'speed': 2.660}
    # Speed is in metres/sec by default

    speed_kts = (wind["speed"] * 1.944)
    speed_m_s = round(wind["speed"], 1)
    degrees = wind["deg"]

    if speed_kts < 1:
        description = 'Calm'
    elif speed_kts < 4:
        description = 'Light air'
    elif speed_kts < 7:
        description = 'Light breeze'
    elif speed_kts < 11:
        description = 'Gentle breeze'
    elif speed_kts < 16:
        description = 'Moderate breeze'
    elif speed_kts < 22:
        description = 'Fresh breeze'
    elif speed_kts < 28:
        description = 'Strong breeze'
    elif speed_kts < 34:
        description = 'Near gale'
    elif speed_kts < 41:
        description = 'Gale'
    elif speed_kts < 48:
        description = 'Strong gale'
    elif speed_kts < 56:
        description = 'Storm'
    elif speed_kts < 64:
        description = 'Violent storm'
    else:
        description = 'Hurricane'

    if (degrees <= 22.5) or (degrees > 337.5):
        degrees = u'\u2193'
    elif (degrees > 22.5) and (degrees <= 67.5):
        degrees = u'\u2199'
    elif (degrees > 67.5) and (degrees <= 112.5):
        degrees = u'\u2190'
    elif (degrees > 112.5) and (degrees <= 157.5):
        degrees = u'\u2196'
    elif (degrees > 157.5) and (degrees <= 202.5):
        degrees = u'\u2191'
    elif (degrees > 202.5) and (degrees <= 247.5):
        degrees = u'\u2197'
    elif (degrees > 247.5) and (degrees <= 292.5):
        degrees = u'\u2192'
    elif (degrees > 292.5) and (degrees <= 337.5):
        degrees = u'\u2198'

    return "{} {}m/s ({})".format(description, speed_m_s, degrees)

def lookup_weather(api_key, city_lookup):
    print("Looking up the weather at {}".format(city_lookup))
    api = get_api(api_key)

    if is_place_id(city_lookup):
        observation = api.weather_at_id(int(city_lookup))
    elif is_place_coords(city_lookup):
        coords = get_place_coords(city_lookup)
        observation = api.weather_at_coords(coords[0], coords[1])
    else:
        observation = api.weather_at_place(name=city_lookup)

    weather = observation.get_weather()
    return weather

def get_api(api_key):
    """ Retrieves the OWM API object based on the supplied key """
    # This place can be used to change OWM behaviour, incl subscription type, language, etc.
    # See https://pyowm.readthedocs.io/en/latest/usage-examples-v2/weather-api-usage-examples.html#create-global-owm-object
    owm = OWM(api_key)
    return owm

def is_place_id(city_lookup):
    """ Checks whether or not the city lookup can be cast to an int, representing a WOEID """
    try:
        int(city_lookup) 
        return True
    except ValueError:
        return False

def is_place_coords(city_lookup):
    """ 
    Checks whether or not coordinates exist and are able to be cast to a float.
    From OWM documentation:
        - The location's latitude, must be between -90.0 and 90.0
        - The location's longitude, must be between -180.0 and 180.0
    More info: https://github.com/csparpa/pyowm/blob/master/pyowm/weatherapi25/owm25.py#L234
    """
    try:
        coords = get_place_coords(city_lookup)
        
        # Check for valid floats
        latitude = float(coords[0])
        longitude = float(coords[1])

        # Check for valid latitude bounds
        if (latitude < -90.0) or (latitude > 90.0):
            return False

        # Check for valid longitude bounds
        if (longitude < -180.0) or (longitude > 180.0):
            return False

        # Latitude and Longitude are checked to be floats and within the accepted bounds
        return True
    except ValueError:
        return False

def get_place_coords(city_lookup):
    """
    Parses a geo coord in the form of (latitude,longitude) and returns
    them as an array. Note that a simple "latitude,longitude" is also
    valid as a coordinate set
    """
    latitude, longitude = map(float, city_lookup.strip('()[]').split(','))
    return [latitude, longitude]

def get_argparser():
    parser = argparse.ArgumentParser()
    parser.add_argument("api_key", help="Your OpenWeatherMap API key or APPID key")
    parser.add_argument("--city-lookup", help="Optional lookup value, either a city name, coords, or city id.")
    return parser

if __name__ == "__main__":
    """ Test harness for when running outside of Sopel """
    parser = get_argparser()
    args = parser.parse_args()
    
    api_key = args.api_key
    city_lookup = args.city_lookup
    if city_lookup is None:
        city_lookup = 'Melbourne'

    weather = lookup_weather(api_key, city_lookup)
    message = format_weather_message(city_lookup, weather)
    print(message)
    print("Completed lookup request.")
