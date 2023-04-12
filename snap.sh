#!/bin/bash

DATETIME=$(date)
PLATFORM=$(hostname)
MESSAGE="${PLATFORM}: ${DATETIME}"
python3 /home/pi/birdboxes/msnap.py $PLATFORM "$MESSAGE"


