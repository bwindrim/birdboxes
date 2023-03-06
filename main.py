### i2s_test3.py
import micropython
import time
import gc # garbage collector
from micropython import const
from machine import Pin, RTC, ADC, WDT, lightsleep
from i2c_responder import I2CResponder
from struct import pack, unpack

micropython.opt_level(0) # zero is default, i.e. assertions are enabled

btn = Pin(12, Pin.IN, Pin.PULL_UP) # push-button input
pwr = Pin(22, Pin.OPEN_DRAIN, value=1)    # wide-input shim enable, pull low for power off
led = Pin(25, Pin.OUT, value=1)    # Pico LED control
sda = Pin(26, Pin.IN, Pin.PULL_UP) # when using ADC pins for I2C...
scl = Pin(27, Pin.IN, Pin.PULL_UP) # ...we need to turn on the pull-ups
adc = ADC(Pin(28)) # main battery voltage measurement
rtc = RTC()
i2c = I2CResponder(1, sda_gpio=26, scl_gpio=27, responder_address=0x41)

do_prt = 0
btn_down = False

def pi_power_off():
    "Disable +5V power to the Pi by turning off the wide-input shim"
    pwr.off()
    led.off()
    # turn the pull-ups off to conserve power
#     sda.init(Pin.IN, None)
#     scl.init(Pin.IN, None)
    return

def pi_power_on():
    "Enable +5V power to the Pi by turning on the wide-input shim"
    pwr.on()
    led.on()
    # turn the pull-ups back on
#     sda.init(Pin.IN, Pin.PULL_UP)
#     scl.init(Pin.IN, Pin.PULL_UP)
    return

def suspend(interval_s):
    "Sleep for the specified number of seconds, or until button pressed"
    reason = 0x10
    if do_prt >= 2:
        print("Sleeping for", interval_s, "s...")
    while interval_s > 0 and btn.value() is 1: # TBD: fix for interval_s % 5 != 0
        wdt.feed() # the watchdog timer appears to keep running during lightsleep()
        delay = min(interval_s*1000, 5000) # sleep for <= 5 seconds at a time
        if do_prt >= 2:
            time.sleep_ms(delay - 1)
        else:
            lightsleep(delay - 1)
        # blink the LED
        led.on()
        time.sleep_ms(1)
        led.off()
        interval_s -= 5
    if interval_s > 0: # it was the button press that exited the loop
        btn_down = True
        reason = 0x30 # button-press wakeup
    if do_prt >= 2:
        print("...wakeup, reason =", reason)
    return reason

# Check whether we were rebooted by the watchdog (WDT)
status = machine.reset_cause() # initialise status
if status is machine.WDT_RESET:
    print("Watchdog reset - sleeping for 10 seconds")
    time.sleep(10) # give time for REPL to break in before watchdog restarts
else:
    assert(status is machine.PWRON_RESET)
    print("Power-on reset")
watch_seconds = 0 # should be 4 minutes, in case Pi is hung when Pico restarts
wake_seconds  = 30 # should be 15 minutes, so Pi doesn't stay off
wdt = WDT(timeout=8388) # set ~8 sec (max) watchdog timeout

try:
    gc.disable() # we call garbage collection explicitly, below
    print("Polling I2C")
    prefix_reg = 0
    # All times are in milliseconds(?)
    ticks_base = time.ticks_ms() # get the start time for the watch delay

    while True: # main loop
        wdt.feed()

        # Poll for I2C writes
        if i2c.write_data_is_available(): # process register write
            buffer_in = i2c.get_write_bytes(max_size=16) # ToDo: what if we're faster than the bus?
            assert(len(buffer_in) > 0)
            if len(buffer_in) is 1: # just a register selection, a read should follow
                prefix_reg = buffer_in[0]   # buffer only contains a register number
            else:  # there is data after the reg number
                prefix_reg = buffer_in[0]   # first byte must be a register number
                data = buffer_in[1:]        # copy the tail of the buffer
                if data and do_prt >= 2:
                    print("Received I2C WRITE: reg =", prefix_reg, "data =", data, "len =", len(data))
                if prefix_reg is 5 and len(data) is 1: # watch time register (1 byte)
                    watch_seconds = int.from_bytes(data, 'little', False)
                    ticks_base = time.ticks_ms() # reset watch time base
                    prefix_reg = 0
                    if do_prt >= 1:
                        print("WATCH set to", watch_seconds)
                elif prefix_reg is 6 and len(data) is 2: # wake time register (2 bytes)
                    wake_seconds = int.from_bytes(data, 'little', False) << 2 # value is in 2-sec units
                    prefix_reg = 0
                    if do_prt >= 1:
                        print("WAKE set to", wake_seconds)
                elif prefix_reg is 3 and len(data) is 10: # RTC date/time
                    rtc.datetime(unpack("HBBBBBBH", data))
                    prefix_reg = 0
                elif do_prt >= 1 and len(data) > 0:
                    prefix_reg = 0
                    print("Unhandled reg write, reg =", prefix_reg, "buffer_in =", buffer_in)

        # Poll for I2C reads                
        if i2c.read_is_pending(): # process register read
            if prefix_reg == 1: # status register + watch reset
                ticks_base = time.ticks_ms() # reset watch time base
                data = status.to_bytes(1, 'little')
                assert(len(data) == 1)
                if do_prt >= 1:
                    print("Status:", status)
            elif prefix_reg == 2: # ADC value
                value = adc.read_u16()
                data = value.to_bytes(2,'little')
                assert(len(data) == 2)
                if do_prt >= 1:
                    print("ADC:", value)
            elif prefix_reg == 3: # RTC date/time
                data = pack("HBBBBBBH", *rtc.datetime())
                assert(len(data) == 10)
                if do_prt >= 1:
                    print("RTC:", data)
            elif prefix_reg == 4: # status register read and clear
                data = status.to_bytes(1, 'little')
                assert(len(data) == 1)
                status = 0
                if do_prt >= 1:
                    print("Status read and cleared")
            elif prefix_reg == 5: # watch time register (1 byte)
                data = watch_seconds.to_bytes(1, 'little')
                assert(len(data) == 1)
                if do_prt >= 2:
                    print("WATCH:", watch_seconds)
            elif prefix_reg == 6: # wake time register (2 bytes)
                data = (wake_seconds >> 2).to_bytes(2, 'little')
                assert(len(data) == 2)
                if do_prt >= 2:
                    print("WAKE:", wake_seconds)
            else: # return a zero byte for all unrecognised regs
                data = b'\x00'
                assert(len(data) == 1)
                if do_prt >= 2:
                    print("Default")
            i2c.put_read_bytes(data) # send the register data
            if do_prt >= 2:
                print("Sent I2C READ data for register", prefix_reg)
            prefix_reg = 0 # don't retain prefix

        # Poll the pushbutton
        if btn.value() is 0: # button is down
            status |= 0x20 # set the button flag in the status

        # Check for watch expiry (NOT the hardware watchdog)
        ticks_now = time.ticks_ms()
        ticks_interval = time.ticks_diff(ticks_now, ticks_base)
        if watch_seconds != 0 and ticks_interval >= watch_seconds*1000: # timeout set and reached
            if do_prt >= 2:
                print("Watch timeout exceeded: timeout =", watch_seconds*1000, "interval =", ticks_interval);
            pi_power_off() # cut the power to the Pi
            status |= suspend(wake_seconds) # merge the wakeup reason into status
            pi_power_on() # restore power to the Pi
            ticks_base = time.ticks_ms() # reset the watch

        # At the tail of the loop we give the garbage collector its own watchdog slice to run in
        wdt.feed()
        gc.collect()

except KeyboardInterrupt:
    pass
