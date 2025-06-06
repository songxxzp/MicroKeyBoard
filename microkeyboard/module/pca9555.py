import time
import machine

from machine import Pin, I2C


class PCA9555:
    # PCA9555 Register Addresses
    INPUT_PORT_0 = 0x00               # Input Port 0
    INPUT_PORT_1 = 0x01               # Input Port 1
    OUTPUT_PORT_0 = 0x02              # Output Port 0
    OUTPUT_PORT_1 = 0x03              # Output Port 1
    POLARITY_INVERSION_PORT_0 = 0x04  # Polarity Inversion Port 0
    POLARITY_INVERSION_PORT_1 = 0x05  # Polarity Inversion Port 1
    CONFIGURATION_PORT_0 = 0x06       # Configuration Port 0 (0 for output, 1 for input)
    CONFIGURATION_PORT_1 = 0x07       # Configuration Port 1 (0 for output, 1 for input)

    def __init__(self, i2c: I2C, address=0x20):
        """
        Initializes the PCA9555 library.

        Args:
            i2c: An already initialized machine.I2C object.
            address: The I2C address of the PCA9555 (default is 0x20).
                     The A0, A1, A2 pins of the PCA9555 determine its address.
        """
        self.i2c = i2c
        self.address = address
        self._port0_config = 0xFF # Default all pins to input
        self._port1_config = 0xFF # Default all pins to input

        # set buffers
        self.read_data_buffer = bytearray(1)
        self.write_data_buffer = bytearray(2)
        self.gpio_buffer = bytearray(2)

        # attrs
        # self._last_read_tick

        # Scan for I2C devices to confirm PCA9555 presence
        devices = self.i2c.scan()
        if self.address not in devices:
            raise OSError(f"PCA9555 at address 0x{address:02x} not found on I2C bus.")
        
        # Initialize configuration registers to set all pins as inputs (default state)
        self._write_register(self.CONFIGURATION_PORT_0, self._port0_config)
        self._write_register(self.CONFIGURATION_PORT_1, self._port1_config)
        
        print(f"PCA9555 initialized at I2C address 0x{self.address:02x}")

    def _write_register(self, register: int, value: int):
        """
        Writes a byte value to a PCA9555 register.
        """
        try:
            self.write_data_buffer[0] = register
            self.write_data_buffer[1] = value
            self.i2c.writeto(self.address, self.write_data_buffer)
            # self.i2c.writeto(self.address, bytes([register, value]))
        except OSError as e:
            raise OSError(f"Failed to write to PCA9555 register 0x{register:02x}: {e}")

    def _read_register(self, register: int):
        """
        Reads a byte value from a PCA9555 register.
        """
        try:
            self.write_data_buffer[0] = register
            self.i2c.writeto(self.address, self.write_data_buffer[:1])
            self.i2c.readfrom_into(self.address, self.read_data_buffer)
            return self.read_data_buffer[0]
            # self.i2c.writeto(self.address, bytes([register]))
            # data = self.i2c.readfrom(self.address, 1)
            # return data[0]
        except OSError as e:
            raise OSError(f"Failed to read from PCA9555 register 0x{register:02x}: {e}")

    def _set_bit(self, value: int, bit: int) -> int:
        """
        Sets a specific bit in a given byte value.
        """
        return value | (1 << bit)

    def _clear_bit(self, value: int, bit: int) -> int:
        """
        Clears a specific bit in a given byte value.
        """
        return value & ~(1 << bit)

    def set_pin_mode(self, pin, mode):
        """
        Sets the mode (input or output) for a single pin.

        Args:
            pin: The pin number (0-15).
            mode: 0 for OUTPUT, 1 for INPUT.
        """
        if not 0 <= pin <= 15:
            raise ValueError("Pin number must be between 0 and 15.")
        if mode not in (0, 1):
            raise ValueError("Mode must be 0 (OUTPUT) or 1 (INPUT).")

        port = pin // 8
        bit = pin % 8

        if port == 0:
            current_config = self._port0_config
            if mode == 0: # Output
                self._port0_config = self._clear_bit(current_config, bit)
            else: # Input
                self._port0_config = self._set_bit(current_config, bit)
            self._write_register(self.CONFIGURATION_PORT_0, self._port0_config)
        else: # port == 1
            current_config = self._port1_config
            if mode == 0: # Output
                self._port1_config = self._clear_bit(current_config, bit)
            else: # Input
                self._port1_config = self._set_bit(current_config, bit)
            self._write_register(self.CONFIGURATION_PORT_1, self._port1_config)
        
        # print(f"Pin {pin} set to {'OUTPUT' if mode == 0 else 'INPUT'}")

    def set_port_mode(self, port_num, config_byte):
        """
        Sets the mode for an entire port (8 pins).

        Args:
            port_num: The port number (0 or 1).
            config_byte: A byte where each bit corresponds to a pin's mode.
                         0 means output, 1 means input.
                         E.g., 0x00 for all pins as output, 0xFF for all pins as input.
        """
        if port_num not in (0, 1):
            raise ValueError("Port number must be 0 or 1.")
        
        if port_num == 0:
            self._port0_config = config_byte
            self._write_register(self.CONFIGURATION_PORT_0, self._port0_config)
        else:
            self._port1_config = config_byte
            self._write_register(self.CONFIGURATION_PORT_1, self._port1_config)
        
        # print(f"Port {port_num} configuration set to 0x{config_byte:02x}")


    def digital_write(self, pin: int, value: bool):
        """
        Sets the digital level (HIGH/LOW) for a single output pin.

        Args:
            pin: The pin number (0-15).
            value: 0 (LOW) or 1 (HIGH).
        """
        if not 0 <= pin <= 15:
            raise ValueError("Pin number must be between 0 and 15.")
        if value not in (0, 1):
            raise ValueError("Value must be 0 or 1.")

        port = pin // 8
        bit = pin % 8

        if port == 0:
            current_output = self._read_register(self.OUTPUT_PORT_0)
            if value == 1:
                new_output = self._set_bit(current_output, bit)
            else:
                new_output = self._clear_bit(current_output, bit)
            self._write_register(self.OUTPUT_PORT_0, new_output)
        else: # port == 1
            current_output = self._read_register(self.OUTPUT_PORT_1)
            if value == 1:
                new_output = self._set_bit(current_output, bit)
            else:
                new_output = self._clear_bit(current_output, bit)
            self._write_register(self.OUTPUT_PORT_1, new_output)
        
        # print(f"Pin {pin} set to {value}")

    def digital_read(self, pin: int) -> bool:
        """
        Reads the digital level for a single input pin.

        Args:
            pin: The pin number (0-15).

        Returns:
            0 (LOW) or 1 (HIGH).
        """
        if not 0 <= pin <= 15:
            raise ValueError("Pin number must be between 0 and 15.")

        port = pin // 8
        bit = pin % 8

        if port == 0:
            input_value = self._read_register(self.INPUT_PORT_0)
        else: # port == 1
            input_value = self._read_register(self.INPUT_PORT_1)
        
        if input_value == 1:
            self.gpio_buffer[port] = self._set_bit(self.gpio_buffer[port], bit)
        else:
            self.gpio_buffer[port] = self._clear_bit(self.gpio_buffer[port], bit)

        return (input_value >> bit) & 0x01

    def write_output_port(self, port_num: int, value: int):
        """
        Sets the digital levels for an entire output port.

        Args:
            port_num: The port number (0 or 1).
            value: A byte where each bit corresponds to a pin's output level.
                   0 means LOW, 1 means HIGH.
        """
        if port_num not in (0, 1):
            raise ValueError("Port number must be 0 or 1.")
        
        if port_num == 0:
            self._write_register(self.OUTPUT_PORT_0, value)
        else:
            self._write_register(self.OUTPUT_PORT_1, value)
        
        # print(f"Port {port_num} output set to 0x{value:02x}")

    def read_input_port(self, port_num: int) -> int:
        """
        Reads the digital levels for an entire input port.

        Args:
            port_num: The port number (0 or 1).

        Returns:
            A byte where each bit corresponds to a pin's input level.
        """
        if port_num not in (0, 1):
            raise ValueError("Port number must be 0 or 1.")
        
        if port_num == 0:
            input_value = self._read_register(self.INPUT_PORT_0)
        else:
            input_value = self._read_register(self.INPUT_PORT_1)

        self.gpio_buffer[port_num] = input_value

        return input_value

    def set_polarity_inversion(self, port_num: int, inversion_byte):
        """
        Configures input polarity inversion for a port.

        Args:
            port_num: The port number (0 or 1).
            inversion_byte: A byte where each bit corresponds to a pin's polarity inversion setting.
                            0 means no inversion, 1 means inversion.
                            If set to 1, a HIGH input on the pin will be read as LOW, and vice-versa.
        """
        if port_num not in (0, 1):
            raise ValueError("Port number must be 0 or 1.")
        
        if port_num == 0:
            self._write_register(self.POLARITY_INVERSION_PORT_0, inversion_byte)
        else:
            self._write_register(self.POLARITY_INVERSION_PORT_1, inversion_byte)
        
        # print(f"Port {port_num} polarity inversion set to 0x{inversion_byte:02x}")

    def get_polarity_inversion(self, port_num: int):
        """
        Gets the current input polarity inversion settings for a port.

        Args:
            port_num: The port number (0 or 1).

        Returns:
            A byte where each bit corresponds to a pin's polarity inversion setting.
        """
        if port_num not in (0, 1):
            raise ValueError("Port number must be 0 or 1.")
        
        if port_num == 0:
            return self._read_register(self.POLARITY_INVERSION_PORT_0)
        else:
            return self._read_register(self.POLARITY_INVERSION_PORT_1)
    
    def scan(self, pin: Pin):
        self.read_input_port(0)
        self.read_input_port(1)


if __name__ == "__main__":
    # --- 1. Initialize I2C Bus for PCA9555 ---
    # Your I2C configuration: I2C(0, scl=Pin(10), sda=Pin(9), freq=400000), address 0x24
    esp32_gpio_11 = 11  # interupt
    i2c = machine.I2C(0, scl=machine.Pin(10), sda=machine.Pin(9), freq=400000)
    pca_address = 0x24 # Your PCA9555 I2C address

    # Scan I2C devices to confirm PCA9555 presence
    print("Scanning I2C bus for devices...")
    devices = i2c.scan()
    print("Found devices at addresses:", [hex(addr) for addr in devices])

    if pca_address not in devices:
        print(f"Error: PCA9555 at address 0x{pca_address:02x} not found. Please check wiring and address jumpers.")
        import sys
        sys.exit() # Exit if device not found

    # --- 2. Initialize PCA9555 Driver ---
    try:
        pca = PCA9555(i2c, address=pca_address)
        print(f"PCA9555 at 0x{pca_address:02x} initialized.")
    except Exception as e:
        print(f"Failed to initialize PCA9555: {e}")
        import sys
        sys.exit()

    # --- 3. Configure all PCA9555 I/O pins as Inputs ---
    # PCA9555's CONFIGURATION register: 0 for output, 1 for input
    # 0xFF (binary 11111111) sets all 8 pins of a port as inputs
    try:
        pca.set_port_mode(0, 0xFF) # Set Port 0 (pins 0-7) to all inputs
        pca.set_port_mode(1, 0xFF) # Set Port 1 (pins 8-15) to all inputs
        print("All PCA9555 I/O pins configured as inputs.")
        print("REMINDER: PCA9555 does NOT have internal pull-up resistors. Ensure external pull-ups are used for stable readings.")
    except Exception as e:
        print(f"Failed to set PCA9555 pin modes: {e}")
        import sys
        sys.exit()

    # --- 4. Configure ESP32 GPIO 11 as an Input ---
    try:
        # Using PULL_UP for stability, as external pull-ups are common for switches/buttons
        esp32_int_pin = machine.Pin(esp32_gpio_11, machine.Pin.IN, machine.Pin.PULL_UP)
        print(f"ESP32 GPIO {esp32_gpio_11} configured as input with PULL_UP.")
    except Exception as e:
        print(f"Error configuring ESP32 GPIO {esp32_gpio_11}: {e}")
        print("Please check if GPIO 11 is available and correctly specified for your ESP32 board.")
        import sys
        sys.exit()

    # --- 5. Read Initial States and Start Monitoring for Changes ---
    # Store the last read states for comparison
    last_pca_port0_state = pca.read_input_port(0)
    last_pca_port1_state = pca.read_input_port(1)
    last_esp32_pin_11_state = esp32_int_pin.value()

    print(f"\nInitial PCA9555 Port 0 state: 0x{last_pca_port0_state:02x} (Binary: {last_pca_port0_state:08b})")
    print(f"Initial PCA9555 Port 1 state: 0x{last_pca_port1_state:02x} (Binary: {last_pca_port1_state:08b})")
    print(f"Initial ESP32 GPIO {esp32_gpio_11} state: {'HIGH' if last_esp32_pin_11_state else 'LOW'}")
    print("\nMonitoring PCA9555 and ESP32 GPIO 11 inputs for changes... Press Ctrl+C to stop.")

    try:
        while True:
            # Read current PCA9555 states
            current_pca_port0_state = pca.read_input_port(0)
            current_pca_port1_state = pca.read_input_port(1)

            # Read current ESP32 GPIO 11 state
            current_esp32_pin_11_state = esp32_int_pin.value()

            # Check for changes on PCA9555 Port 0
            if current_pca_port0_state != last_pca_port0_state:
                changed_bits_0 = current_pca_port0_state ^ last_pca_port0_state # XOR to find changed bits
                for i in range(8):
                    if (changed_bits_0 >> i) & 0x01: # Check if the i-th bit changed
                        pin_num = i # PCA9555 pin 0-7
                        pin_state = (current_pca_port0_state >> i) & 0x01
                        print(f"  PCA9555 Pin {pin_num} changed to: {'HIGH' if pin_state else 'LOW'}")
                last_pca_port0_state = current_pca_port0_state # Update last state

            # Check for changes on PCA9555 Port 1
            if current_pca_port1_state != last_pca_port1_state:
                changed_bits_1 = current_pca_port1_state ^ last_pca_port1_state
                for i in range(8):
                    if (changed_bits_1 >> i) & 0x01:
                        pin_num = 8 + i # PCA9555 pin 8-15
                        pin_state = (current_pca_port1_state >> i) & 0x01
                        print(f"  PCA9555 Pin {pin_num} changed to: {'HIGH' if pin_state else 'LOW'}")
                last_pca_port1_state = current_pca_port1_state # Update last state

            # Check for changes on ESP32 GPIO 11
            if current_esp32_pin_11_state != last_esp32_pin_11_state:
                print(f"  ESP32 GPIO {esp32_gpio_11} changed to: {'HIGH' if current_esp32_pin_11_state else 'LOW'}")
                last_esp32_pin_11_state = current_esp32_pin_11_state # Update last state

            time.sleep_ms(5) # Short delay to prevent excessive I2C polling and CPU usage
    except KeyboardInterrupt:
        print("\nMonitoring stopped by user (Ctrl+C).")
    except Exception as e:
        print(f"An error occurred during monitoring: {e}")

    print("Program finished.")
