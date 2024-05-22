#!/bin/bash
if [ ! -d /sys/class/gpio/gpio5 ] ; then
	echo 5 >/sys/class/gpio/export
fi
if [ ! -d /sys/class/gpio/gpio4 ] ; then
	echo 4 >/sys/class/gpio/export
fi
old=$(cat /sys/class/gpio/gpio5/value)
new=$(cat /sys/class/gpio/gpio4/value)
echo $new >/sys/class/gpio/gpio5/value

FILE=$(date +"BB1_%FT%H-%M-%S.jpg")
LOCAL_PATH=/mnt/local/photo

/usr/bin/raspistill -awb off -awbg '1.0,1.0' -n -t 500 -w 640 -h 480 -q 75 -o - | tee $LOCAL_PATH/$FILE
chmod a-w $LOCAL_PATH/$FILE

echo $old >/sys/class/gpio/gpio5/value
