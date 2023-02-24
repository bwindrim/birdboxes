#!/bin/bash

/usr/sbin/i2cset -y 1 0x41 5   180 b # set 3-minute watch timeout
/usr/sbin/i2cset -y 1 0x41 6 14400 w # set to wake after 4 hours

counter=15 # 15-minute countdown until shutdown

while true;
do
    echo "counter = " $counter
    /usr/sbin/i2cget -y 1 0x41 1 b # read the PicoWatcher status to reset watch count

    if [ $counter -le 0 ]
    then
        # Ensure that we'll shutdown even if the battmon service doesn't start
        /sbin/shutdown now "Backstop 15-minute shutdown from piwatcher.service"
    fi

    ((counter--))
    sleep 60
done

