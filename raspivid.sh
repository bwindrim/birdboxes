#!/bin/bash

FILE=$(date +"BB3_%FT%H-%M-%S.h264")

/usr/bin/raspivid -t 0 -n -w 640 -h 480 -rot 180 -o - | tee --output-error=exit /tmp/$FILE

