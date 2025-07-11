import random

from neopixel import NeoPixel
from machine import Pin
from typing import Optional, Callable, List, Dict, Tuple, Union

from microkeyboard.module.pca9555 import I2CPin, PCA9555


class CustomNeoPixel(NeoPixel):
    def __init__(self, pin, n, bpp=3, timing=(350, 900, 650, 600)):
        self.pin = pin
        self.n = n
        self.bpp = bpp
        self.buf = bytearray(n * bpp)
        self.pin.init(pin.OUT)
        # Timing arg can either be 1 for 800kHz or 0 for 400kHz,
        # or a user-specified timing ns tuple (high_0, low_0, high_1, low_1).
        self.timing = timing


class LEDManager:
    def __init__(
        self,
        led_config: Dict,
        ledmap: Optional[Dict[str, int]] = {},
        bus: Optional[List] = {},
    ):
        self.ltype = led_config.get("ltype", "neopixel")
        self.led_pixels = led_config.get("led_pixels", 68)
        self.max_light_level = led_config.get("max_light_level", 16)
        self.onstart_light_level = led_config.get("onstart_light_level", 1)
        self.led_data_pin = led_config.get("led_data_pin")
        self.led_power_pin = led_config.get("led_power_pin")
        self.ledmap = ledmap

        # Light effect:
        self.background_mode = "random"

        if isinstance(self.led_power_pin, int):
            self.led_power = Pin(self.led_power_pin, Pin.OUT, value=0)
        elif isinstance(self.led_power_pin, dict):
            # TODO: use global i2c/bus instance
            self.led_power = I2CPin(PCA9555(bus[("i2c", self.led_power_pin["sda_pin"], self.led_power_pin["scl_pin"])], address=int(self.led_power_pin["address"], 16)),self.led_power_pin["pin"], mode=I2CPin.OUT)
        else:
            self.led_power = None
            pass  # TODO

        self.enabled = False
        if self.led_power is not None:
            self.led_power.value(self.enabled)

        self.pixels = CustomNeoPixel(Pin(self.led_data_pin, Pin.OUT, value=0), self.led_pixels)
        self.pixels.fill((self.onstart_light_level, self.onstart_light_level, self.onstart_light_level))
        self.pixels.write()


    def disable(self):
        self.enabled = False
        if self.led_power is not None:
            self.led_power.value(0)

    def enable(self):
        self.enabled = True
        if self.led_power is not None:
            self.led_power.value(1)
        self.write_pixels()
    
    def switch(self):
        self.enabled = not self.enabled
        if self.led_power is not None:
            self.led_power.value(self.enabled)
        if self.enabled:
            self.write_pixels()

    def fill(self, color: Tuple[int]):
        self.pixels.fill(color)

    def clear(self):
        self.pixels.fill((0, 0, 0))
        self.pixels.write()

    def set_pixel(self, i: Union[int, str], color: Tuple[int], write: bool = False) -> bool:
        if isinstance(i, str):
            if i not in self.ledmap:
                return False
            i = self.ledmap[i]
        self.pixels[i] = tuple(min(l, self.max_light_level) for l in color)
        if write:
            self.pixels.write()
        return True

    def write_pixels(self):
        self.pixels.write()

    def random_color(self, max_light_level: Optional[int]=None):
        max_light_level = max_light_level or self.max_light_level
        color = (random.randint(0, max_light_level), random.randint(0, max_light_level), random.randint(0, max_light_level))
        return color
    
    def set_background(self, background_mode: str, max_light_level: Optional[int]=None):
        """
            random
            blank
        """
        if background_mode == "random":
            for i in range(self.led_pixels):
                self.set_pixel(i, self.random_color(max_light_level))
        elif background_mode == "blank":
            self.fill((0, 0, 0))
        else:
            raise NotImplementedError(f"background mode: {background_mode}")
        self.background_mode = background_mode
        self.write_pixels()

    def next_background(self):
        if self.background_mode == "random":
            self.set_background("blank")
        elif self.background_mode == "blank":
            self.set_background("random")
        else:
            raise NotImplementedError(f"background mode: {self.background_mode}")

    def default_color(self, max_light_level: Optional[int]=None):
        if self.background_mode == "random":
            return self.random_color(max_light_level=max_light_level)
        return (0, 0, 0)


if __name__ == "__main__":
    import time
    led_config = {
        "led_pixels": 71,
        "led_data_pin": 47,
        "led_power_pin": 48
    }
    led_manager = LEDManager(led_config)
    led_manager.disable()
    time.sleep(1)
    led_manager.fill((16, 0, 0))
    led_manager.enable()
    time.sleep(1)
