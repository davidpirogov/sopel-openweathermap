# -*- coding: utf-8 -*-
import argparse
from datetime import datetime
from pyowm import OWM
from pyowm.exceptions.api_response_error import NotFoundError, UnauthorizedError
from pyowm.exceptions.api_call_error import APICallError

LOC_NOT_FOUND_MSG = "Could not find your location. Try refining with <city>,<two-letter-country-code> such as Melbourne,AU or Melbourne,US"
API_OFFLINE_MSG = "The OpenWeatherMap API is not currently online. Try again later."
OBSERVATION_LOOKUP_LIMIT = 3

try:
    import sopel
    from sopel import tools
    from sopel import module
    from sopel.module import commands, example, NOLIMIT
    from sopel.config.types import StaticSection, ValidatedAttribute
except ImportError:
    # Probably running from the command line
    pass


@sopel.module.commands('weather', 'wea')
@sopel.module.example('.weather London', 'Gets the weather for London and returns the first result. Use a country suffix to get more accurate information, such as London,GB.',
                      'Can also use a latitude,longitude decimal notation search, along with a specific OWM ID search')
@sopel.module.rate(server=1)
def weather(bot, trigger):
    """
    .weather location - show the weather at a given location and returns the first result. Use a country suffix to get more accurate information, such as London,GB.
    Can also use a latitude,longitude decimal notation search, along with a specific OWM ID search
    """
    location_lookup = trigger.group(2)
    if not location_lookup:
        location_lookup = bot.db.get_nick_value(trigger.nick, 'place_id')
        if not location_lookup:
            bot.reply("I don't know where you live. "
                      "Give me a location, like {pfx}{command} London, "
                      "or tell me where you live by saying {pfx}setlocation "
                      "London, for example.".format(command=trigger.group(1),
                                                    pfx=bot.config.core.help_prefix))
            return

    api = bot.memory['owm']['api']
    message = get_weather(api, location_lookup)
    say_info(bot, message)


@sopel.module.commands('setlocation', 'setcityid')
@sopel.module.example('.setlocation Columbus, OH')
def setlocation(bot, trigger):
    """ Sets a nick's default city location """
    if not trigger.group(2):
        bot.reply('Give me a location, like "Washington, DC" or "London".')
        return NOLIMIT

    api = bot.memory['owm']['api']
    location_lookup = trigger.group(2)
    location_group_list = lookup_location(api, location_lookup)
    location_list = []
    if len(location_group_list) == 0:
        # Attempt to load observations based on the nearest place to this lookup
        # and pull the locations from that set
        observations = lookup_observations_at_place(api, location_lookup)
        for obs in observations:
            location_list.append(obs.get_location())
    else:
        # Load locations based on the group list supplied with a direct lookup
        for lg in location_group_list:
            location_name = lg['name']
            location_group = lg['locations']
            if len(location_group) > 0:
                location_list.append({'name': location_name, 'location': location_group[0]})

    if len(location_list) > 1:
        location_refine_message = "Please refine your location by adding a country code (case sensitive). Valid options are: {}".format(
            str(list(map(lambda x: "{},{}".format(x.get_name(), x.get_country()), location_list))).strip('[]'))
        bot.reply(location_refine_message)
    elif len(location_list) == 0:
        bot.reply(LOC_NOT_FOUND_MSG)
    else:
        location = location_list.pop()
        if isinstance(location, dict):
            location = location['location']

        name = location.get_name()
        country = location.get_country()
        place_id = location.get_ID()

        bot.db.set_nick_value(trigger.nick, "place_id", place_id)
        bot.reply("I now have you at ID #{}: {},{}".format(place_id, name, country))


class OWMSection(StaticSection):
    api_key = ValidatedAttribute('api_key', str, default="")


def configure(config):
    config.define_section("owm", OWMSection)
    config.owm.configure_setting("api_key", "What is your OpenWeatherMap.org API Key or APPID?")


def setup(bot):
    """ Ensures that our set up configuration items are present """
    # Ensure configuration
    bot.config.define_section('owm', OWMSection)

    # Load our OWM API into bot memory
    if 'owm' not in bot.memory:
        api_key = bot.config.owm.api_key
        owm_api = get_api(api_key)
        bot.memory['owm'] = tools.SopelMemory()
        bot.memory['owm']['api'] = owm_api


def shutdown(bot):
    del bot.memory['owm']

# --- End Sopel Code Section ---


def get_weather(api, location_lookup):
    """ Gets the weather at a location or any error messages """
    try:
        approx_observation = False
        if is_place_id(location_lookup):
            observation = api.weather_at_id(int(location_lookup))
        elif is_place_coords(location_lookup):
            coords = get_place_coords(location_lookup)
            observation = api.weather_at_coords(coords[0], coords[1])
        else:
            location_group_list = lookup_location(api, location_lookup)
            if len(location_group_list) == 0:
                approx_observation = True

            if approx_observation:
                # Do an approximate search for location
                observations = lookup_observations_at_place(api, location_lookup)
            else:
                # Get the first result from our location group list
                location_group_set = location_group_list[0]
                location_group = location_group_set['locations']
                observations = []
                uvs = []
                location = location_group[0]
                observations = lookup_observations_at_place(api, "{},{}".format(location.get_name(), location.get_country()), 'accurate')
                uvs.append(get_uv_index(api, location))

            if len(observations) == 0:
                raise NotFoundError(cause='No observations found')

            observation = observations[0]

        # Format our observation into the appropriate message
        location_text = "{},{}".format(observation.get_location().get_name(), observation.get_location().get_country())
        if approx_observation:
            # Highlight that an approximate location was found
            location_text = "{}(*)".format(location_text)

        weather = observation.get_weather()
        uv = get_uv_index(api, observation.get_location())
        message = format_weather_message(location_text, weather, uv)
    except NotFoundError:
        global LOC_NOT_FOUND_MSG
        message = LOC_NOT_FOUND_MSG
    except UnauthorizedError as ue:
        message = str(ue)
    except APICallError:
        global API_OFFLINE_MSG
        message = API_OFFLINE_MSG

    return message


def get_weather_at_location(api, location):
    """ Looks up an observation at a specific location id """
    observation = lookup_observation(api, location.get_id())
    return observation


def format_weather_message(location, weather, uv):
    cover = get_cover(weather)
    temp = get_temperature(weather)
    humidity = get_humidity(weather)
    wind = get_wind(weather)
    uv_index = round(uv.get_value(), 1)
    uv_risk = uv.get_exposure_risk()

    return "{}: {} {} {} {} UV Index {} ({} at local solar noon)".format(location, cover, temp, humidity, wind, uv_index, uv_risk)


def get_uv_index(api, location):
    uv = api.uvindex_around_coords(location.get_lat(), location.get_lon())
    return uv


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


def lookup_location(api, location_lookup):
    """ Looks up a location to see if it's valid """
    registry = api.city_id_registry()

    # Split the location on a comma if there is a country
    # e.g., "Wellington,NZ" because that country needs to be
    # supplied as a separate parameter in registry.locations_for
    loc = location_lookup.split(',')
    loc_lookup = loc[0].strip()
    loc_country = ""
    if len(loc) > 1:
        loc_country = loc[1].strip()

    # Look up the registery for our locations
    # Available accuracy: 'exact', 'like', 'nocase'
    lookup_accuracy = 'like'
    if not loc_country:
        locations = registry.locations_for(loc_lookup, matching=lookup_accuracy)
    else:
        locations = registry.locations_for(loc_lookup, country=loc_country, matching=lookup_accuracy)

    # location_list structure is: { "Melbourne,AU": [ multiple, locations ] }
    location_group_list = []
    for l in locations:
        # Only append to the location list if the location lookup name is identical to the location name
        if l.get_name() == loc_lookup:
            canonical_name = "{},{}".format(l.get_name(), l.get_country())
            if not any(d.get('name', None) == canonical_name for d in location_group_list):
                location_group_list.append({'name': canonical_name, 'locations': []})

            location_list = [ll for ll in location_group_list if ll['name'] == canonical_name][0]
            location_list['locations'].append(l)

    location_group_list.sort(key=lambda x: x['name'])
    return location_group_list


def lookup_observation(api, location):
    """ Looks up the observation based on the location value provided """
    if is_place_id(location):
        observation = api.weather_at_id(int(location))
    elif is_place_coords(location):
        coords = get_place_coords(location)
        observation = api.weather_at_coords(coords[0], coords[1])
    else:
        observation = api.weather_at_place(name=location)

    return observation


def lookup_observations_at_place(api, location_lookup, searchtype='like'):
    observations = api.weather_at_places(location_lookup, searchtype=searchtype, limit=OBSERVATION_LOOKUP_LIMIT)
    return observations


def lookup_weather(api, location):
    observation = lookup_observation(api, location)
    weather = observation.get_weather()
    return weather


def get_api(api_key):
    """ Retrieves the OWM API object based on the supplied key """
    if len(str(api_key).strip()) == 0:
        raise ValueError("The API Key is blank or empty")

    # This place can be used to change OWM behaviour, incl subscription type, language, etc.
    # See https://pyowm.readthedocs.io/en/latest/usage-examples-v2/weather-api-usage-examples.html#create-global-owm-object
    owm = OWM(api_key)
    return owm


def is_place_id(location):
    """ Checks whether or not the city lookup can be cast to an int, representing a OWM Place ID """
    try:
        int(location)
        return True
    except (TypeError, ValueError):
        return False


def is_place_coords(location):
    """
    Checks whether or not coordinates exist and are able to be cast to a float.
    From OWM documentation:
        - The location's latitude, must be between -90.0 and 90.0
        - The location's longitude, must be between -180.0 and 180.0
    More info: https://github.com/csparpa/pyowm/blob/master/pyowm/weatherapi25/owm25.py#L234
    """
    try:
        coords = get_place_coords(location)

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


def get_place_coords(location):
    """
    Parses a geo coord in the form of (latitude,longitude) and returns
    them as an array. Note that a simple "latitude,longitude" is also
    valid as a coordinate set
    """
    latitude, longitude = map(float, location.strip('()[]').split(','))
    return [latitude, longitude]


def say_info(bot, info_text):
    """ Outputs a specific bit of infomational text for the channel """
    bot.say(info_text)


def get_argparser():
    parser = argparse.ArgumentParser()
    parser.add_argument("api_key", help="Your OpenWeatherMap API key or APPID key")
    parser.add_argument("--location", help="Optional lookup value, either a city name, coords, or city id.")
    return parser


if __name__ == "__main__":
    """ Test harness for when running outside of Sopel """
    parser = get_argparser()
    args = parser.parse_args()

    api_key = args.api_key
    location_lookup = args.location
    if location_lookup is None:
        location_lookup = 'Melbourne'

    print("Looking up weather for location '{}'".format(location_lookup))
    api = get_api(api_key)
    message = get_weather(api, location_lookup)
    print(message)

    print("Getting locations for location '{}'".format(location_lookup))
    location_group_list = lookup_location(api, location_lookup)
    location_list = []
    if len(location_group_list) == 0:
        # Attempt to load observations based on the nearest place to this lookup
        # and pull the locations from that set
        observations = lookup_observations_at_place(api, location_lookup)
        for obs in observations:
            location_list.append(obs.get_location())
    else:
        # Load locations based on the group list supplied with a direct lookup
        for lg in location_group_list:
            location_name = lg['name']
            location_group = lg['locations']
            if len(location_group) > 0:
                location_list.append({'name': location_name, 'location': location_group[0]})

    if len(location_list) > 1:
        location_refine_message = "Please refine your location by adding a country code. Valid options are: {}".format(str(list(map(lambda x: x['name'], location_list))).strip('[]'))
        print(location_refine_message)
    elif len(location_list) == 0:
        print(LOC_NOT_FOUND_MSG)
    else:
        location = location_list.pop()
        name = location['location'].get_name()
        country = location['location'].get_country()
        place_id = location['location'].get_ID()

        print("{},{} has place id {}".format(name, country, place_id))
