import os
import time
import json
import random
import neopixel
import usb.device
import gc
import framebuf
import machine
from ulab import numpy as np
import micropython

from typing import List, Dict, Optional, Callable, Tuple, Union
from machine import Pin, I2S, SPI, SoftSPI

from st7789py import ST7789, color565
import vga2_bold_16x32 as font

from audio import AudioManager, Sampler, MIDIPlayer, midinumber_to_note, note_to_midinumber
from graphics import interpolate
from bluetoothkeyboard import BluetoothKeyboard
from utils import partial, exists, makedirs, check_disk_space
from utils import DEBUG
# from keys import VirtualKey, PhysicalKey
from keyboards import PhysicalKeyBoard, VirtualKeyBoard, MusicKeyBoard, LEDManager


class ScreenManager:  # TODO: global logger
    def __init__(
        self,
        config_path = "/config/screen_config.json",
    ):
        if exists(config_path):
            self.config = json.load(open(config_path))

            self.type: int = self.config.get("type", "ST7789")  # TODO: use for import driver
            physical_width: int = self.config.get("width", 135)
            physical_height: int = self.config.get("height", 240)
            rotation: int = self.config.get("rotation", 1)

            self.spi = SPI(
                2,
                baudrate=40000000,
                sck=Pin(self.config.get("sck", 1)),
                mosi=Pin(self.config.get("mosi", 2)),
                miso=None
            )  # TODO: reuse spi

            self.tft = ST7789(
                self.spi,
                physical_width,
                physical_height,
                reset=Pin(self.config.get("reset", 42), Pin.OUT),
                cs=Pin(self.config.get("cs", 40), Pin.OUT),
                dc=Pin(self.config.get("dc", 41), Pin.OUT),
                backlight=Pin(self.config.get("backlight", 39), Pin.OUT),
                rotation=rotation,
            )

            self.width = self.tft.width
            self.height = self.tft.height

            self.enabled = True
            self.prepared = False
        else:
            self.config = None
            self.tft = None
            self.enabled = False
            self.prepared = False

    def prepare_animate(self, fps: int = 8) -> bool:
        if self.tft is None:
            return False
        self.screen_buf = bytearray(self.width * self.height * 2)
        self.background_buf = bytearray(self.width * self.height * 2)
        self.fbuf = framebuf.FrameBuffer(self.screen_buf, self.width, self.height, framebuf.RGB565)
        self.bbuf = framebuf.FrameBuffer(self.background_buf, self.width, self.height, framebuf.RGB565)
        
        avtar_width = 120
        avtar_height = 135

        self.abuf_len = 8
        self.abufs = tuple([framebuf.FrameBuffer(bytearray(avtar_width * avtar_height * 2), avtar_width, avtar_height, framebuf.RGB565) for _ in range(self.abuf_len)])  # TODO: write into config

        with open("/animate565/upython-with-micro.240135.rgb565") as f:
            f.readinto(self.bbuf)
        for i in range(self.abuf_len):
            with open(f"/animate565/frame_000{i}.rgb565") as f:
                f.readinto(self.abufs[i])

        self.last_fresh_time = time.ticks_ms()
        self.next_prepared = False
        self.pause = False
        self.fps = fps
        self.frame_index = 0
        self.prepared = True
        self.enabled = True
        self.tft.backlight.value(1)

        self.fbuf.blit(self.bbuf, 0, 0, 0)
        self.tft.blit_buffer(buffer=self.screen_buf, x=0, y=0, width=self.width, height=self.height)
        return True

    def pause_animate(self, pause: bool = False):
        if self.tft is None:
            return
        self.pause = (not self.pause) or pause
        print(f"pause animate: {self.pause}")

    def step_animate(self, write: bool = True, texts: List[str] = []):
        if self.tft is None:
            return
        if not (self.enabled and self.prepared):
            return
        if self.pause:
            return

        current_time = time.ticks_ms()
        if current_time - self.last_fresh_time >= 999 // self.fps:
            if write:
                self.tft.blit_buffer(buffer=self.fbuf, x=0, y=0, width=self.width, height=self.height)
                self.last_fresh_time = current_time
                self.next_prepared = False
        elif not self.next_prepared:
            self.fbuf.blit(self.bbuf, 0, 0, 0)
            self.fbuf.blit(self.abufs[self.frame_index], 120, 0, 0)
            self.frame_index = (self.frame_index + 1) % self.abuf_len
            start_y = 135 // 2 - 10 * len(texts)
            for i, text in enumerate(texts):
                self.fbuf.text(text, (120 - 8 * len(text)) // 2, start_y + i * 10, 0)
            self.next_prepared = True
        else:
            return
    
    def stop_animate(self):
        if self.tft is None:
            return
        self.prepared = False
        self.enabled = False
        self.tft.backlight.value(0)

    def text_lines(self, lines: List[str]):
        if self.tft is None:
            return
        if self.tft is None:
            return
        tft = self.tft
        color_values = tuple([255 for _ in lines])
        height_division = tft.height // len(color_values)
        for i, color_value in enumerate(color_values):  # TODO: use rect instead of lines
            start_row = i * height_division
            end_row = (i + 1) * height_division
            for row in range(start_row, end_row):
                rgb_color = [0 if idx != i else int(interpolate(0, color_value, row - start_row, height_division)) for idx in range(3)]
                color = color565(rgb_color)

            for row in range(start_row, end_row):
                tft.hline(0, row, tft.width, color)
            name = lines[i]
            text_x = (tft.width - font.WIDTH * len(name)) // 2
            text_y = start_row + (end_row - start_row - font.HEIGHT) // 2
            tft.text(font, name, text_x, text_y, 0xFFFF, color)
        return tft


def main():
    check_disk_space()
    time.sleep_ms(1000)

    screen_manager = ScreenManager(
        config_path="/config/screen_config.json"
    )

    screen_manager.text_lines(["MicroKeyBoard", "Starting"])
    # virtual_key_board = VirtualKeyBoard()

    virtual_key_board = MusicKeyBoard(
        music_mapping_path="/config/music_keymap.json",
        mode = "F Major"
    )

    screen_manager.text_lines(["MicroKeyBoard", "Music Mode", "F Major"])

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

    def play_note(idx: int, events: List[Tuple[Union[int, float], str, bool]], led_manager: LEDManager, note_key_mapping: Dict[str, str]):
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
    midi_player.time_multiplayer = 1
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
    virtual_key_board.bind_fn_layer_func("S", pressed_function=screen_manager.stop_animate)
    virtual_key_board.bind_fn_layer_func("A", pressed_function=screen_manager.prepare_animate)
    virtual_key_board.bind_fn_layer_func("P", pressed_function=screen_manager.pause_animate)

    screen_manager.prepare_animate()
    texts = ["MicroKeyboard", "Piano Mode", getattr(virtual_key_board, "mode", "")]

    while True:
        scan_start_us = time.ticks_us()
        midi_player.play(play_func)
        screen_manager.step_animate(texts=texts)
        if count % 10 == 0:
            virtual_key_board.scan(1, activate=True)
        else:
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
            print(f"scan speed: {count}/s, gap {max_scan_gap}ms, mem_free: {gc.mem_free()}")
            count = 0
            max_scan_gap = 0
            start_time = current_time


if __name__ == "__main__":
    main()
