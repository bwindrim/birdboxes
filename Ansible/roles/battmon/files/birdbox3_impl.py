"""
Implementation module for BirdBox 3 (original birdbox3.py hardware-specific parts)
"""
from typing import Any, List, Optional, Tuple, Union
from datetime import timedelta
import struct
import smbus
import RPi.GPIO as GPIO
from os.path import exists

# Constants
PWRON_RESET: int = 1
WDT_RESET: int = 3

broker_name: str = "broker.hivemq.com"

# Use BCM GPIO references
GPIO.setmode(GPIO.BCM)
battery: List[int] = [6, 12, 13, 26]

GPIO.setup(battery, GPIO.IN, pull_up_down=GPIO.PUD_UP)

# Pico/I2C setup
i2c: smbus.SMBus = smbus.SMBus(1)
addr: int = 0x41

EMERGENCY_SHUTDOWN_FILE = "/tmp/emergency_shutdown"
EMERGENCY_SHUTDOWN_MESSAGE = "/tmp/emergency_shutdown detected, shutting down until noon tomorrow"
EMERGENCY_WAKE_TIME = timedelta(days=1, hours=12)

def status_to_bytestr(status: int) -> bytes:
    hw_status = status & 0x0F
    sw_status = (status & 0x30) >> 4
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
    conversion_factor = 13.16 / 46731
    full_battery = 13.24
    empty_battery = 11.0
    voltage = val * conversion_factor
    percentage = 100 * ((voltage - empty_battery) / (full_battery - empty_battery))
    if percentage > 100:
        percentage = 100
    return '{:.2f}'.format(voltage) + "v " + '{:.0f}%'.format(percentage)

def secondary_voltage(val: Optional[int]) -> str:
    if val is None:
        return "ERR"
    conversion_factor = 3 * 3.3 / 65535
    full_battery = 4.2
    empty_battery = 2.8
    voltage = val * conversion_factor
    percentage = 100 * ((voltage - empty_battery) / (full_battery - empty_battery))
    if percentage > 100:
        percentage = 100
    return '{:.2f}'.format(voltage) + "v " + '{:.0f}%'.format(percentage)

def piwatcher_status() -> List[bytes]:
    try:
        result = i2c.read_byte_data(addr, 1)
    except OSError:
        return [b'ERR', b'-1', b'OSError']
    return [b'OK', bytes(hex(result), 'utf-8'), status_to_bytestr(result)]

def piwatcher_reset() -> List[bytes]:
    try:
        result = i2c.read_byte_data(addr, 4)
    except OSError:
        return [b'ERR', b'-1', b'OSError']
    return [b"OK", bytes(hex(result), 'utf-8'), status_to_bytestr(result)]

def piwatcher_led(state: bool) -> None:
    try:
        i2c.write_byte_data(addr, 8, int(state))
        i2c.read_byte(addr)
    except OSError:
        pass

def piwatcher_wake(minutes: int) -> None:
    while minutes < 0:
        minutes = minutes + 1440
    seconds = min(129600, minutes * 60)
    try:
        i2c.write_word_data(addr, 6, (seconds + 1) >> 2)
        i2c.read_byte(addr)
    except OSError:
        pass

def piwatcher_watch(minutes: int) -> None:
    seconds = min(240, minutes * 60)
    try:
        i2c.write_byte_data(addr, 5, seconds)
        i2c.read_byte(addr)
    except OSError:
        pass

def stop_boot_watchdog() -> None:
    import subprocess
    subprocess.run(["/bin/systemctl", "stop", "piwatcher.service"])

def getBatteryLevel(reg: int = 2) -> Optional[int]:
    try:
        level = i2c.read_word_data(addr, reg)
    except OSError:
        level = None
    return level

def evaluate(now: timedelta, level: int) -> Tuple[timedelta, timedelta, str]:
    message = "Scheduled shutdown"
    if now < timedelta(hours=5, minutes=30):
        stay_up = timedelta(minutes=10)
        wake_time = timedelta(hours=8)
        message = "Night-time immediate shutdown"
        return (stay_up, wake_time, message)
    elif now < timedelta(hours=7, minutes=30):
        stay_up = timedelta(minutes=60)
        wake_time = timedelta(hours=8)
        message = "Early morning shutdown"
        return (stay_up, wake_time, message)
    elif level is not None and level >= 43000:
        stay_up = timedelta(minutes=120)
        wake_time = now + timedelta(minutes=360)
    else:
        stay_up = timedelta(minutes=10)
        if now >= timedelta(hours=12):
            wake_time = timedelta(days=1, hours=8)
            message = "Emergency shutdown until 8am tomorrow"
        else:
            wake_time = timedelta(hours=20)
            message = "Emergency shutdown until 8pm today"

    total_minutes = int(wake_time.total_seconds() // 60)
    wake_time = timedelta(minutes=(total_minutes // 15) * 15)
    while (wake_time - now) < timedelta(minutes=15):
        wake_time = wake_time + timedelta(minutes=15)
    if wake_time >= timedelta(hours=23):
        wake_time = max(wake_time, timedelta(days=1, hours=8))
    if (now + stay_up) > timedelta(days=1):
        stay_up = timedelta(days=1) - now
    return (stay_up, wake_time, message)

def format_battery(level: Optional[int]) -> str:
    primary = primary_voltage(level)
    try:
        level2 = getBatteryLevel(7)
    except Exception:
        level2 = None
    secondary = secondary_voltage(level2)
    return f"{primary}, {secondary}"

def cleanup() -> None:
    GPIO.cleanup()
