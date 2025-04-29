import _thread
import time
import json
import random
import neopixel
import usb.device
import gc
import array
import asyncio
from ulab import numpy as np
import micropython

from typing import List, Dict, Optional, Callable, Tuple
from machine import Pin, I2S, SPI
from usb.device.keyboard import KeyboardInterface, KeyCode, LEDCode

import st7789py as st7789
import vga2_bold_16x32 as font

from audio import AudioManager, Sampler
from graphics import interpolate
from bluetoothkeyboard import BluetoothKeyboard
from utils import partial, exists


DEBUG = True


class LEDManager:
    def __init__(
        self,
        led_config: Dict      
    ):
        self.ltype = led_config.get("ltype", "neopixel")
        self.led_pixels = led_config.get("led_pixels", 68)
        self.max_light_level = led_config.get("max_light_level", 16)
        self.onstart_light_level = led_config.get("onstart_light_level", 1)
        self.led_data_pin = led_config.get("led_data_pin")
        self.led_power_pin = led_config.get("led_power_pin")
        
        self.led_power = Pin(self.led_power_pin, Pin.OUT)
        self.led_power.value(1)

        self.pixels = neopixel.NeoPixel(Pin(self.led_data_pin, Pin.OUT), self.led_pixels)
        # for i in range(self.led_pixels):
        #     self.pixels[i] = (self.onstart_light_level, self.onstart_light_level, self.onstart_light_level)
        self.pixels.fill((self.onstart_light_level, self.onstart_light_level, self.onstart_light_level))
        self.pixels.write()

    def led_switch(self, open: bool = True):
        self.led_power.value(open)

    def set_pixel(self, i: int, color: Tuple[int], write: bool = False):
        self.pixels[i] = (max(l, self.max_light_level) for l in color)
        if write:
            self.pixels.write()

    def write_pixels(self):
        self.pixels.write()


class VirtualKey:
    def __init__(
        self,
        key_name: str,
        keycode: int,
        physical_key: "PhysicalKey",
        pressed_function: Optional[Callable] = None,
        released_function: Optional[Callable] = None
    ) -> None:
        # self.key_id  # TODO
        self.keycode = keycode
        self.key_name = key_name
        self.pressed_function = pressed_function or self.default_pressed_function
        self.released_function = released_function or self.default_released_function
        # TODO: press condition function
        self.bind_physical = None
        self.press_time = None
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
        if DEBUG:
            print(f"virtual({self.keycode}, {self.key_name}) is released.")

    # TODO: @property
    # def is_pressed(self):
    #     return self.pressed
        # pressed = self.bind_physical.pressed if self.bind_physical is not None else False
        # return pressed

    def press(self):
        self.pressed = True
        self.press_time = time.ticks_ms()
        if self.pressed_function:
            pressed_function_result = self.pressed_function()
            if pressed_function_result is None:  # TODO
                return None
            return pressed_function_result
        return None
        
    def release(self):
        self.pressed = False
        if self.released_function:
            released_function_result = self.released_function()
            if released_function_result is None:  # TODO
                return None
            return released_function_result
        return None


class PhysicalKey:
    def __init__(self, key_id: int, key_name: str, max_light_level: int = 16) -> None:
        self.key_id = key_id
        self.key_name = key_name
        self.pressed = False
        # self.bind_light = None    # TODO: bind led on board
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
        power_pin: Optional[int] = None,
        wakeup_pin: Optional[int] = None,
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
        power_pin = power_pin or self.key_config.get("power_pin", None)
        wakeup_pin = wakeup_pin or self.key_config.get("wakeup_pin", None)
        max_keys = max_keys or self.key_config.get("max_keys", None)
        keymap_path = keymap_path or self.key_config.get("keymap_path", None)
        max_light_level = max_light_level or self.key_config.get("max_light_level", None)
    
        self.key_pl = Pin(pl_pin, Pin.OUT, value=1)
        self.key_ce = Pin(ce_pin, Pin.OUT, value=0)
        self.key_clk = Pin(clock_pin, Pin.OUT, value=0)
        self.key_in = Pin(read_pin, Pin.IN)
        self.key_power = Pin(power_pin, Pin.OUT, value=1) if power_pin is not None else None
        self.wakeup_pin = Pin(wakeup_pin, Pin.IN) if wakeup_pin is not None else None

        self.max_keys = max_keys
        self.physical_keys = [None for _ in range(max_keys)]
        self.keymap_dict = json.load(open(keymap_path))
        self.used_key_num = len(self.keymap_dict)
        assert self.used_key_num <= self.max_keys, "More keys are used than the maximum allowed!"
        for key_name, key_id in self.keymap_dict.items():
            self.physical_keys[key_id] = PhysicalKey(key_id=key_id, key_name=key_name, max_light_level=max_light_level)
        
        self.led = LEDManager(self.key_config)

        # Calculate the number of bytes needed to store max_keys bits
        self.bytes_needed = (self.max_keys + 7) // 8

        # Double buffer for key states: previous_state and current_state
        # Each key state is stored as a bit (0 or 1)
        self._buffer_a = bytearray(self.bytes_needed)
        self._buffer_b = bytearray(self.bytes_needed)

        # Pointers to the current and previous state buffers
        self._current_buffer = self._buffer_a
        self._previous_buffer = self._buffer_b # Initially, both are zero, representing all keys released
        
    def scan_keys(self, interval_us=1) -> None:
        # key_states = self.key_states_view
        for byte_index in range(self.bytes_needed):
            self._current_buffer[byte_index] = 0

        # Load key state
        self.key_pl.value(0)
        time.sleep_us(interval_us)
        self.key_pl.value(1)
        time.sleep_us(interval_us)
        
        # read key states
        # self.key_ce.value(0)
        # time.sleep_us(interval_us)
        for i in range(self.max_keys):
            # key_states[i] = not self.key_in.value()

            # Determine byte and bit index
            byte_index = i // 8
            bit_index = i % 8

            # Read the pin value, invert it (assuming active low)
            state = int(not self.key_in.value())

            self._current_buffer[byte_index] |= (state << bit_index)

            self.key_clk.value(1)
            time.sleep_us(interval_us)
            self.key_clk.value(0)
            time.sleep_us(interval_us)
        # self.key_ce.value(1)
    
    def scan(self, interval_us=1) -> bool:
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

                        # If state changed and current state is 1 (0 -> 1): Key Pressed
                        if current_state == 1:
                            # This check should technically not be needed if logic is perfect,
                            # but good defensive programming.
                            # if not physical_key.pressed:
                            physical_key.pressed = True
                            if 'DEBUG' in globals() and DEBUG:
                                print(f"physical({physical_key.key_id}, {physical_key.key_name}) is pressed at {time.ticks_ms()}.")
                            if physical_key.bind_virtual is not None:
                                physical_key.bind_virtual.press()
                            else:
                                if 'DEBUG' in globals() and DEBUG:
                                    print(f"physical({physical_key.key_id}, {physical_key.key_name}) not bind for press")

                        # If state changed and current state is 0 (1 -> 0): Key Released
                        else: # current_state must be 0
                            # This check should technically not be needed
                            # if physical_key.pressed:
                            physical_key.pressed = False
                            if 'DEBUG' in globals() and DEBUG:
                                print(f"physical({physical_key.key_id}, {physical_key.key_name}) is released at {time.ticks_ms()}.")
                            if physical_key.bind_virtual is not None:
                                physical_key.bind_virtual.release()
                            else:
                                if 'DEBUG' in globals() and DEBUG:
                                    print(f"physical({physical_key.key_id}, {physical_key.key_name}) not bind for release")

        self._previous_buffer, self._current_buffer = self._current_buffer, self._previous_buffer
        return scan_change

    def is_pressed(self) -> bool:
        self.scan_keys()
        for byte_index in range(self.bytes_needed):
            current_byte = self._current_buffer[byte_index]
            if current_byte > 0:
                return True
        return False


class VirtualKeyBoard:
    def __init__(self,
        connection_mode: str = "bluetooth",
        mapping_path: str = "/config/virtual_keymaps.json",
        key_num: int = 68,  # Real used key num.
        max_phiscal_keys: int = 72,
    ):
        # assert key_num >= self.phsical_key_board.used_key_num, "virt key num < phys key num."
        self.phsical_key_board = PhysicalKeyBoard(max_keys=max_phiscal_keys)  # TODO: as an arg
        key_num = max(key_num, self.phsical_key_board.used_key_num)
        self.key_num = key_num
        if exists(mapping_path):
            self.virtual_key_mappings = json.load(open(mapping_path))
        else:
            self.virtual_key_mappings = None

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

        self.virtual_keys: List[VirtualKey] = self.build_virtual_keys()

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
                self.ble_interface = BluetoothKeyboard()
            self.ble_interface.start()
            self.interface = self.ble_interface
        elif self.connection_mode == "debug":
            # TODO: DebugKeyBoard class
            global DEBUG
            DEBUG = True
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
                    keycode=getattr(KeyCode, key_code_name, None), physical_key=physical_key, pressed_function=None, released_function=None
                )
                virtual_keys.append(virtual_key)
        self.build_fn_layer(virtual_keys)
        return virtual_keys

    def build_fn_layer(self, virtual_keys: List[VirtualKey]):
        for virtual_key in virtual_keys:
            if virtual_key.bind_physical.key_name == "FN":  # create ".py" file or build from file.
                def fn_pressed_function(virtual_key_board: "VirtualKeyBoard"):
                    print("change to layer 1")
                    virtual_key_board.layer = 1
                def fn_released_function(virtual_key_board: "VirtualKeyBoard"):
                    print("change to layer 0")
                    virtual_key_board.layer = 0
                virtual_key.pressed_function = partial(fn_pressed_function, self)
                virtual_key.released_function = partial(fn_released_function, self)
            if virtual_key.bind_physical.key_name == "Q":
                def ble_pressed_function(virtual_key_board: "VirtualKeyBoard", original_func: Callable = None):
                    if virtual_key_board.layer == 1:
                        virtual_key_board.set_connection_mode("bluetooth")
                    elif original_func:
                        original_func()
                virtual_key.pressed_function = partial(ble_pressed_function, self, virtual_key.pressed_function)
            if virtual_key.bind_physical.key_name == "W":
                def usb_pressed_function(virtual_key_board: "VirtualKeyBoard", original_func: Callable = None):
                    if virtual_key_board.layer == 1:
                        virtual_key_board.set_connection_mode("usb_hid")
                    elif original_func:
                        original_func()
                virtual_key.pressed_function = partial(usb_pressed_function, self, virtual_key.pressed_function)
            if virtual_key.bind_physical.key_name == "E":
                def debug_pressed_function(virtual_key_board: "VirtualKeyBoard", original_func: Callable = None):
                    if virtual_key_board.layer == 1:
                        virtual_key_board.set_connection_mode("debug")
                    elif original_func:
                        original_func()
                virtual_key.pressed_function = partial(debug_pressed_function, self, virtual_key.pressed_function)
            if virtual_key.bind_physical.key_name == "R":
                def clear_ble_pressed_function(virtual_key_board: "VirtualKeyBoard", original_func: Callable = None):
                    if virtual_key_board.layer == 1:
                        if self.ble_interface:
                            self.ble_interface.clear_paired_devices()
                    elif original_func:
                        original_func()
                virtual_key.pressed_function = partial(clear_ble_pressed_function, self, virtual_key.pressed_function)

    def scan(self, interval_us: int = 1):
        if not self.phsical_key_board.scan(interval_us=interval_us):
            return

        self.keystates.clear()
        self.pressed_keys.clear()
        virtual_keys = self.virtual_keys
        for virtual_key in virtual_keys:
            if virtual_key.pressed and virtual_key.keycode is not None:
                self.pressed_keys.append(virtual_key)
                # self.keystates.append(virtual_key.keycode)
        self.pressed_keys.sort(key=lambda k:k.press_time, reverse=True)
        self.keystates = [k.keycode for k in self.pressed_keys[:6]]
        if self.keystates != self.prev_keystates:
            self.prev_keystates.clear()
            self.prev_keystates.extend(self.keystates)
            if DEBUG:
                print(self.keystates)
            if self.interface is not None:
                self.interface.send_keys(self.keystates)


class MusicKeyBoard(VirtualKeyBoard):
    def __init__(self, 
        music_mapping_path: str,
        audio_manager: Optional[AudioManager] = None,
        mode: str = "C Major",
        *args,
        **kwargs
    ):
        if exists(music_mapping_path):
            self.music_mapping_path = music_mapping_path
            if audio_manager is None:
                audio_manager = AudioManager(
                    rate=16000,
                    buffer_samples=1024,
                    ibuf=4096,
                    always_play=True,
                    volume_factor=0.1
                )
            self.audio_manager = audio_manager
            self.sampler = Sampler("/wav/piano/16000")
            self.music_mappings = json.load(open(self.music_mapping_path))
            self.mode = mode
            self.music_mapping = self.music_mappings[mode]
            micropython.mem_info()
            for i, note in enumerate(sorted(list(self.music_mapping.values()), key=lambda n: n[-1])):
                print(f"Loading {i} th note: {note}, alloc: {gc.mem_alloc()}, free: {gc.mem_free()}")
                self.audio_manager.load_wav(note, self.sampler.get_sample(note, duration=2.0).tobytes())
                # micropython.mem_info()
                gc.collect()
        else:
            self.music_mapping_path = None
            self.audio_manager = None
            self.music_mapping = {}

        super().__init__(*args, **kwargs)

    def build_fn_layer(self, virtual_keys: List[VirtualKey]):
        super().build_fn_layer(virtual_keys)
        for virtual_key in virtual_keys:
            if virtual_key.bind_physical.key_name in ["AUDIO_CALL", "M"]:
                def sound_pressed_function(virtual_key_board: "MusicKeyBoard", original_func: Callable = None):
                    if virtual_key_board.layer == 1:
                        if virtual_key_board.audio_manager.volume_factor > 0:
                            virtual_key_board.audio_manager.volume_factor = 0
                        else:
                            virtual_key_board.audio_manager.volume_factor = 0.1
                    elif original_func:
                        original_func()
                virtual_key.pressed_function = partial(sound_pressed_function, self, virtual_key.pressed_function)

    def build_virtual_keys(self):
        virtual_keys: List[VirtualKey] = []
        for physical_key in self.phsical_key_board.physical_keys:
            if physical_key is not None:
                key_code_name = physical_key.key_name
                if self.virtual_key_mappings is not None:
                    key_code_name = self.virtual_key_mappings["layers"]["0"].get(physical_key.key_name, None) or key_code_name
                if physical_key.key_name in self.music_mapping:
                    virtual_key = VirtualKey(
                        key_name=key_code_name,
                        keycode=getattr(KeyCode, key_code_name, None),
                        physical_key=physical_key,
                        pressed_function=None,
                        released_function=None,
                    )
                    def pressed_function(virtual_key: VirtualKey, note: str):
                        virtual_key.playing_wav_id = self.audio_manager.play_note(note)
                    def released_function(virtual_key: VirtualKey):
                        if hasattr(virtual_key, "playing_wav_id"):
                            self.audio_manager.stop_note(wav_id=virtual_key.playing_wav_id, delay=500)
                    virtual_key.pressed_function = partial(pressed_function, virtual_key, self.music_mapping[physical_key.key_name])
                    virtual_key.released_function = partial(released_function, virtual_key)
                else:
                    virtual_key = VirtualKey(key_name=key_code_name, keycode=getattr(KeyCode, key_code_name, None), physical_key=physical_key)
                virtual_keys.append(virtual_key)
        self.build_fn_layer(virtual_keys)
        return virtual_keys


def screen(tft, names: List[str] = ["MicroKeyBoard", "Mode", "F Major"]):  # TODO: build screen manager
    color_values = (255, 255, 255)
    height_division = tft.height // len(color_values)
    for i, color_value in enumerate(color_values):
        start_row = i * height_division
        end_row = (i + 1) * height_division
        for row in range(start_row, end_row):
            rgb_color = [0 if idx != i else int(interpolate(0, color_value, row - start_row, height_division)) for idx in range(3)]
            color = st7789.color565(rgb_color)

        for row in range(start_row, end_row):
            tft.hline(0, row, tft.width, color)

        name = names[i]
        text_x = (tft.width - font.WIDTH * len(name)) // 2
        text_y = start_row + (end_row - start_row - font.HEIGHT) // 2
        tft.text(font, name, text_x, text_y, st7789.WHITE, color)

    return tft


def main():
    time.sleep_ms(1000)
    tft = st7789.ST7789(
        SPI(2, baudrate=30000000, sck=Pin(1), mosi=Pin(2), miso=None),
        135,
        240,
        reset=Pin(42, Pin.OUT),
        cs=Pin(40, Pin.OUT),
        dc=Pin(41, Pin.OUT),
        backlight=Pin(39, Pin.OUT),
        rotation=1,
    )
    screen(tft,names=["MicroKeyBoard", "Music Mode", "Starting"])
    # virtual_key_board = VirtualKeyBoard()

    virtual_key_board = MusicKeyBoard(
        music_mapping_path="config/music_keymap.json",
        mode = "F Major"
    )
    time.sleep_ms(50)
    screen(tft,names=["MicroKeyBoard", "Music Mode", "F Major"])
    count = 0
    max_scan_gap = 0
    start_time = time.ticks_ms()
    current_time = time.ticks_ms()
    while True:
        scan_start_time = time.ticks_ms()
        virtual_key_board.scan(1)
        # virtual_key_board.phsical_key_board.scan(0)
        # virtual_key_board.phsical_key_board.scan_keys(0)
        # max_scan_gap = max(max_scan_gap, time.ticks_ms() - scan_start_time)
        # time.sleep_ms(1)
        count += 1
        max_scan_gap = max(max_scan_gap, time.ticks_ms() - current_time)
        current_time = time.ticks_ms()

        # if current_time - start_time >= 500:
        #     gc.collect()

        if current_time - start_time >= 1000:
            print(f"scan speed: {count}/s, gap {max_scan_gap}ms, mem_free: {gc.mem_free()}")
            count = 0
            max_scan_gap = 0
            start_time = current_time

        # for color in [st7789.RED, st7789.GREEN, st7789.BLUE]:
        #     for x in range(tft.width):
        #         tft.pixel(x, 0, color)
        #         tft.pixel(x, tft.height - 1, color)

        #     for y in range(tft.height):
        #         tft.pixel(0 , y, color)
        #         tft.pixel(tft.width - 1, y, color)


if __name__ == "__main__":
    main()

