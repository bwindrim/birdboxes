import sys
import time
import subprocess
import smbus # for I2C
from struct import pack, unpack
import RPi.GPIO as GPIO
import paho.mqtt.client as mqtt
from datetime import datetime
from os.path import exists

broker_name = "192.168.3.1" # WG address of Pi2B

# These are constants from MicroPython's machine module, which we don't havedirect access to here
PWRON_RESET = 1
WDT_RESET = 3

# Use BCM GPIO references instead of physical pin numbers
GPIO.setmode(GPIO.BCM)

# Define GPIO signals to use
battery = [6,12,13,26]

force_up = None

GPIO.setup(battery, GPIO.IN, pull_up_down=GPIO.PUD_UP)

# Set up I2C link to the Pico
i2c = smbus.SMBus(1)
addr = 0x41

def hours(num):
    "Returns the duration in minutes of the specified number of hours"
    return num*60

def minutes(days, hours, mins):
    "TBD"
    return ((days*24 + hours) * 60 + mins)

def status_to_str(status):
    "Convert PicoWatcher status to a readable string"
    hw_status = status & 0x0F
    sw_status = status & 0x30 >> 4
    if hw_status is WDT_RESET:
        return "watchdog_reset"
    if hw_status is PWRON_RESET:
        return "poweron_reset"
    if sw_status is 3:
        return "button_rebooted"
    if status is 2:
        return "button_pressed"
    if status is 1:
        return "timer_rebooted"
    return ""
    
def piwatcher_status():
    "Query PicoWatcher to reset watch timer"
    result = i2c.read_byte_data(addr, 1)
    print("PicoWatcher status =", result)
    return ["OK", hex(result), status_to_str(result)]

def piwatcher_reset():
    "Reset PicoWatcher status register, to clear timer_rebooted, button_pressed, etc."
    result = i2c.read_byte_data(addr, 4)
    print("PicoWatcher reset =", result)
    return ["OK", hex(result), status_to_str(result)]

def piwatcher_led(state):
    "Switch the PicoWatcher LED on or off"
    setting = "off"
    if state:
        setting = "on"

def piwatcher_wake(minutes):
    "Set the wake interval for PicoWatcher"
    seconds = min(129600, minutes * 60) # clamp wake delay to 36 hours, to stay within 16-bit limit
    result = i2c.write_word_data(addr, 6, seconds)
    print("PicoWatcher wake", seconds, "result =", result)

def piwatcher_watch(minutes):
    "Set the watch timeout interval for PicoWatcher"
    seconds = min (240, minutes * 60) # clamp wake delay to 240 seconds, to stay within 8-bit limit
    result = i2c.write_byte_data(addr, 5, seconds)
    print("PicoWatcher watch", seconds, "result =", result)
                  
def picowatcher_rtc(time=None):
    "Get or set the Pico's RTC"
    if time is None:
        time_list = i2c.read_i2c_block_data(addr, 3, 10)
        time_bytes = bytes(time_list)
        result = struct.unpack("HBBBBBBH", time_bytes)
    else:
        time_bytes = struct.pack("HBBBBBBH", *time)
        time_list = list(time_bytes)
        result = i2c.write_i2c_block_data(addr, 3, time_list)
    return result

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
    "Read the battery level from PicoWatcher"
    level = i2c.read_word_data(addr, 2)
    return level

def evaluate(now, level):
    "Decide how long to stay up and to sleep, based on current time-of-day and battery level"
    if now < minutes(0,5,30): # It's after midnight but before 8:30, power off until 9:00 today
        stay_up = 0
        wake_time = minutes(0,9,0)
        message = "Night-time immediate shutdown"
        return (stay_up, wake_time, message) # early out
    elif now < minutes(0,8,30): # It's after 5:30 but before 8:30, stay up for an hour then power off until 9:00 today
        stay_up = 60
        wake_time = minutes(0,9,0)
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
        wake_time = minutes(1,9,0)
        message = "Scheduled half-hour shutdown"
    elif level >= 40: # 2 battery bars, stay up for 15 minutes then power off until 9:00 tomorrow
        stay_up = 15
        wake_time = minutes(1,9,0)
        message = "Scheduled 15-minute shutdown"
    else: # Battery critical, power off immediately until 12:00 tomorrow
        stay_up = 0
        wake_time = minutes(1,12,0)
        message = "Emergency shutdown"
    wake_time = wake_time // 15 * 15 # Round wake time down to nearest 15 minutes
    if wake_time >= minutes(0,23,0): # wake is 11PM or later
        wake_time = max(wake_time, minutes(1,9,0)) # Don't bother waking until 9am
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
def on_message(client, userdata, message):
    if message.retain:
        print(message.topic, "=", str(message.payload.decode("utf-8")), "(retained)")
    else:
        print(message.topic, "=", str(message.payload.decode("utf-8")), "(live)")
    if message.topic is "birdboxes/birdbox1/force_up":
        if message.payload:
            force_up = bool(int.from_bytes(message.payload, byteorder='little'))
        else:
            force_up = None

def on_log(client, userdata, level, buf):
    print("log: ",buf)
    
client = mqtt.Client("BirdBox1")
client.connect(broker_name)
client.on_message=on_message
client.on_log = on_log

# main program 
try:
    client.loop_start() # start the loop in a thread
    stop_boot_watchdog()     # stop the boot watchdog script, as we're taking over its job
    initial_status = piwatcher_status() # store the piwatcher status
    print("PiWatcher initial status =", initial_status)    # log the status
    if len(initial_status) >= 2:
        client.publish("birdboxes/birdbox1/initial_status", int(initial_status[1], base=16), retain=True)
    piwatcher_reset()        # clear the PiWatcher status
    piwatcher_led(False)     # turn off the PiWatcher's LED
    piwatcher_watch(3)       # set 3-minute watchdog timeout
    # All absolute times are in minutes from the start of today (00:00)
    t = time.localtime()
    now = t.tm_hour*60 + t.tm_min # minute in the day
    noon_today = minutes(0,12,0)
    noon_tomorrow = minutes(1,12,0)
    print ("now =", now, "noon today =", noon_today, "noon tomorrow =", noon_tomorrow)
    client.publish("birdboxes/birdbox1/startup_time", time.asctime(), retain=True)
    # Set a default wake interval, as a backstop
    if (now > (noon_today - 60)): # it's after 11am already
        piwatcher_wake(noon_tomorrow - now) # wake tomorrow
    else:
        piwatcher_wake(noon_today - now) # wake today
    # Read the battery level from the solar controller
    level = getBatteryLevel()
    print ("Battery level = ", level)
    client.publish("birdboxes/birdbox1/initial_battery_level", level, retain=True)

    stay_up = 15 # default 15-minute time before shutting down, overridden below
    wake_time = noon_tomorrow # default wake-up time
    message = "Default shutdown"
    # Decide how long to stay up, based on time of day and battery level
    stay_up, wake_time, message = evaluate(now, level)
    print("stay-up duration =", stay_up, "wake-up time =", wake_time)
    client.publish("birdboxes/birdbox1/initial_stay_up", stay_up, retain=True)
    client.publish("birdboxes/birdbox1/wake_time", timestr(wake_time), retain=True)
    # Main watchdog wakeup loop
    while stay_up > 0:
        # Sleep for one minute
        time.sleep(60) # sleep interval shouldn't be longer than half the watchdog time
        now = now + 1  # advance 'now' by one minute
        stay_up = stay_up - 1 # decrement the remaining stay-up duration by one minute
        client.publish("birdboxes/birdbox1/stay_up", stay_up, retain=False)
        status = piwatcher_status()  # reset the watchdog
        level = getBatteryLevel()
        print("now = ", timestr(now), "stay up = ", stay_up, "battery level =", level, "status =", status)
        client.publish("birdboxes/birdbox1/battery_level", level, retain=True)
        if len(status) >= 2:
            client.publish("birdboxes/birdbox1/status", int(status[1], base=16), retain=True)
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
    client.publish("birdboxes/birdbox1/shutdown_time", time.asctime(), retain=True)
    client.publish("birdboxes/birdbox1/wake_time", timestr(wake_time), retain=True)
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

