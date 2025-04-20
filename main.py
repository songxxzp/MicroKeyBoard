import time
import json
import random
import neopixel
import usb.device

from typing import List, Dict, Optional
from machine import Pin
from usb.device.keyboard import KeyboardInterface, KeyCode, LEDCode

from bluetoothkeyboard import BluetoothKeyboard


DEBUG = True


def partial(func, *args):
    def wrapper(*more_args):
        return func(*args, *more_args)
    return wrapper


class LEDManager:
    def __init__(
        self,
        led_config: Dict      
    ):
        self.ltype = led_config.get("ltype", "neopixel")
        self.led_pixels = led_config.get("led_pixels", 68)
        self.max_light_level = led_config.get("max_light_level", 16)
        self.led_data_pin = led_config.get("led_data_pin")
        self.led_power_pin = led_config.get("led_power_pin")
        
        self.led_power = Pin(self.led_power_pin, Pin.OUT)
        self.led_power.value(1)

        self.pixels = neopixel.NeoPixel(Pin(self.led_data_pin, Pin.OUT), self.led_pixels)
        for i in range(self.led_pixels):
            self.pixels[i] = (self.max_light_level, self.max_light_level, self.max_light_level)
        self.pixels.write()


class VirtualKey:
    def __init__(self, key_name: str, keycode: int, physical_key: "PhysicalKey", pressed_function=None) -> None:
        self.keycode = keycode
        self.key_name = key_name
        self.pressed_function = self.default_pressed_function if pressed_function is None else pressed_function  # TODO: rename
        self.released_function = self.default_released_function  # TODO
        # TODO: press condition function
        self.bind_physical = None
        self.pressed = False
        self.update_time = time.time()

        self.bind_physical_key(physical_key)

    def bind_physical_key(self, physical_key: "PhysicalKey"):
        self.bind_physical = physical_key
        physical_key.bind_virtual = self

    def unbind_physical_key(self):
        self.bind_physical.bind_virtual = None
        self.bind_physical = None

    def default_pressed_function(self):
        if DEBUG:
            print(f"virtual({self.keycode}, {self.key_name}) is pressed.")

    def default_released_function(self):
        pass

    # TODO: @property
    def is_pressed(self):
        pressed = self.bind_physical.pressed if self.bind_physical is not None else False
        return pressed

    def press(self):
        self.pressed = True
        if self.pressed_function:
            pressed_function_result = self.pressed_function()
            if pressed_function_result is None:  # TODO
                return None
            return pressed_function_result
        return None
        
    def release(self):
        self.pressed = False
        return None


class PhysicalKey:
    def __init__(self, key_id: int, key_name: str, max_light_level: int = 16) -> None:
        self.key_id = key_id
        self.key_name = key_name
        self.pressed = False
        self.color = (max_light_level, max_light_level, max_light_level)
        self.random_color(max_light_level)
        self.bind_virtual: "VirtualKey" = None
        # TODO: add used mark to avoid conflict
    
    def random_color(self, max_light_level):
        self.color = (
            random.randint(0, max_light_level),
            random.randint(0, max_light_level),
            random.randint(0, max_light_level)
        )
    
    def bind_virtual_key(self, virtual_key: "VirtualKey"):
        self.bind_virtual = virtual_key
        virtual_key.bind_physical = self

    def unbind_virtual_key(self):
        self.bind_virtual.bind_physical = None
        self.bind_virtual = None

    def default_pressed_function(self):  # TODO
        pass

    def default_released_function(self):  # TODO
        pass


class PhysicalKeyBoard:
    def __init__(
        self,
        key_config_path: str = "/config/physical_keyboard.json",
        ktype: Optional[str] = None,
        clock_pin: Optional[int] = None,
        pl_pin: Optional[int] = None,
        ce_pin: Optional[int] = None,
        read_pin: Optional[int] = None,
        max_keys: Optional[int] = None,  # The maximum number of keys for key scanning. The actual number of keys used is less than or equal to this number.
        keymap_path: Optional[str] = None,  # "/config/physical_keymap.json",
        max_light_level: Optional[int] = None
    ):
        self.key_config = json.load(open(key_config_path))

        ktype = ktype or self.key_config.get("ktype", None)
        clock_pin = pl_pin or self.key_config.get("clock_pin", None)
        pl_pin = pl_pin or self.key_config.get("pl_pin", None)
        ce_pin = ce_pin or self.key_config.get("ce_pin", None)
        read_pin = read_pin or self.key_config.get("read_pin", None)
        max_keys = max_keys or self.key_config.get("max_keys", None)
        keymap_path = keymap_path or self.key_config.get("keymap_path", None)
        max_light_level = max_light_level or self.key_config.get("max_light_level", None)
    
        self.key_pl = Pin(pl_pin, Pin.OUT, value=1)
        self.key_ce = Pin(ce_pin, Pin.OUT, value=1)
        self.key_clk = Pin(clock_pin, Pin.OUT, value=0)
        self.key_in = Pin(read_pin, Pin.IN)
        
        self.max_keys = max_keys
        self.physical_keys = [None for _ in range(max_keys)]
        self.keymap_dict = json.load(open(keymap_path))
        self.used_key_num = len(self.keymap_dict)
        assert self.used_key_num <= self.max_keys, "More keys are used than the maximum allowed!"
        for key_name, key_id in self.keymap_dict.items():
            self.physical_keys[key_id] = PhysicalKey(key_id=key_id, key_name=key_name, max_light_level=max_light_level)
        
        self.led = LEDManager(self.key_config)
        
    def scan_keys(self, interval_us=1) -> List[bool]:
        key_states = [False for _ in range(self.max_keys)]  # Pressed: 1; Released: 0
                
        # Load key state
        self.key_pl.value(0)
        time.sleep_us(interval_us)
        self.key_pl.value(1)
        time.sleep_us(interval_us)
        
        # read key states
        self.key_ce.value(0)
        time.sleep_us(interval_us)
        for i in range(self.max_keys):
            key_states[i] = not self.key_in.value()
            self.key_clk.value(1)
            time.sleep_us(interval_us)
            self.key_clk.value(0)
            time.sleep_us(interval_us)
        self.key_ce.value(1)
        return key_states
    
    def scan(self, interval_us=1):
        key_states = self.scan_keys(interval_us=interval_us)
        for key_id, key_state in enumerate(key_states):
            physical_key = self.physical_keys[key_id]
            if physical_key is None:
                continue
            if not physical_key.pressed and key_state:
                physical_key.pressed = True
                if DEBUG:
                    print(f"physical({physical_key.key_id}, {physical_key.key_name}) is pressed.")
                if physical_key.bind_virtual is not None:
                    physical_key.bind_virtual.press()
                else:
                    if DEBUG:
                        print(f"physical({physical_key.key_id}, {physical_key.key_name}) not bind")
            if physical_key.pressed and not key_state:
                physical_key.pressed = False
                if DEBUG:
                    print(f"physical({physical_key.key_id}, {physical_key.key_name}) is released.")
                if physical_key.bind_virtual is not None:
                    physical_key.bind_virtual.release()
                else:
                    if DEBUG:
                        print(f"physical({physical_key.key_id}, {physical_key.key_name}) not bind")

    def is_pressed(self) -> bool:
        key_states = self.scan_keys()
        for key_id, key_state in enumerate(key_states):
            physical_key = self.physical_keys[key_id]
            if physical_key is None:
                continue
            if key_state:
                return True
        return False


class VirtualKeyBoard:
    def __init__(self,
        mode: str = "bluetooth",
        mapping_path: str = "config/mapping.json",
        fn_mapping_path: str = "config/fn_mapping.json",
        key_num: int = 68,  # Real used key num.
        max_phiscal_keys: int = 72,
    ):
        self.mode = mode
        self.key_num = key_num
        self.phsical_key_board = PhysicalKeyBoard(max_keys=max_phiscal_keys)

        if self.phsical_key_board.is_pressed():  # TODO: phsical key function
            self.mode = "debug"

        assert key_num >= self.phsical_key_board.used_key_num, "virt key num < phys key num."
        # assert key_num == len(self.virtual_keys), "virt key num is not expected."

        if self.mode == "usb_hid":
            # TODO: USBKeyBoard class
            self.interface = KeyboardInterface()  # wrap interface
            self.usb_device = usb.device.get()
            self.usb_device.init(self.interface, builtin_driver=True)
        if self.mode == "bluetooth":
            self.interface = BluetoothKeyboard()
            self.interface.start()
        elif self.mode == "debug":
            # TODO: DebugKeyBoard class
            global DEBUG
            DEBUG = True
            self.interface = None
            print("Enabled DEBUG MODE")
        else:
            raise NotImplementedError(f"mode {self.mode} not implemented.")

        self.keystates = []
        self.prev_keystates = []

        self.virtual_keys: List[VirtualKey] = [VirtualKey(key_name=physical_key.key_name, keycode=getattr(KeyCode, physical_key.key_name, None), physical_key=physical_key, pressed_function=None) for physical_key in self.phsical_key_board.physical_keys if physical_key is not None]

    def scan(self, interval_us=1):
        self.keystates.clear()
        self.phsical_key_board.scan(interval_us=interval_us)
        for virtual_key in self.virtual_keys:
            if virtual_key.is_pressed() and virtual_key.keycode is not None:
                self.keystates.append(virtual_key.keycode)
        if self.keystates != self.prev_keystates:
            self.prev_keystates.clear()
            self.prev_keystates.extend(self.keystates)
            if DEBUG:
                print(self.keystates)
            if self.interface is not None:
                self.interface.send_keys(self.keystates)


def main():
    # time.sleep_ms(3000)
    # phsical_key_board = PhysicalKeyBoard()
    virtual_key_board = VirtualKeyBoard()
    time.sleep_ms(50)
    while True:
        virtual_key_board.scan()
        time.sleep_ms(1)


if __name__ == "__main__":
    main()
