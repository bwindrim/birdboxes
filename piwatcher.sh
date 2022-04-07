#!/bin/bash

/usr/local/bin/piwatcher watch 180  # set 3-minute watchdog timeout
/usr/local/bin/piwatcher wake 14400 # set to wake after 4 hours

# Ensure that we'll shutdown even if the battmon service doesn't start
/sbin/shutdown +15 "Backstop 15-minute shutdown from piwatcher.service"

while true;
do
    /usr/local/bin/piwatcher status # >> /dev/null
    sleep 60
done

