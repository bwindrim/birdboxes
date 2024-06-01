#!/bin/bash
if [ ! -d /sys/class/gpio/gpio5 ] ; then
	echo 5 >/sys/class/gpio/export
fi
echo out >/sys/class/gpio/gpio5/direction
if [ ! -d /sys/class/gpio/gpio4 ] ; then
	echo 4 >/sys/class/gpio/export
fi
old=$(cat /sys/class/gpio/gpio5/value)
new=$(cat /sys/class/gpio/gpio4/value)
echo 1 >/sys/class/gpio/gpio5/value

FILE=$(date +"BB1_%FT%H-%M-%S.jpg")
LOCAL_PATH=/mnt/local/timelapse
REMOTE_PATH=/mnt/remote/birdbox1/timelapse

/usr/bin/raspistill -awb off -awbg '1.0,1.0' -n -t 500 -w 1024 -h 768 -q 75 -o $LOCAL_PATH/$FILE
echo $old >/sys/class/gpio/gpio5/value
chmod a-w $LOCAL_PATH/$FILE

if [ -d "$REMOTE_PATH" ]; then
    cp -p $LOCAL_PATH/$FILE $REMOTE_PATH/$FILE
fi
