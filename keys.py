import random
import time

from typing import Optional, Callable
from utils import DEBUG


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
