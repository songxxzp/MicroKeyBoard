# MicroPython driver for TCA8418 Keyboard Multiplexor
# Converted from Adafruit CircuitPython library:
# https://github.com/adafruit/Adafruit_CircuitPython_TCA8418/blob/main/adafruit_tca8418.py

from micropython import const
import machine

# TCA8418 Register Addresses
TCA8418_I2CADDR_DEFAULT = const(0x34)

_TCA8418_REG_CONFIG = const(0x01)
_TCA8418_REG_INTSTAT = const(0x02)
_TCA8418_REG_KEYLCKEC = const(0x03)
_TCA8418_REG_KEYEVENT = const(0x04) # Key event FIFO

_TCA8418_REG_GPIODATSTAT1 = const(0x14) # Data input status (GPIODATSTAT1/2/3)
_TCA8418_REG_GPIODATOUT1 = const(0x17) # Data output value (GPIODATOUT1/2/3)
_TCA8418_REG_INTEN1 = const(0x1A) # Interrupt enable (INTEN1/2/3)
_TCA8418_REG_KPGPIO1 = const(0x1D) # Keypad or GPIO mode select (KPGPIO1/2/3)
_TCA8418_REG_GPIOINTSTAT1 = const(0x11) # GPIO interrupt status (GPIOINTSTAT1/2/3)

_TCA8418_REG_EVTMODE1 = const(0x20) # Event mode (EVTMODE1/2/3)
_TCA8418_REG_GPIODIR1 = const(0x23) # GPIO direction (GPIODIR1/2/3)
_TCA8418_REG_INTLVL1 = const(0x26) # Interrupt level (INTLVL1/2/3)
_TCA8418_REG_DEBOUNCEDIS1 = const(0x29) # Debounce disable (DEBOUNCEDIS1/2/3)
_TCA8418_REG_GPIOPULL1 = const(0x2C) # Pull-up enable (GPIOPULL1/2/3)

# Simple constants for DigitalInOut compatibility
class Direction:
    INPUT = 0
    OUTPUT = 1

class Pull:
    UP = 1 # TCA8418 only supports pull-up

# Helper class for 18-bit registers spread across 3 bytes
# And for accessing individual bits within these registers
# All methods are now explicit
class TCA8418_register:
    def __init__(
        self,
        tca, # Reference to the main TCA8418 object
        base_addr: int,
        invert_value: bool = False,
        read_only: bool = False,
        initial_value: int | None = None, # Allow None
    ):
        self._tca = tca
        self._baseaddr = base_addr
        self._invert = invert_value
        self._ro = read_only

        if not read_only and initial_value is not None:
            # Write initial value across 3 bytes
            self._tca._write_reg(base_addr, initial_value & 0xFF)
            self._tca._write_reg(base_addr + 1, (initial_value >> 8) & 0xFF)
            self._tca._write_reg(base_addr + 2, (initial_value >> 16) & 0x03) # Only bits 16, 17 used

    def get_value_18bit(self) -> int:
        # Read all 18 bits of register data and return as one integer
        val = self._tca._read_reg(self._baseaddr + 2)
        val <<= 8
        val |= self._tca._read_reg(self._baseaddr + 1)
        val <<= 8
        val |= self._tca._read_reg(self._baseaddr)
        val &= 0x3FFFF # Mask to 18 bits
        return val

    def get_bit(self, pin_number: int) -> bool:
        # Read the single bit at 'pin_number' offset
        value = self._tca._get_gpio_register_bit(self._baseaddr, pin_number)
        if self._invert:
            value = not value
        return value

    def set_bit(self, pin_number: int, value: bool) -> None:
        # Set a single bit at 'pin_number' offset to 'value'
        if self._ro:
            raise NotImplementedError("Read only register")
        if self._invert:
            value = not value
        self._tca._set_gpio_register_bit(self._baseaddr, pin_number, value)


class TCA8418:
    """Driver for the TCA8418 I2C Keyboard expander / multiplexor."""

    # Pin aliases for convenience (R0-R7, C0-C9 -> 0-17)
    R0 = 0
    R1 = 1
    R2 = 2
    R3 = 3
    R4 = 4
    R5 = 5
    R6 = 6
    R7 = 7
    C0 = 8
    C1 = 9
    C2 = 10
    C3 = 11
    C4 = 12
    C5 = 13
    C6 = 14
    C7 = 15
    C8 = 16
    C9 = 17

    def __init__(self, i2c_bus: machine.I2C, address: int = TCA8418_I2CADDR_DEFAULT) -> None:
        self._i2c = i2c_bus
        self._addr = address

        # --- Register access using explicit getters and setters ---

        # Initialize multi-pin registers using TCA8418_register helper instances
        # access methods like instance.get_bit(pin) or instance.set_bit(pin, value)

        # disable all interrupt (INTEN1/2/3)
        self.enable_int = TCA8418_register(self, _TCA8418_REG_INTEN1, initial_value=0)
        self.gpio_int_status = TCA8418_register(
             self, _TCA8418_REG_GPIOINTSTAT1, read_only=True
        )
        # Read to clear GPIO interrupt status on startup (read the 18-bit value)
        _ = self.gpio_int_status.get_value_18bit()


        # plain GPIO expansion as indexable properties

        # set all pins to inputs (GPIODIR1/2/3 = 0)
        self.gpio_direction = TCA8418_register(
             self, _TCA8418_REG_GPIODIR1, initial_value=0
        )
        # set all pins to GPIO mode (KPGPIO1/2/3 = 1, inverted means initial_value=0 sets to GPIO=1)
        self.gpio_mode = TCA8418_register(
             self, _TCA8418_REG_KPGPIO1, invert_value=True, initial_value=0
        )
        # set all pins to Keypad mode (KPGPIO1/2/3 = 0)
        # Use non-inverted for keypad mode setting
        self.keypad_mode = TCA8418_register(self, _TCA8418_REG_KPGPIO1, invert_value=False)


        # set all pins low output (GPIODATOUT1/2/3 = 0)
        self.output_value = TCA8418_register(
             self, _TCA8418_REG_GPIODATOUT1, initial_value=0
        )
        # input value (GPIODATSTAT1/2/3, read only)
        self.input_value = TCA8418_register(
             self, _TCA8418_REG_GPIODATSTAT1, read_only=True
        )
        # enable all pullups (GPIOPULL1/2/3 = 1, inverted means initial_value=0 sets to pullup=1)
        self.pullup = TCA8418_register(
             self, _TCA8418_REG_GPIOPULL1, invert_value=True, initial_value=0
        )
        # enable all debounce (DEBOUNCEDIS1/2/3 = 0, inverted means initial_value=0 sets to debounce=1)
        self.debounce = TCA8418_register(
             self, _TCA8418_REG_DEBOUNCEDIS1, invert_value=True, initial_value=0
        )
        # default int on falling edge (INTLVL1/2/3 = 0)
        self.int_on_rising = TCA8418_register(
             self, _TCA8418_REG_INTLVL1, initial_value=0
        )

        # default no gpio in event queue (EVTMODE1/2/3 = 0)
        self.event_mode_fifo = TCA8418_register(
             self, _TCA8418_REG_EVTMODE1, initial_value=0
        )


        # read in event queue to clear any pending events from powerup
        # print(self.get_events_count(), "events") # for debugging
        while self.get_events_count() > 0:
             _ = self.read_next_event()  # read and toss

        # reset interrupts by writing 1s to clear status bits in INTSTAT register
        self._write_reg(_TCA8418_REG_INTSTAT, 0x1F) # Write 1 to bits 0-4 to clear

    # --- Explicit Getter and Setter methods for single bits/fields ---

    def get_events_count(self) -> int:
        """Get the number of events in the FIFO (from KEYLCKEC register bits 0-3)"""
        return (self._read_reg(_TCA8418_REG_KEYLCKEC) >> 0) & 0b1111

    # INTSTAT register bits (Read/Write - writing 1 clears)
    def get_cad_int(self) -> bool: return self._get_reg_bit(_TCA8418_REG_INTSTAT, 4)
    def clear_cad_int(self) -> None: self._set_reg_bit(_TCA8418_REG_INTSTAT, 4, True) # Write 1 to clear

    def get_overflow_int(self) -> bool: return self._get_reg_bit(_TCA8418_REG_INTSTAT, 3)
    def clear_overflow_int(self) -> None: self._set_reg_bit(_TCA8418_REG_INTSTAT, 3, True) # Write 1 to clear

    def get_keylock_int(self) -> bool: return self._get_reg_bit(_TCA8418_REG_INTSTAT, 2)
    def clear_keylock_int(self) -> None: self._set_reg_bit(_TCA8418_REG_INTSTAT, 2, True) # Write 1 to clear

    def get_gpi_int(self) -> bool: return self._get_reg_bit(_TCA8418_REG_INTSTAT, 1)
    def clear_gpi_int(self) -> None: self._set_reg_bit(_TCA8418_REG_INTSTAT, 1, True) # Write 1 to clear

    def get_key_int(self) -> bool: return self._get_reg_bit(_TCA8418_REG_INTSTAT, 0)
    def clear_key_int(self) -> None: self._set_reg_bit(_TCA8418_REG_INTSTAT, 0, True) # Write 1 to clear

    # CONFIG register bits (Read/Write)
    def get_gpi_event_while_locked(self) -> bool: return self._get_reg_bit(_TCA8418_REG_CONFIG, 6)
    def set_gpi_event_while_locked(self, value: bool) -> None: self._set_reg_bit(_TCA8418_REG_CONFIG, 6, value)

    def get_overflow_mode(self) -> bool: return self._get_reg_bit(_TCA8418_REG_CONFIG, 5)
    def set_overflow_mode(self, value: bool) -> None: self._set_reg_bit(_TCA8418_REG_CONFIG, 5, value)

    def get_int_retrigger(self) -> bool: return self._get_reg_bit(_TCA8418_REG_CONFIG, 4)
    def set_int_retrigger(self, value: bool) -> None: self._set_reg_bit(_TCA8418_REG_CONFIG, 4, value)

    def get_overflow_intenable(self) -> bool: return self._get_reg_bit(_TCA8418_REG_CONFIG, 3)
    def set_overflow_intenable(self, value: bool) -> None: self._set_reg_bit(_TCA8418_REG_CONFIG, 3, value)

    def get_keylock_intenable(self) -> bool: return self._get_reg_bit(_TCA8418_REG_CONFIG, 2)
    def set_keylock_intenable(self, value: bool) -> None: self._set_reg_bit(_TCA8418_REG_CONFIG, 2, value)

    def get_GPI_intenable(self) -> bool: return self._get_reg_bit(_TCA8418_REG_CONFIG, 1)
    def set_GPI_intenable(self, value: bool) -> None: self._set_reg_bit(_TCA8418_REG_CONFIG, 1, value)

    def get_key_intenable(self) -> bool: return self._get_reg_bit(_TCA8418_REG_CONFIG, 0)
    def set_key_intenable(self, value: bool) -> None: self._set_reg_bit(_TCA8418_REG_CONFIG, 0, value)

    def read_next_event(self) -> int:
        """Read the next key event from the FIFO"""
        if self.get_events_count() == 0:
            raise RuntimeError("No events in FIFO")
        # Read from the KEYEVENT register (FIFO)
        return self._read_reg(_TCA8418_REG_KEYEVENT)

    # Helper methods to access bits across GPIODATSTAT/OUT, INTEN, KPGPIO, etc.
    # These map a pin number (0-17) to the correct register (base + pin//8)
    # and bit offset (pin%8).
    def _set_gpio_register_bit(self, reg_base_addr: int, pin_number: int, value: bool) -> None:
        if not 0 <= pin_number <= 17:
            raise ValueError("Pin number must be between 0 & 17")
        reg_addr = reg_base_addr + pin_number // 8
        bit_offset = pin_number % 8
        self._set_reg_bit(reg_addr, bit_offset, value)

    def _get_gpio_register_bit(self, reg_base_addr: int, pin_number: int) -> bool:
        if not 0 <= pin_number <= 17:
            raise ValueError("Pin number must be between 0 & 17")
        reg_addr = reg_base_addr + pin_number // 8
        bit_offset = pin_number % 8
        return self._get_reg_bit(reg_addr, bit_offset)

    def get_pin(self, pin: int): # Returns DigitalInOut instance
        """Convenience function to create an instance of the DigitalInOut class
        pointing at the specified pin of this TCA8418 device.
        """
        assert 0 <= pin <= 17
        # Ensure the pin is configured as GPIO before creating DigitalInOut
        self.gpio_mode.set_bit(pin, True) # Set to GPIO mode using set_bit
        return DigitalInOut(pin, self)

    # Low-level register helpers using machine.I2C
    def _set_reg_bit(self, addr: int, bitoffset: int, value: bool) -> None:
        temp = self._read_reg(addr)
        if value:
            temp |= (1 << bitoffset)
        else:
            temp &= ~(1 << bitoffset)
        self._write_reg(addr, temp)

    def _get_reg_bit(self, addr: int, bitoffset: int) -> bool:
        temp = self._read_reg(addr)
        return bool(temp & (1 << bitoffset))

    def _write_reg(self, addr: int, val: int) -> None:
        # TCA8418 Write Operation: START -> Addr + W -> ACK -> RegAddr -> ACK -> Data -> ACK -> STOP
        try:
            self._i2c.writeto(self._addr, bytes([addr, val]))
        except OSError as e:
            print("I2C write error:", e)
            # Handle error appropriately

    def _read_reg(self, addr: int) -> int:
        # TCA8418 Read Operation: START -> Addr + W -> ACK -> RegAddr -> ACK -> START -> Addr + R -> ACK -> Data -> NACK -> STOP
        try:
            buffer = bytearray(1)
            self._i2c.writeto(self._addr, bytes([addr])) # Send register address
            self._i2c.readfrom_into(self._addr, buffer) # Read 1 byte into buffer
            return buffer[0]
        except OSError as e:
            print("I2C read error:", e)
            # Handle error appropriately
            return 0 # Return a default value or raise


# All methods are now explicit
class DigitalInOut:
    """Digital input/output of the TCA8418. Mimics digitalio.DigitalInOut interface.
    Note: TCA8418 does not support pull-down resistors.
    """

    def __init__(self, pin_number: int, tca: TCA8418) -> None:
        """Specify the pin number of the TCA8418 0..17, and instance."""
        self._pin = pin_number
        self._tca = tca
        # Ensure the pin is set to GPIO mode when creating the object
        # This was done in get_pin, but good to be sure.
        self._tca.gpio_mode.set_bit(pin_number, True)
        self._dir = None # Store current direction

    # Use local Direction and Pull constants
    # pylint: disable=unused-argument
    def switch_to_output(self, value: bool = False, **kwargs) -> None:
        """Switch the pin state to a digital output."""
        self.set_direction(Direction.OUTPUT)
        self.set_value(value)

    def switch_to_input(self, pull: int | None = None, **kwargs) -> None: # Pull expects int or None
        """Switch the pin state to a digital input."""
        self.set_direction(Direction.INPUT)
        self.set_pull(pull)

    # pylint: enable=unused-argument

    def get_value(self) -> bool:
        """Get the value of the pin."""
        # Read input value if configured as input, output value if configured as output
        # Need to read direction first to know which register to check
        is_output = self._tca.gpio_direction.get_bit(self._pin)
        if not is_output: # Direction.INPUT
             return self._tca.input_value.get_bit(self._pin)
        else: # Direction.OUTPUT
             # Reading back the output value set in the register
             return self._tca.output_value.get_bit(self._pin)

    def set_value(self, val: bool) -> None:
        # Need to read direction first to enforce output mode
        is_output = self._tca.gpio_direction.get_bit(self._pin)
        if not is_output: # Direction.INPUT
             raise AttributeError("Pin must be set to OUTPUT mode to set value")
        self._tca.output_value.set_bit(self._pin, val)

    def get_direction(self) -> int: # Return int
        """Get the direction of the pin (INPUT or OUTPUT)."""
        # Read from TCA8418's direction register
        is_output = self._tca.gpio_direction.get_bit(self._pin)
        self._dir = Direction.OUTPUT if is_output else Direction.INPUT
        return self._dir

    def set_direction(self, val: int) -> None: # Expect int
        if val == Direction.INPUT:
            self._tca.gpio_direction.set_bit(self._pin, False) # False for Input
        elif val == Direction.OUTPUT:
            self._tca.gpio_direction.set_bit(self._pin, True) # True for Output
        else:
            raise ValueError("Expected Direction.INPUT or Direction.OUTPUT!")

        self._dir = val # Store the set direction

    def get_pull(self) -> int | None: # Return int or None
        """Get the pull setting for the digital IO (Pull.UP or None)."""
        # Read from TCA8418's pullup register
        if self._tca.pullup.get_bit(self._pin):
             return Pull.UP
        return None

    def set_pull(self, val: int | None) -> None: # Expect int or None
        # Need to read direction first to enforce input mode
        is_output = self._tca.gpio_direction.get_bit(self._pin)
        if is_output: # Direction.OUTPUT
             raise AttributeError("Pull setting only applies to INPUT direction")

        if val is Pull.UP:
            # for inputs, turn on the pullup (write True)
            self._tca.pullup.set_bit(self._pin, True)
        elif val is None:
            self._tca.pullup.set_bit(self._pin, False)
        else:
            raise NotImplementedError("Pull-down resistors not supported.")
