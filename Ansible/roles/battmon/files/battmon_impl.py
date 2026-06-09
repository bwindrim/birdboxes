"""
Implementation module for BirdBox 1 & 2 (original battmon.py hardware-specific parts)
"""
from typing import List, Optional, Tuple
from datetime import timedelta
import subprocess
import RPi.GPIO as GPIO
from os.path import exists

broker_name: str = "broker.hivemq.com"

client_name = None

# Use BCM GPIO references instead of physical pin numbers
GPIO.setmode(GPIO.BCM)

# Define GPIO signals to use for the battery level
battery: List[int] = [13, 12, 7, 22]

GPIO.setup(battery, GPIO.IN, pull_up_down=GPIO.PUD_UP)

def piwatcher_status() -> List[bytes]:
    result = subprocess.run(["/usr/local/bin/piwatcher", "status"], capture_output=True)
    return result.stdout.split()

def piwatcher_reset() -> None:
    subprocess.run(["/usr/local/bin/piwatcher", "reset"], capture_output=True)

def piwatcher_led(state: bool) -> None:
    setting = "off"
    if state:
        setting = "on"
    # BirdBox1's PiWatcher doesn't support the LED command; guard earlier callers
    if subprocess.os.uname().nodename != "birdbox1":
        subprocess.run(["/usr/local/bin/piwatcher", "led", setting], capture_output=True)

def piwatcher_wake(minutes: int) -> None:
    if minutes < 10:
        minutes = 10
    seconds = minutes * 60
    if seconds > 129600:
        seconds = 129600
    subprocess.run(["/usr/local/bin/piwatcher", "wake", str(seconds)], capture_output=True)

def piwatcher_watch(minutes: int) -> None:
    if minutes < 3:
        minutes = 3
    seconds = minutes * 60
    if seconds > 255:
        seconds = 255
    subprocess.run(["/usr/local/bin/piwatcher", "watch", str(seconds)], capture_output=True)

def system_shutdown(msg: str = "System going down", when: str = "now") -> None:
    subprocess.run(["/sbin/shutdown", str(when), str(msg)])

def stop_boot_watchdog() -> None:
    subprocess.run(["/bin/systemctl", "stop", "piwatcher.service"])

def getBatteryLevel(numReads: int = 20) -> int:
    level = 0
    for i in range(numReads):
        for pin in battery:
            level += (1 - GPIO.input(pin))
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
    elif level >= 100:
        stay_up = timedelta(minutes=120)
        wake_time = now + timedelta(minutes=360)
    elif level >= 85:
        stay_up = timedelta(minutes=90)
        wake_time = now + timedelta(minutes=360)
    elif level >= 75:
        stay_up = timedelta(minutes=60)
        wake_time = now + timedelta(minutes=360)
    elif level >= 60:
        stay_up = timedelta(minutes=30)
        wake_time = now + timedelta(minutes=720)
    elif level >= 50:
        stay_up = timedelta(minutes=20)
        if now >= timedelta(hours=20):
            wake_time = timedelta(days=1, hours=8)
            message = "Low battery shutdown until 8am tomorrow"
        elif now >= timedelta(hours=12):
            wake_time = timedelta(hours=20)
            message = "Low battery shutdown until 8pm today"
        else:
            wake_time = timedelta(hours=14)
            message = "Low battery shutdown until 2pm today"
    else:
        stay_up = timedelta(minutes=10)
        if now >= timedelta(hours=12):
            wake_time = timedelta(days=1, hours=8)
            message = "Emergency shutdown until 8am tomorrow"
        else:
            wake_time = timedelta(hours=20)
            message = "Emergency shutdown until 8pm today"

    # Round wake time
    total_minutes = int(wake_time.total_seconds() // 60)
    wake_time = timedelta(minutes=(total_minutes // 15) * 15)
    if wake_time >= timedelta(hours=23):
        from datetime import timedelta as _td
        wake_time = max(wake_time, _td(days=1, hours=8))
    return (stay_up, wake_time, message)

def format_battery(level: Optional[int]) -> str:
    if level is None:
        return "ERR"
    return f"{level}%"

def cleanup() -> None:
    GPIO.cleanup()
