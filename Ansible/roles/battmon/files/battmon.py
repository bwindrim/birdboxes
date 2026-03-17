# BirdBox 1 & 2
import sys
import time
import subprocess
import RPi.GPIO as GPIO
import paho.mqtt.client as mqtt
import requests
from datetime import timedelta
from os.path import exists
import socket

broker_name = "broker.hivemq.com" # HiveMQ public broker, no authentication.
client_name = socket.gethostname()
root_topic = f"BWBirdBoxes/{client_name}"

# Use BCM GPIO references instead of physical pin numbers
GPIO.setmode(GPIO.BCM)

# Define GPIO signals to use for the battery level
battery = [13, 12, 7, 22]

force_up = None

GPIO.setup(battery, GPIO.IN, pull_up_down=GPIO.PUD_UP)

def hours(num):
    "Returns the duration as a timedelta for the specified number of hours"
    return timedelta(hours=num)


def floor_to_15(td):
    "Round a timedelta down to the nearest 15 minutes"
    total_minutes = int(td.total_seconds() // 60)
    return timedelta(minutes=(total_minutes // 15) * 15)

def minutes_until(start, end):
    "Return whole minutes between timedeltas (can be negative)"
    delta = end - start
    return int(delta.total_seconds() // 60)

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
    if client_name != "birdbox1": # BirdBox1's PiWatcher doesn't support the LED command, so skip it to avoid errors
        result = subprocess.run(["/usr/local/bin/piwatcher", "led", setting], capture_output=True)
        print("PiWatcher status =", result)

def piwatcher_wake(minutes):
    "Set the wake interval for PiWatcher"
    if minutes < 10:
        minutes = 10 # enforce minimum wake interval
    seconds = minutes * 60
    if seconds > 129600: # clamp wake delay to 36 hours, to stay within limit
        seconds = 129600
    result = subprocess.run(["/usr/local/bin/piwatcher", "wake", str(seconds)], capture_output=True)
    print("PiWatcher wake", seconds, "result =", result)

def piwatcher_watch(minutes):
    if minutes < 3: # enforce minimum watch time
        minutes = 3
    "Set the watchdog timeout interval for PiWatcher"
    seconds = minutes * 60
    if seconds > 255:
        seconds = 255 # don't exceed hw-defined limit
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
    "Decide how long to stay up and to sleep, based on current time-of-day and battery level"
    message = "Scheduled shutdown" # default message, may be overridden below


    if now < timedelta(hours=5, minutes=30): # It's after midnight but before 8:30, power off until 9:00 today
        stay_up = timedelta(minutes=10)
        wake_time = timedelta(hours=8)
        message = "Night-time immediate shutdown"
        return (stay_up, wake_time, message) # early out
    elif now < timedelta(hours=7, minutes=30): # It's after 5:30 but before 7:30, stay up for an hour then power off until 8:00 today
        stay_up = timedelta(minutes=60)
        wake_time = timedelta(hours=8)
        message = "Early morning shutdown"
        return (stay_up, wake_time, message) # early out
    elif level >= 100: # 4 battery bars, stay up for 2 hours then power off for 3 hours
        stay_up = timedelta(minutes=120)
        wake_time = now + timedelta(minutes=360)
    elif level >= 85: # 3-4 battery bars, stay up for 1.5 hours then power off for 4 hours
        stay_up = timedelta(minutes=90)
        wake_time = now + timedelta(minutes=360)
    elif level >= 75: # 3 battery bars, stay up for 1 hour then power off for 5 hours
        stay_up = timedelta(minutes=60)
        wake_time = now + timedelta(minutes=360)
    elif level >= 60: # 2-3 battery bars, stay up for 30 minutes then power off for (at least) 12 hours
        stay_up = timedelta(minutes=30)
        wake_time = now + timedelta(minutes=720)
    elif level >= 50: # 2 battery bars, stay up for 20 minutes then power off until 8:00 tomorrow
        stay_up = timedelta(minutes=20)
        if now >= timedelta(hours=12): # is after midday
            wake_time = timedelta(days=1, hours=8)
            message = "Low battery shutdown until 12pm tomorrow"
        else:
            wake_time = timedelta(hours=14)
            message = "Low battery shutdown until 2pm today"
    else: # Battery critical, power off immediately until 12:00 tomorrow
        stay_up = timedelta(minutes=10)
        if now >= timedelta(hours=12):
            wake_time = timedelta(days=1, hours=14)
            message = "Emergency shutdown until 2pm tomorrow"
        else:
            wake_time = timedelta(hours=14)
            message = "Emergency shutdown until 2pm today"

    wake_time = floor_to_15(wake_time) # Round wake time down to nearest 15 minutes
    if wake_time >= timedelta(hours=23): # wake is 11PM or later
        wake_time = max(wake_time, timedelta(days=1, hours=8)) # Don't bother waking until 8am
    return (stay_up, wake_time, message)

def timestr(td):
    "Convert time representation to readable time string"
    total_minutes = int(td.total_seconds() // 60)
    hours, mins = divmod(total_minutes, 60)
    return format(hours, "02") + ":" + format(mins, "02")

def test(level, interval=15):
    "Test function for evaluate"
    for offset in range(0, 1440, interval):
        current = timedelta(minutes=offset)
        stay_up, wake_time, message = evaluate(current, level)
        print(timestr(current), " = ", int(stay_up.total_seconds() // 60), "mins", timestr(wake_time))

def test_all():
    "Test function for evaluate"
    for level in range(80,0,-10):
        test(level)

def ntfy(msg):
    requests.post("https://ntfy.sh/BWBirdBoxes",
                  data=msg.encode(encoding='utf-8'))

# MQTT setup
def on_message(client, userdata, message):
    if message.retain:
        print(message.topic, "=", str(message.payload.decode("utf-8")), "(retained)")
    else:
        print(message.topic, "=", str(message.payload.decode("utf-8")), "(live)")
    if message.topic == f"{root_topic}/force_up":
        if message.payload:
            force_up = bool(int.from_bytes(message.payload, byteorder='little'))
        else:
            force_up = None

def on_log(client, userdata, level, buf):
    print("log: ",buf)
    
client = mqtt.Client(client_name)
client.connect_async(broker_name) # connect in background, in case broker not reachable
client.on_message=on_message
client.on_log = on_log

# main program 
try:
    client.loop_start() # start the loop in a thread
    stop_boot_watchdog()     # stop the boot watchdog script, as we're taking over its job
    initial_status = piwatcher_status() # store the piwatcher status
    print("PiWatcher initial status =", initial_status)    # log the status
    if len(initial_status) >= 2:
        client.publish(f"{root_topic}/initial_status", int(initial_status[1], base=16), qos=1, retain=True)
    piwatcher_reset()        # clear the PiWatcher status
    piwatcher_led(False)     # turn off the PiWatcher's LED
    piwatcher_watch(3)       # set 3-minute watchdog timeout
    # All absolute times are timedeltas relative to start of today
    # ToDo: change to use datetime for the start of today, and absolute datetimes for the wake times, to avoid issues with crossing midnight.
    t = time.localtime()
    now = timedelta(hours=t.tm_hour, minutes=t.tm_min)
    noon_today = timedelta(hours=12)
    noon_tomorrow = timedelta(days=1, hours=12)
    print ("now =", timestr(now), "noon today =", timestr(noon_today), "noon tomorrow =", timestr(noon_tomorrow))
    client.publish(f"{root_topic}/startup_time", time.asctime(), qos=1, retain=True)
    # Set a default wake interval, as a backstop
    if (now > (noon_today - timedelta(hours=1))): # it's after 11am already
        piwatcher_wake(minutes_until(now, noon_tomorrow)) # wake tomorrow
    else:
        piwatcher_wake(minutes_until(now, noon_today)) # wake today
    # Read the battery level from the solar controller
    level = getBatteryLevel(numReads=25)
    print ("Battery level = ", level)
    client.publish(f"{root_topic}/initial_battery_level", f'{level}%', qos=1, retain=True)

    stay_up = timedelta(minutes=15) # default 15-minute time before shutting down, overridden below
    wake_time = noon_tomorrow # default wake-up time
    message = "Default shutdown"
    # Decide how long to stay up, based on time of day and battery level
    stay_up, wake_time, message = evaluate(now, level)
    piwatcher_wake(max(minutes_until(now, wake_time) - 3, 0)) # set the wake-up interval
    stay_up_minutes = int(stay_up.total_seconds() // 60)
    print("stay-up duration =", stay_up_minutes, "wake-up time =", timestr(wake_time))
    client.publish(f"{root_topic}/initial_stay_up", stay_up_minutes, qos=1, retain=True)
    client.publish(f"{root_topic}/wake_time", timestr(wake_time), qos=1, retain=True)
    ntfy(f'{client_name} up at {timestr(now)}, for {stay_up_minutes} mins: batt {level}%')
    # Main watchdog wakeup loop
    while stay_up > timedelta(0):
        # Sleep for one minute
        time.sleep(60) # sleep interval shouldn't be longer than half the watchdog time
        now = now + timedelta(minutes=1)  # advance 'now' by one minute
        stay_up = stay_up - timedelta(minutes=1) # decrement the remaining stay-up duration by one minute
        stay_up_minutes = int(stay_up.total_seconds() // 60)
        client.publish(f"{root_topic}/stay_up", stay_up_minutes, qos=1, retain=False)
        status = piwatcher_status()  # reset the watchdog
        level = getBatteryLevel(numReads=25)
        print("now = ", timestr(now), "stay up = ", stay_up_minutes, "battery level =", level, "status =", status)
        client.publish(f"{root_topic}/battery_level", f'{level}%', qos=1, retain=True)
        if len(status) >= 2:
            status_val = int(status[1], base=16)
            if status_val != 0:
                client.publish(f"{root_topic}/status", status_val, qos=1, retain=True)
        if b'button_pressed' in status: # shutdown immediately
#            piwatcher_reset()        # clear the PiWatcher status
            stay_up = timedelta(0)
            message = "Button pressed, immediate shutdown"
        if exists("/tmp/shutdown"): # if shutdown requested
            stay_up = timedelta(0)
            message = "/tmp/shutdown detected, immediate shutdown"
        piwatcher_wake(max(minutes_until(now, wake_time) - 3, 0)) # update the wake-up interval
    # We've left the loop, initiate shutdown
    piwatcher_watch(3)      # set 3-minute watchdog timeout, again, in case it was cancelled by user
    piwatcher_led(True)     # turn on the PiWatcher's LED
#     piwatcher_wake(max(minutes_until(now, wake_time) - 3, 0)) # set the wake-up interval
    print("Shutting down, wake time is", timestr(wake_time))
    client.publish(f"{root_topic}/shutdown_time", time.asctime(), qos=1, retain=True)
    client.publish(f"{root_topic}/wake_time", timestr(wake_time), qos=1, retain=True)
    ntfy(f'{client_name} down at {timestr(now)}, until {timestr(wake_time)}: batt {level}%, {message}')
    if exists("/tmp/noshutdown"): # if shutdown is to be blocked
        print("Shutdown blocked by /tmp/noshutdown, deferring by one hour")
        system_shutdown(message, when="+60")
    else:
        system_shutdown(message)
    # idle loop while we wait for shutdown
    while True:
        time.sleep(60) # sleep for one minute
        now = now + timedelta(minutes=1)  # advance 'now' by one minute
        status = piwatcher_status()  # reset the watchdog
        print("now = ", timestr(now), "stay up = ", stay_up_minutes, "battery level =", getBatteryLevel(), "status =", status)
except KeyboardInterrupt:
    piwatcher_watch(0) # disable the watchdog
    print ("Done.")
    client.loop_stop() # stop the MQTT loop thread
    GPIO.cleanup()
