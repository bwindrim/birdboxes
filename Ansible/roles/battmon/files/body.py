"""
Common body for battmon and birdbox3
Implements the main logic and relies on an "impl" module for hardware-specific functions.
"""
from typing import Any, List, Optional
import time
import socket
import requests
from datetime import timedelta
from os.path import exists
import paho.mqtt.client as mqtt

force_up: Optional[bool] = None

def hours(num: int) -> timedelta:
    return timedelta(hours=num)

def floor_to_15(td: timedelta) -> timedelta:
    total_minutes = int(td.total_seconds() // 60)
    return timedelta(minutes=(total_minutes // 15) * 15)

def minutes_until(start: timedelta, end: timedelta) -> int:
    delta = end - start
    return int(delta.total_seconds() // 60)

def timestr(td: timedelta) -> str:
    total_minutes = int(td.total_seconds() // 60)
    hours, mins = divmod(total_minutes, 60)
    return format(hours, "02") + ":" + format(mins, "02")

def ntfy(msg: str) -> None:
    try:
        requests.post("https://ntfy.sh/BWBirdBoxes", data=msg.encode(encoding='utf-8'))
    except Exception:
        pass

def on_message(client: mqtt.Client, userdata: Any, message: mqtt.MQTTMessage) -> None:
    global force_up
    if message.retain:
        print(message.topic, "=", str(message.payload.decode("utf-8")), "(retained)")
    else:
        print(message.topic, "=", str(message.payload.decode("utf-8")), "(live)")
    if message.topic.endswith('/force_up'):
        if message.payload:
            try:
                force_up = bool(int.from_bytes(message.payload, byteorder='little'))
            except Exception:
                force_up = None
        else:
            force_up = None

def on_log(client: mqtt.Client, userdata: Any, level: int, buf: str) -> None:
    print("battmon MQTT: ", buf)

def system_shutdown(msg: str = "System going down", when: str = "now") -> None:
    print("Shutdown:", msg)
    try:
        import subprocess
        subprocess.run(["/sbin/shutdown", str(when), str(msg)])
    except Exception as e:
        print("shutdown failed:", e)

def main(impl) -> None:
    global force_up
    broker_name = getattr(impl, 'broker_name', 'broker.hivemq.com')
    client_name = socket.gethostname()
    root_topic = f"BWBirdBoxes/{client_name}"

    client: mqtt.Client = mqtt.Client(client_name)
    client.connect_async(broker_name)
    client.on_message = on_message
    client.on_log = on_log

    try:
        client.loop_start()
        impl.stop_boot_watchdog()
        initial_status = impl.piwatcher_status()
        print("PiWatcher initial status =", initial_status)
        if isinstance(initial_status, (list, tuple)) and len(initial_status) >= 2:
            try:
                client.publish(f"{root_topic}/initial_status", int(initial_status[1], base=16), qos=1, retain=True)
            except Exception:
                pass
        impl.piwatcher_reset()
        impl.piwatcher_led(False)
        impl.piwatcher_watch(3)

        t = time.localtime()
        now = timedelta(hours=t.tm_hour, minutes=t.tm_min)
        noon_today = timedelta(hours=12)
        noon_tomorrow = timedelta(days=1, hours=12)
        print("now =", timestr(now), "noon today =", timestr(noon_today), "noon tomorrow =", timestr(noon_tomorrow))
        client.publish(f"{root_topic}/startup_time", time.asctime(), qos=1, retain=True)

        if (now > (noon_today - timedelta(hours=1))):
            impl.piwatcher_wake(minutes_until(now, noon_tomorrow))
        else:
            impl.piwatcher_wake(minutes_until(now, noon_today))

        # Read battery
        try:
            level = impl.getBatteryLevel()
        except TypeError:
            level = impl.getBatteryLevel(None)
        print("Battery level =", level)

        # Publish initial battery using impl formatter if present
        if hasattr(impl, 'format_battery'):
            pub_batt = impl.format_battery(level)
        else:
            pub_batt = f'{level}%'
        client.publish(f"{root_topic}/initial_battery_level", pub_batt, qos=1, retain=True)

        stay_up, wake_time, message = impl.evaluate(now, level)
        impl.piwatcher_wake(max(minutes_until(now, wake_time) - 3, 0))
        stay_up_minutes = int(stay_up.total_seconds() // 60)
        print("stay-up duration =", stay_up_minutes, "wake-up time =", timestr(wake_time))
        client.publish(f"{root_topic}/initial_stay_up", stay_up_minutes, qos=1, retain=True)
        client.publish(f"{root_topic}/wake_time", timestr(wake_time), qos=1, retain=True)
        ntfy(f'{client_name} up at {timestr(now)}, for {stay_up_minutes} mins: batt {pub_batt}')

        # Main loop
        while stay_up > timedelta(0):
            time.sleep(60)
            now = now + timedelta(minutes=1)
            stay_up = stay_up - timedelta(minutes=1)
            stay_up_minutes = int(stay_up.total_seconds() // 60)
            client.publish(f"{root_topic}/stay_up", stay_up_minutes, qos=1, retain=False)
            status = impl.piwatcher_status()
            level = impl.getBatteryLevel()
            print("now =", timestr(now), "stay up =", stay_up_minutes, "battery level =", level, "status =", status)

            # publish battery reading using impl formatter if present
            if hasattr(impl, 'format_battery'):
                client.publish(f"{root_topic}/battery_level", impl.format_battery(level), qos=1, retain=True)
            else:
                client.publish(f"{root_topic}/battery_level", f'{level}%', qos=1, retain=True)

            if isinstance(status, (list, tuple)) and len(status) >= 2:
                try:
                    status_val = int(status[1], base=16)
                    if status_val != 0:
                        client.publish(f"{root_topic}/status", status_val, qos=1, retain=True)
                except Exception:
                    pass

            if b'button_pressed' in status:
                stay_up = timedelta(minutes=0)
                message = "Button pressed, immediate shutdown"

            if exists("/tmp/shutdown"):
                stay_up = timedelta(minutes=0)
                message = "/tmp/shutdown detected, immediate shutdown"

            # impl-specific emergency file handling
            em_file = getattr(impl, 'EMERGENCY_SHUTDOWN_FILE', None)
            if em_file and exists(em_file):
                stay_up = timedelta(minutes=0)
                message = getattr(impl, 'EMERGENCY_SHUTDOWN_MESSAGE', "/tmp/emergency_shutdown detected, immediate shutdown")
                wake_override = getattr(impl, 'EMERGENCY_WAKE_TIME', None)
                if wake_override is not None:
                    wake_time = wake_override

            impl.piwatcher_wake(max(minutes_until(now, wake_time) - 3, 0))

        # Prepare for shutdown
        t = time.localtime()
        now = timedelta(hours=t.tm_hour, minutes=t.tm_min)
        impl.piwatcher_watch(3)
        impl.piwatcher_led(True)
        impl.piwatcher_wake(max(minutes_until(now, wake_time) - 3, 0))
        print("Shutting down, wake time is", timestr(wake_time))
        client.publish(f"{root_topic}/shutdown_time", time.asctime(), qos=1, retain=True)
        client.publish(f"{root_topic}/wake_time", timestr(wake_time), qos=1, retain=True)
        client.publish(f"{root_topic}/message", message, qos=1, retain=True)
        ntfy(f'{client_name} down at {timestr(now)}, until {timestr(wake_time)}: batt {pub_batt}, {message}')

        if exists("/tmp/noshutdown"):
            print("Shutdown blocked by /tmp/noshutdown, deferring by one hour")
            system_shutdown(message, when="+60")
        else:
            system_shutdown(message)

        while True:
            time.sleep(60)
            now = now + timedelta(minutes=1)
            status = impl.piwatcher_status()
            print("now =", timestr(now), "stay up =", stay_up_minutes, "battery level =", impl.getBatteryLevel(), "status =", status)

    except KeyboardInterrupt:
        impl.piwatcher_watch(0)
        print("Done.")
        client.loop_stop()
        if hasattr(impl, 'cleanup'):
            impl.cleanup()
