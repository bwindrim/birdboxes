import sys
import time
import subprocess
import RPi.GPIO as GPIO
from datetime import datetime
from os.path import exists

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
#    print("PiWatcher status =", result)
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
    "Set the watchdog timeout interval for PiWatcher"
    seconds = minutes * 60
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

def getBatteryLevel(numReads=20):
    "Read the battery level via the GPIOs"
    level = 0
    # Perform repeated reads of each battery pin, and sum them
    for i in range(numReads):
        for pin in battery:
            level += (1 - GPIO.input(pin))
    return level

def evaluate(now, level):
    "Decide how long to stay up and sleep, based on current time-of-day and battery level"
    if now < minutes(0,9,0): # It's after midnight, power off immediately until 9:00 today
        stay_up = 0
        wake_time = minutes(0,9,0)
        message = "Night-time immediate shutdown"
        return (stay_up, wake_time, message) # early out
    elif level >= 80: # 4 battery bars, stay up for 2 hours then power off for 4 hours
        stay_up = 120
        wake_time = now + stay_up + 240
        message = "Scheduled two-hour shutdown"
    elif level >= 70: # 3-4 battery bars, stay up for 90 minutes then power off for 4 1/2 hours
        stay_up = 90
        wake_time = now + stay_up + 270
        message = "Scheduled 90-minute shutdown"
    elif level >= 60: # 3 battery bars, stay up for 60 minutes then power off until 9:00 tomorrow
        stay_up = 60
        wake_time = minutes(1,9,0)
        message = "Scheduled one-hour shutdown"
    elif level >= 50: # 2-3 battery bars, stay up for 30 minutes then power off until 9:00 tomorrow
        stay_up = 30
        wake_time = minutes(1,9,0)
        message = "Scheduled half-hour shutdown"
    elif level >= 40: # 2 battery bars, stay up for 15 minutes then power off until 12:00 tomorrow
        stay_up = 15
        wake_time = minutes(1,12,0)
        message = "Scheduled 15-minute shutdown"
    else: # Battery critical, power off immediately until 12:00 tomorrow
        stay_up = 0
        wake_time = minutes(1,12,0)
        message = "Emergency shutdown"
    # Don't bother waking between 11PM and 9AM
    if wake_time >= minutes(0,23,0): # wake is 11PM or later
        wake_time = max(wake_time, minutes(1,9,0))
    return (stay_up, wake_time, message)

def timestr(time):
    "Convert time representation to readable time string"
    hours, mins = divmod(time, 60)
    string = format(hours, "02") + ":" + format(mins, "02")
    return string

def test(level):
    "Test function for evaluate"
    for time in range(0, 1440, 15):
        stay_up, wake_time, message = evaluate(time, level)
        print(timestr(time), " = ", stay_up, "mins", timestr(wake_time))

def test_all():
    "Test function for evaluate"
    for level in range(80,0,-10):
        test(level)

# main program 
try:
    stop_boot_watchdog()     # stop the boot watchdog script, as we're taking over its job
    initial_status = piwatcher_status() # store the piwatcher status
    print("PiWatcher initial status =", initial_status)    # log the status
    piwatcher_reset()        # clear the PiWatcher status
    piwatcher_led(False)     # turn off the PiWatcher's LED
    piwatcher_watch(3)       # set 3-minute watchdog timeout
    # All absolute times are in minutes from the start of today (00:00)
    t = time.localtime()
    now = t.tm_hour*60 + t.tm_min # minute in the day
    noon_today = minutes(0,12,0)
    noon_tomorrow = minutes(1,12,0)
    print ("now =", now, "noon today =", noon_today, "noon tomorrow =", noon_tomorrow)
    # Set a default wake interval, as a backstop
    if (now > (noon_today - 60)): # it's after 11am already
        piwatcher_wake(noon_tomorrow - now) # wake tomorrow
    else:
        piwatcher_wake(noon_today - now) # wake today
    # Read the battery level from the solar controller
    level = getBatteryLevel()
    print ("Battery level = ", level)
    stay_up = 15 # default 15-minute time before shutting down, overridden below
    wake_time = noon_tomorrow # default wake-up time
    message = "Default shutdown"
    # Decide how long to stay up, based on time of day and battery level
    stay_up, wake_time, message = evaluate(now, level)
    print("stay-up duration =", stay_up, "wake-up time =", wake_time)
    # Main watchdog wakeup loop
    while stay_up > 0:
        # Sleep for one minute
        time.sleep(60) # sleep interval shouldn't be longer than half the watchdog time
        now = now + 1  # advance 'now' by one minute
        stay_up = stay_up - 1 # decrement the remaining stay-up duration by one minute
        status = piwatcher_status()  # reset the watchdog
        print("now = ", timestr(now), "stay up = ", stay_up, "battery level =", getBatteryLevel(), "status =", status)
        if b'button_pressed' in status: # shutdown immediately
            stay_up = 0
            message = "Button pressed, immediate shutdown"
        if exists("/tmp/shutdown"): # if shutdown requested
            stay_up = 0
            message = "/tmp/shutdown detected, immediate shutdown"
    # We've left the loop, initiate shutdown
    piwatcher_watch(3)      # set 3-minute watchdog timeout, again, in case it was cancelled by user
    piwatcher_led(True)     # turn on the PiWatcher's LED
    piwatcher_wake(wake_time - now) # set the wake-up interval
    print("Shutting down, wake time is", timestr(wake_time))
    if exists("/tmp/noshutdown"): # if shutdown is to be blocked
        print("Shutdown blocked by /tmp/noshutdown, deferring by one hour")
        system_shutdown(message, when="+60")
    else:
        system_shutdown(message)
    # idle loop while we wait for shutdown
    while True:
        time.sleep(60) # sleep for one minute
        print("PiWatcher status = ", piwatcher_status())  # reset the watchdog
except KeyboardInterrupt:
    piwatcher_watch(0) # disable the watchdog
    print ("Done.")
    GPIO.cleanup()

