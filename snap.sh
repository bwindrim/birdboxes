#!/bin/bash

FILE=$(date +"BB1_%FT%H-%M-%S.jpg")
LOCAL_PATH=/mnt/local/timelapse
REMOTE_PATH=/mnt/remote/birdbox1/timelapse

/usr/bin/raspistill -awb off -awbg '1.0,1.0' -n -t 500 -w 640 -h 480 -q 75 -o $LOCAL_PATH/$FILE
chmod a-w $LOCAL_PATH/$FILE

if [ -d "$REMOTE_PATH" ]; then
    cp -p $LOCAL_PATH/$FILE $REMOTE_PATH/$FILE
fi
