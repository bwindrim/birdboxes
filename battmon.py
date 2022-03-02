import sys
import time
import subprocess
import RPi.GPIO as GPIO
from datetime import datetime

# Use BCM GPIO references instead of physical pin numbers
GPIO.setmode(GPIO.BCM)

# Define GPIO signals to use
battery = [6,12,13,26]

GPIO.setup(battery, GPIO.IN, pull_up_down=GPIO.PUD_UP)

def seconds(days, hours, mins, secs):
    "TBD"
    return ((days*24 + hours) * 60 + mins) * 60 + secs

def piwatcher_status():
    "Query PiWatcher to reset watchdog timer"
    result = subprocess.run(["/usr/local/bin/piwatcher", "status"], capture_output=True)
    print("PiWatcher status =", result)
    
def piwatcher_led(state):
    "Switch the PiWatcher LED on or off"
    
    setting = "off"
    
    if state:
        setting = "off"
        
    result = subprocess.run(["/usr/local/bin/piwatcher", "led", setting], capture_output=True)
    print("PiWatcher status =", result)
    
def piwatcher_wake(seconds):
    "Set the wake interval for PiWatcher"
    result = subprocess.run(["/usr/local/bin/piwatcher", "wake", str(seconds)], capture_output=True)
    print("PiWatcher wake =", result)
    
def piwatcher_watch(seconds):
    "Set the watchdog timeout interval for PiWatcher"
    #result = "not run"
    result = subprocess.run(["/usr/local/bin/piwatcher", "watch", str(seconds)], capture_output=True)
    print("PiWatcher watch =", result)
    
def system_shutdown(msg="System going down", when="now"):
    "Shut down the system"
    print("Shutting down:", msg)
    result = subprocess.run(["/usr/sbin/shutdown", when, str(msg)])
    print("shutdown =", result)
    
def getBatteryLevel(numReads):
    "Read the battery level via the GPIOs"
    
    level = 0

    for i in range(numReads):
        for pin in battery:
            level += (1 - GPIO.input(pin))

    return level

def hours(num):
    "Returns the duration in seconds of the specified number of hours"
    return num*60*60

# main program 
try:
    # Set a default wakeup of 8 hours. This will apply if the system is
    # forcibly restarted by the watchdog.
    piwatcher_wake(hours(8))
    piwatcher_watch(120)     # set 2-minute watchdog timeout
    piwatcher_led(False)     # turn off the LED
    system_shutdown("Midnight shutdown", when="23:59")
    
    # All absolute times are in seconds from the start of today (00:00)
    t = time.localtime()
    h = t.tm_hour
    m = h*60 + t.tm_min 
    s = m*60 + t.tm_sec # second in the day
    
    if h in range(12,13):
        #It's between midnight and 9am, shut down until 9am
        wake_time_rel = seconds(1,9,0, 0) - s
        piwatcher_wake(wake_time_rel)
        system_shutdown("It's between midnight and 9am, shutting down until 9am")
    
    
    while True:
        piwatcher_status()  # reset the watchdog

        level = 60 # getBatteryLevel(20)
        print ("Battery level = ", level)
        
        if level <= 20: # 1 battery bar or less
            # battery is critically low, shut down for 24 hours,
            # don't stop to take pictures
            print("Battery <= 20, emergency shutdown")
            piwatcher_wake(hours(24))
            system_shutdown("Emergency shutdown, battery critical")
        elif level <= 40: # 2 battery bars
            # battery is low, shut down for 6 hours but take a photo first
            print("Battery <= 40, immediate shutdown")
            piwatcher_wake(hours(6))
            system_shutdown("Shutdown, battery low")
        elif level <= 60: # 3 battery bars
            # battery is adequate, stay up for 2 hours then shut down for 4
            piwatcher_wake(hours(4))
            system_shutdown("Scheduled shutdown", when="+120")
        else:
            piwatcher_wake(hours(4))
            system_shutdown("Scheduled shutdown", when="+240")
            
        time.sleep(60) # sleep interval shouldn't be longer than half the watchdog time
        
except KeyboardInterrupt:
    piwatcher_watch(0) # disable the watchdog
    print ("Done.")
    GPIO.cleanup()
