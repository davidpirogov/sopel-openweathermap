from typing import List, Tuple
from pyowm.commons.cityidregistry import CityIDRegistry
from pyowm.commons.enums import SubscriptionTypeEnum
from pyowm.uvindexapi30.uvindex import UVIndex
from pyowm.weatherapi25 import weather
from pyowm.weatherapi25.observation import Observation
from pyowm.weatherapi25.weather import Weather
from pyowm.weatherapi25.location import Location
from urllib.parse import quote_plus
import regex as re
from pyowm.commons.exceptions import APIRequestError, APIResponseError, ConfigurationError, NotFoundError, PyOWMError
from pyowm.owm import OWM
from sopel.config.types import StaticSection, ValidatedAttribute
from sopel import tools  # type: ignore

log = tools.get_logger('openweathermap')

LOC_NOT_FOUND_MSG = "Could not find your location. Try refining such as Melbourne,AU or " \
                    "Melbourne,FL. OpenWeatherMap uses 2-letter code for US states and " \
                    "also countries (ISO3166)"

LOC_SPECIFY_MSG = "Please specifiy one of: geo coordinates (lat;long), OpenWeatherMap ID " \
                   "(#number), or location text"

LOC_COLLISION_MSG = "There are multiple results for '{}'. Visit " \
                    "https://openweathermap.org/find?q={} to find the right city. You can then " \
                    "use either the geo coords or the city id to reference the right '{}'"

LOC_REFINE_MSG = "Please refine your location by adding a country code. Valid " \
                 "options are: {}"

API_OFFLINE_MSG = "The OpenWeatherMap API could not be reached or is not online. Try again later."

OWM_CONFIG_ERROR_MSG = "The OpenWeatherMap API is not correctly configured in the Sopel " \
                       "configuration. Please reach out to the Sopel IRC bot administrator."

OBSERVATION_LOOKUP_LIMIT = 3

class OWMSection(StaticSection):
    api_key = ValidatedAttribute('api_key', str, default="")


def get_api(api_key,
    subscription_type=SubscriptionTypeEnum.FREE,
    language:str="en",
    connection:dict={
        "use_ssl": True,
        "verify_ssl_certs": True,
        "use_proxy": False,
        "timeout_secs": 5
        },
    proxies:dict={
        "http":"http://",
        "https":"https://",
        }
    ) -> OWM:
    """
    Retrieves the OWM API v3 object based on the supplied API key.

    Must supply an api_key that can be created at https://home.openweathermap.org/api_keys

    Other options are configurable based on
    https://pyowm.readthedocs.io/en/latest/v3/code-recipes.html#initialize-pyowm-with-configuration-loaded-from-an-external-json-file

    """
    if len(str(api_key).strip()) == 0:
        raise ValueError("The API Key is blank or empty")

    owm = OWM(api_key, config={
        "subscription_type": subscription_type,
        "language": language,
        "connection": connection,
        "proxies": proxies
    })

    return owm


def format_weather_message(location_name:str, weather:Weather, uv:UVIndex) -> str:
    """
    Formats a weather observation message for Sopel output
    """

    cover = get_cover(weather)
    temp = get_temperature(weather)
    humidity = get_humidity(weather)
    wind = get_wind(weather)
    uv_index = round(uv.value, 1)
    uv_risk = uv.get_exposure_risk()

    return "{}: {} {} {} {} UV Index {} ({} at local solar noon)".format(
        location_name, cover, temp, humidity, wind, uv_index, uv_risk)


def get_cover(w:Weather) -> str:
    return w.detailed_status


def get_temperature(w:Weather) -> str:
    temp_c = w.temperature('celsius')
    temp_f = w.temperature('fahrenheit')

    return "{}\u00B0C ({}\u00B0F)".format(round(temp_c['temp'], 1), round(temp_f['temp'], 1))


def get_humidity(w:Weather) -> str:
    return "Humidity: {}%".format(w.humidity)


def get_wind(w:Weather) -> str:
    wind = w.wind("meters_sec")
    wind_k = w.wind("knots")

    speed_kts = round(wind_k["speed"], 1)
    speed_m_s = round(wind["speed"], 1)
    degrees = None
    if 'deg' in wind:
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

    if degrees is not None:
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
    else:
        degrees = 'Unknown direction'

    return "{} {}m/s ({})".format(description, speed_m_s, degrees)


def parse_location_args(args: str) -> list:
    """
    Parses the location text from a user to determine the type of location
    that has been specified
    """

    location = {
        "type":"unknown"
    }

    # Check geocoords with a semi-colon separator
    if is_geolocation(args, ";"):
        log.debug("Identified location argument as geolocation with semi-colon separator")
        location["type"] = "geocoords"
        location = {**location, **get_geolocation(args, ";")}

    # Check geocoords with a comma separator
    elif is_geolocation(args, ","):
        log.debug("Identified location argument as geolocation with comma separator")
        location["type"] = "geocoords"
        location = {**location, **get_geolocation(args, ",")}

    # Check OWM Place ID
    elif is_place_id(args):
        log.debug("Identified location argument as an OWM Place ID")
        location["type"] = "place_id"
        location["place_id"] = get_place_id(args)

    # Extract as much data from a location based query string as possible
    else:
        log.debug("Identified location argument as a query argument")
        location["type"] = "location"
        location = {**location, **get_location_string(args)}

    return location


def sanitize_field(field:str) -> str:
    """
    Santizes a field that is used to process user input by keeping alphanumeric (multilingual)
    characters only and stripping leading/trailing whitespace. Permits zero or one exclamation
    marks as the first character of the field
    """
    stripped_field = field.strip()
    if stripped_field[0:1] == "!":
        return f'!{__clean_field(stripped_field[1:])}'
    elif stripped_field[0:1] == "*":
        return f'*{__clean_field(stripped_field[1:])}'
    else:
        return __clean_field(stripped_field)

def __clean_field(field:str) -> str:
    """ Performs a regex on a field """
    # Space is important in the regex
    return "".join(re.findall("[\p{L} ]", field.strip(), re.UNICODE))

def is_geolocation(location: str, separator:str=";") -> bool:
    """
    Checks for the presence of a separator (default is a semi-colon) and if the
    coordinates are in valid ranges
    """

    geolocation = get_geolocation(location, separator)
    if geolocation is None:
        return False

    return is_lat_within_range(geolocation["latitude"]) \
        and is_long_within_range(geolocation["longitude"])

def get_geolocation(location: str, separator: str=";") -> dict:
    """
    Extracts a geolocation from a location string WITHOUT checking for validity
    """
    try:
        geo_coords = location.split(separator)
        if len(geo_coords) != 2:
            return None

        candidate_latitude = geo_coords[0].strip()
        candidate_longitude = geo_coords[1].strip()

        # Check for square brackets at the start of the latitude and end of longitude
        if candidate_latitude[0:1] == "[" and candidate_longitude[-1] == "]":
            candidate_latitude = candidate_latitude[1:]
            candidate_longitude = candidate_longitude[:len(candidate_longitude) - 1]

        return {
            "latitude": float(candidate_latitude),
            "longitude": float(candidate_longitude)
        }
    except (AttributeError, TypeError, ValueError):
        return None

def is_lat_within_range(latitude: float) -> bool:
    """
    Checks if a Latitude coordinate is within the acceptable range of -90.0 and 90.0
    """
    return (latitude >= -90.0) and (latitude <= 90.0)

def is_long_within_range(longitude: float) -> bool:
    """
    Checks if a Longitude coordinate is within the acceptable range of -180.0 and 180.0
    """
    return (longitude >= -180.0) and (longitude <= 180.0)


def is_place_id(location: str) -> bool:
    """
    Checks whether or not the location looks like an OWM Place ID
    """

    place_id_candidate = get_place_id(location)
    if place_id_candidate is None:
        return False

    return True

def get_place_id(location:str) -> int:
    """
    Extracts an integer in the correct range from a location string
    """

    if type(location) == int and location > 0:
        return location

    # Location has to be at least 1 digit
    location_candidate = str(location)
    if len(location_candidate) == 0:
        return None

    # Strip optional leading tokens that represent a place id
    if "#" == location_candidate[0:1]:
        location_candidate = location_candidate[1:]

    try:
        # Place IDs can only ever be positive
        int_val = int(location_candidate)
        if int_val > 0:
            return int_val
        else:
            return None

    except (TypeError, ValueError):
        return None


def get_location_string(location:str) -> dict:
    """
    Extracts city, state, country according to ISO3166 format for use with the OpenWeatherMap API
    https://en.wikipedia.org/wiki/List_of_ISO_3166_country_codes
    """

    # Only permit city,country variations
    if location.count(",") > 1:
        return None

    return extract_city_state_country(location)

def extract_city_state_country(location: str, separator=",") -> dict:
    """
    Extracts an assumed city, state, and country from the location string
    Note: converts state and country fields into uppercase so that OpenWeatherMap API can
    process them correctly
    """

    location_elements = location.split(separator)

    # City, State, Country
    # Unfortunately OpenWeatherMap API does not differentiate between states and countries
    # TODO: Remove this code as part of a subsequent update and return when OpenWeatherMap API
    #       is able to manage states and countries
    # if len(location_elements) == 3:
    #     return {
    #         "city": sanitize_field(location_elements[0]),
    #         "state": sanitize_field(location_elements[1].upper()),
    #         "country": sanitize_field(location_elements[2].upper())
    #     }

    # City, Country
    if len(location_elements) == 2:
        return {
            "city": sanitize_field(location_elements[0]),
            "country": sanitize_field(location_elements[1].upper())
        }

    # City
    else:
        return {
            "city": sanitize_field(location_elements[0])
        }

def construct_location_name(location:dict) -> str:
    """
    Constructs a location name based on the supplied dictionary of elements, ensuring that
    they are in the correct format
    """

    if location["type"] == "location":
        if "state" in location:
            return f"{location['city']},{location['state']},{location['country']}"
        elif "country" in location:
            return f"{location['city']},{location['country']}"
        else:
            return location['city']

    elif location["type"] == "geocoords":
        return f"{location['latitude']},{location['longitude']}"

    elif location["type"] == "place_id":
        # Even if we have a place_id, if the city key is set, we want to return the city
        # name instead
        if "city" in location:
            return location["city"]

        return str(location["place_id"])


def get_weather_message(api:OWM, location: dict) -> str:
    """
    Gets the weather at a location or any error messages
    """
    try:
        if location["type"] == "place_id":
            message = __get_weather_at_place_id(api, location)

        elif location["type"] == "geocoords":
            message = __get_weather_at_geocoords(api, location)

        elif location["type"] == "location":
            message = __get_weather_at_location(api, location)

        else:
            message = "Unknown location type was encountered, please use one of the valid options"

        log.debug("Observation message is %s", message)

    except (ConfigurationError, PyOWMError) as owm_config_error:
        global OWM_CONFIG_ERROR_MSG
        message = OWM_CONFIG_ERROR_MSG
        log.error(owm_config_error)

    except (APIRequestError, APIResponseError) as api_error:
        global API_OFFLINE_MSG
        message = API_OFFLINE_MSG
        log.error(api_error)

    return message


def __get_weather_message_from_observation(api:OWM,
    location:dict,
    obs_weather:Observation,
    obs_uv:UVIndex) -> str:
    """
    Gets a formatted weather message based on an observation
    """
    weather: Weather = obs_weather.weather
    return format_weather_message(construct_location_name(location), weather, obs_uv)


def __get_weather_at_place_id(api: OWM, location: dict):
    """
    Gets the weather at a known place id
    """

    obs_weather, obs_uv = __get_observation_at_place_id(api, location)
    location["city"] = obs_weather.location.name

    return __get_weather_message_from_observation(api, location, obs_weather, obs_uv)

def __get_observation_at_place_id(api: OWM, location:dict) -> Tuple[Observation, UVIndex]:
    """
    Gets an observation at a specific place id
    """

    weather_manager = api.weather_manager()
    obs_weather: Observation = weather_manager.weather_at_id(location["place_id"])
    if obs_weather is None:
        return LOC_NOT_FOUND_MSG

    uvindex_manager = api.uvindex_manager()
    obs_uv: UVIndex = uvindex_manager.uvindex_around_coords(obs_weather.location.lat,
        obs_weather.location.lon)

    return (obs_weather, obs_uv)


def __get_weather_at_geocoords(api: OWM, location: dict):
    """
    Gets the formatted weather message at a set of geocoordinates
    """

    obs_weather, obs_uv = __get_observation_at_geocoords(api, location)
    return __get_weather_message_from_observation(api, location, obs_weather, obs_uv)

def __get_observation_at_geocoords(api:OWM, location:dict) -> Tuple[Observation, UVIndex]:
    """
    Gets the observation at a set of coordinates
    """
    weather_manager = api.weather_manager()
    obs_weather: Observation = weather_manager.weather_at_coords(lat=location["latitude"],
        lon=location["longitude"])
    if obs_weather is None:
        return LOC_NOT_FOUND_MSG

    uvindex_manager = api.uvindex_manager()
    obs_uv: UVIndex = uvindex_manager.uvindex_around_coords(obs_weather.location.lat,
        obs_weather.location.lon)

    return (obs_weather, obs_uv)

def get_owm_location(api:OWM, location:dict) -> Tuple[str, Tuple[int, str, str]]:
    """
    Gets an OWM Location based on the supplied location search parameters
    """

    log.debug("Getting weather at location '%s'", construct_location_name(location))
    if location["type"] == "location":
        owm_locations: list[Location] = get_owm_locations_from_text(api, location)
        return check_owm_locations_list(location, owm_locations)

    try:
        if location["type"] == "place_id":
            obs_weather, _ = __get_observation_at_place_id(api, location)
        elif location["type"] == "geocoords":
            obs_weather, _ = __get_observation_at_geocoords(api, location)

        if obs_weather.location.country != None:
            place_location = (obs_weather.location.id, obs_weather.location.name, obs_weather.location.country)
        else:
            place_location = (obs_weather.location.id, obs_weather.location.name, "")

        return (None, place_location)
    except NotFoundError:
        return (LOC_NOT_FOUND_MSG, None)

def __get_weather_at_location(api: OWM, location: dict) -> str:
    """
    Gets the weather at a location based on a supplied location dictionary
    """

    log.debug("Getting weather at location '%s'", construct_location_name(location))
    (error_message, owm_location) = get_owm_location(api, location)

    if error_message is not None:
        return error_message

    location_by_id = {
        "type": "place_id",
        # Tuple (5367815, 'London', 'CA')
        "place_id": owm_location[0]
    }
    obs_weather, obs_uv = __get_observation_at_place_id(api, location_by_id)
    return __get_weather_message_from_observation(api, location, obs_weather, obs_uv)

def check_owm_locations_list(location: dict,
     owm_locations: List[Tuple[int, str, str]]) -> Tuple[str, Tuple[int, str, str]]:
    """
    Checks the OWM Locations list and returns a tuple with either an error message or an OWM
    Location
    """

    if len(owm_locations) == 0:
        if "country" in location and location["country"] == "US":
            error_message = f"{LOC_NOT_FOUND_MSG}. For US cities only, you need to specify the " \
                            "2-letter state, not 'US'."
        else:
            error_message = LOC_NOT_FOUND_MSG

        return (error_message, None)

    elif len(owm_locations) == 1:
        return (None, owm_locations[0])

    # Iterate over the list and check for candidates that have the same city name and same country
    # If any exist, then return the message to the user that they need to pick via ID
    if has_api_name_collision(owm_locations) or len(owm_locations) > OBSERVATION_LOOKUP_LIMIT:
        return (LOC_COLLISION_MSG.format(
            construct_location_name(location),
            # Parameter that is quoted for the OpenWeatherMap API URL
            quote_plus(location["city"]),
            construct_location_name(location)), None)

    return (LOC_REFINE_MSG.format(
                                  # Tuple (5367815, 'London', 'CA')
                                  str(list(map(lambda x: "{},{}".format(x[1], x[2]),
                                    owm_locations))).strip('[]')), None)

def has_api_name_collision(owm_locations: List[Tuple]) -> bool:
    """
    Checks to see if there is a collision in API names based on city,country pairs
    """

    api_name_collision = False
    previously_found_items: List[Tuple] = []
    for owm_location in owm_locations:
        for prev_location in previously_found_items:
            # Tuple (5367815, 'London', 'CA')
            if owm_location[1] == prev_location[1] and \
                owm_location[2] == prev_location[2]:
                # We have a match on multiple name, country pair
                api_name_collision = True

            # Exit prev_location loop
            if api_name_collision:
                break

        # Exit owm_location loop
        if api_name_collision:
            break
        else:
            previously_found_items.append(owm_location)

    return api_name_collision

def get_owm_locations_from_text(api:OWM, location:dict) -> List[Tuple[int, str, str]]:
    """
    Gets a list of OWM location tuples from supplied text dictionary of location elements
    """
    if location["type"] != "location":
        log.warn("There is no need to get an OWM location from text for any location that is not "
                 "of type 'location'.")
        return None

    # Change the observation type if there is an exclamation mark at the start of the city
    # name so that it only finds accurate names or a star to find any matching names
    search_type = "nocase"
    if location["city"][0:1] == "!":
        search_type = "exact"
        location["city"] = location["city"][1:]
    elif location["city"][0:1] == "*":
        search_type = "like"
        location["city"] = location["city"][1:]

    log.debug("Search type for city '%s' is '%s'", location["city"], search_type)
    registry: CityIDRegistry = api.city_id_registry()

    if "country" in location:
        owm_locations = registry.ids_for(city_name=location["city"],
            country=location["country"], matching=search_type)
    else:
        owm_locations = registry.ids_for(city_name=location["city"], matching=search_type)

    # If DEBUG is turned on
    # https://docs.python.org/3/library/logging.html#levels
    if log.getEffectiveLevel() == 10:
        log.debug("Found %d candidate city ids for name '%s'", len(owm_locations),
            construct_location_name(location))
        for city_id in owm_locations:
            log.debug("\t %s", city_id)

    return owm_locations



