import time

from machine import Pin

from microkeyboard.module.pca9555 import PCA9555 # 确保pca9555.py文件在MicroPython设备上


class I2CPin:
    """
    A class that mimics the functionality and interface of machine.Pin,
    but controls a specific pin on a PCA9555 I2C GPIO expander.
    """

    # Constants to match machine.Pin modes
    IN = Pin.IN
    OUT = Pin.OUT
    OPEN_DRAIN = Pin.OPEN_DRAIN # PCA9555 is push-pull, so OPEN_DRAIN will behave like OUT
    PULL_UP = Pin.PULL_UP    # PCA9555 does not have internal pull-ups, this will be ignored
    PULL_DOWN = Pin.PULL_DOWN  # PCA9555 does not have internal pull-downs, this will be ignored

    def __init__(self, pca_instance: PCA9555, pin_number: int, mode=-1, pull=-1):
        """
        Initializes an I2CPin object for a specific PCA9555 pin.

        Args:
            pca_instance: An initialized PCA9555 object (e.g., pca = PCA9555(i2c)).
            pin_number: The physical pin number on the PCA9555 (0 to 15).
            mode: Optional. The initial pin mode (I2CPin.IN or I2CPin.OUT).
                  If not provided, the current mode set in PCA9555 will be used.
            pull: Optional. The pull resistor setting (I2CPin.PULL_UP or I2CPin.PULL_DOWN).
                  Note: PCA9555 does NOT have internal pull resistors. This parameter
                  is included for API compatibility but will be ignored.
        """
        if not isinstance(pca_instance, PCA9555):
            raise TypeError("pca_instance must be an initialized PCA9555 object.")
        if not 0 <= pin_number <= 15:
            raise ValueError("pin_number must be between 0 and 15.")

        self._pca = pca_instance
        self._pin_num = pin_number
        self._mode = None # To store the current mode: 0 for OUT, 1 for IN
        self._handler = None
        self._trigger = None
        
        # Apply initial mode if provided
        if mode != -1:
            self.init(mode, pull)
        else:
            # If no mode is provided, try to read the current config
            # Note: The PCA9555 driver (pca9555.py) does not currently expose a way
            # to read a pin's current configuration, so we default to input.
            # You might need to extend pca9555.py if you strictly need this.
            # For now, we'll assume it's unconfigured or stick to a safe default.
            # It's always best to explicitly set the mode.
            print(f"Warning: I2CPin {pin_number} initialized without explicit mode. Please call init() or specify mode in constructor.")

    def init(self, mode, pull=-1):
        """
        Configures the pin mode (input or output).

        Args:
            mode: The pin mode (I2CPin.IN or I2CPin.OUT).
            pull: Optional. Pull resistor setting. Ignored for PCA9555.
        """
        if mode == self.IN:
            self._pca.set_pin_mode(self._pin_num, 1) # 1 for input in PCA9555 driver
            self._mode = 1 # Store internal mode for consistency
        elif mode == self.OUT or mode == self.OPEN_DRAIN:
            self._pca.set_pin_mode(self._pin_num, 0) # 0 for output in PCA9555 driver
            self._mode = 0 # Store internal mode for consistency
        else:
            raise ValueError("Invalid pin mode specified. Use I2CPin.IN or I2CPin.OUT.")
        
        # print(f"I2CPin {self._pin_num} set to mode: {mode}")

    def value(self, x=None):
        """
        Gets or sets the pin's digital value.

        Args:
            x: Optional. If None, reads the pin's value.
               If 0 or 1, sets the pin's output value.

        Returns:
            The pin's value if x is None (0 or 1).
        """
        if x is None:
            # Read pin value (assumes pin is configured as input or output and you want its state)
            return self._pca.digital_read(self._pin_num)
        else:
            # Set pin value (assumes pin is configured as output)
            if self._mode is None:
                 print(f"Warning: I2CPin {self._pin_num} value() called before explicit mode setting. Assuming OUTPUT.")
                 self.init(self.OUT) # Default to output if not explicitly set
            elif self._mode != 0: # 0 means OUTPUT
                 raise RuntimeError(f"I2CPin {self._pin_num} is not configured as an OUTPUT. Current mode: {'INPUT' if self._mode == 1 else 'UNKNOWN'}")

            self._pca.digital_write(self._pin_num, x)
            return None # Consistent with machine.Pin.value(x) return type

    def on(self):
        """
        Sets the pin to a high (1) state. Only effective for output pins.
        """
        self.value(1)

    def off(self):
        """
        Sets the pin to a low (0) state. Only effective for output pins.
        """
        self.value(0)

    def toggle(self):
        """
        Toggles the pin's state. Only effective for output pins.
        """
        current_val = self.value() # Read current output state (assumes it's an output)
        self.value(1 - current_val) # Toggle it

    def irq(self, handler=None, trigger=Pin.IRQ_FALLING | Pin.IRQ_RISING, priority=1, wake=None, hard=False):
        # This function only set irq. However, handler won't be called without extra codes.
        self._handler = handler
        self._trigger = trigger


class ScanI2CPin(I2CPin):
    """
    A class that mimics the functionality and interface of machine.Pin,
    but controls a specific pin on a PCA9555 I2C GPIO expander.
    Pin value is updated by PCA9555.
    IRQ is also called by PCA9555.
    """

    def __init__(self, pca_instance: PCA9555, pin_number: int, mode=-1, pull=-1):
        super().__init__(pca_instance=pca_instance, pin_number=pin_number, mode=mode, pull=pull)
        self._value = self._pca.digital_read(self._pin_num)
        # self._last_read_tick

    def value(self, x = None):
        """
        Gets or sets the pin's digital value.

        Args:
            x: Optional. If None, reads the pin's value.
               If 0 or 1, sets the pin's output value.

        Returns:
            The pin's value if x is None (0 or 1).
        """
        if x is None:
            self._value = (self._pca.gpio_buffer[self._pin_num // 8] >> (self._pin_num % 8)) & 0x01
            return self._value
        else:
            return super().value(x=x)

    def call_irq(self):
        if self._handler is not None:
            self._handler(self)
