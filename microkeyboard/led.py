import neopixel

from machine import Pin

from typing import Optional, Callable, List, Dict, Tuple, Union


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
        
        self.led_power = Pin(self.led_power_pin, Pin.OUT, value=0)
        self.enabled = True
        self.led_power.value(self.enabled)

        self.pixels = neopixel.NeoPixel(Pin(self.led_data_pin, Pin.OUT), self.led_pixels, timing=1)
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

    def fill(self, color: Tuple[int]):
        self.pixels.fill(color)

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
