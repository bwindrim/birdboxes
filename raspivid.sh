#!/bin/bash

FILE=$(date +"BB1_%FT%H-%M-%S.h264")

/usr/bin/raspivid -awb off -awbg '1.0,1.0' -t 0 -n -w 640 -h 480 -o - | tee --output-error=exit /mnt/capture/$FILE

