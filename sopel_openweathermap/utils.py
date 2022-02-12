from string import capwords
from typing import List, Tuple
from urllib.parse import quote_plus

import regex as re
from pyowm.airpollutionapi30.airpollution_manager import AirPollutionManager
from pyowm.airpollutionapi30.airstatus import AirStatus
from pyowm.commons.cityidregistry import CityIDRegistry
from pyowm.commons.enums import SubscriptionTypeEnum
from pyowm.commons.exceptions import (
    APIRequestError,
    APIResponseError,
    ConfigurationError,
    NotFoundError,
    PyOWMError,
)
from pyowm.owm import OWM
from pyowm.uvindexapi30.uvindex import UVIndex
from pyowm.weatherapi25.observation import Observation
from pyowm.weatherapi25.weather import Weather
from sopel import tools
from sopel.bot import SopelWrapper
from sopel.config.types import BooleanAttribute, StaticSection, ValidatedAttribute

log = tools.get_logger("openweathermap")

LOC_NOT_FOUND_MSG = (
    "Could not find your location. Try refining such as Melbourne,AU or "
    "Melbourne,FL. OpenWeatherMap uses 2-letter code for US states and "
    "also countries (ISO3166)"
)

LOC_SPECIFY_MSG = (
    "Please specify one of: geo coordinates (lat;long), OpenWeatherMap ID "
    "(#number), or location text"
)

LOC_COLLISION_MSG = (
    "Due to the OWM data, there are ambiguous results for '{}'. Visit "
    "https://openweathermap.org/find?q={} to find the correct place id you want."
)

LOC_REFINE_MSG = (
    "Please refine your location by adding a country code or looking up a place id. Valid "
    "options are: {}"
)

API_OFFLINE_MSG = (
    "The OpenWeatherMap API could not be reached or is not online. Try again later."
)

OWM_CONFIG_ERROR_MSG = (
    "The OpenWeatherMap API is not correctly configured in the Sopel "
    "configuration. Please reach out to the Sopel IRC bot administrator."
)

# Number of observations after which the LOC_COLLISION_MSG is shown instead of the
# observation options (usually same city name in different countries)
OBSERVATION_LOOKUP_LIMIT = 3


class OWMSection(StaticSection):

    api_key = ValidatedAttribute("api_key", parse=str, default="")

    # Whether or not to enable the air quality metric, depending on whether or not the version
    # of pyowm supports air quality.
    enable_air_quality = BooleanAttribute("enable_air_quality", default=False)

    # Whether or not to guess multiple city-country pairs into a
    enable_location_best_guess = BooleanAttribute(
        "enable_location_best_guess", default=True
    )


def get_api(
    api_key,
    subscription_type=SubscriptionTypeEnum.FREE,
    language: str = "en",
    connection: dict = {
        "use_ssl": True,
        "verify_ssl_certs": True,
        "use_proxy": False,
        "timeout_secs": 5,
    },
    proxies: dict = {
        "http": "http://",
        "https": "https://",
    },
) -> OWM:
    """
    Retrieves the OWM API v3 object based on the supplied API key.

    Must supply an api_key that can be created at https://home.openweathermap.org/api_keys

    Other options are configurable based on
    https://pyowm.readthedocs.io/en/latest/v3/code-recipes.html#initialize-pyowm-with-configuration-loaded-from-an-external-json-file

    """
    if len(str(api_key).strip()) == 0:
        raise ValueError("The API Key is blank or empty")

    owm = OWM(
        api_key,
        config={
            "subscription_type": subscription_type,
            "language": language,
            "connection": connection,
            "proxies": proxies,
        },
    )

    return owm


def get_owm_api(bot: SopelWrapper) -> OWM:
    """
    Retrieves the OWM API endpoint from the bot's memory
    """

    if "owm" not in bot.memory:
        log.error(
            "Sopel memory does not contain the OpenWeatherMap configuration section. "
            "Ensure that it has been configured using the setup() method."
        )
        return None

    if "api" not in bot.memory["owm"]:
        log.error(
            "Sopel memory does not contain an initialized OpenWeatherMap API."
            "Ensure that it has been configured using the setup() method."
        )
        return None

    return bot.memory["owm"]["api"]


def parse_location_args(args: str) -> list:
    """
    Parses the location text from a user to determine the type of location
    that has been specified
    """

    location = {"type": "unknown"}

    # Check geocoords with a semi-colon separator
    if is_geolocation(args, ";"):
        log.debug(
            "Identified location argument as geolocation with semi-colon separator"
        )
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


def get_weather_message(bot: SopelWrapper, location: dict) -> str:
    """
    Gets the weather at a location or any error messages
    """
    try:
        if location["type"] == "place_id":
            message = __get_weather_message_at_place_id(bot, location)

        elif location["type"] == "geocoords":
            message = __get_weather_message_at_geocoords(bot, location)

        elif location["type"] == "location":
            message = __get_weather_message_at_location(bot, location)

        else:
            message = "Unknown location type was encountered, please use one of the valid options"

        log.debug("Observation message is %s", message)

    except (APIRequestError, APIResponseError) as api_error:
        global API_OFFLINE_MSG
        message = API_OFFLINE_MSG
        log.error(api_error)

    except (ConfigurationError, PyOWMError) as owm_config_error:
        global OWM_CONFIG_ERROR_MSG
        message = OWM_CONFIG_ERROR_MSG
        log.error(owm_config_error)

    return message


def __get_weather_message_at_place_id(bot: SopelWrapper, location: dict):
    """
    Gets the formatted weather message at a known place id
    """

    obs_weather, obs_uv, air_status = __get_observation_at_place_id(bot, location)
    location["city"] = obs_weather.location.name

    if obs_weather.location.country is not None:
        location["country"] = obs_weather.location.country

    return __get_weather_message_from_observation(
        location, obs_weather, obs_uv, air_status
    )


def __get_weather_message_at_geocoords(bot: SopelWrapper, location: dict):
    """
    Gets the formatted weather message at a set of geocoordinates
    """
    obs_weather, obs_uv, air_quality = __get_observation_at_geocoords(bot, location)
    return __get_weather_message_from_observation(
        location, obs_weather, obs_uv, air_quality
    )


def __get_weather_message_at_location(bot: SopelWrapper, location: dict) -> str:
    """
    Gets the formatted weather message at a location based on a supplied location dictionary
    """

    log.debug(
        "Getting weather message for location '%s'", construct_location_name(location)
    )

    is_location_best_guess_enabled: bool = bot.memory["owm"][
        "enable_location_best_guess"
    ]
    log.debug("Is location best guess is enabled: %s", is_location_best_guess_enabled)

    log.debug(
        "Getting a list of all the possible locations that match our location query"
    )
    (error_message, owm_possible_locations) = get_owm_locations(bot, location)
    if error_message is not None:
        return error_message

    log.debug("Checking locations for specific match based on location context")
    (error_message, owm_locations) = check_owm_locations_list(
        location, owm_possible_locations, is_location_best_guess_enabled
    )
    if error_message is not None:
        return error_message

    if is_location_best_guess_enabled and len(owm_locations) > 1:
        log.debug("Location best guess is enabled, getting range of temperatures")
        weather_message = __get_observation_range_at_location_set(
            bot, location, owm_locations
        )
        return weather_message
    else:

        # owm_location tuple looks like (5367815, 'London', 'CA')
        location_by_id = {
            "type": "place_id",
            "place_id": owm_locations[0][0],
            "city": owm_locations[0][1],
            "country": owm_locations[0][2],
        }

        obs_weather, obs_uv, air_status = __get_observation_at_place_id(
            bot, location_by_id
        )
        return __get_weather_message_from_observation(
            location_by_id, obs_weather, obs_uv, air_status
        )


def __get_observation_range_at_location_set(
    bot, location: dict, owm_locations: List[Tuple[int, str, str]]
) -> str:
    """
    Gets a range of observations for the locations in the owm_locations set
    """

    log.debug(
        "Getting a range of observations for %d OWM locations", len(owm_locations)
    )
    api: OWM = get_owm_api(bot)
    observations: List[Weather] = []
    for loc in owm_locations:

        weather_manager = api.weather_manager()
        obs_weather: Observation = weather_manager.weather_at_id(loc[0])
        if obs_weather is None:
            return (
                f"{LOC_NOT_FOUND_MSG}. OpenWeatherMap data is inconsistent and needs manual "
                "lookup of place id or location geocoords"
            )

        observations.append(obs_weather.weather)

    # Earth temperature should be between these bounds
    max_temp: float = -200
    min_temp: float = 200
    display_temp: dict[str, float] = {
        "max_temp_c": None,
        "max_temp_f": None,
        "min_temp_c": None,
        "min_temp_f": None,
    }

    for obs in observations:
        log.debug("\t %s", obs.temperature("celsius"))
        if obs.temperature("celsius")["temp"] > max_temp:
            max_temp = round(obs.temperature("celsius")["temp"], 2)
            display_temp["max_temp_c"] = round(obs.temperature("celsius")["temp"], 1)
            display_temp["max_temp_f"] = round(obs.temperature("fahrenheit")["temp"], 1)
        # Separate if statements in-case a single observation is recorded for both
        if obs.temperature("celsius")["temp"] < min_temp:
            min_temp = round(obs.temperature("celsius")["temp"], 2)
            display_temp["min_temp_c"] = round(obs.temperature("celsius")["temp"], 1)
            display_temp["min_temp_f"] = round(obs.temperature("fahrenheit")["temp"], 1)

    location_name = construct_location_name(location)
    return "{}: {}\u00B0C - {}\u00B0C ({}\u00B0F - {}\u00B0F) {}".format(
        location_name,
        display_temp["min_temp_c"],
        display_temp["max_temp_c"],
        display_temp["min_temp_f"],
        display_temp["max_temp_f"],
        LOC_COLLISION_MSG.format(location_name, quote_plus(location["city"])),
    )


def __get_observation_at_geocoords(
    bot: SopelWrapper, location: dict
) -> Tuple[Observation, UVIndex, AirStatus]:
    """
    Gets the observation at a set of coordinates
    """
    api: OWM = get_owm_api(bot)
    weather_manager = api.weather_manager()
    obs_weather: Observation = weather_manager.weather_at_coords(
        lat=location["latitude"], lon=location["longitude"]
    )
    if obs_weather is None:
        return LOC_NOT_FOUND_MSG

    uvindex_manager = api.uvindex_manager()
    obs_uv: UVIndex = uvindex_manager.uvindex_around_coords(
        obs_weather.location.lat, obs_weather.location.lon
    )

    air_quality: AirStatus = None
    if bot.memory["owm"]["enable_air_quality"]:
        aq_manager: AirPollutionManager = api.airpollution_manager()
        air_quality = aq_manager.air_quality_at_coords(
            obs_weather.location.lat, obs_weather.location.lon
        )

    return (obs_weather, obs_uv, air_quality)


def __get_observation_at_place_id(
    bot: SopelWrapper, location: dict
) -> Tuple[Observation, UVIndex, AirStatus]:
    """
    Gets an observation at a specific place id
    """
    api: OWM = get_owm_api(bot)
    weather_manager = api.weather_manager()
    obs_weather: Observation = weather_manager.weather_at_id(location["place_id"])
    if obs_weather is None:
        return LOC_NOT_FOUND_MSG

    uvindex_manager = api.uvindex_manager()
    obs_uv: UVIndex = uvindex_manager.uvindex_around_coords(
        obs_weather.location.lat, obs_weather.location.lon
    )

    air_quality: AirStatus = None
    if bot.memory["owm"]["enable_air_quality"]:
        aq_manager: AirPollutionManager = api.airpollution_manager()
        air_quality = aq_manager.air_quality_at_coords(
            obs_weather.location.lat, obs_weather.location.lon
        )

    return (obs_weather, obs_uv, air_quality)


def __get_weather_message_from_observation(
    location: dict,
    obs_weather: Observation,
    obs_uv: UVIndex,
    air_status: AirStatus = None,
) -> str:
    """
    Gets a formatted weather message based on an observation
    """
    weather: Weather = obs_weather.weather
    return format_weather_message(
        construct_location_name(location), weather, obs_uv, air_status
    )


def format_weather_message(
    location_name: str, weather: Weather, uv: UVIndex, air_status: AirStatus
) -> str:
    """
    Formats a weather observation message for Sopel output
    """
    cover = get_cover(weather)
    temp = get_temperature(weather)
    humidity = get_humidity(weather)
    wind = get_wind(weather)
    uv_index = round(uv.value, 1)
    uv_risk = uv.get_exposure_risk()
    response_message = (
        f"{location_name}: {cover} {temp} {humidity} {wind} "
        f"UV Index {uv_index} ({uv_risk} at noon)"
    )

    air_quality_message = ""
    if air_status is not None:

        qualitative_name = get_air_quality_qualitative_name(
            air_status.air_quality_data["aqi"]
        )
        worst_offenders = get_air_quality_worst_offender(air_status.air_quality_data)

        if worst_offenders is None:
            air_quality_message = "Air Quality: {}".format(qualitative_name)
        else:
            air_quality_message = "Air Quality: {}: {}".format(
                qualitative_name, worst_offenders
            )

        response_message = f"{response_message} {air_quality_message}"

    return response_message


def get_air_quality_worst_offender(air_quality_data: dict) -> str:
    """
    Gets the worst offender for the air quality metric
    """

    if air_quality_data is None or "aqi" not in air_quality_data:
        return None

    air_quality_level = air_quality_data["aqi"]
    air_quality_matrix = __get_air_quality_index_matrix(air_quality_data)
    worst_offenders = []

    for air_quality_metric in air_quality_matrix:
        if (
            air_quality_metric["level"] == air_quality_level and air_quality_level > 1
        ):  # We don't want to include when air_quality_level is 1 (Good)
            worst_offenders.append(air_quality_metric)

    if len(worst_offenders) == 0:
        return None

    index = 0
    worst_offenders_text = ""
    for air_quality_offender in worst_offenders:

        token_text = "{}: {} (≥{})".format(
            air_quality_offender["metric"],
            air_quality_offender["value"],
            air_quality_offender["min"],
        )

        if index == 0:
            worst_offenders_text = "{}".format(token_text)
        else:
            worst_offenders_text = "{}, {}".format(worst_offenders_text, token_text)

        index += 1

    return worst_offenders_text


def __get_air_quality_index_matrix(air_quality_data: dict) -> List[dict]:
    """
    Returns an Air Quality Index matrix dictionary based on
    https://openweathermap.org/api/air-pollution and which level each of the air_quality_data
    readings fall into.
    """

    air_quality_names = {
        "co": "CO",
        "no2": "NO2",
        "o3": "Ozone",
        "pm2_5": "PM2.5",
        "pm10": "PM10",
    }

    air_quality_definitions = {
        "co": [
            {"min": 0, "max": 200},
            {"min": 200, "max": 300},
            {"min": 300, "max": 400},
            {"min": 400, "max": 500},
            {"min": 500, "max": 9999999},
        ],
        "no2": [
            {"min": 0, "max": 50},
            {"min": 50, "max": 100},
            {"min": 100, "max": 200},
            {"min": 200, "max": 400},
            {"min": 400, "max": 9999999},
        ],
        "o3": [
            {"min": 0, "max": 60},
            {"min": 60, "max": 120},
            {"min": 120, "max": 180},
            {"min": 180, "max": 240},
            {"min": 240, "max": 9999999},
        ],
        "pm2_5": [
            {"min": 0, "max": 15},
            {"min": 15, "max": 30},
            {"min": 30, "max": 55},
            {"min": 55, "max": 110},
            {"min": 110, "max": 9999999},
        ],
        "pm10": [
            {"min": 0, "max": 25},
            {"min": 25, "max": 50},
            {"min": 50, "max": 90},
            {"min": 90, "max": 180},
            {"min": 180, "max": 9999999},
        ],
    }

    air_quality_matrix = []
    for aq_key in air_quality_data:
        if aq_key in air_quality_definitions:
            # Check which level and by how far the air quality metric exceeds the definition
            air_quality_metrics = air_quality_definitions[aq_key]
            aq_value = air_quality_data[aq_key]
            index_offset = 1

            for air_quality_metric in air_quality_metrics:
                if (
                    aq_value >= air_quality_metric["min"]
                    and aq_value < air_quality_metric["max"]
                ):
                    air_quality_matrix.append(
                        {
                            "metric": air_quality_names[aq_key],
                            "level": index_offset,
                            "value": aq_value,
                            "min": air_quality_metric["min"],
                        }
                    )
                    break

                index_offset += 1

    return air_quality_matrix


def get_air_quality_qualitative_name(index: int) -> str:
    """
    Gets the qualitative name for the air quality based on the index ordinal supplied

    More information: https://openweathermap.org/api/air-pollution
    """

    if index == 1:
        return "Good"
    elif index == 2:
        return "Fair"
    elif index == 3:
        return "Moderate"
    elif index == 4:
        return "Poor"
    else:
        return "Very Poor"


def get_cover(w: Weather) -> str:
    return w.detailed_status


def get_temperature(w: Weather) -> str:
    temp_c = w.temperature("celsius")
    temp_f = w.temperature("fahrenheit")

    return "{}\u00B0C ({}\u00B0F)".format(
        round(temp_c["temp"], 1), round(temp_f["temp"], 1)
    )


def get_humidity(w: Weather) -> str:
    return "Humidity: {}%".format(w.humidity)


def get_wind(w: Weather) -> str:
    wind = w.wind("meters_sec")
    wind_k = w.wind("knots")

    speed_kts = round(wind_k["speed"], 1)
    speed_m_s = round(wind["speed"], 1)
    degrees = None
    if "deg" in wind:
        degrees = wind["deg"]

    if speed_kts < 1:
        description = "Calm"
    elif speed_kts < 4:
        description = "Light air"
    elif speed_kts < 7:
        description = "Light breeze"
    elif speed_kts < 11:
        description = "Gentle breeze"
    elif speed_kts < 16:
        description = "Moderate breeze"
    elif speed_kts < 22:
        description = "Fresh breeze"
    elif speed_kts < 28:
        description = "Strong breeze"
    elif speed_kts < 34:
        description = "Near gale"
    elif speed_kts < 41:
        description = "Gale"
    elif speed_kts < 48:
        description = "Strong gale"
    elif speed_kts < 56:
        description = "Storm"
    elif speed_kts < 64:
        description = "Violent storm"
    else:
        description = "Hurricane"

    if degrees is not None:
        if (degrees <= 22.5) or (degrees > 337.5):
            degrees = "\u2193"
        elif (degrees > 22.5) and (degrees <= 67.5):
            degrees = "\u2199"
        elif (degrees > 67.5) and (degrees <= 112.5):
            degrees = "\u2190"
        elif (degrees > 112.5) and (degrees <= 157.5):
            degrees = "\u2196"
        elif (degrees > 157.5) and (degrees <= 202.5):
            degrees = "\u2191"
        elif (degrees > 202.5) and (degrees <= 247.5):
            degrees = "\u2197"
        elif (degrees > 247.5) and (degrees <= 292.5):
            degrees = "\u2192"
        elif (degrees > 292.5) and (degrees <= 337.5):
            degrees = "\u2198"
    else:
        degrees = "Unknown direction"

    return "{} {}m/s ({})".format(description, speed_m_s, degrees)


def sanitize_field(field: str) -> str:
    """
    Santizes a field that is used to process user input by keeping alphanumeric (multilingual)
    characters only and stripping leading/trailing whitespace. Permits zero or one exclamation
    marks as the first character of the field
    """
    stripped_field = field.strip()
    if stripped_field[0:1] == "!":
        return f"!{__clean_field(stripped_field[1:])}"
    elif stripped_field[0:1] == "*":
        return f"*{__clean_field(stripped_field[1:])}"
    else:
        return __clean_field(stripped_field)


def __clean_field(field: str) -> str:
    """Performs a regex on a field"""

    # Unicode Regex Explanation:
    #
    # \p{Pf} : any kind of closing quote, such as "Martha's Vineyard, MA"
    # \p{L}  : any kind of letter from any language
    # \'     : single quote
    # \-     : dash, such as "Winston-Salem"
    # Space is important in the regex
    #
    # trunk-ignore(flake8/W605)
    return "".join(re.findall("[\p{Pf}\p{L}'\- ]", field.strip(), re.UNICODE))


def is_geolocation(location: str, separator: str = ";") -> bool:
    """
    Checks for the presence of a separator (default is a semi-colon) and if the
    coordinates are in valid ranges
    """

    geolocation = get_geolocation(location, separator)
    if geolocation is None:
        return False

    return is_lat_within_range(geolocation["latitude"]) and is_long_within_range(
        geolocation["longitude"]
    )


def get_geolocation(location: str, separator: str = ";") -> dict:
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
            candidate_longitude = candidate_longitude[: len(candidate_longitude) - 1]

        return {
            "latitude": float(candidate_latitude),
            "longitude": float(candidate_longitude),
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


def get_place_id(location: str) -> int:
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


def get_location_string(location: str) -> dict:
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
            "country": sanitize_field(location_elements[1].upper()),
        }

    # City
    else:
        return {"city": sanitize_field(location_elements[0])}


def construct_location_name(location: dict) -> str:
    """
    Constructs a location name based on the supplied dictionary of elements, ensuring that
    they are in the correct format
    """
    if location["type"] == "location":
        city_name = capwords(location["city"])
        if "country" in location:
            return f"{city_name},{location['country']}"
        else:
            return city_name

    elif location["type"] == "geocoords":
        return f"{location['latitude']},{location['longitude']}"

    elif location["type"] == "place_id":
        # Even if we have a place_id, if the city & country key is set, we want to return the city
        # and country name instead
        if "country" in location and "city" in location:
            city_name = capwords(location["city"])
            return f"{city_name},{location['country']}"

        elif "city" in location:
            city_name = capwords(location["city"])
            return location["city"]

        return str(location["place_id"])


def get_owm_locations(
    bot: SopelWrapper, location: dict
) -> Tuple[str, List[Tuple[int, str, str]]]:
    """
    Gets a list of OWM locations based on the supplied location search parameters
    """

    log.debug(
        "Getting weather results at location '%s'", construct_location_name(location)
    )
    api: OWM = get_owm_api(bot)

    if location["type"] == "location":
        try:
            owm_locations: List[Tuple[int, str, str]] = get_owm_locations_from_text(
                api, location
            )
            return (None, owm_locations)
        except ValueError as e:
            return (e, None)

    try:
        obs_weather: Observation = None
        if location["type"] == "place_id":
            obs_weather, _, _ = __get_observation_at_place_id(api, location)
        elif location["type"] == "geocoords":
            obs_weather, _, _ = __get_observation_at_geocoords(api, location)
        else:
            raise PyOWMError(
                f'Internal error: unknown location type "{obs_weather["type"]}"'
            )

        if obs_weather.location.country is not None:
            place_location = (
                obs_weather.location.id,
                obs_weather.location.name,
                obs_weather.location.country,
            )
        else:
            place_location = (obs_weather.location.id, obs_weather.location.name, "")

        return (None, [place_location])
    except NotFoundError:
        return (LOC_NOT_FOUND_MSG, None)


def check_owm_locations_list(
    location: dict,
    owm_locations: List[Tuple[int, str, str]],
    is_best_guess_location_pair: bool = False,
) -> Tuple[str, List[Tuple[int, str, str]]]:
    """
    Checks the OWM Locations list and returns a tuple with either an error message or a
    list of OWM locations that are valid for the query
    """

    # No locations
    if len(owm_locations) == 0:
        if "country" in location and location["country"] == "US":
            error_message = (
                f"{LOC_NOT_FOUND_MSG}. NOTE: For US cities only, you need to specify the "
                "2-letter state, not 'US'."
            )
        else:
            error_message = LOC_NOT_FOUND_MSG

        return (error_message, None)

    # Too many locations
    elif len(owm_locations) > OBSERVATION_LOOKUP_LIMIT:
        return (
            LOC_COLLISION_MSG.format(
                construct_location_name(location),
                # Parameter that is quoted for the OpenWeatherMap API URL
                quote_plus(location["city"]),
            ),
            None,
        )

    # Exactly one location
    elif len(owm_locations) == 1:
        return (None, owm_locations)

    # Handle complex OpenWeatherMap edge cases:
    # Name collision exists for the same city,country combination and we are have enabled
    # guessing the best location
    if is_best_guess_location_pair and is_location_combination_same_country(
        owm_locations
    ):
        log.debug("OWM Locations are the same country combination: %s", owm_locations)
        return (None, owm_locations)

    # Further refinement possible out of the list of locations
    else:
        return (
            LOC_REFINE_MSG.format(
                # Tuple (5367815, 'London', 'CA')
                str(
                    list(map(lambda x: "{},{}".format(x[1], x[2]), owm_locations))
                ).strip("[]")
            ),
            None,
        )


def is_location_combination_same_country(
    owm_locations: List[Tuple[int, str, str]]
) -> bool:
    """
    Checks to see if the list of owm_locations is the same combination of city,country pairs
    only distinguishable by place_id integers
    """

    if len(owm_locations) == 0:
        return False

    is_same_combination = True
    first_location = owm_locations[0]
    for location in owm_locations:
        if location[1] != first_location[1] or location[2] != first_location[2]:
            is_same_combination = False

    return is_same_combination


def get_owm_locations_from_text(api: OWM, location: dict) -> List[Tuple[int, str, str]]:
    """
    Gets a list of OWM location tuples from supplied text dictionary of location elements
    """
    if location["type"] != "location":
        log.warn(
            "There is no need to get an OWM location from text for any location that is not "
            "of type 'location'."
        )
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
        if len(location["country"]) > 2:
            raise ValueError("Country (or US state) must be a 2 character string.")

        owm_locations = registry.ids_for(
            city_name=location["city"],
            country=location["country"],
            matching=search_type,
        )
    else:
        owm_locations = registry.ids_for(
            city_name=location["city"], matching=search_type
        )

    # If DEBUG is turned on
    # https://docs.python.org/3/library/logging.html#levels
    if log.getEffectiveLevel() == 10:
        log.debug(
            "Found %d candidate city ids for name '%s'",
            len(owm_locations),
            construct_location_name(location),
        )
        for city_id in owm_locations:
            log.debug("\t %s", city_id)

    return owm_locations
