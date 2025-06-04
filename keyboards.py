import time
import json
import machine
import gc
import usb
import neopixel

from machine import Pin, I2S, SPI, SoftSPI
from typing import Optional, Callable, List, Dict, Tuple, Union
from utils import DEBUG, debugging, debug_switch
from usb.device.keyboard import KeyboardInterface, KeyCode, LEDCode

from bluetoothkeyboard import BluetoothKeyboard
from audio import Sampler, AudioManager
from keys import PhysicalKey, VirtualKey
from utils import partial, exists, makedirs
from tca8418 import TCA8418


def fn_layer_pressed_function(
    virtual_key_board: "VirtualKeyBoard",
    virtual_key: "VirtualKey",
    layer_codes: Optional[Tuple[str]] = None,
    pressed_function: Optional[Callable] = None,
    original_func: Optional[Callable] = None,
    layer_id: int = 1,
):
    if virtual_key_board.layer == int(layer_id):
        if layer_codes is not None:
            virtual_key.keycode = layer_codes[1]
        if pressed_function is not None:
            pressed_function()
    elif original_func is not None:
        original_func()


def fn_layer_released_function(
    virtual_key_board: "VirtualKeyBoard",
    virtual_key: "VirtualKey",
    layer_codes: Optional[Tuple[str]] = None,
    released_function: Optional[Callable] = None,
    original_func: Optional[Callable] = None,
    layer_id: int = 1,
):
    if layer_codes is not None:
        virtual_key.keycode = layer_codes[0]
    if virtual_key_board.layer == int(layer_id):
        if released_function is not None:
            released_function()
    elif original_func is not None:
        original_func()


class LEDManager:
    def __init__(
        self,
        led_config: Dict,
        ledmap: Optional[Dict[str, int]] = {}
    ):
        self.ltype = led_config.get("ltype", "neopixel")
        self.led_pixels = led_config.get("led_pixels", 68)
        self.max_light_level = led_config.get("max_light_level", 16)
        self.onstart_light_level = led_config.get("onstart_light_level", 1)
        self.led_data_pin = led_config.get("led_data_pin")
        self.led_power_pin = led_config.get("led_power_pin")
        self.ledmap = ledmap
        
        self.led_power = Pin(self.led_power_pin, Pin.OUT)
        self.enabled = True
        self.led_power.value(self.enabled)

        self.pixels = neopixel.NeoPixel(Pin(self.led_data_pin, Pin.OUT), self.led_pixels)
        # for i in range(self.led_pixels):
        #     self.pixels[i] = (self.onstart_light_level, self.onstart_light_level, self.onstart_light_level)
        self.pixels.fill((self.onstart_light_level, self.onstart_light_level, self.onstart_light_level))
        self.pixels.write()

    def disable(self):
        self.enabled = False
        self.led_power.value(0)

    def enable(self):
        self.enabled = True
        self.led_power.value(1)
        self.write_pixels()
    
    def switch(self):
        self.enabled = not self.enabled
        self.led_power.value(self.enabled)
        if self.enabled:
            self.write_pixels()

    def clear(self):
        self.pixels.fill((0, 0, 0))
        self.pixels.write()

    def set_pixel(self, i: Union[int, str], color: Tuple[int], write: bool = False):
        if isinstance(i, str):
            i = self.ledmap[i]
        self.pixels[i] = tuple(min(l, self.max_light_level) for l in color)
        if write:
            self.pixels.write()

    def write_pixels(self):
        self.pixels.write()


class PhysicalKeyBoard:
    def __init__(
        self,
        key_config_path: str = "/config/physical_keyboard.json",
        ktype: Optional[str] = None,
        clock_pin: Optional[int] = None,
        pl_pin: Optional[int] = None,
        ce_pin: Optional[int] = None,
        read_pin: Optional[int] = None,
        power_pin: Optional[int] = None,
        wakeup_pin: Optional[int] = None,
        max_keys: Optional[int] = None,  # The maximum number of keys for key scanning. The actual number of keys used is less than or equal to this number.
        keymap_path: Optional[str] = None,  # "/config/physical_keymap.json",
        max_light_level: Optional[int] = None,
        scan_mode: Optional[int] = None,
    ):
        self.key_config = json.load(open(key_config_path))

        ktype = ktype or self.key_config.get("ktype", None)
        clock_pin = pl_pin or self.key_config.get("clock_pin", None)
        pl_pin = pl_pin or self.key_config.get("pl_pin", None)
        ce_pin = ce_pin or self.key_config.get("ce_pin", None)
        read_pin = read_pin or self.key_config.get("read_pin", None)
        power_pin = power_pin or self.key_config.get("power_pin", None)
        wakeup_pin = wakeup_pin or self.key_config.get("wakeup_pin", None)
        max_keys = max_keys or self.key_config.get("max_keys", None)
        keymap_path = keymap_path or self.key_config.get("keymap_path", None)
        max_light_level = max_light_level or self.key_config.get("max_light_level", None)
        self.scan_mode = scan_mode or self.key_config.get("scan_mode", None)
    
        self.key_pl = Pin(pl_pin, Pin.OUT, value=1)
        self.key_ce = Pin(ce_pin, Pin.OUT, value=0)
        self.key_power = Pin(power_pin, Pin.OUT, value=1) if power_pin is not None else None
        self.wakeup = Pin(wakeup_pin, mode=Pin.IN, pull=Pin.PULL_DOWN) if wakeup_pin is not None else None
        if self.scan_mode == "SPI":
            self.key_clk = Pin(clock_pin)
            self.key_in = Pin(read_pin)
            self.spi = SPI(
                1,
                baudrate=4000000,
                sck=self.key_clk,
                mosi=None,
                miso=self.key_in,
                polarity=1,
                firstbit=SPI.LSB
            )
        elif self.scan_mode == "SoftSPI":
            self.key_clk = Pin(clock_pin)
            self.key_in = Pin(read_pin)
            self.spi = SoftSPI(
                baudrate=100000,
                sck=self.key_clk,
                mosi=Pin(0),
                miso=self.key_in,
                polarity=1,
                firstbit=SoftSPI.LSB
            )
        elif self.scan_mode == "GPIO":
            self.key_clk = Pin(clock_pin, Pin.OUT, value=0)
            self.key_in = Pin(read_pin, Pin.IN)
            self.spi = None
        else:
            raise NotImplementedError(f"scan mode not implemented: {self.scan_mode}")

        self.max_keys = max_keys
        self.physical_keys = [None for _ in range(max_keys)]
        keymap_json = json.load(open(keymap_path))
        if "keymap" in keymap_json:
            self.keymap_dict = keymap_json["keymap"]
        else:
            self.keymap_dict = keymap_json
        self.used_key_num = len(self.keymap_dict)
        assert self.used_key_num <= self.max_keys, "More keys are used than the maximum allowed!"
        for key_name, key_id in self.keymap_dict.items():
            self.physical_keys[key_id] = PhysicalKey(key_id=key_id, key_name=key_name, max_light_level=max_light_level)
        
        self.led_manager = LEDManager(self.key_config, ledmap=keymap_json.get("ledmap", {}))

        # Calculate the number of bytes needed to store max_keys bits
        self.bytes_needed = (self.max_keys + 7) // 8

        # Double buffer for key states: previous_state and current_state
        # Each key state is stored as a bit (0 or 1)
        self._buffer_a = bytearray(self.bytes_needed)
        self._buffer_b = bytearray(self.bytes_needed)
        for byte_index in range(self.bytes_needed):
            self._buffer_a[byte_index] = 0xff
            self._buffer_b[byte_index] = 0xff

        # Pointers to the current and previous state buffers
        self._current_buffer = self._buffer_a
        self._previous_buffer = self._buffer_b # Initially, both are zero, representing all keys released
        
    def scan_keys(self, interval_us=1, scan_mode: Optional[str] = None) -> None:
        scan_mode = scan_mode or self.scan_mode
        if scan_mode in ("SPI", "SoftSPI"):
            # Load key state
            self.key_pl.value(0)
            self.key_pl.value(1)
            self.spi.readinto(self._current_buffer)
        else:
            self.key_pl.value(0)
            time.sleep_us(interval_us)
            self.key_pl.value(1)
            time.sleep_us(interval_us)
            for byte_index in range(self.bytes_needed):
                self._current_buffer[byte_index] = 0
            # read key states
            # self.key_ce.value(0)
            # time.sleep_us(interval_us)
            for i in range(self.max_keys):
                # key_states[i] = not self.key_in.value()

                # Determine byte and bit index
                byte_index = i // 8
                bit_index = i % 8

                # Read the pin value
                state = int(self.key_in.value())

                self._current_buffer[byte_index] |= (state << bit_index)

                self.key_clk.value(1)
                time.sleep_us(interval_us)
                self.key_clk.value(0)
                time.sleep_us(interval_us)
            # self.key_ce.value(1)

    def sleep(self):
        # TODO: esp32 is only for esp32, change for other boards
        import esp32
        led_enabled = self.led_manager.enabled
        self.led_manager.led_power.value(0)
        if hasattr(self, "key_power"):
            self.key_power.value(0)
        self.wakeup.init(mode=Pin.IN, pull=Pin.PULL_DOWN, hold=True)
        # TODO: close screen, close I2S
        # TODO: keep ble
        esp32.wake_on_ext0(pin=self.wakeup, level=esp32.WAKEUP_ANY_HIGH)
        print("Preparing sleep")
        time.sleep(1)
        machine.lightsleep()  # TODO: wait for all key released
        print(f"Waking Up. {machine.wake_reason()}")
        if hasattr(self, "key_power"):
            self.key_power.value(1)
        if led_enabled:
            self.led_manager.enable()

    def scan(self, interval_us=1, activate: bool = True) -> bool:  # TODO: filter
        # activate is always True
        self.scan_keys(interval_us=interval_us)
        scan_change = False
        for byte_index in range(self.bytes_needed):
            current_byte = self._current_buffer[byte_index]
            previous_byte = self._previous_buffer[byte_index]

            # Find changed bits using XOR: bit is 1 if different, 0 if same
            changed_bits = current_byte ^ previous_byte

            # If there are any changes in this byte
            if changed_bits:
                scan_change = True
                # Iterate through each bit in the byte (0 to 7)
                for bit_index in range(8):
                    # Calculate the global key ID
                    key_id = byte_index * 8 + bit_index

                    # Stop if we exceed the actual number of keys
                    if key_id >= self.max_keys:
                        break # Exit inner loop (bits in byte)

                    # Check if this specific bit (key) changed
                    if (changed_bits >> bit_index) & 1:
                        # Get the current state of the key (0 or 1)
                        current_state = (current_byte >> bit_index) & 1

                        physical_key = self.physical_keys[key_id]
                        if physical_key is None:
                            continue

                        # If state changed and current state is 0 (1 -> 0): Key Pressed
                        if current_state == 0:
                            # This check should technically not be needed if logic is perfect,
                            # but good defensive programming.
                            # if not physical_key.pressed:
                            physical_key.pressed = True
                            if debugging():
                                print(f"physical({physical_key.key_id}, {physical_key.key_name}) is pressed at {time.ticks_ms()}.")
                            if physical_key.bind_virtual is not None:
                                physical_key.bind_virtual.press()
                            else:
                                if debugging():
                                    print(f"physical({physical_key.key_id}, {physical_key.key_name}) not bind for press")

                        # If state changed and current state is 1 (0 -> 1): Key Released
                        else: # current_state must be 1
                            # This check should technically not be needed
                            # if physical_key.pressed:
                            physical_key.pressed = False
                            if debugging():
                                print(f"physical({physical_key.key_id}, {physical_key.key_name}) is released at {time.ticks_ms()}.")
                            if physical_key.bind_virtual is not None:
                                physical_key.bind_virtual.release()
                            else:
                                if debugging():
                                    print(f"physical({physical_key.key_id}, {physical_key.key_name}) not bind for release")

        self._previous_buffer, self._current_buffer = self._current_buffer, self._previous_buffer
        return scan_change

    def is_pressed(self) -> bool:
        self.scan_keys(scan_mode="GPIO")
        for byte_index in range(self.bytes_needed):
            current_byte = self._current_buffer[byte_index]
            if current_byte < 0xff:
                # key_id = byte_index * 8 + bit_index
                print(f"Is pressed: {byte_index}, {current_byte}")
                return True
        return False


class TCA8418PhysicalKeyBoard(PhysicalKeyBoard):
    def __init__(
        self,
        key_config_path: str = "/config/physical_keyboard.json",
    ):
        self.key_config = json.load(open(key_config_path))

        ktype = self.key_config.get("ktype", None)
        sda_pin = self.key_config.get("sda_pin", None)
        scl_pin = self.key_config.get("scl_pin", None)
        wakeup_pin = self.key_config.get("wakeup_pin", None)
        
        max_keys = self.key_config.get("max_keys", None)
        keymap_path = self.key_config.get("keymap_path", None)
        max_light_level = self.key_config.get("max_light_level", None)
        self.scan_mode = self.key_config.get("scan_mode", None)

        self.tca_addr = 0x34
    
        self.i2c = machine.I2C(0, scl=machine.Pin(scl_pin), sda=machine.Pin(sda_pin), freq=400000)
        self.wakeup = Pin(wakeup_pin, machine.Pin.IN, machine.Pin.PULL_UP) if wakeup_pin is not None else None

        self.event_pending = False
        self.wakeup.irq(trigger=machine.Pin.IRQ_FALLING, handler=self.tca_interrupt_handler)

        self.tca = TCA8418(self.i2c, self.tca_addr)
        ROW_PINS = [TCA8418.R0, TCA8418.R1, TCA8418.R2, TCA8418.R3, TCA8418.R4, TCA8418.R5, TCA8418.R6, TCA8418.R7] # Pins 0-7
        COL_PINS = [TCA8418.C0, TCA8418.C1, TCA8418.C2, TCA8418.C3, TCA8418.C4, TCA8418.C5, TCA8418.C6, TCA8418.C7, TCA8418.C8, TCA8418.C9] # Pins 8-17

        # --- Configure TCA8418 for Keypad Mode ---
        # Set all ROW_PINS and COL_PINS to Keypad mode (KPGPIO = 0 for keypad)
        tca = self.tca
        all_keypad_pins = ROW_PINS + COL_PINS
        for pin in all_keypad_pins:
            # Use set_bit method of keypad_mode register instance
            tca.keypad_mode.set_bit(pin, True) # Set to Keypad mode (inverted logic)

        # Configure rows as outputs and columns as inputs with pull-ups
        for pin in ROW_PINS:
            # Use set_bit method of gpio_direction register instance
            tca.gpio_direction.set_bit(pin, True) # Rows are outputs
            # Use set_bit method of pullup register instance
            tca.pullup.set_bit(pin, False) # No pull-up on outputs (inverted logic)

        for pin in COL_PINS:
            # Use set_bit method of gpio_direction register instance
            tca.gpio_direction.set_bit(pin, False) # Columns are inputs
            # Use set_bit method of pullup register instance
            tca.pullup.set_bit(pin, True) # Enable pull-up on inputs (inverted logic)

        # Enable Key event FIFO interrupt using the setter method
        tca.set_key_intenable(True)
        # Disable GPIO interrupts if only using keypad using the setter method
        tca.set_GPI_intenable(False)

        # Enable debounce for all relevant pins (typically rows and columns involved in scanning)
        # The debounce applies per pin. Set debounce=True for all ROW and COL pins.
        for pin in all_keypad_pins:
                # Use set_bit method of debounce register instance
            tca.debounce.set_bit(pin, True) # Enable debounce (inverted logic)

        # Clear any pending interrupts using the clearer methods
        tca.clear_key_int()
        tca.clear_gpi_int()
        tca.clear_overflow_int()
        tca.clear_keylock_int()
        tca.clear_cad_int()

        # TODO: reuse below code:
        self.max_keys = max_keys
        self.physical_keys = [None for _ in range(max_keys)]
        keymap_json = json.load(open(keymap_path))
        if "keymap" in keymap_json:
            self.keymap_dict = keymap_json["keymap"]
        else:
            self.keymap_dict = keymap_json
        self.used_key_num = len(self.keymap_dict)
        assert self.used_key_num <= self.max_keys, "More keys are used than the maximum allowed!"
        for key_name, key_id in self.keymap_dict.items():
            self.physical_keys[key_id] = PhysicalKey(key_id=key_id, key_name=key_name, max_light_level=max_light_level)
        
        self.led_manager = LEDManager(self.key_config, ledmap=keymap_json.get("ledmap", {}))

    def tca_interrupt_handler(self, pin):
        self.event_pending = True

    def scan(self, interval_us: int = 1, activate: bool = False) -> bool:  # TODO: activate scan
        if not (self.event_pending or activate):
            return False
        time.sleep_us(interval_us)
        self.event_pending = False
        tca = self.tca
        event_flag = False
        while tca.get_events_count() > 0:
            event = tca.read_next_event()
            keycode = event & 0x7F
            is_press = bool(event & 0x80)

            if 1 <= keycode <= 80: # Keypad Array
                event_flag = True
                physical_key = self.physical_keys[keycode]
                physical_key.pressed = is_press

                if is_press:
                    if debugging():
                        print(f"physical({physical_key.key_id}, {physical_key.key_name}) is pressed at {time.ticks_ms()}.")
                    if physical_key.bind_virtual is not None:
                        physical_key.bind_virtual.press()
                    else:
                        if debugging():
                            print(f"physical({physical_key.key_id}, {physical_key.key_name}) not bind for press")
                else:
                    if physical_key.bind_virtual is not None:
                        physical_key.bind_virtual.release()
                    else:
                        if debugging():
                            print(f"physical({physical_key.key_id}, {physical_key.key_name}) not bind for release")
            elif 97 <= keycode <= 104: # Row GPI Events
                pass
            elif 105 <= (keycode - 1) <= 114: # Column GPI Events
                pass
            else:
                raise NotImplementedError(f"Get tca8418 keycode: {keycode}")
            tca.clear_key_int()
        return event_flag

    def is_pressed(self) -> bool:
        # TODO
        return False

    def sleep(self):
        # TODO
        import esp32
        led_enabled = self.led_manager.enabled
        self.led_manager.led_power.value(0)
        # TODO: close screen, close I2S
        # TODO: keep ble
        print("Preparing sleep")
        time.sleep(1)
        esp32.wake_on_ext0(pin=self.wakeup, level=esp32.WAKEUP_ALL_LOW)
        machine.lightsleep()  # TODO: wait for all key released
        print(f"Waking Up. {machine.wake_reason()}")
        if led_enabled:
            self.led_manager.enable()
        return


class VirtualKeyBoard:
    def __init__(self,
        connection_mode: str = "bluetooth",
        mapping_path: str = "/config/virtual_keymaps.json",
        key_config_path: str = "/config/physical_keyboard.json",
        key_num: int = 68,  # Real used key num.
        max_phiscal_keys: int = 72,
    ):
        # assert key_num >= self.phsical_key_board.used_key_num, "virt key num < phys key num."
        if exists(mapping_path):
            self.virtual_key_mappings = json.load(open(mapping_path))
            self.virtual_key_name = self.virtual_key_mappings.get("name", "MicroKeyBoard")
        else:
            self.virtual_key_mappings = None
            self.virtual_key_name = "MicroKeyBoard"
        ktype = self.virtual_key_mappings.get("ktype", "74hc165")
        if ktype == "tca8418":
            self.phsical_key_board = TCA8418PhysicalKeyBoard(key_config_path=key_config_path)  # TODO: as an arg
        elif ktype == "74hc165":
            self.phsical_key_board = PhysicalKeyBoard(key_config_path=key_config_path, max_keys=max_phiscal_keys)  # TODO: as an arg
        else:
            raise NotImplementedError(f"Not implemented ktype: {ktype}")
        key_num = max(key_num, self.phsical_key_board.used_key_num)
        self.key_num = key_num

        # editable keyboard state
        self.connection_mode = None
        self.layer = 0

        if self.phsical_key_board.is_pressed():  # TODO: phsical key function
            connection_mode = "debug"

        self.connection_mode = None
        self.ble_interface = None
        self.set_connection_mode(connection_mode)

        self.pressed_keys: List[VirtualKey] = []
        self.keystates = []
        self.prev_keystates = []

        self.virtual_keys: List[VirtualKey] = None
        self.build_virtual_keys()

    def set_connection_mode(self, connection_mode: str):
        if connection_mode == self.connection_mode:
            return

        if self.connection_mode == "usb_hid":
            pass
        elif self.connection_mode == "bluetooth":
            if self.ble_interface is not None:
                self.ble_interface.stop()

        self.connection_mode = connection_mode
        if self.connection_mode == "usb_hid":
            print("swiching to usb mode")
            # TODO: USBKeyBoard class
            self.usb_interface = KeyboardInterface()  # wrap interface
            self.usb_device = usb.device.get()
            self.usb_device.init(self.usb_interface, builtin_driver=True)
            self.interface = self.usb_interface
        elif self.connection_mode == "bluetooth":
            print("swiching to ble mode")
            if self.ble_interface is None:
                self.ble_interface = BluetoothKeyboard(
                    device_name=self.virtual_key_name
                )
            self.ble_interface.start()
            self.interface = self.ble_interface
        elif self.connection_mode == "debug":
            # TODO: DebugKeyBoard class
            debug_switch(True)
            self.interface = None
            print("Enabled DEBUG MODE")
        else:
            raise NotImplementedError(f"connection mode {self.connection_mode} not implemented.")

    def build_virtual_keys(self):
        virtual_keys: List[VirtualKey] = []
        for physical_key in self.phsical_key_board.physical_keys:
            if physical_key is not None:
                key_code_name = physical_key.key_name
                if self.virtual_key_mappings is not None:
                    key_code_name = self.virtual_key_mappings["layers"]["0"].get(physical_key.key_name, None) or key_code_name
                virtual_key = VirtualKey(
                    key_name=key_code_name,
                    keycode=getattr(KeyCode, key_code_name, None),
                    physical_key=physical_key,
                    pressed_function=None,
                    released_function=None
                )
                virtual_keys.append(virtual_key)
        self.virtual_keys = virtual_keys
        self.build_fn_layer(virtual_keys)

    def build_fn_layer(self, virtual_keys: List[VirtualKey]):
        for layer_id in self.virtual_key_mappings["layers"]:  # TODO: check conflict
            for virtual_key in virtual_keys:
                physical_key = virtual_key.bind_physical
                layer_i_code_name = self.virtual_key_mappings["layers"][layer_id].get(physical_key.key_name, None)
                layer_codes = (virtual_key.keycode, getattr(KeyCode, layer_i_code_name, None) if layer_i_code_name is not None else None)
                if self.virtual_key_mappings is not None and physical_key.key_name in self.virtual_key_mappings["layers"][layer_id]:
                    virtual_key.pressed_function = partial(fn_layer_pressed_function, self, virtual_key, layer_codes, virtual_key.pressed_function, original_func=virtual_key.pressed_function, layer_id=int(layer_id))
                    virtual_key.released_function = partial(fn_layer_released_function, self, virtual_key, layer_codes, virtual_key.released_function, original_func=virtual_key.released_function, layer_id=int(layer_id))

        for virtual_key in virtual_keys:
            physical_key = virtual_key.bind_physical
            if physical_key.key_name == "FN":  # TODO: create ".py" file or build from file. Or use Function Mark in keymaps.
                def fn_pressed_function(virtual_key_board: "VirtualKeyBoard"):
                    print("change to layer 1")
                    virtual_key_board.layer = 1
                def fn_released_function(virtual_key_board: "VirtualKeyBoard"):
                    print("change to layer 0")
                    virtual_key_board.layer = 0
                virtual_key.pressed_function = partial(fn_pressed_function, self)
                virtual_key.released_function = partial(fn_released_function, self)
            elif physical_key.key_name == "FN2":
                def fn_pressed_function(virtual_key_board: "VirtualKeyBoard"):
                    print("change to layer 2")
                    virtual_key_board.layer = 2
                def fn_released_function(virtual_key_board: "VirtualKeyBoard"):
                    print("change to layer 0")
                    virtual_key_board.layer = 0  # TODO: change to last layer
                virtual_key.pressed_function = partial(fn_pressed_function, self)
                virtual_key.released_function = partial(fn_released_function, self)
            elif physical_key.key_name == "Q":
                def ble_pressed_function(virtual_key_board: "VirtualKeyBoard", original_func: Callable = None):
                    if virtual_key_board.layer == 1:
                        virtual_key_board.set_connection_mode("bluetooth")
                    elif original_func:
                        original_func()
                virtual_key.pressed_function = partial(ble_pressed_function, self, virtual_key.pressed_function)
            elif physical_key.key_name == "W":
                def usb_pressed_function(virtual_key_board: "VirtualKeyBoard", original_func: Callable = None):
                    if virtual_key_board.layer == 1:
                        virtual_key_board.set_connection_mode("usb_hid")
                    elif original_func:
                        original_func()
                virtual_key.pressed_function = partial(usb_pressed_function, self, virtual_key.pressed_function)
            elif physical_key.key_name == "E":
                def debug_pressed_function(virtual_key_board: "VirtualKeyBoard", original_func: Callable = None):
                    if virtual_key_board.layer == 1:
                        virtual_key_board.set_connection_mode("debug")
                    elif original_func:
                        original_func()
                virtual_key.pressed_function = partial(debug_pressed_function, self, virtual_key.pressed_function)
            elif physical_key.key_name == "R":
                def clear_ble_pressed_function(virtual_key_board: "VirtualKeyBoard", original_func: Callable = None):
                    if virtual_key_board.layer == 1:
                        if self.ble_interface:
                            self.ble_interface.clear_paired_devices()
                    elif original_func:
                        original_func()
                virtual_key.pressed_function = partial(clear_ble_pressed_function, self, virtual_key.pressed_function)

    def bind_fn_layer_func(self, key_name: str, layer_id: int = 1, pressed_function: Optional[Callable] = None, released_function: Optional[Callable] = None):
        for virtual_key in self.virtual_keys:
            physical_key = virtual_key.bind_physical
            layer_i_code_name = self.virtual_key_mappings["layers"][str(layer_id)].get(physical_key.key_name, None)
            layer_codes = (virtual_key.keycode, getattr(KeyCode, layer_i_code_name, None) if layer_i_code_name is not None else None)
            if physical_key.key_name == key_name:  # TODO: build a mapping dict
                virtual_key.pressed_function = partial(fn_layer_pressed_function, self, virtual_key, layer_codes, pressed_function, virtual_key.pressed_function, layer_id=layer_id)
                virtual_key.released_function = partial(fn_layer_released_function, self, virtual_key, layer_codes, released_function, virtual_key.released_function, layer_id=layer_id)

    def scan(self, interval_us: int = 1, activate: bool = False):
        if not self.phsical_key_board.scan(interval_us=interval_us, activate=activate):
            return

        self.keystates.clear()
        self.pressed_keys.clear()
        virtual_keys = self.virtual_keys
        for virtual_key in virtual_keys:
            if virtual_key.pressed and virtual_key.keycode is not None:
                self.pressed_keys.append(virtual_key)
                # self.keystates.append(virtual_key.keycode)
        self.pressed_keys.sort(key=lambda k:k.press_time, reverse=True)
        self.keystates = [k.keycode for k in self.pressed_keys[:6]]  # TODO: Don't use list.
        if self.keystates != self.prev_keystates:
            self.prev_keystates.clear()
            self.prev_keystates.extend(self.keystates)
            if debugging():
                print(self.keystates)
            if self.interface is not None:
                self.interface.send_keys(self.keystates)


class MusicKeyBoard(VirtualKeyBoard):
    def __init__(self, 
        music_mapping_path: str,
        audio_manager: Optional[AudioManager] = None,
        mode: str = "C Major",
        note_wav_path: str = "/wav/piano/16000_2s",
        note_cache_path: Optional[str] = "/cache/piano/16000_1.8s",
        key_config_path: str = "/config/physical_keyboard.json",
        *args,
        **kwargs
    ):
        if exists(music_mapping_path) and exists(key_config_path):
            self.music_enabled = True
            self.music_mapping_path = music_mapping_path
            self.sampler = Sampler(note_wav_path)
            self.music_mappings = json.load(open(self.music_mapping_path))
            self.mode = mode
            self.music_mapping = self.music_mappings[mode]
            key_config = json.load(open(key_config_path))
            sck_pin, ws_pin, sd_pin, en_pin = 48, 47, 45, 38
            if "i2s" in key_config:
                sck_pin = key_config["i2s"].get("sck_pin", None)
                ws_pin = key_config["i2s"].get("ws_pin", None)
                sd_pin = key_config["i2s"].get("sd_pin", None)
                en_pin = key_config["i2s"].get("en_pin", None)

            if audio_manager is None:
                audio_manager = AudioManager(
                    rate=16000,
                    buffer_samples=1024,
                    ibuf=4096,
                    always_play=True,
                    sck_pin=sck_pin,
                    ws_pin=ws_pin,
                    sd_pin=sd_pin,
                    en_pin=en_pin,
                    # volume_factor=0.1
                )

            self.audio_manager = audio_manager

            self.note_key_mapping = {}

            if note_cache_path is not None and not exists(note_cache_path):
                makedirs(note_cache_path)
            for i, note in enumerate(sorted(list(self.music_mapping.values()), key=lambda n: n[-1])):
                print(f"Loading {i} th note: {note}, alloc: {gc.mem_alloc()}, free: {gc.mem_free()}")
                if note_cache_path is not None:
                    if exists(f"{note_cache_path}/{note}"):
                        wav_data = open(f"{note_cache_path}/{note}", "rb").read()
                    else:
                        wav_data = self.sampler.get_sample(note, duration=1.8).tobytes()
                        with open(f"{note_cache_path}/{note}", "wb") as f:
                            f.write(wav_data)
                else:
                    wav_data = self.sampler.get_sample(note, duration=1.8).tobytes()
                self.audio_manager.load_wav(note, wav_data)
                # micropython.mem_info()
                gc.collect()
        else:
            self.music_enabled = False
            self.music_mapping_path = None
            self.audio_manager = None
            self.music_mapping = {}
            self.note_key_mapping = {}

        super().__init__(*args, key_config_path=key_config_path, **kwargs)

    def enable_switch(self):
        if self.music_enabled:
            if self.audio_manager.is_playing():
                self.audio_manager.stop_all()
            # self.audio_manager.disable_irq()
            self.music_enabled = False
        else:
            # self.audio_manager.enable_irq()
            if self.audio_manager is not None:
                self.music_enabled = True

    def build_fn_layer(self, virtual_keys: List[VirtualKey]):
        super().build_fn_layer(virtual_keys)

        self.bind_fn_layer_func("M", pressed_function=self.enable_switch)

    def build_virtual_keys(self):
        virtual_keys: List[VirtualKey] = []
        for physical_key in self.phsical_key_board.physical_keys:
            if physical_key is not None:
                key_code_name = physical_key.key_name
                if self.virtual_key_mappings is not None:
                    key_code_name = self.virtual_key_mappings["layers"]["0"].get(physical_key.key_name, None) or key_code_name
                if physical_key.key_name in self.music_mapping:
                    self.note_key_mapping[self.music_mapping[physical_key.key_name]] = physical_key.key_name
                    virtual_key = VirtualKey(
                        key_name=key_code_name,
                        keycode=getattr(KeyCode, key_code_name, None),
                        physical_key=physical_key,
                        pressed_function=None,
                        released_function=None,
                    )
                    def pressed_function(virtual_key_board: "MusicKeyBoard", virtual_key: VirtualKey, note: str):
                        if virtual_key_board.music_enabled:
                            virtual_key.playing_wav_id = self.audio_manager.play_note(note)
                    def released_function(virtual_key: VirtualKey):
                        if hasattr(virtual_key, "playing_wav_id"):
                            self.audio_manager.stop_note(wav_id=virtual_key.playing_wav_id, delay=500)
                    virtual_key.pressed_function = partial(pressed_function, self, virtual_key, self.music_mapping[physical_key.key_name])
                    virtual_key.released_function = partial(released_function, virtual_key)
                else:
                    virtual_key = VirtualKey(key_name=key_code_name, keycode=getattr(KeyCode, key_code_name, None), physical_key=physical_key)
                virtual_keys.append(virtual_key)
        self.virtual_keys = virtual_keys
        self.build_fn_layer(virtual_keys)

