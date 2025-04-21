import time
import json
import random
import neopixel
import usb.device

from typing import List, Dict, Optional
from machine import Pin, I2S, SPI
from usb.device.keyboard import KeyboardInterface, KeyCode, LEDCode

import st7789py as st7789
import vga2_bold_16x32 as font

from graphics import interpolate
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


class AudioManager:
    def __init__(
        self,
        sck_pin: int = 48,
        ws_pin: int = 47,
        sd_pin: int = 45,
        i2s_id: int = 0,
        bits: int = 16,
        format=I2S.MONO,
        rate=16000,
        ibuf: int = 65536,
    ):
        self.audio_out = I2S(
            i2s_id,
            sck=Pin(sck_pin),
            ws=Pin(ws_pin),
            sd=Pin(sd_pin),
            mode=I2S.TX,
            bits=bits,
            format=format,
            rate=rate,  # 8000
            ibuf=ibuf,  # 5000
        )
        self.wav = None
        self.wav_samples = bytearray(1000)
        self.wav_samples_mv = memoryview(self.wav_samples)
        self.is_playing = False
    
    def _i2s_callback(self, arg):
        if self.wav and self.is_playing:
            num_read = self.wav.readinto(self.wav_samples_mv)
            if num_read == 0:  # 文件结束
                self.stop()
            else:
                self.audio_out.write(self.wav_samples_mv[:num_read])

    def play(self, wav_file):
        if self.is_playing:
            self.stop()
            
        self.wav = open(wav_file, "rb")
        self.wav.seek(44)  # 跳过WAV文件头
        self.is_playing = True
        self.audio_out.irq(self._i2s_callback)
        # 触发第一次写入
        self._i2s_callback(None)

    def stop(self):
        if self.is_playing:
            self.is_playing = False
            self.audio_out.irq(None)
            if self.wav:
                self.wav.close()
                self.wav = None

    def block_play(self, wav_file):
        if self.is_playing:
            return False
        wav = open(wav_file, "rb")
        _ = wav.seek(44)
        wav_samples = bytearray(1000)
        wav_samples_mv = memoryview(wav_samples)
        while True:
            num_read = wav.readinto(wav_samples_mv)
            if num_read == 0:
                # end-of-file, advance to first byte of Data section
                # _ = wav.seek(44)
                break
            else:
                _ = self.audio_out.write(wav_samples_mv[:num_read])
        wav.close()
        return True

    def __del__(self):
        self.audio_out.deinit()


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
        self.key_ce = Pin(ce_pin, Pin.OUT, value=1)
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
        # assert key_num >= self.phsical_key_board.used_key_num, "virt key num < phys key num."
        self.phsical_key_board = PhysicalKeyBoard(max_keys=max_phiscal_keys)  # TODO: as an arg
        key_num = max(key_num, self.phsical_key_board.used_key_num)
        self.mode = mode
        self.key_num = key_num

        if self.phsical_key_board.is_pressed():  # TODO: phsical key function
            self.mode = "debug"

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


def screen():
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

    names = ["Micro", "Key", "Board"]

    color_values = (255, 255, 255)
    height_division = tft.height // len(color_values)
    for i, color_value in enumerate(color_values):
        start_row = i * height_division
        end_row = (i + 1) * height_division
        for row in range(start_row, end_row):
            rgb_color = [0 if idx != i else int(interpolate(0, color_value, row - start_row, height_division)) for idx in range(3)]
            color = st7789.color565(rgb_color)
            tft.hline(0, row, tft.width, color)

        name = names[i]
        text_x = (tft.width - font.WIDTH * len(name)) // 2
        text_y = start_row + (end_row - start_row - font.HEIGHT) // 2
        tft.text(font, name, text_x, text_y, st7789.WHITE, color)

    return tft


def main():
    # time.sleep_ms(3000)
    # phsical_key_board = PhysicalKeyBoard()
    audio_manager = AudioManager()
    audio_manager.block_play("wav/piano/16000/C4vH.wav")
    audio_manager.play("wav/piano/16000/C4vH.wav")
    virtual_key_board = VirtualKeyBoard()
    time.sleep_ms(50)
    tft = screen()
    while True:
        virtual_key_board.scan()
        time.sleep_ms(1)
        for color in [st7789.RED, st7789.GREEN, st7789.BLUE]:
            for x in range(tft.width):
                tft.pixel(x, 0, color)
                tft.pixel(x, tft.height - 1, color)

            for y in range(tft.height):
                tft.pixel(0 , y, color)
                tft.pixel(tft.width - 1, y, color)


if __name__ == "__main__":
    main()
