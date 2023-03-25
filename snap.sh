#!/bin/bash

DATETIME=$(date)
PLATFORM="BirdBox3"
MESSAGE="${PLATFORM}: ${DATETIME}"
python3 /home/pi/birdboxes/msnap.py $PLATFORM "$MESSAGE"


