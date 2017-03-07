# Timmy's Danbooru Twitter Bot

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

A Danbooru Twitter bot using a set hourly schedule. This is the same exact script that runs the [Anime School Girls Bot](https://twitter.com/SchoolGirlsBot) on Twitter.

## Requirements

- Python 3.3 or later
- [`requests`](https://pypi.python.org/pypi/requests), [`schedule`](https://pypi.python.org/pypi/schedule), and [`tweepy`](https://pypi.python.org/pypi/tweepy) libraries. You can use `pip install -r requirements.txt` to automatically install those required libraries.

## Setup and Use

Before running the bot, set up `config.json`. You can use the provided [`config_example.json`](./config_example.json) file as a template.

To start, use the following command: `python3 dbtweets.py`.

To terminate, simply press `Ctrl-C`.

---

Copyright 2017 Pokémon Trainer Timmy. Licensed under the MIT License.
