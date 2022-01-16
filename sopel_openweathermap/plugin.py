# -*- coding: utf-8 -*-
import argparse
from datetime import datetime
from pyowm import OWM
# from pyowm.exceptions.api_response_error import NotFoundError, UnauthorizedError
# from pyowm.exceptions.api_call_error import APICallError
from sopel import module
from sopel import plugin, tools  # type: ignore
from sopel.bot import Sopel, SopelWrapper  # type: ignore
from sopel.config import Config  # type: ignore
from sopel.trigger import Trigger  # type: ignore

from .utils import OWMSection, get_api, parse_location_args, get_weather_message, get_owm_location

log = tools.get_logger('openweathermap')


# --- Sopel Setup Section ---

def configure(config):
    log.debug(type(config))
    config.define_section("owm", OWMSection)
    config.owm.configure_setting("api_key", "What is your OpenWeatherMap.org API Key or APPID?")


def setup(bot: SopelWrapper) -> None:
    """ Ensures that our set up configuration items are present """
    # Ensure configuration
    bot.config.define_section('owm', OWMSection)

    # Load our OWM API into bot memory
    if 'owm' not in bot.memory:
        api_key = bot.config.owm.api_key
        owm_api = get_api(api_key)
        bot.memory['owm'] = tools.SopelMemory()
        bot.memory['owm']['api'] = owm_api

def shutdown(bot: SopelWrapper) -> None:
    del bot.memory['owm']

def get_owm_api(bot: SopelWrapper) -> OWM:
    """
    Retrieves the OWM API endpoint from the bot's memory
    """

    if 'owm' not in bot.memory:
        log.error("Sopel memory does not contain the OpenWeatherMap configuration section. "
                  "Ensure that it has been configured using the setup() method.")
        return None

    if 'api' not in bot.memory['owm']:
        log.error("Sopel memory does not contain an initialized OpenWeatherMap API."
                  "Ensure that it has been configured using the setup() method.")
        return None

    return bot.memory['owm']['api']

# --- End Sopel Setup Section ---

@module.commands('weather', 'wea')
@module.example('.weather London',
    'Gets the weather for London and returns the first result. Use a US-state or Country suffix to get '
    'more accurate information, such as London,GB or London,CA')
@module.rate(server=1)
def get_weather(bot: SopelWrapper, trigger: Trigger) -> None:
    """
    Gets the weather at a given location and returns the first result
    """
    location_lookup_args = trigger.group(2)
    if location_lookup_args is None:

        location_lookup_args = bot.db.get_nick_value(trigger.nick, 'place_id')
        if not location_lookup_args:
            bot.reply("I don't know where you live. "
                      "Give me a location, like {pfx}{command} London, "
                      "or tell me where you live by saying {pfx}setlocation "
                      "London, for example.".format(command=trigger.group(1),
                                                    pfx=bot.config.core.help_prefix))
            return plugin.NOLIMIT

    api = get_owm_api(bot)
    location = parse_location_args(location_lookup_args)
    message = get_weather_message(api, location)
    bot.reply(message)

@module.commands('setlocation', 'setcityid')
@module.example('.setlocation Columbus, OH')
def setlocation(bot, trigger):
    """
    Sets a nick's default city location
    """

    location_lookup_args = trigger.group(2)
    if location_lookup_args is None:
        bot.reply('Give me a location, like "Washington, DC" or "London".')
        return plugin.NOLIMIT

    api = get_owm_api(bot)
    location = parse_location_args(location_lookup_args)
    (error_message, owm_location) = get_owm_location(api, location)

    if error_message is not None:
        bot.reply(error_message)
        return 0

    (place_id, city, country) = owm_location
    bot.db.set_nick_value(trigger.nick, "place_id", place_id)
    bot.reply(f"I now have you at ID {place_id}: {city},{country}")
