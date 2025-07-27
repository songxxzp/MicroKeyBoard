import time
import json
import machine
import micropython

from machine import Pin, I2S, SPI, SoftSPI, I2C
from typing import Optional, Callable, List, Dict, Tuple, Union, Iterator

from microkeyboard.devices import GLOBAL_DEIVCE_MANAGER
from microkeyboard.pins import IRQPin
from microkeyboard.utils import debugging, debug_switch, partial, exists, makedirs
from microkeyboard.keyboards.keys import AbstractKey, PhysicalKey, VirtualKey, PhysicalKnob
from microkeyboard.module.tca8418 import TCA8418
from microkeyboard.module.pca9555 import PCA9555
from microkeyboard.keyboards.led import LEDManager


class PhysicalKeyBoard:
    def __init__(
        self,
        key_config: str = "/config/physical_keyboard.json",
        virtual_keyboard: Optional["VirtualKeyBoard"] = None,
        led_manager: Optional[LEDManager] = None,
    ):
        if isinstance(key_config, str):
            self.key_config = json.load(open(key_config))
        elif isinstance(key_config, dict):
            self.key_config = key_config
        else:
            raise NotImplementedError(type(key_config))
        
        self.virtual_keyboard = virtual_keyboard
        self.event_pending = False
        self.last_scan_finished = True
        self.physical_keys: Optional[Union[List[PhysicalKey], Dict[int, PhysicalKey]]] = None

        max_keys = self.key_config.get("max_keys", None)
        keymap_path = self.key_config.get("keymap_path", None)

        if keymap_path is None or max_keys is None:  # TODO: PhysicalKeyBoards should have it's own __init__
            return

        # TODO: reuse below code:
        self.max_keys = max_keys
        self.physical_keys = [None for _ in range(max_keys)]
        keymap_json = json.load(open(keymap_path))

        self.keymap_dict = {}
        if "keymap" in keymap_json:
            self.keymap_dict = keymap_json["keymap"]

        self.used_key_num = len(self.keymap_dict)
        assert self.used_key_num <= self.max_keys, "More keys are used than the maximum allowed!"
        for key_name, key_id in self.keymap_dict.items():
            self.physical_keys[key_id] = PhysicalKey(key_id=key_id, key_name=key_name)

        self.led_manager = led_manager or LEDManager(self.key_config, ledmap=keymap_json.get("ledmap", {}))

        self.knobmap_dict = {}
        self.physical_knobs: List[PhysicalKnob] = []
        if "knobmap" in keymap_json:
            self.knobmap_dict = keymap_json["knobmap"]

        for knob_name, key_ids in self.knobmap_dict.items():
            ((key_a_name, key_a_id), (key_b_name, key_b_id)) = key_ids.items()
            key_a = AbstractKey(key_id=key_a_id, key_name=key_a_name, is_component=True)
            key_b = AbstractKey(key_id=key_b_id, key_name=key_b_name, is_component=True)
            self.physical_keys[key_a_id] = key_a
            self.physical_keys[key_b_id] = key_b
            self.physical_knobs.append(PhysicalKnob(key_a, key_b))

    def interrupt_handler(self, pin: Pin):
        # self.schedule_scan(False)
        if self.last_scan_finished:
            self.last_scan_finished = False
            micropython.schedule(self.schedule_scan, False)
    
    def schedule_scan(self, activate: bool = True):
        if not self.event_pending:
            self.event_pending = True
            self.virtual_keyboard.scan(activate=activate)
        self.last_scan_finished = True

    def is_pressed(self) -> bool:
        return False

    def sleep(self):
        return

    def scan(self, activate: bool = True) -> bool:
        return False

    def knob_scan(self) -> bool:
        event_flag = False
        for physical_knob in self.physical_knobs:
            if physical_knob.check_rotation():
                event_flag = True
                physical_key = physical_knob.rotated_key()
                if physical_key is None:
                    continue
                pressed = not (physical_knob.rotation == 0)
                if pressed:
                    if physical_key.bind_virtual is not None:
                        physical_key.bind_virtual.press()
                else:
                    if physical_key.bind_virtual is not None:
                        physical_key.bind_virtual.release()
        return event_flag

    def key_iter(self) -> Iterator[PhysicalKey]:
        if self.physical_keys is not None:
            if isinstance(self.physical_keys, list):
                for physical_key in self.physical_keys:
                    yield physical_key
            elif isinstance(self.physical_keys, dict):
                for physical_key in self.physical_keys.values():
                    yield physical_key
            else:
                raise TypeError(type(physical_key))


class ShiftRegisterKeyBoard(PhysicalKeyBoard):
    def __init__(
        self,
        key_config: str = "/config/physical_keyboard.json",
        virtual_keyboard: Optional["VirtualKeyBoard"] = None,
        ktype: Optional[str] = None,
        clock_pin: Optional[int] = None,
        pl_pin: Optional[int] = None,
        ce_pin: Optional[int] = None,
        read_pin: Optional[int] = None,
        power_pin: Optional[int] = None,
        wakeup_pin: Optional[int] = None,
        scan_mode: Optional[int] = None,
        led_manager: Optional[LEDManager] = None,
    ):
        super().__init__(key_config=key_config, virtual_keyboard=virtual_keyboard, led_manager=led_manager)

        ktype = ktype or self.key_config.get("ktype", None)
        clock_pin = pl_pin or self.key_config.get("clock_pin", None)
        pl_pin = pl_pin or self.key_config.get("pl_pin", None)
        ce_pin = ce_pin or self.key_config.get("ce_pin", None)
        read_pin = read_pin or self.key_config.get("read_pin", None)
        power_pin = power_pin or self.key_config.get("power_pin", None)
        wakeup_pin = wakeup_pin or self.key_config.get("wakeup_pin", None)
        self.scan_mode = scan_mode or self.key_config.get("scan_mode", None)

        self.key_pl = Pin(pl_pin, Pin.OUT, value=1)
        self.key_ce = Pin(ce_pin, Pin.OUT, value=0)
        self.key_power = Pin(power_pin, Pin.OUT, value=1) if power_pin is not None else None
        self.wakeup = IRQPin(wakeup_pin, mode=Pin.IN, pull=Pin.PULL_DOWN) if wakeup_pin is not None else None
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
        
    def scan_keys(self, scan_mode: Optional[str] = None) -> None:
        scan_mode = scan_mode or self.scan_mode
        if scan_mode in ("SPI", "SoftSPI"):
            # Load key state
            self.key_pl.value(0)
            self.key_pl.value(1)
            self.spi.readinto(self._current_buffer)
        else:
            interval_us = 1
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

    def scan(self, activate: bool = True) -> bool:  # TODO: filter
        # activate is always True
        self.scan_keys()
        self.event_pending = False
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

        if scan_change and self.led_manager.enabled:
            self.led_manager.write_pixels()

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


class TCA8418KeyBoard(PhysicalKeyBoard):
    def __init__(
        self,
        key_config: str = "/config/physical_keyboard.json",
        virtual_keyboard: Optional["VirtualKeyBoard"] = None,
        wakeup: Optional[Pin] = None,
        i2c: Optional[I2C] = None,
        i2c_addr: Optional[int] = None,
        led_manager: Optional[LEDManager] = None,
    ):
        super().__init__(key_config=key_config, virtual_keyboard=virtual_keyboard, led_manager=led_manager)

        ktype = self.key_config.get("ktype", None)
        sda_pin = self.key_config.get("sda_pin", None)
        scl_pin = self.key_config.get("scl_pin", None)
        wakeup_pin = self.key_config.get("wakeup_pin", None)

        self.scan_mode = self.key_config.get("scan_mode", None)

        self.event_pending = False
        self.i2c_reading = False

        if "kdeivce" in self.key_config:
            self.tca = GLOBAL_DEIVCE_MANAGER.get_device(self.key_config["kdeivce"])
            if wakeup is None:
                if "ideivce" in self.key_config:
                    self.wakeup = GLOBAL_DEIVCE_MANAGER.get_device(self.key_config["ideivce"])
                    self.wakeup.irq(trigger=machine.Pin.IRQ_FALLING, handler=self.interrupt_handler)
                else:
                    self.wakeup = None
            else:
                self.wakeup = wakeup
        else:  # TODO: Will be deprecated in the next major update
            tca_addr = i2c_addr or int(self.key_config.get("address", "0x34"), 16)
            i2c = i2c or I2C(0, scl=machine.Pin(scl_pin), sda=machine.Pin(sda_pin), freq=400000)
            self.tca = TCA8418(i2c, tca_addr)

            if wakeup is None:
                self.wakeup = IRQPin(wakeup_pin, machine.Pin.IN, machine.Pin.PULL_UP) if wakeup_pin is not None else None
                if self.wakeup is not None:
                    self.wakeup.irq(trigger=machine.Pin.IRQ_FALLING, handler=self.interrupt_handler)
            else:
                self.wakeup = wakeup

        # INIT TCA8418
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

    def scan(self, activate: bool = False) -> bool:  # TODO: activate scan
        if (not (self.event_pending or activate)) or self.i2c_reading:
            return False
        self.i2c_reading = True
        self.event_pending = False
        tca = self.tca
        event_flag = False
        while True:
            event = tca.read_next_event()
            if event is None:
                break
            keycode = event & 0x7F
            is_press = bool(event & 0x80)

            if 1 <= keycode <= 80: # Keypad Array, TODO: change id to 0-79
                event_flag = True
                physical_key = self.physical_keys[keycode]
                if physical_key is None:
                    raise AssertionError(f"physical_key is None, keycode: {keycode}")
                physical_key.pressed = is_press

                if is_press:
                    if debugging():
                        print(f"physical({physical_key.key_id}, {physical_key.key_name}) is pressed at {time.ticks_ms()}.")
                    if physical_key.bind_virtual is not None:
                        physical_key.bind_virtual.press()
                        self.led_manager.set_pixel(physical_key.key_name, self.led_manager.random_color())
                    else:
                        if debugging():
                            print(f"physical({physical_key.key_id}, {physical_key.key_name}) not bind for press")
                else:
                    if physical_key.bind_virtual is not None:
                        physical_key.bind_virtual.release()
                        self.led_manager.set_pixel(physical_key.key_name, self.led_manager.default_color())
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
        self.i2c_reading = False
        if event_flag and self.led_manager.enabled:
            self.led_manager.write_pixels()
        return event_flag

    def sleep(self):
        # TODO
        return
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


class PCA9555KeyBoard(PhysicalKeyBoard):
    def __init__(
        self,
        key_config: str = "/config/physical_keyboard.json",
        virtual_keyboard: Optional["VirtualKeyBoard"] = None,
        wakeup: Optional[Pin] = None,
        i2c: Optional[I2C] = None,
        i2c_addr: Optional[int] = None,
        led_manager: Optional[LEDManager] = None,
    ):
        super().__init__(key_config=key_config, virtual_keyboard=virtual_keyboard, led_manager=led_manager)
        ktype = self.key_config.get("ktype", None)
        sda_pin = self.key_config.get("sda_pin", None)
        scl_pin = self.key_config.get("scl_pin", None)
        wakeup_pin = self.key_config.get("wakeup_pin", None)

        self.scan_mode = self.key_config.get("scan_mode", None)

        self.event_pending = False


        if "kdeivce" in self.key_config:
            self.pca = GLOBAL_DEIVCE_MANAGER.get_device(self.key_config["kdeivce"])
            if wakeup is None:
                if "ideivce" in self.key_config:
                    self.wakeup = GLOBAL_DEIVCE_MANAGER.get_device(self.key_config["ideivce"])
                    self.wakeup.irq(trigger=machine.Pin.IRQ_FALLING, handler=self.interrupt_handler)
                else:
                    self.wakeup = None
            else:
                self.wakeup = wakeup
        else:  # TODO: Will be deprecated in the next major update
            pca_addr = i2c_addr or int(self.key_config.get("address", "0x20"), 16)
            i2c = i2c or I2C(0, scl=machine.Pin(scl_pin), sda=machine.Pin(sda_pin), freq=400000)
            self.pca = PCA9555(i2c, address=pca_addr)

            if wakeup is None:
                self.wakeup = IRQPin(wakeup_pin, machine.Pin.IN, machine.Pin.PULL_UP) if wakeup_pin is not None else None
                if self.wakeup is not None:
                    self.wakeup.irq(trigger=machine.Pin.IRQ_FALLING, handler=self.interrupt_handler)
            else:
                self.wakeup = wakeup

        # set pin mode
        for _, key_id in self.keymap_dict.items():
            self.pca.set_pin_mode(key_id, 1)  # 0 for OUTPUT, 1 for INPUT.

    def scan(self, activate: bool = False) -> bool:
        if not (self.event_pending or activate):
            return False

        self.event_pending = False
        pca = self.pca
        event_flag = False
        if activate:
            pca.scan()

        for physical_key in self.physical_keys:
            if physical_key is not None:
                is_press = not pca.digital_read_from_buffer(physical_key.key_id)
                if physical_key.pressed == is_press:
                    continue
                event_flag = True
                physical_key.pressed = is_press

                if physical_key.is_component:  # TODO: component key do not bind virtual
                    continue

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
        event_flag = self.knob_scan() or event_flag
        return event_flag


class PhysicalKeyBoards(PhysicalKeyBoard):
    """
    Contain a list of PhysicalKeyBoard.
    """

    def __init__(
        self,
        key_config: str = "/config/physical_keyboard.json",
        virtual_keyboard: Optional["VirtualKeyBoard"] = None,
        wakeup: Optional["Pin"] = None,
    ):
        super().__init__(key_config=key_config, virtual_keyboard=virtual_keyboard)
        self.ktype = self.key_config.get("ktype", None)
        self.devices = self.key_config.get("devices", [])

        self.wakeups: Dict[str, IRQPin] = {}
        self.phsical_key_boards: List[PhysicalKeyBoard] = []
        self.used_key_num = 0

        if wakeup:
            self.wakeups["default"] = wakeup

        # TODO: Distinguish which int is tirggered and only scan that chip.
        for device_config in self.devices:
            if "ideivce" in device_config:
                wakeup_name = device_config["ideivce"]
                if wakeup_name not in self.wakeups:
                    wakeup = GLOBAL_DEIVCE_MANAGER.get_device(wakeup_name)
                    wakeup.irq(trigger=machine.Pin.IRQ_FALLING, handler=self.interrupt_handler)
                    self.wakeups["wakeup_name"] = wakeup

        # TODO: Move to PhysicalKeyBoard?
        ledmap = {}
        for device_config in self.devices:
            keymap_path = device_config.get("keymap_path", None)
            if keymap_path is None or not exists(keymap_path):
                continue
            keymap_json = json.load(open(keymap_path))
            if "ledmap" in keymap_json:
                ledmap.update(keymap_json["ledmap"])

        self.led_manager = LEDManager(self.key_config, ledmap=ledmap)

        for device_config in self.devices:
            device_ktype = device_config["ktype"]

            if device_ktype == "tca8418":
                wakeup_name = device_config.get("ideivce", None)
                phsical_key_board = TCA8418KeyBoard(
                    key_config=device_config,
                    wakeup=self.wakeups.get(wakeup_name, None) if wakeup_name is not None else None,
                    led_manager=self.led_manager
                )
            elif device_ktype == "pca9555":
                wakeup_name = device_config.get("ideivce", None)
                phsical_key_board = PCA9555KeyBoard(
                    key_config=device_config,
                    wakeup=self.wakeups.get(wakeup_name, None) if wakeup_name is not None else None,
                    led_manager=self.led_manager
                )
            else:
                raise NotImplementedError(f"Not implemented device_ktype: {device_ktype}")
            print(f"device_ktype: {device_ktype}, device_config: {device_config}")
            self.used_key_num += phsical_key_board.used_key_num
            self.phsical_key_boards.append(phsical_key_board)

    def key_iter(self) -> Iterator[PhysicalKey]:
        for phsical_key_board in self.phsical_key_boards:
            if phsical_key_board.physical_keys is not None:
                if isinstance(phsical_key_board.physical_keys, list):
                    for physical_key in phsical_key_board.physical_keys:
                        yield physical_key
                elif isinstance(phsical_key_board.physical_keys, dict):
                    for physical_key in phsical_key_board.physical_keys.values():
                        yield physical_key
                else:
                    raise TypeError(type(phsical_key_board.physical_keys))

    def interrupt_handler(self, pin: Pin):
        for phsical_key_board in self.phsical_key_boards:
            # TODO: Distinguish which int is tirggered and only scan that chip.
            phsical_key_board.event_pending = True
        # self.schedule_scan(False)
        if self.last_scan_finished:
            self.last_scan_finished = False
            micropython.schedule(self.schedule_scan, False)

    def scan(self, activate: bool = True) -> bool:
        self.event_pending = False
        final_scan_result = False
        for phsical_key_board in self.phsical_key_boards:
            scan_result = phsical_key_board.scan(activate=activate)
            final_scan_result = final_scan_result or scan_result
        return final_scan_result
