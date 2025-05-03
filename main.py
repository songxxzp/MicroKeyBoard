import os
import time
import json
import random
import neopixel
import usb.device
import gc
import machine
from ulab import numpy as np
import micropython

from typing import List, Dict, Optional, Callable, Tuple, Union
from machine import Pin, I2S, SPI, SoftSPI

import st7789py as st7789
import vga2_bold_16x32 as font

from audio import AudioManager, Sampler, MIDIPlayer, midinumber_to_note, note_to_midinumber
from graphics import interpolate
from bluetoothkeyboard import BluetoothKeyboard
from utils import partial, exists, makedirs, check_disk_space
from utils import DEBUG
# from keys import VirtualKey, PhysicalKey
from keyboards import PhysicalKeyBoard, VirtualKeyBoard, MusicKeyBoard, LEDManager


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
    check_disk_space()
    time.sleep_ms(1000)
    tft = st7789.ST7789(
        SPI(2, baudrate=40000000, sck=Pin(1), mosi=Pin(2), miso=None),
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
        music_mapping_path="/config/music_keymap.json",
        mode = "F Major"
    )

    time.sleep_ms(50)
    screen(tft,names=["MicroKeyBoard", "Music Mode", "F Major"])
    count = 0
    max_scan_gap = 0
    start_time = time.ticks_ms()
    current_time = time.ticks_ms()

    for i in range(virtual_key_board.phsical_key_board.led_manager.led_pixels):
        virtual_key_board.phsical_key_board.led_manager.set_pixel(i, (0, 1, 0), write=True)
        time.sleep(0.01)

    midi_player = MIDIPlayer(
        file_path="mid/fukakai - KAF - Treble - Piano.mid"
    )

    def play_note(idx: int, events: List[Tuple[int, str, bool]], led_manager: LEDManager, note_key_mapping: Dict[str, str]):
        _, note, play = events[idx]
        if note not in note_key_mapping:
            # raise NotImplementedError(f"{note} not set")
            print(f"{note} not set")
            return False
        if play:
            led_manager.set_pixel(note_key_mapping[note], (32, 24, 24))
            for next_idx in range(idx + 1, len(events)):
                _, next_note, play = events[next_idx]
                if play and next_note in note_key_mapping:
                    led_manager.set_pixel(note_key_mapping[next_note], (2, 4, 4))
                    break
            led_manager.write_pixels()
        else:
            led_manager.set_pixel(note_key_mapping[note], (1, 1, 1), write=True)
    play_func = partial(play_note, led_manager=virtual_key_board.phsical_key_board.led_manager, note_key_mapping=virtual_key_board.note_key_mapping)
    midi_player.time_multiplayer = 1 / 0.75
    virtual_key_board.bind_fn_layer_func("ENTER", pressed_function=midi_player.start)
    def stop_midi(midi_player: MIDIPlayer, led_manager: LEDManager):
        midi_player.stop()
        led_manager.clear()
    virtual_key_board.bind_fn_layer_func("BACKSPACE", pressed_function=partial(stop_midi, midi_player, virtual_key_board.phsical_key_board.led_manager))
    virtual_key_board.bind_fn_layer_func("L", pressed_function=virtual_key_board.phsical_key_board.led_manager.switch)
    virtual_key_board.bind_fn_layer_func("OPEN_BRACKET", pressed_function=partial(machine.freq, 80000000))
    virtual_key_board.bind_fn_layer_func("CLOSE_BRACKET", pressed_function=partial(machine.freq, 240000000))

    # TODO: only use for keyboard with int
    virtual_key_board.bind_fn_layer_func("DELETE", released_function=virtual_key_board.phsical_key_board.sleep)

    while True:
        scan_start_us = time.ticks_us()
        midi_player.play(play_func)
        virtual_key_board.scan(1)
        # virtual_key_board.phsical_key_board.scan(0)
        # virtual_key_board.phsical_key_board.scan_keys(0)
        # max_scan_gap = max(max_scan_gap, time.ticks_ms() - scan_start_time)
        # time.sleep_ms(1)
        count += 1
        max_scan_gap = max(max_scan_gap, time.ticks_ms() - current_time)
        current_time = time.ticks_ms()
        scan_end_us = time.ticks_us()
        time.sleep_us(min(max(990 - scan_end_us + scan_start_us, 0), 1000))  # TODO: dynamic speed

        if current_time - start_time >= 1000:
            # print(f"scan speed: {count}/s, gap {max_scan_gap}ms, mem_free: {gc.mem_free()}")
            count = 0
            max_scan_gap = 0
            start_time = current_time


if __name__ == "__main__":
    main()
