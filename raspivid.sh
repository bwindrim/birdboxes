#!/bin/bash

FILE=$(date +"BB3_%FT%H-%M-%S.h264")
LOCAL_PATH=/mnt/local/video

/usr/bin/raspivid -awb off -awbg '1.0,1.0' -t 0 -n -w 640 -h 480 -o - | tee --output-error=exit $LOCAL_PATH/$FILE
chmod a-w $LOCAL_PATH/$FILE
