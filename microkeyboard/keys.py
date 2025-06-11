import random
import time

from typing import Optional, Callable
from microkeyboard.utils import debugging
from microkeyboard.led import LEDManager


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
        self.bind_physical = None  # TODO: remove this
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
        if debugging():
            print(f"virtual({self.keycode}, {self.key_name}) is pressed.")

    def default_released_function(self):
        if debugging():
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


class AbstractKey:
    """
    A real pin or a virtual pin.
    """
    def __init__(self, key_id: int, key_name: str, is_component: bool = True) -> None:
        self.key_id = key_id
        self.key_name = key_name
        self.pressed = False
        self.bind_virtual: "VirtualKey" = None  # TODO: do not bind virtual key
        self.is_component = is_component

    def bind_virtual_key(self, virtual_key: "VirtualKey"):
        self.bind_virtual = virtual_key
        virtual_key.bind_physical = self

    def unbind_virtual_key(self):
        self.bind_virtual.bind_physical = None
        self.bind_virtual = None


class PhysicalKey(AbstractKey):
    """
    A physical key on the keyboard.
    """
    def __init__(self, key_id: int, key_name: str, is_component: bool = False) -> None:
        super().__init__(key_id=key_id, key_name=key_name, is_component=is_component)
        self.led_manager: "LEDManager" = None
        # self.bind_light = None    # TODO: bind led on board
        # TODO: add used mark to avoid conflict

    def bind_led_manager(self, led_manager: "LEDManager", led_id: int):
        self.led_manager = led_manager
        self.led_id = led_id

    def default_pressed_function(self):  # TODO
        pass

    def default_released_function(self):  # TODO
        pass


class PhysicalKnob:
    """
    A physical knob on the keyboard.
    """
    def __init__(self, key_a: AbstractKey, key_b: AbstractKey):
        # TODO: bind 2 virtual keys here
        self.key_a = key_a
        self.key_b = key_b
        self.rotation = 0

        self._last_rotation = 0
        self._last_state = (None, None)

    def rotated_key(self) -> Optional[AbstractKey]:
        if self.rotation == 0:
            if self._last_rotation == 1:
                return self.key_a
            elif self._last_rotation == -1:
                return self.key_b
            return None
        elif self.rotation == 1:
            return self.key_a
        elif self.rotation == -1:
            return self.key_b

    def check_rotation(self) -> bool:
        # TODO: Eliminate jitter based on history
        last_a, last_b = self._last_state
        curr_a, curr_b = self.key_a.pressed, self.key_b.pressed
        if last_a is None or last_b is None:
            self._last_state = curr_a, curr_b
            return False
        elif last_a == curr_a and last_b == curr_b:  # not changed
            return False
        else:
            # print(f"last_a: {last_a}, last_b: {last_b}, curr_a: {curr_a}, curr_b: {curr_b}")
            self._last_rotation = self.rotation
            if curr_a == curr_b:  # released
                self.rotation = 0
            elif last_a != curr_a:  # rotation a
                self.rotation = 1
            elif last_b != curr_b:  # rotation b
                self.rotation = -1
            else:
                self._last_state = curr_a, curr_b
                return False
            self._last_state = curr_a, curr_b
            return True
