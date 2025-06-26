import os
import time
import json
import random
import gc
import machine
import micropython

from machine import Timer
from typing import List, Dict, Optional, Callable, Tuple, Union

from microkeyboard.audio import AudioManager, Sampler, MIDIPlayer, midinumber_to_note, note_to_midinumber
from microkeyboard.utils import partial, exists, makedirs, check_disk_space, debug_switch, debugging
from microkeyboard.module.pca9555 import PCA9555
from microkeyboard.keyboards.virtualkeyboards import VirtualKeyBoard, MusicKeyBoard
from microkeyboard.keyboards.led import LEDManager
from microkeyboard.screen import ScreenManager


def main():
    check_disk_space()
    time.sleep_ms(1000)
    virtual_key_board = VirtualKeyBoard(
        mapping_path="/config/virtual_keymaps",
        key_config_path="/config/physical_keyboard.json"
    )

    count = [0, True]
    max_scan_gap = 0
    start_time = time.ticks_ms()
    current_time = time.ticks_ms()

    # virtual_key_board.bind_fn_layer_func("L", pressed_function=virtual_key_board.phsical_key_board.led_manager.switch)
    # virtual_key_board.bind_fn_layer_func("N", pressed_function=virtual_key_board.phsical_key_board.led_manager.next_background)
    # virtual_key_board.bind_fn_layer_func("P", pressed_function=debug_switch)
    # virtual_key_board.bind_fn_layer_func("OPEN_BRACKET", pressed_function=partial(machine.freq, 80000000))
    # virtual_key_board.bind_fn_layer_func("CLOSE_BRACKET", pressed_function=partial(machine.freq, 240000000))

    last_print_start = time.ticks_ms()
    last_print_delay = 0

    scan_timer = Timer(0)

    def scan(t: Timer = scan_timer, virtual_key_board=virtual_key_board, count=count):
        try:
            count[0] += 1
            count[1] = True
            virtual_key_board.scan(activate=True)
        except Exception as exception:
            t.deinit()
            raise exception

    debug_switch(False)
    # machine.freq(80000000)

    virtual_key_board.phsical_key_board.led_manager.enable()
    virtual_key_board.phsical_key_board.led_manager.set_background("blank")

    for i in range(virtual_key_board.phsical_key_board.led_manager.led_pixels):
        virtual_key_board.phsical_key_board.led_manager.set_pixel(i, (random.randint(0, 15), random.randint(0, 15), random.randint(0, 15)), write=True)
        time.sleep(0.02)
        # virtual_key_board.phsical_key_board.led_manager.set_pixel(i, (0, 0, 0), write=True)
    time.sleep(1)
    virtual_key_board.phsical_key_board.led_manager.set_background("random")

    virtual_key_board.phsical_key_board.led_manager.disable()

    virtual_key_board.scan(activate=True)

    while True:
        scan_start_us = time.ticks_us()
        scan()

        max_scan_gap = max(max_scan_gap, time.ticks_ms() - current_time)
        current_time = time.ticks_ms()
        scan_end_us = time.ticks_us()
        time.sleep_us(min(max(990 * 8 - scan_end_us + scan_start_us, 0), 990 * 8))  # TODO: dynamic speed

        if debugging() and current_time - start_time >= 1000:
            last_print_start = time.ticks_ms()
            print(f"{count[0]}/s, gap: {max_scan_gap}ms, mem: {gc.mem_free()}, prt: {last_print_delay}ms")
            count[0] = 0
            max_scan_gap = 0
            current_time = time.ticks_ms()
            last_print_delay = current_time - last_print_start
            start_time = current_time


if __name__ == "__main__":
    main()

