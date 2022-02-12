from urllib.parse import quote_plus

from sopel import module, plugin, tools
from sopel.bot import SopelWrapper
from sopel.config import Config
from sopel.trigger import Trigger

from .utils import (
    LOC_COLLISION_MSG,
    OWMSection,
    construct_location_name,
    get_api,
    get_owm_locations,
    get_weather_message,
    parse_location_args,
)

log = tools.get_logger("openweathermap")


# --- Sopel Setup Section ---


def configure(config: Config):
    config.define_section("owm", OWMSection)
    config.owm.configure_setting(
        "api_key", "What is your OpenWeatherMap.org API Key or APPID?"
    )

    config.owm.configure_setting(
        "enable_air_quality",
        "Do you have a version of PyOWM that supports air quality and want to enable it?",
        default=False,
    )

    config.owm.configure_setting(
        "enable_location_best_guess",
        "Do you want to enable location best guess when there are city duplicates?",
        default=True,
    )


def setup(bot: SopelWrapper) -> None:
    """Ensures that our set up configuration items are present"""
    # Ensure configuration
    bot.config.define_section("owm", OWMSection)

    # Load our OWM API into bot memory
    if "owm" not in bot.memory:
        api_key = bot.config.owm.api_key
        owm_api = get_api(api_key)
        bot.memory["owm"] = tools.SopelMemory()
        bot.memory["owm"]["api"] = owm_api
        bot.memory["owm"]["enable_air_quality"] = bot.config.owm.enable_air_quality
        bot.memory["owm"][
            "enable_location_best_guess"
        ] = bot.config.owm.enable_location_best_guess


def shutdown(bot: SopelWrapper) -> None:
    del bot.memory["owm"]


# --- End Sopel Setup Section ---


@module.commands("weather", "wea")
@module.example(
    ".weather London",
    "Gets the weather for London and returns the first result. Use a US-state or Country suffix to get "
    "more accurate information, such as London,GB or London,CA",
)
@module.rate(server=1)
def get_weather(bot: SopelWrapper, trigger: Trigger) -> None:
    """
    Gets the weather at a given location and returns the first result
    """
    location_lookup_args = trigger.group(2)
    if location_lookup_args is None:

        location_lookup_args = bot.db.get_nick_value(trigger.nick, "place_id")
        if not location_lookup_args:
            bot.reply(
                "I don't know where you live. "
                "Give me a location, like {pfx}{command} London, "
                "or tell me where you live by saying {pfx}setlocation "
                "London, for example.".format(
                    command=trigger.group(1), pfx=bot.config.core.help_prefix
                )
            )
            return plugin.NOLIMIT

    location = parse_location_args(location_lookup_args)
    message = get_weather_message(bot, location)
    bot.reply(message)


@module.commands("setlocation", "setcityid")
@module.example(".setlocation Columbus, OH")
def setlocation(bot: SopelWrapper, trigger: Trigger):
    """
    Sets a nick's default city location
    """

    location_lookup_args = trigger.group(2)
    if location_lookup_args is None:
        bot.reply('Give me a location, like "Washington,DC" or "London".')
        return plugin.NOLIMIT

    location = parse_location_args(location_lookup_args)
    (error_message, owm_locations) = get_owm_locations(bot, location)

    if error_message is not None:
        bot.reply(error_message)
        return 0
    elif len(owm_locations) > 1:
        bot.reply(
            LOC_COLLISION_MSG.format(
                construct_location_name(location), quote_plus(location["city"])
            )
        )
        return 0

    (place_id, city, country) = owm_locations[0]
    bot.db.set_nick_value(trigger.nick, "place_id", place_id)
    bot.reply(f"I now have you at ID {place_id}: {city},{country}")
