# Sopel OpenWeatherMap

An OpenWeatherMap module for looking up the weather using the Sopel IRC bot

## Installation

Tested on Ubuntu 20.04 LTS. Requires python 3.7, [pyowm v3](https://github.com/csparpa/pyowm), and
[Sopel 7.1](https://github.com/sopel-irc/sopel)

Highly recommended to create a separate [pyenv environment](https://realpython.com/intro-to-pyenv/)
for the Sopel bot and use pip to install the repository. The plugin will be available to Sopel
as an [Entry point plugin](https://sopel.chat/docs/plugin.html#term-Entry-point-plugin)

```bash
pyenv virtualenv sopel_7_1
pip install sopel
cd .../sopel-openweathermap
pip install .
pip install -r requirements.txt
```

## Configuration

The plugin has several configuration options with sensible defaults.

### api_key

Type: `string`

Mandatory option that must be specified in the configuration file. Get your API key from
[OpenWeatherMap](https://openweathermap.org/api).

### enable_air_quality

Type: `bool` (True or False)

Default: `False`

Whether or not to enable the Air Quality measurement for the weather message. Ensure that you have
an up to date version of PyOWM that has correct air quality APIs.

### enable_location_best_guess

Type: `bool` (True or False)

Default: `True`

Whether or not to enable a location best guess attempt when there are multiple, identical results
for the same city,country combination. Due to OpenWeatherMap data quality issues, setting this
option to `True` returns a temperature range with a link to find the correct place id. Setting
this option to `False` makes the user choose a correct place id.

### HOWTO

1. Retrieve an API key from [OpenWeatherMap](https://openweathermap.org/api)
2. Run the sopel configuration option to set up the module in the bot:

   ```bash
   sopel -w
   ```

3. Disable the existing, non-functioning Sopel weather module by editing the default.cfg file and
   adding/appending to the core exclude list

```ini
[core]
...
exclude=weather
```

### Alternative Configuration

For those who don't like running interactive `sopel -w` you need to add to the default.cfg file
the following with your OWM API Key or APPID

```ini
[owm]
api_key=...
enable_air_quality=False
enable_location_best_guess=True
```

## Usage

The OpenWeatherMap API retrieves information based on the supplied location. There are three
ways to request a location:

1. A unique, numeric id that is the most accurate way to express a location
   - For example, [London,GB](https://openweathermap.org/city/2643743) has the id of `2643743`, which can be extracted from the API or from the URL
2. A geo coordinate in the form of decimal latitude,longitude
   - Latitude and Longitude must be a decimal within the valid ranges
   - Permitted separators are semi-colon `;` and comma `,`
   - For compatibility with the OpenWeatherMap website, any square brackets around the geo coordinates are stripped out
3. Text that represents a city, country pair. There are several caveats
   - Cities in the US need to use the city, 2-letter US state abbreviation
   - Cities outside of the US need to use the city, 2-letter Country abbreviation
   - To search for a city name with exact match to the search term, use the `!` character before the city name. For example, `!London,GB`
   - To search for a city that contains the search term, use the `*` character before the city name. For example, `*London,GB`

### IRC commands

IRC commands for retrieving the weather from OpenWeatherMap are:

```bash
.weather Melbourne,AU
.weather New York
.weather 1850147                // Unique ID of Tokyo, JP
.weather 24.4667, 54.3667       // Closest city is Abu Dhabi, AE
```

You can also use `.weather` without specifying anything if you have previously taught the bot your location via `.setlocation`.

For example:

```bash
.setlocation New York
```

**Note**: The `.setlocation` command works on the basis of your nickname, meaning that changes to nickname require an additional `.setlocation` to be called.

## Testing

Tests are run via Python unittests and are stored in the `tests/` directory.

```bash
python -m unittest
```
