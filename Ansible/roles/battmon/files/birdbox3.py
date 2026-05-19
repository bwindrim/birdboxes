# BirdBox 3
import sys
import time
import subprocess
import smbus # for I2C
import struct
import RPi.GPIO as GPIO
import paho.mqtt.client as mqtt
import requests
from datetime import timedelta
from os.path import exists
from typing import Any, List, Optional, Tuple, Union
import socket

broker_name: str = "broker.hivemq.com" # HiveMQ public broker, no authentication.
client_name: str = socket.gethostname()
root_topic: str = f"BWBirdBoxes/{client_name}"

# These are constants from MicroPython's machine module, which we don't have direct access to here
PWRON_RESET: int = 1
WDT_RESET: int = 3

# Use BCM GPIO references instead of physical pin numbers
GPIO.setmode(GPIO.BCM)

# Define GPIO signals to use
battery: List[int] = [6, 12, 13, 26]

# PicoWatcher I2C register numbers:
# 1 - status register (read to reset watch countdown)
# 2 - ADC value (2 bytes, read-only)
# 3 - RTC date&time (10 bytes, read&write)
# 4 - status register read and clear (1 bytes, read-only)
# 5 - watch time (1 byte, read&write)
# 6 - wake time (2 bytes, read&write)
# 7 - ADC2 value (2 bytes, read-only)
# 8 - LED control (1 byte, read&write)

force_up: Optional[bool] = None
RTCData = Tuple[int, int, int, int, int, int, int, int]

GPIO.setup(battery, GPIO.IN, pull_up_down=GPIO.PUD_UP)

# Set up I2C link to the Pico
i2c: smbus.SMBus = smbus.SMBus(1)
addr: int = 0x41

def hours(num: int) -> timedelta:
    "Returns the duration as a timedelta for the specified number of hours"
    return timedelta(hours=num)


def floor_to_15(td: timedelta) -> timedelta:
    "Round a timedelta down to the nearest 15 minutes"
    total_minutes = int(td.total_seconds() // 60)
    return timedelta(minutes=(total_minutes // 15) * 15)

def minutes_until(start: timedelta, end: timedelta) -> int:
    "Return whole minutes between timedeltas (can be negative)"
    delta = end - start
    return int(delta.total_seconds() // 60)

def status_to_bytestr(status: int) -> bytes:
    "Convert PicoWatcher status to a readable string"
    hw_status = status & 0x0F
    sw_status = (status & 0x30) >> 4
    print("status =", status, "hw_status =", hw_status, "sw_status =", sw_status)
    if hw_status == WDT_RESET:
        return b'watchdog_reset'
    if hw_status == PWRON_RESET:
        return b'poweron_reset'
    if sw_status == 3:
        return b'button_rebooted'
    if sw_status == 2:
        return b'button_pressed'
    if sw_status == 1:
        return b'timer_rebooted'
    return b''

def primary_voltage(val: Optional[int]) -> str:
    if val is None:
        return "ERR"
    conversion_factor = 13.16 / 46731 # recorded values
    full_battery = 13.24    # reference voltages for a full/empty battery, in volts
    empty_battery = 11.0   # the values could vary by battery size/manufacturer so you might need to adjust them
    voltage = val * conversion_factor
    percentage = 100 * ((voltage - empty_battery) / (full_battery - empty_battery))
    if percentage > 100:
        percentage = 100

    return '{:.2f}'.format(voltage) + "v " + '{:.0f}%'.format(percentage)

def secondary_voltage(val: Optional[int]) -> str:
    if val is None:
        return "ERR"
    conversion_factor = 3 * 3.3 / 65535
    full_battery = 4.2    # reference voltages for a full/empty battery, in volts
    empty_battery = 2.8   # the values could vary by battery size/manufacturer so you might need to adjust them
    voltage = val * conversion_factor
    percentage = 100 * ((voltage - empty_battery) / (full_battery - empty_battery))
    if percentage > 100:
        percentage = 100

    return '{:.2f}'.format(voltage) + "v " + '{:.0f}%'.format(percentage)

# ToDo: fold these two functions together
def piwatcher_status() -> List[bytes]:
    "Query PicoWatcher to reset watch timer"
    try:
        result = i2c.read_byte_data(addr, 1)
    except OSError:
        return [b'ERR', b'-1', b'OSError']
    print("PicoWatcher status =", result)
    return [b'OK', bytes(hex(result), 'utf-8'), status_to_bytestr(result)]

def piwatcher_reset() -> List[bytes]:
    "Reset PicoWatcher status register, to clear timer_rebooted, button_pressed, etc."
    try:
        result = i2c.read_byte_data(addr, 4)
    except OSError:
        return [b'ERR', b'-1', b'OSError']
    print("PicoWatcher reset =", result)
    return [b"OK", bytes(hex(result), 'utf-8'), status_to_bytestr(result)]

def piwatcher_led(state: int) -> None:
    "Switch the PicoWatcher LED on or off"
    try:
        result = i2c.write_byte_data(addr, 8, state)
        i2c.read_byte(addr) # dummy read
    except OSError:
        print("PicoWatcher I2C failure: LED write")
        result = None
    print("PicoWatcher LED =", state)
    
def piwatcher_wake(minutes: int) -> None:
    "Set the wake interval for PicoWatcher"
    while minutes < 0:
        minutes = minutes + 1440 # adjust for day crossings (*hack*)
    seconds = min(129600, minutes * 60) # clamp wake delay to 36 hours, to stay within 16-bit limit
    try:
        result = i2c.write_word_data(addr, 6, (seconds + 1) >> 2) # wake interval is specified in 2-sec units
        i2c.read_byte(addr) # dummy read
    except OSError:
        print("PicoWatcher I2C failure: wake")
        result = None
    print("PicoWatcher wake", seconds, "result =", result)

def piwatcher_watch(minutes: int) -> None:
    "Set the watch timeout interval for PicoWatcher"
    seconds = min (240, minutes * 60) # clamp wake delay to 240 seconds, to stay within 8-bit limit
    try:
        result = i2c.write_byte_data(addr, 5, seconds)
        i2c.read_byte(addr) # dummy read
    except OSError:
        print("PicoWatcher I2C failure: watch")
        result = None
    print("PicoWatcher watch", seconds, "result =", result)
                  
def picowatcher_rtc(time: Optional[RTCData] = None) -> Union[RTCData, int, None]:
    "Get or set the Pico's RTC"
    if time is None:
        time_list = i2c.read_i2c_block_data(addr, 3, 10)
        time_bytes = bytes(time_list)
        result = struct.unpack("HBBBBBBH", time_bytes)
    else:
        time_bytes = struct.pack("HBBBBBBH", *time)
        time_list = list(time_bytes)
        result = i2c.write_i2c_block_data(addr, 3, time_list)
        i2c.read_byte(addr) # dummy read
    return result

def system_shutdown(msg: str = "System going down", when: str = "now") -> None:
    "Shut down the system"
    print("Shutdown:", msg)
    result = subprocess.run(["/sbin/shutdown", str(when), str(msg)])
    print("shutdown =", result)

def stop_boot_watchdog() -> None:
    "Stop the piwatcher service"
    result = subprocess.run(["/bin/systemctl", "stop", "piwatcher.service"])
    print("stop piwatcher =", result)

def getBatteryLevel(reg: int = 2) -> Optional[int]:
    "Read the battery level from PicoWatcher"
    try:
        level = i2c.read_word_data(addr, reg)
    except OSError:
        print("PicoWatcher read failure: battery level", reg)
        level = None
    return level

def evaluate(now: timedelta, level: int) -> Tuple[timedelta, timedelta, str]:
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
    elif level >= 43000: # battery OK, stay up for 4 hours then power off for 2 hours
        stay_up = timedelta(minutes=120)
        wake_time = now + timedelta(minutes=360)
    else: # Battery low, power off immediately until 12:00 tomorrow
        stay_up = timedelta(minutes=10)
        if now >= timedelta(hours=12):
            wake_time = timedelta(days=1, hours=8)
            message = "Emergency shutdown until 8am tomorrow"
        else:
            wake_time = timedelta(hours=20)
            message = "Emergency shutdown until 8pm today"

    wake_time = floor_to_15(wake_time) # Round wake time down to nearest 15 minutes
    while (wake_time - now) < timedelta(minutes=15): # make sure that wake_time is at least 15mins in the future
        wake_time = wake_time + timedelta(minutes=15)
    if wake_time >= timedelta(hours=23): # wake is 11PM or later
        wake_time = max(wake_time, timedelta(days=1, hours=8)) # Don't bother waking until 8am
    if (now + stay_up) > timedelta(days=1): # don't stay up past midnight
        stay_up = timedelta(days=1) - now
    return (stay_up, wake_time, message)

def timestr(td: timedelta) -> str:
    "Convert time representation to readable time string"
    total_minutes = int(td.total_seconds() // 60)
    hours, mins = divmod(total_minutes, 60)
    return format(hours, "02") + ":" + format(mins, "02")

def test(level: int, interval: int = 15) -> None:
    "Test function for evaluate"
    for offset in range(0, 1440, interval):
        current = timedelta(minutes=offset)
        stay_up, wake_time, message = evaluate(current, level)
        print(timestr(current), " = ", int(stay_up.total_seconds() // 60), "mins", timestr(wake_time))

def test_all() -> None:
    "Test function for evaluate"
    for level in range(80,0,-10):
        test(level)

def ntfy(msg: str) -> None:
    requests.post("https://ntfy.sh/BWBirdBoxes",
                  data=msg.encode(encoding='utf-8'))

# MQTT setup
def on_message(client: mqtt.Client, userdata: Any, message: mqtt.MQTTMessage) -> None:
    global force_up
    if message.retain:
        print(message.topic, "=", str(message.payload.decode("utf-8")), "(retained)")
    else:
        print(message.topic, "=", str(message.payload.decode("utf-8")), "(live)")
    if message.topic == f"{root_topic}/force_up":
        if message.payload:
            force_up = bool(int.from_bytes(message.payload, byteorder='little'))
        else:
            force_up = None

def on_log(client: mqtt.Client, userdata: Any, level: int, buf: str) -> None:
    print("battmon MQTT: ", buf)
    
client: mqtt.Client = mqtt.Client(client_name)
client.on_message=on_message
client.on_log = on_log
client.connect_async(broker_name) # connect in background, in case broker not reachable

# main program 
try:
    client.loop_start() # start the MQTT client loop in a thread
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
    start_day = t.tm_yday
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
    level = getBatteryLevel()
    level2 = getBatteryLevel(7)
    voltage1 = primary_voltage(level)
    voltage2 = secondary_voltage(level2)
    print ("Battery levels: primary =", level, "secondary =", level2)
    client.publish(f"{root_topic}/initial_battery_level", voltage1, qos=1, retain=True)
    client.publish(f"{root_topic}/initial_battery2_level", voltage2, qos=1, retain=True)
    stay_up = timedelta(minutes=15) # default 15-minute time before shutting down, overridden below
    wake_time = noon_tomorrow # default wake-up time
    message = "Default shutdown"
    # Decide how long to stay up, based on time of day and battery level
    if level != None: # if there wasn't an I2C error reading the level
        stay_up, wake_time, message = evaluate(now, level)
    
    stay_up_minutes = int(stay_up.total_seconds() // 60)
    print("stay-up duration =", stay_up_minutes, "wake-up time =", timestr(wake_time))
    client.publish(f"{root_topic}/initial_stay_up", stay_up_minutes, qos=1, retain=True)
    client.publish(f"{root_topic}/wake_time", timestr(wake_time), qos=1, retain=True)
    ntfy(f'{client_name} up at {timestr(now)}, for {stay_up_minutes} mins: batt1 {voltage1}, batt2 {voltage2}')
    # Main watchdog wakeup loop
    while stay_up > timedelta(0):
        # Sleep for one minute
        time.sleep(60) # sleep interval shouldn't be longer than half the watchdog time
        now = now + timedelta(minutes=1)  # advance 'now' by one minute
        stay_up = stay_up - timedelta(minutes=1) # decrement the remaining stay-up duration by one minute
        stay_up_minutes = int(stay_up.total_seconds() // 60)
        client.publish(f"{root_topic}/stay_up", stay_up_minutes, qos=1, retain=False)
        status = piwatcher_status()  # reset the watchdog
        level = getBatteryLevel()
        print("now = ", timestr(now), "stay up = ", stay_up_minutes, "battery level =", level, "status =", status)
        client.publish(f"{root_topic}/battery_level", primary_voltage(level), qos=1, retain=True)
        if len(status) >= 2:
            status_val = int(status[1], base=16)
            if status_val != 0:
                client.publish(f"{root_topic}/status", status_val, qos=1, retain=True)
        if level < 43000: # low battery, shutdown immediately
            stay_up = timedelta(minutes=0)
            message = "Low battery, immediate shutdown"
        if b'button_pressed' in status: # shutdown immediately
            stay_up = timedelta(minutes=0)
            message = "Button pressed, immediate shutdown"
        if exists("/tmp/shutdown"): # if shutdown requested
            stay_up = timedelta(minutes=0)
            message = "/tmp/shutdown detected, immediate shutdown"
        if exists("/tmp/emergency_shutdown"): # if emergency shutdown requested
            stay_up = timedelta(minutes=0)
            wake_time = timedelta(hours=1, minutes=12, seconds=0)
            message = "/tmp/emergency_shutdown detected, shutting down until noon tomorrow"
        piwatcher_reset()        # clear the PiWatcher status
    # We've left the loop, initiate shutdown
    t = time.localtime() # get an accurate value for now
    now = timedelta(hours=t.tm_hour, minutes=t.tm_min)
#    now = now + 1440*(t.tm_yday - start_day) # adjust for any day crossings since boot (ToDo: incomplete)
    piwatcher_watch(3)      # set 3-minute watchdog timeout, again, in case it was cancelled by user
    piwatcher_led(True)     # turn on the PiWatcher's LED
    piwatcher_wake(max(minutes_until(now, wake_time) - 3, 0)) # set the wake-up interval
    print("Shutting down, wake time is", timestr(wake_time))
    client.publish(f"{root_topic}/shutdown_time", time.asctime(), qos=1, retain=True)
    client.publish(f"{root_topic}/wake_time", timestr(wake_time), qos=1, retain=True)
    client.publish(f"{root_topic}/message", message, qos=1, retain=True)
    ntfy(f'{client_name} down at {timestr(now)}, until {timestr(wake_time)}: batt1 {primary_voltage(level)}, {message}')
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
