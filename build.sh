#!/bin/bash
set -e
# syntax checking
pyflakes3 myenergi_display/*.py
# code style checking
pycodestyle --max-line-length=250 myenergi_display/*.py
poetry -vvv build

