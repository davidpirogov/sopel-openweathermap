# sopel-openweathermap
An OpenWeatherMap module for looking up the weather using the Sopel IRC bot

# Installation
Tested on Ubuntu 16.04 LTS. Requires python 3.5, [pyowm](https://github.com/csparpa/pyowm), and [Sopel](https://github.com/sopel-irc/sopel)

```bash
pip3 install sopel pyowm
```

# Configuration
1. Retrieve an API key from [OpenWeatherMap](https://openweathermap.org/api)
2. Run the sopel configuration option to set up the module in the bot:
```bash
sopel -w
```
3. Disable the existing, non-functioning Sopel weather module by editing the default.cfg file and adding/appending to the core exclude list
```ini
[core]
...
exclude=weather
```

# Usage
Commands for retrieving the weather from OpenWeatherMap are:
```
.weather Melbourne
```

If you want the bot to remember your location, so in future you just need to enter ```.weather```:
```
.setlocation Melbourne
```

# Testing

Ensure you have your API Key or APPID ready. Assuming the API Key below is ```a1b2c3...x8z9```
```bash
$ python3 owm-weather.py a1b2c3...x8z9 --location="Melbourne,AU"
Getting observation for location Melbourne,AU
Melbourne: clear sky 42.4°C (108.3°F) Humidity: 11% Moderate breeze 8.2m/s (↘)
Getting locations for location Melbourne,AU
Melbourne,AU has place id 2158177
```

