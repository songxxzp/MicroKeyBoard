# Use ampy to sync files.

import usb.device
from usb.device.keyboard import KeyboardInterface, KeyCode
import time


def keyboard_example():
    # Register the keyboard interface and re-enumerate
    k = KeyboardInterface()
    usb.device.get().init(k, builtin_driver=True)

    print("Entering keyboard...")

    # iteration will always send
    time.sleep_ms(1000)
    if k.is_open():
        # Press M
        k.send_keys([KeyCode.M])
        # Press I, Release M.
        k.send_keys([KeyCode.I])
        # Press C, Release I.
        k.send_keys([KeyCode.C])
        # Press R, Release C.
        k.send_keys([KeyCode.R])
        # Press O, Release R.
        k.send_keys([KeyCode.O])
        # Release O.
        k.send_keys([])


if __name__ == "__main__":
    keyboard_example()

