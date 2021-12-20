#!/usr/bin/env python
import os
import sys

try:
    from setuptools import setup
except ImportError:
    print(
        'You do not have setuptools isntalled and can not install this module. The easiest '
        'way to fix this is to install pip by following the instructions at '
        'https://pip.readthedocs.io/en/latest/installing/\n',
        file=sys.stderr,
    )
    sys.exit(1)


if __name__ == '__main__':
    print('Sopel does not correctly load plugins installed with setup.py directly. '
          'Please use "pip install ." or add '
          f'{os.path.dirname(os.path.abspath(__file__))}/sopel_openweathermap '
          'to core.extra in your configuration file.',
          file=sys.stderr)


with open('README.md') as readme_file:
    readme = readme_file.read()

setup(
    long_description=f"{readme}\n\n",
    long_description_content_type="text/markdown"
)
