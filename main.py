import os
import time
import json
import random
import gc
import framebuf
import machine

from typing import List, Dict, Optional, Callable, Tuple, Union
from machine import Pin, I2S, SPI, SoftSPI, UART

from st7789py import ST7789, color565
import vga2_bold_16x32 as font

from microkeyboard.audio import AudioManager, Sampler, MIDIPlayer, midinumber_to_note, note_to_midinumber
from microkeyboard.graphics import interpolate
from microkeyboard.utils import partial, exists, makedirs, check_disk_space, debug_switch, debugging
from microkeyboard.keyboards import PhysicalKeyBoard, VirtualKeyBoard, MusicKeyBoard, LEDManager


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
        if not self.enabled:
            return
        tft = self.tft
        height_division = 32
        for i, name in enumerate(lines):  # TODO: use rect instead of lines
            if name is not None:
                name = name + " " * max(0, 16 - len(name))
                start_row = i * height_division
                end_row = (i + 1) * height_division

                text_x = 0
                text_y = start_row + (end_row - start_row - font.HEIGHT) // 2
                tft.text(font, name, text_x, text_y, 0xFFFF, 0x0000)
        return tft


class AIManager:
    def __init__(self):
        self.uart = UART(1, baudrate=115200, tx=17, rx=18)
        self.cli_buffer = ""

    def send(self, text: str, enter: bool = True):
        if enter:
            self.uart.write(text.encode('utf-8') + b'\r\n')
        else:
            self.uart.write(text.encode('utf-8'))

    def read(self, lenth: int = 1024):
        reply_data = self.uart.read(lenth)
        if reply_data is None:
            reply_str = ""
        else:
            reply_str = reply_data.decode()
        # print(reply_str)
        self.cli_buffer += reply_str
        if len(self.cli_buffer) > 1023:
            self.cli_buffer = self.cli_buffer[-512:]
        return reply_str

    def tty(self):
        print("ENTER UART TTY:")
        while True:
            # time.sleep(0.2)
            # print(">>> ", end="")
            # time.sleep(0.2)
            try:
                command = input()
            except KeyboardInterrupt:
                # TODO: send Ctrl-C
                print("Use `exit` to exit.")
            if command == "exit" or command == "@exit":
                break
            if command == "@show":
                self.read(1024)
                print(self.cli_buffer)
                continue
            self.send(command)
            last_reply_str = ">>> "
            for _ in range(10):
                time.sleep(0.5)
                reply_str = self.read(2048)
                print(reply_str, end="")
                if last_reply_str == "" and reply_str == "":
                    break
                last_reply_str = reply_str
            print()
        print("EXIT UART TTY:")

    def start_program(self):
        # wait for boot:
        last_reply_str = ""
        flag = False
        print("Waiting for login. If already logined, Ctrl-C to skip.")
        try:
            for _ in range(30):
                time.sleep(3)
                reply_str = self.read(1024)
                print(reply_str)
                last_reply_str = last_reply_str[-128:] + reply_str
                if last_reply_str == "":  # already logined
                    break
                if last_reply_str.endswith("login: "):
                    flag = True
                    break
        except KeyboardInterrupt:
            return

        if not flag:
            print("Connection failed or already logined.")
            return

        commands_list = [
            "debian",  # username
            "rv",  # password
            "su",  # change to root
            "rv",  # password
            "cd /home/debian/workspace/cvi_klm && python inference_serve.py 2>/dev/null",
            # "source /home/debian/envs/base/bin/activate"
            # "LD_LIBRARY_PATH=/home/debian/workspace/cvitek_tpu_sdk/lib python3 inference_serve.py",
        ]

        # login
        for command in commands_list:
            time.sleep(0.5)
            self.send(command)
            time.sleep(2)
            print(self.read(4096))
        
        print("Waiting for start")
        flag = False
        for _ in range(90):
            time.sleep(3)
            reply_str = self.read(4096)
            print(reply_str)
            last_reply_str = last_reply_str[-128:] + reply_str
            if "## READY ##" in last_reply_str:
                flag = True
                break
        if not flag:
            print("Prediction start failed")
        print(self.read(4096))

    def ai_clear(self):
        self.send("@clear", enter=True)

    def predict(self, prefix: str, screen_manager: ScreenManager, accept=True) -> str:
        if accept:
            print("In predict")
        self.send("@pred", enter=True)
        # prefix = ""
        time.sleep(2)
        reply = self.read(1024)
        print(f"self.cli_buffer: {self.cli_buffer}")
        if accept:
            print(f"direct reply: {reply}")
        pred = self.cli_buffer.strip().split('\n')[-1].strip()
        print(f"pred: {pred}")
        screen_manager.text_lines([None, None, f"Pred: {pred}"])
        if accept:
            self.send("@accept", enter=True)
            reply = self.read(1024)
        return pred

def main():
    check_disk_space()
    time.sleep_ms(1000)

    ai_manager = AIManager()

    screen_manager = ScreenManager(
        config_path="/config/screen_config.json"
    )

    screen_manager.text_lines(["MicroKeyBoard", "Starting"])
    # virtual_key_board = VirtualKeyBoard()

    virtual_key_board = MusicKeyBoard(
        music_mapping_path="fake",
        mode = "F Major"
    )

    screen_manager.text_lines(["MicroKeyBoard", "AI Mode"])

    count = 0
    max_scan_gap = 0
    start_time = time.ticks_ms()
    current_time = time.ticks_ms()

    for i in range(virtual_key_board.phsical_key_board.led_manager.led_pixels):
        virtual_key_board.phsical_key_board.led_manager.set_pixel(i, (0, 0, 0))
        virtual_key_board.phsical_key_board.led_manager.write_pixels()

    for i in range(virtual_key_board.phsical_key_board.led_manager.led_pixels):
        virtual_key_board.phsical_key_board.led_manager.set_pixel(i, (1, 1, 1), write=True)
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
    virtual_key_board.bind_fn_layer_func("D", pressed_function=screen_manager.pause_animate)

    virtual_key_board.bind_fn_layer_func("P", pressed_function=debug_switch)

    # screen_manager.prepare_animate()
    # texts = ["MicroKeyboard", "Piano Mode", getattr(virtual_key_board, "mode", "")]


    ai_manager.start_program()
    # ai_manager.tty()

    last_pressed_key_names = []
    current_string = ""
    send_string = ""

    virtual_key_board.bind_fn_layer_func("AUDIO_CALL", layer_id=0, pressed_function=partial(ai_manager.predict, prefix=send_string, screen_manager=screen_manager))
    virtual_key_board.bind_fn_layer_func("AUDIO_CALL", layer_id=1, pressed_function=partial(ai_manager.tty))

    white_list_char = "ABCDEFGHIJKLMNOPQRSTUVWXYZ".lower()
    white_list_sign = " ,.?;:'\\|[]{}()_-+=1234567890!@#$%^&*()\""
    white_list_char += white_list_sign

    screen_manager.tft.fill(0x0000)
    screen_manager.text_lines(["Pres: ", "Pref: ", ""])
    key_name_mapping = {
        "SPACE": " ",
        "N0": "0",
        "N1": "1",
        "N2": "2",
        "N3": "3",
        "N4": "4",
        "N5": "5",
        "N6": "6",
        "N7": "7",
        "N8": "8",
        "N9": "9",
        "COMMA": ",",
        "DOT": ".",
        "MINUS": "-",
        "EQUAL": "=",
    }
    
    last_print_start = time.ticks_ms()
    last_print_delay = 0

    while True:
        scan_start_us = time.ticks_us()
        midi_player.play(play_func)
        # screen_manager.step_animate(texts=texts)
        if count % 8 == 0:
            pressed_key_names = virtual_key_board.scan(1, activate=True, return_pressed=True)
        else:
            pressed_key_names = virtual_key_board.scan(1, return_pressed=True)
        # if count % 128 == 0:
        #     ai_manager.predict("", screen_manager, accept=False)

        if pressed_key_names is not None:
            change_flag = False
            clean_pred_flag = False
            show_pressed_names = ""
            new_string = ""
            # pressed
            for key_name in pressed_key_names:
                show_key_name = key_name_mapping[key_name] if key_name in key_name_mapping else key_name.lower()
                show_pressed_names += show_key_name
                if key_name not in last_pressed_key_names:
                    change_flag = True
                    if show_key_name in white_list_char:
                        clean_pred_flag = True
                        new_string += show_key_name
            # released
            for key_name in last_pressed_key_names:
                if key_name not in pressed_key_names:
                    change_flag = True
            # update
            if change_flag:
                current_string = current_string + new_string
                send_string += new_string
                current_string = current_string[-8:]
                if clean_pred_flag:
                    screen_manager.text_lines(["Pres: " + show_pressed_names, "Pref: " + current_string, ""])
                else:
                    screen_manager.text_lines(["Pres: " + show_pressed_names, "Pref: " + current_string])
                print("Pres: " + show_pressed_names + "\nPref: " + current_string)
                last_pressed_key_names = pressed_key_names

                # send prefix to tpu using uart
                for c in new_string:
                    ai_manager.send(f"#{c}", enter=True)
                # predict_str = ai_manager.predict(send_string)
                # send_string = ""

        # virtual_key_board.phsical_key_board.scan(0)
        # virtual_key_board.phsical_key_board.scan_keys(0)
        # max_scan_gap = max(max_scan_gap, time.ticks_ms() - scan_start_time)
        # time.sleep_ms(1)
        count += 1
        max_scan_gap = max(max_scan_gap, time.ticks_ms() - current_time)
        current_time = time.ticks_ms()
        scan_end_us = time.ticks_us()
        time.sleep_us(min(max(990 - scan_end_us + scan_start_us, 0), 990))  # TODO: dynamic speed

        if debugging() and current_time - start_time >= 1000:
            last_print_start = time.ticks_ms()
            print(f"{count}/s, gap: {max_scan_gap}ms, mem: {gc.mem_free()}, prt: {last_print_delay}ms")
            count = 0
            max_scan_gap = 0
            current_time = time.ticks_ms()
            last_print_delay = current_time - last_print_start
            start_time = current_time


if __name__ == "__main__":
    main()
