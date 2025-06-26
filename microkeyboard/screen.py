import framebuf
import json
import time

from typing import List, Dict, Optional, Callable, Tuple, Union
from machine import Pin, SPI, SoftSPI

from st7789py import ST7789, color565
import vga2_bold_16x32 as font

from microkeyboard.graphics import interpolate
from microkeyboard.utils import partial, exists, makedirs, check_disk_space, debug_switch, debugging


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
        self.tft.sleep_mode(False)
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
        self.tft.sleep_mode(True)

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
