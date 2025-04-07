import time
import json
import random

from machine import Pin

DEBUG = True


class PhysicalKey:
    def __init__(self, key_id: int, key_name: str, max_light_level: int = 16) -> None:
        self.key_id = key_id
        self.key_name = key_name
        self.pressed = False
        self.color = (max_light_level, max_light_level, max_light_level)
        self.random_color(max_light_level)
        # TODO: add used mark to avoid conflict
    
    def random_color(self, max_light_level):
        self.color = (
            random.randint(0, max_light_level),
            random.randint(0, max_light_level),
            random.randint(0, max_light_level)
        )
        
        
class PhysicalKeyBoard:
    def __init__(
        self,
        clock_pin: int = 11,
        pl_pin: int = 12,
        ce_pin: int = 13,
        read_pin: int = 14,
        max_keys: int = 72,
        keymap_path: str = "/config/physical_keymap.json",
        max_light_level: int = 16
    ):
        self.key_pl = Pin(pl_pin, Pin.OUT, value=1)
        self.key_ce = Pin(ce_pin, Pin.OUT, value=1)
        self.key_clk = Pin(clock_pin, Pin.OUT, value=0)
        self.key_in = Pin(read_pin, Pin.IN)
        
        self.max_keys = max_keys
        self.physical_keys = [None for _ in range(max_keys)]
        # self.keymap_path = keymap_path
        self.keymap_dict = json.load(open(keymap_path))
        for key_name, key_id in self.keymap_dict.items():
            self.physical_keys[key_id] = PhysicalKey(key_id=key_id, key_name=key_name, max_light_level=max_light_level)
        
    def scan_keys(self, interval_us=1):
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
            if physical_key.pressed and not key_state:
                physical_key.pressed = False
                if DEBUG:
                    print(f"physical({physical_key.key_id}, {physical_key.key_name}) is released.")


def main():
    phsical_key_board = PhysicalKeyBoard()
    time.sleep_ms(50)
    while True:
        phsical_key_board.scan()
        time.sleep_ms(1)
    
    pass

if __name__ == "__main__":
    main()





