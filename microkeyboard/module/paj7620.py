#
# MicroPython Version - Adapted from CircuitPython Library
#
# Original Source: https://github.com/deshipu/circuitpython-paj7620/blob/main/paj7620.py
#
# Original SPDX-FileCopyrightText: 2017 Scott Shawcroft, written for Adafruit Industries
# Original SPDX-FileCopyrightText: Copyright (c) 2022 Radomir Dopieralski
# Original SPDX-License-Identifier: MIT
#
# This adaptation focuses on compatibility with MicroPython's machine.I2C.
#

# import ustruct
from machine import I2C, Pin # Import necessary MicroPython modules

# Gesture definitions
UP = 0x01
DOWN = 0x02
LEFT = 0x04
RIGHT = 0x08
NEAR = 0x10
FAR = 0x20
CW = 0x40
CCW = 0x80
WAVE = 0x100

# Initialization addresses and data
# These are the register configurations needed to initialize the PAJ7620
# for operation.
_ADDR = (
    b"\xefAB789BFGHIJLQ^`\x80\x81\x82\x8b\x90\x95\x96\x97\x9a\x9c"
    b"\xa5\xcc\xcd\xce\xcf\xd0\xef\x02\x03\x04%'()>^egijmnrstw\xef"
    b"AB"
)
_DATA = (
    b"\x00\x00\x00\x07\x17\x06\x01-\x0f<\x00\x1e\"\x10\x10'BD\x04"
    b"\x01\x06\n\x0c\x05\x14?\x19\x19\x0b\x13d!\x01\x0f\x10\x02\x01"
    b"9\x7f\x08\xff=\x96\x97\xcd\x01,\x01\x015\x00\x01\x00\xff\x01"
)

class PAJ7620Gesture:
    """
    Driver for the PAJ7620 gesture sensor.

    This class provides an interface to initialize the sensor and read
    detected gestures.
    """

    def __init__(self, i2c_bus, addr=0x73):
        """
        Initializes the PAJ7620 gesture sensor.

        Args:
            i2c_bus: An initialized MicroPython machine.I2C object.
            addr (int): The I2C address of the PAJ7620 sensor. Default is 0x73.
        """
        self.i2c = i2c_bus
        self.addr = addr
        self.buf = bytearray(2) # Buffer for I2C read/write operations

        # Initialize the sensor by writing the predefined register configurations.
        # This sequence is crucial for getting the sensor into an operational state.
        for address, data in zip(_ADDR, _DATA):
            self.buf[0] = address
            self.buf[1] = data
            self.i2c.writeto(self.addr, self.buf)

    def read(self):
        """
        Read and clear the gestures from the sensor.

        The PAJ7620 reports detected gestures in a specific register.
        Reading this register also clears the gesture flag, allowing
        new gestures to be detected.

        Returns:
            int: A bitmask representing the detected gestures.
                 Multiple gestures can be combined (e.g., UP | RIGHT).
        """
        # Command to read the gesture status register (0x43)
        self.i2c.writeto(self.addr, b"\x43")
        self.i2c.readfrom_into(self.addr, self.buf)

        # The gesture data is returned as two bytes, which we combine into an integer.
        # MicroPython's ustruct module can be used for more complex packing/unpacking,
        # but for two bytes, int.from_bytes is straightforward.
        return int.from_bytes(self.buf, "little")
