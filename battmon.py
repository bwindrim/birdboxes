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
    "Returns the duration in minutes of the specified number of hours"
    return num*60

def minutes(days, hours, mins):
    "TBD"
    return ((days*24 + hours) * 60 + mins)

def piwatcher_status():
    "Query PiWatcher to reset watchdog timer"
    result = subprocess.run(["/usr/local/bin/piwatcher", "status"], capture_output=True)
    print("PiWatcher status =", result)
    return result.stdout.split()
    
def piwatcher_reset():
    "Reset PiWatcher status register, to clear timer_rebooted, button_pressed, etc."
    result = subprocess.run(["/usr/local/bin/piwatcher", "reset"], capture_output=True)
    print("PiWatcher status =", result)

def piwatcher_led(state):
    "Switch the PiWatcher LED on or off"
    setting = "off"
    if state:
        setting = "on"
    result = subprocess.run(["/usr/local/bin/piwatcher", "led", setting], capture_output=True)
    print("PiWatcher status =", result)
    
def piwatcher_wake(minutes):
    "Set the wake interval for PiWatcher"
#    seconds = (minutes % 1440) * 60 # assume that a wake delay of >24 hours is a mistake
    seconds = minutes * 60
    if seconds > 129600: # clamp wake delay to 36 hours, to stay within limit
        seconds = 129600
    result = subprocess.run(["/usr/local/bin/piwatcher", "wake", str(seconds)], capture_output=True)
    print("PiWatcher wake", seconds, "result =", result)
    
def piwatcher_watch(minutes):
    seconds = minutes * 60
    "Set the watchdog timeout interval for PiWatcher"
    result = subprocess.run(["/usr/local/bin/piwatcher", "watch", str(seconds)], capture_output=True)
    print("PiWatcher watch", seconds, "result =", result)
    
def system_shutdown(msg="System going down", when="now"):
    "Shut down the system"
    print("Shutdown:", msg)
    result = subprocess.run(["/sbin/shutdown", str(when), str(msg)])
    print("shutdown =", result)
    
def stop_boot_watchdog():
    "Stop the piwatcher service"
    result = subprocess.run(["/bin/systemctl", "stop", "piwatcher.service"])
    print("stop piwatcher =", result)
    
def getBatteryLevel(numReads):
    "Read the battery level via the GPIOs"
    level = 0
    # Perform repeated reads of each battery pin, and sum them
    for i in range(numReads):
        for pin in battery:
            level += (1 - GPIO.input(pin))
    return level


# main program 
try:
    stop_boot_watchdog()     # stop the boot watchdog script, as  we're taking over
    system_shutdown("Cancelling backstop shutdown", when="-c")
    initial_status = piwatcher_status() # store the piwatcher status
    piwatcher_reset()        # reset the piwatcher status
    piwatcher_led(False)     # turn off the PiWatcher's LED
    piwatcher_watch(180)     # set 3-minute watchdog timeout
    # All absolute times are in minutes from the start of today (00:00)
    t = time.localtime()
    now = t.tm_hour*60 + t.tm_min # minute in the day
    noon_today = minutes(0,12,0)
    noon_tomorrow = minutes(1,12,0)
    print ("now =", now, "noon tomorrow =", noon_tomorrow)
    # Read the battery level from the solar controller
    level = getBatteryLevel(20)
    print ("Battery level = ", level)
    # Decide how long to stay up, based on time of day and battery level
    if t.tm_hour in range (0, 11):
        # It's after midnight, power off immediately until 12pm tomorrow
        piwatcher_wake(noon_today - now)
        system_shutdown("Night-time immediate shutdown")        
    if level >= 80: # 4 battery bars
        # Battery good, stay up for 1 hour then power off until 12:00 tomorrow
        piwatcher_wake(noon_tomorrow - (now + 60))
        system_shutdown("Scheduled one-hour shutdown", when="+60")
    elif level >= 60: # 3 battery bars
        # Battery adequate, stay up for 30 minutes then power off until 12:00 tomorrow
        piwatcher_wake(noon_tomorrow - (now + 30))
        system_shutdown("Scheduled half-hour shutdown", when="+30")
    elif level >= 40: # 2 battery bars
        # Battery low, stay up for 5 minutes then power off until 12:00 tomorrow
        piwatcher_wake(noon_tomorrow - (now + 10))
        system_shutdown("Scheduled ten-minute shutdown", when="+10")
    else:
        # Battery critical, power off immediately until 12pm tomorrow
        piwatcher_wake(noon_tomorrow - now)
        system_shutdown("Default immediate shutdown")
    # main wait loop to kick the watchdog timer
    while True:
        # Main watchdog wakeup loop
        status = piwatcher_status()  # reset the watchdog
        if b'button_pressed' in status:
            piwatcher_led(True)     # turn on the PiWatcher's LED
            piwatcher_wake(noon_tomorrow - now)
            system_shutdown("Button pressed, immediate shutdown")
        # sleep for one minute
        time.sleep(60) # sleep interval shouldn't be longer than half the watchdog time
        now = now + 1  # advance 'now' by one minute
except KeyboardInterrupt:
    piwatcher_watch(0) # disable the watchdog
    print ("Done.")
    GPIO.cleanup()
