#!/bin/bash

FILE=$(date +"BB3_%FT%H-%M-%S.jpg")

/usr/bin/raspistill -n -t 500 -rot 180 -w 640 -h 480 -q 75 -o - | tee /tmp/$FILE

