import sys
import time
import subprocess
import smbus # for I2C
import RPi.GPIO as GPIO
import paho.mqtt.client as mqtt
from datetime import datetime
from os.path import exists
from systemd_service import Service

broker_name = "192.168.3.1" # WG address of Pi2B

# Day numbers relative to the day of boot. These are currently
# constants, and assume that we aren't going to stay up past midnight
# on any boot day, but this may change in future.
today = 0
tomorrow = 1

# Use BCM GPIO references instead of physical pin numbers
GPIO.setmode(GPIO.BCM)

# Define GPIO signals to use
battery = [6,12,13,26]

force_up = None

GPIO.setup(battery, GPIO.IN, pull_up_down=GPIO.PUD_UP)

# Set up I2C link to the PiWatcher
i2c = smbus.SMBus(1)
addr = 0x62

piwatcher_svc = Service("piwatcher")

def hours(num):
    "Returns the duration in minutes of the specified number of hours"
    return num*60

def minutes(days, hours, mins=0):
    "Returns the duration in minutes of the specified number of days, hours, and (optionally) minutes"
    return ((days*24 + hours) * 60 + mins)

def status_to_bytestr(status):
    "Convert PiWatcher status to a readable string"
    if (status & 0x20) != 0:
        return b'button_rebooted '
    if (status & 0x80) != 0:
        return b'button_pressed '
    if (status & 0x40) != 0:
        return b'timer_rebooted '
    return b''

def piwatcher_status():
    "Query PiWatcher to reset watchdog timer"
    try:
        result = i2c.read_byte_data(addr, 0)
    except OSError:
        print("PiWatcher I2C failure: status read")
        return [b'ERR', b'-1', b'OSError']
    print("PiWatcher status =", result)
    return [b'OK', bytes(hex(result), 'utf-8'), status_to_bytestr(result)]

def piwatcher_reset():
    "Reset PiWatcher status register, to clear timer_rebooted, button_pressed, etc."
    try:
        result = i2c.write_byte_data(addr, 0, 0xFF)
    except OSError:
        print("PiWatcher I2C failure: reset write")

def piwatcher_led(state):
    "Switch the PiWatcher LED on or off"
    setting = 0x81
    if state:
        setting = 0x82
    try:
        result = i2c.read_byte_data(addr, 8)
    except OSError:
        print("PiWatcher I2C failure: LED version read")
        return
    if (result < 2) or (result == 0xFF):
        print("PiWatcher: wrong firmware version for LED control")
        return
    try:
        result = i2c.write_byte_data(addr, 8, setting)
    except OSError:
        print("PiWatcher I2C failure: LED write")
    

def piwatcher_wake(minutes):
    "Set the wake interval for PiWatcher"
    while minutes < 0:
        minutes = minutes + 1440 # adjust for day crossings (*hack*)
    seconds = min(129600, minutes * 60) # clamp wake delay to 36 hours, to stay within 16-bit limit
#     try:
#         result = i2c.write_word_data(addr, 2, (seconds + 1) >> 2) # wake interval is specified in 2-sec units
#     except OSError:
#         print("PiWatcher I2C failure: wake")
#         result = None
#     print("PiWatcher wake", seconds, "result =", result)
# def piwatcher_wake(minutes):
#     "Set the wake interval for PiWatcher"
#     if minutes < 10:
#         minutes = 10 # enforce minimum wake interval
#     seconds = minutes * 60
#     if seconds > 129600: # clamp wake delay to 36 hours, to stay within limit
#         seconds = 129600
    result = subprocess.run(["/usr/local/bin/piwatcher", "wake", str(seconds)], capture_output=True)
    print("PiWatcher wake", seconds, "result =", result)


def piwatcher_watch(minutes):
    "Set the watchdog timeout interval for PiWatcher"
    seconds = min (240, minutes * 60) # clamp wake delay to 240 seconds, to stay within 8-bit limit
    try:
        result = i2c.write_byte_data(addr, 1, (seconds & 0xFF))
    except OSError:
        print("PiWatcher I2C failure: watch")
        result = None
    print("PiWatcher watch", seconds, "result =", result)
                  
def system_shutdown(msg="System going down", when="now"):
    "Shut down the system"
    print("Shutdown:", msg)
    result = subprocess.run(["/sbin/shutdown", str(when), str(msg)])
    print("shutdown =", result)

def stop_boot_watchdog():
    "Stop the piwatcher service"
#     result = subprocess.run(["/bin/systemctl", "stop", "piwatcher.service"])
    result = piwatcher_svc.stop()
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
    "Decide how long to stay up and to sleep, based on current time-of-day and battery level"
    if now < minutes(today,5,30): # It's after midnight but before 8:30, power off until 9:00 today
        stay_up = 0
        wake_time = minutes(today,9,0)
        message = "Night-time immediate shutdown"
        return (stay_up, wake_time, message) # early out
    elif now < minutes(today,8,30): # It's after 5:30 but before 8:30, stay up for an hour then power off until 9:00 today
        stay_up = 60
        wake_time = minutes(today,9,0)
        message = "Early morning 1-hour shutdown"
        return (stay_up, wake_time, message) # early out
    elif level >= 80: # 4 battery bars, stay up for 2 hours then power off for 3 hours
        stay_up = 120
        wake_time = now + stay_up + 180
        message = "Scheduled two-hour shutdown"
    elif level >= 70: # 3-4 battery bars, stay up for 1 hour then power off for 4 hours
        stay_up = 60
        wake_time = now + stay_up + 240
        message = "Scheduled one-hour shutdown"
    elif level >= 60: # 3 battery bars, stay up for 40 minutes then power off for 5 1/3 hours
        stay_up = 40
        wake_time = now + stay_up + 260
        message = "Scheduled half-hour shutdown"
    elif level >= 50: # 2-3 battery bars, stay up for 30 minutes then power off until 9:00 tomorrow
        stay_up = 30
        wake_time = minutes(tomorrow,9,0)
        message = "Scheduled half-hour shutdown"
    elif level >= 40: # 2 battery bars, stay up for 15 minutes then power off until 9:00 tomorrow
        stay_up = 15
        wake_time = minutes(tomorrow,9,0)
        message = "Scheduled 15-minute shutdown"
    else: # Battery critical, power off immediately until 12:00 tomorrow
        stay_up = 0
        wake_time = minutes(tomorrow,12,0)
        message = "Emergency shutdown"
    wake_time = wake_time // 15 * 15 # Round wake time down to nearest 15 minutes
    if wake_time >= minutes(today,23,0): # wake is 11PM or later
        wake_time = max(wake_time, minutes(tomorrow,9,0)) # Don't bother waking until 9am
    return (stay_up, wake_time, message)

def timestr(time):
    "Convert time representation to readable time string"
    hours, mins = divmod(time, 60)
    string = format(hours, "02") + ":" + format(mins, "02")
    return string

def test(level, interval=15):
    "Test function for evaluate"
    for time in range(0, 1440, interval):
        stay_up, wake_time, message = evaluate(time, level)
        print(timestr(time), " = ", stay_up, "mins", timestr(wake_time))

def test_all():
    "Test function for evaluate"
    for level in range(80,0,-10):
        test(level)

# MQTT setup
bb_subscribe_list = [
"force_up"
]

def on_log(client, userdata, level, buf):
    print("log: ",buf)
    
def on_message(client, userdata, message):
    print(message.topic, "=", str(message.payload.decode("utf-8")), end='')
    if message.retain:
        print(" (retained)")
    else:
        print(" (live)")
    if message.topic == "birdboxes/testbed/force_up" and not message.retain:
        if message.payload:
            force_up = bool(int.from_bytes(message.payload, byteorder='little'))
            piwatcher_led(True)
        else:
            force_up = None
            piwatcher_led(False)

def list_subscribe(root, topic, subscribe_list):
    "Subscribe to a list of MQTT topics"
    for subtopic in subscribe_list:
        client.subscribe(root + '/' + topic + '/' + subtopic)

client = mqtt.Client("TestBed")
client.connect_async(broker_name) # connect in background, in case broker not reachable
client.on_message=on_message
client.on_log = on_log

# main program 
try:
    client.loop_start() # start the loop in a thread
    stop_boot_watchdog()     # stop the boot watchdog script, as we're taking over its job
    list_subscribe("birdboxes","testbed", bb_subscribe_list)
    initial_status = piwatcher_status() # store the piwatcher status
    print("PiWatcher initial status =", initial_status)    # log the status
    if len(initial_status) >= 2:
        client.publish("birdboxes/testbed/initial_status", int(initial_status[1], base=16), retain=True)
    piwatcher_reset()        # clear the PiWatcher status
    piwatcher_led(False)     # turn off the PiWatcher's LED
    piwatcher_watch(3)       # set 3-minute watchdog timeout
    # All absolute times are in minutes from the beginning of the boot day (00:00)
    t = time.localtime()
    now = t.tm_hour*60 + t.tm_min # minute in the day
    noon_today = minutes(today,12,0)
    noon_tomorrow = minutes(tomorrow,12,0)
    print ("now =", now, "noon today =", noon_today, "noon tomorrow =", noon_tomorrow)
    client.publish("birdboxes/testbed/startup_time", time.asctime(), retain=True)
    # Set a default wake interval, as a backstop
    if (now > (noon_today - 60)): # it's after 11am already
        piwatcher_wake(noon_tomorrow - now) # wake tomorrow
    else:
        piwatcher_wake(noon_today - now) # wake today
    # Read the battery level from the solar controller
    level = getBatteryLevel()
    print ("Battery level = ", level)
    client.publish("birdboxes/testbed/initial_battery_level", level, retain=True)

    stay_up = 15 # default 15-minute time before shutting down, overridden below
    wake_time = noon_tomorrow # default wake-up time
    message = "Default shutdown"
    # Decide how long to stay up, based on time of day and battery level
    stay_up, wake_time, message = evaluate(now, level)
    print("stay-up duration =", stay_up, "wake-up time =", wake_time)
    client.publish("birdboxes/testbed/initial_stay_up", stay_up, retain=True)
    client.publish("birdboxes/testbed/wake_time", timestr(wake_time), retain=True)
    # Main watchdog wakeup loop
    while stay_up > 0:
        # Sleep for one minute
        time.sleep(60) # sleep interval shouldn't be longer than half the watchdog time
        now = now + 1  # advance 'now' by one minute
        stay_up = stay_up - 1 # decrement the remaining stay-up duration by one minute
        client.publish("birdboxes/testbed/stay_up", stay_up, retain=False)
        status = piwatcher_status()  # reset the watchdog
        level = getBatteryLevel()
        print("now = ", timestr(now), "stay up = ", stay_up, "battery level =", level, "status =", status)
        client.publish("birdboxes/testbed/battery_level", level, retain=True)
        if len(status) >= 2:
            client.publish("birdboxes/testbed/status", int(status[1], base=16), retain=True)
        if b'button_pressed' in status: # shutdown immediately
#            piwatcher_reset()        # clear the PiWatcher status
            stay_up = 0
            message = "Button pressed, immediate shutdown"
        if exists("/tmp/shutdown"): # if shutdown requested
            stay_up = 0
            message = "/tmp/shutdown detected, immediate shutdown"
    # We've left the loop, initiate shutdown
    piwatcher_watch(3)      # set 3-minute watchdog timeout, again, in case it was cancelled by user
    piwatcher_led(True)     # turn on the PiWatcher's LED
    piwatcher_wake(wake_time - now - 3) # set the wake-up interval
    print("Shutting down, wake time is", timestr(wake_time))
    client.publish("birdboxes/testbed/shutdown_time", time.asctime(), retain=True)
    client.publish("birdboxes/testbed/wake_time", timestr(wake_time), retain=True)
    if exists("/tmp/noshutdown"): # if shutdown is to be blocked
        print("Shutdown blocked by /tmp/noshutdown, deferring by one hour")
        system_shutdown(message, when="+60")
    else:
        system_shutdown(message)
    # idle loop while we wait for shutdown
    while True:
        time.sleep(60) # sleep for one minute
        now = now + 1  # advance 'now' by one minute
        status = piwatcher_status()  # reset the watchdog
        print("now = ", timestr(now), "stay up = ", stay_up, "battery level =", getBatteryLevel(), "status =", status)
except KeyboardInterrupt:
    piwatcher_watch(0) # disable the watchdog
    print ("Done.")
    client.loop_stop() # stop the MQTT loop thread
    GPIO.cleanup()

