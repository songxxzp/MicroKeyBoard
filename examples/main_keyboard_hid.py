# Use ampy to sync files.

import struct
import bluetooth

from micropython import const

print("Hello, world!")

import usb.device
from usb.device.keyboard import KeyboardInterface, KeyCode, LEDCode
from machine import Pin
import time

# Tuples mapping Pin inputs to the KeyCode each input generates
#
# (Big keyboards usually multiplex multiple keys per input with a scan matrix,
# but this is a simple example.)
KEYS = (
    # ... add more pin to KeyCode mappings here if needed
)

# Tuples mapping Pin outputs to the LEDCode that turns the output on
LEDS = (
    # ... add more pin to LEDCode mappings here if needed
)


class ExampleKeyboard(KeyboardInterface):
    def on_led_update(self, led_mask):
        # print(hex(led_mask))
        for pin, code in LEDS:
            # Set the pin high if 'code' bit is set in led_mask
            pin(code & led_mask)


def keyboard_example():
    # Initialise all the pins as active-low inputs with pullup resistors
    for pin, _ in KEYS:
        pin.init(Pin.IN, Pin.PULL_UP)

    # Initialise all the LEDs as active-high outputs
    for pin, _ in LEDS:
        pin.init(Pin.OUT, value=0)

    # Register the keyboard interface and re-enumerate
    k = ExampleKeyboard()
    usb.device.get().init(k, builtin_driver=True)

    print("Entering keyboard loop...")

    keys = []  # Keys held down, reuse the same list object
    prev_keys = [None]  # Previous keys, starts with a dummy value so first
    # iteration will always send
    time.sleep_ms(1000)
    if k.is_open():
        k.send_keys([KeyCode.M])
    while True:
        if k.is_open():
            keys.clear()
            for pin, code in KEYS:
                if not pin():  # active-low
                    keys.append(code)
            if keys != prev_keys:
                # print(keys)
                k.send_keys(keys)
                prev_keys.clear()
                prev_keys.extend(keys)

        # This simple example scans each input in an infinite loop, but a more
        # complex implementation would probably use a timer or similar.
        time.sleep_ms(1)


keyboard_example()
