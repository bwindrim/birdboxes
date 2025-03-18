#!/bin/bash
if [ ! -d /sys/class/gpio/gpio5 ] ; then
	echo 5 >/sys/class/gpio/export
fi
if [ ! -d /sys/class/gpio/gpio6 ] ; then
	echo 6 >/sys/class/gpio/export
fi
cat /sys/class/gpio/gpio5/value
cat /sys/class/gpio/gpio6/value
old=$(cat /sys/class/gpio/gpio5/value)
new=$(cat /sys/class/gpio/gpio6/value)
echo $new >/sys/class/gpio/gpio5/value
cat /sys/class/gpio/gpio5/value
cat /sys/class/gpio/gpio6/value
DATETIME=$(date)
PLATFORM=$(hostname)
MESSAGE="${PLATFORM}: ${DATETIME}"
python3 /home/pi/birdboxes/msnap.py $PLATFORM "$MESSAGE"
echo $old >/sys/class/gpio/gpio5/value
cat /sys/class/gpio/gpio5/value
cat /sys/class/gpio/gpio6/value



