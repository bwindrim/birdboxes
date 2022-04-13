#!/bin/bash

/usr/local/bin/piwatcher watch 180  # set 3-minute watchdog timeout
/usr/local/bin/piwatcher wake 14400 # set to wake after 4 hours

counter=15 # 15-minute countdown until shutdown

while true;
do
    echo "counter = " $counter
    /usr/local/bin/piwatcher status # >> /dev/null

    if [ $counter -le 0 ]
    then
        # Ensure that we'll shutdown even if the battmon service doesn't start
        /sbin/shutdown now "Backstop 15-minute shutdown from piwatcher.service"
    fi

    ((counter--))
    sleep 60
done

