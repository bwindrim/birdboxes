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

def hours(num):
    "Returns the duration in seconds of the specified number of hours"
    return num*60*60

def minutes(num):
    "Returns the duration in seconds of the specified number of minutes"
    return num*60

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
    print("PiWatcher wake", seconds, "result =", result)
    
def piwatcher_watch(seconds):
    "Set the watchdog timeout interval for PiWatcher"
    result = subprocess.run(["/usr/local/bin/piwatcher", "watch", str(seconds)], capture_output=True)
    print("PiWatcher watch", seconds, "result =", result)
    
def system_shutdown(msg="System going down", when="now"):
    "Shut down the system"
    print("Shutdown:", msg)
    result = subprocess.run(["/sbin/shutdown", when, str(msg)])
    print("shutdown =", result)
    
def getBatteryLevel(numReads):
    "Read the battery level via the GPIOs"
    
    level = 0

    for i in range(numReads):
        for pin in battery:
            level += (1 - GPIO.input(pin))

    return level


# main program 
try:
    piwatcher_led(False)     # turn off the PiWatcher's LED
    piwatcher_watch(120)     # set 2-minute watchdog timeout

    # All absolute times are in seconds from the start of today (00:00)
    t = time.localtime()
    h = t.tm_hour
    m = h*60 + t.tm_min 
    s = m*60 + t.tm_sec # second in the day
    noon_today = seconds(0,12,0,0)
    noon_tomorrow = seconds(1,12,0,0)
    print ("now =", s, "noon today =", noon_today, "noon tomorrow =", noon_tomorrow)
    
    level = 80 # getBatteryLevel(20)
    print ("Battery level = ", level)
    
    if h in range (0, 11):
        # After midnight, power off immediately until 12pm tomorrow
        piwatcher_wake(noon_today - s)
        system_shutdown("Night-time immediate shutdown")        
    if level >= 80: # 4 battery bars
        # Battery good, stay up for 1 hour then power off until 12:00 tomorrow
        piwatcher_wake(noon_tomorrow - (s + minutes(60)))
        system_shutdown("Scheduled one-hour shutdown", when="+60")
    elif level >= 60: # 3 battery bars
        # Battery adequate, stay up for 30 minutes then power off until 12:00 tomorrow
        piwatcher_wake(noon_tomorrow - (s + minutes(30)))
        system_shutdown("Scheduled half-hour shutdown", when="+30")
    elif level >= 40: # 2 battery bars
        # Battery low, stay up for 5 minutes then power off until 12:00 tomorrow
        piwatcher_wake(noon_tomorrow - (s + minutes(5)))
        system_shutdown("Scheduled five-minute shutdown", when="+5")
    else:
        # Battery critical, power off immediately until 12pm tomorrow
        piwatcher_wake(noon_tomorrow - s)
        system_shutdown("Default immediate shutdown")
         
    while True:
        # Main watchdog wakeup loop
        piwatcher_status()  # reset the watchdog
        time.sleep(60) # sleep interval shouldn't be longer than half the watchdog time
        
except KeyboardInterrupt:
    piwatcher_watch(0) # disable the watchdog
    print ("Done.")
    GPIO.cleanup()
