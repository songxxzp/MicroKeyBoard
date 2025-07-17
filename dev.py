import os
import time
import json
import random
import gc
import machine
import micropython

from machine import Timer
from typing import List, Dict, Optional, Callable, Tuple, Union

from microkeyboard.devices import GLOBAL_DEIVCE_MANAGER
from microkeyboard.audio import AudioManager, Sampler, MIDIPlayer, midinumber_to_note, note_to_midinumber
from microkeyboard.utils import partial, exists, makedirs, check_disk_space, debug_switch, debugging
from microkeyboard.keyboards.virtualkeyboards import VirtualKeyBoard, MusicKeyBoard
from microkeyboard.keyboards.led import LEDManager
from microkeyboard.module.pca9555 import PCA9555
from microkeyboard.screen import ScreenManager


def main():
    check_disk_space()
    time.sleep_ms(1000)

    screen_manager = ScreenManager(
        config_path="/config/screen_config.json"
    )

    screen_manager.text_lines(["MicroKeyBoard", "Starting"])
    # virtual_key_board = VirtualKeyBoard(
    #     mapping_path="/config/virtual_keymaps.json",
    #     key_config_path="/config/physical_keyboard.json"
    # )

    virtual_key_board = MusicKeyBoard(
        music_mapping_path="/config/music_keymap.json",
        mode = "F Major"
    )

    gpio_expander: PCA9555 = GLOBAL_DEIVCE_MANAGER.get_device("ex_gpio") 
    gpio_expander.digital_write(0, 1)
    gpio_expander.digital_write(1, 1)
    gpio_expander.set_pin_mode(0, 0)
    gpio_expander.set_pin_mode(1, 0)

    gpio_expander.set_pin_mode(5, 1)

    screen_manager.text_lines(["MicroKeyBoard", "Music Mode"])

    count = [0, True]
    max_scan_gap = 0
    start_time = time.ticks_ms()
    current_time = time.ticks_ms()

    # On start LED
    virtual_key_board.phsical_key_board.led_manager.enable()
    virtual_key_board.phsical_key_board.led_manager.set_background("blank")

    for i in range(virtual_key_board.phsical_key_board.led_manager.led_pixels):
        virtual_key_board.phsical_key_board.led_manager.set_pixel(i, (random.randint(0, 15), random.randint(0, 15), random.randint(0, 15)), write=True)
        time.sleep(0.02)
    time.sleep(1)
    virtual_key_board.phsical_key_board.led_manager.set_background("random")

    virtual_key_board.phsical_key_board.led_manager.disable()

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
    # play_func = partial(play_note, led_manager=virtual_key_board.phsical_key_board.led_manager, note_key_mapping=virtual_key_board.note_key_mapping)
    midi_player.time_multiplayer = 1
    virtual_key_board.bind_fn_layer_func("ENTER", pressed_function=midi_player.start)
    def stop_midi(midi_player: MIDIPlayer, led_manager: LEDManager):
        midi_player.stop()
        led_manager.clear()
    virtual_key_board.bind_fn_layer_func("BACKSPACE", pressed_function=partial(stop_midi, midi_player, virtual_key_board.phsical_key_board.led_manager))
    virtual_key_board.bind_fn_layer_func("OPEN_BRACKET", pressed_function=partial(machine.freq, 80000000))
    virtual_key_board.bind_fn_layer_func("CLOSE_BRACKET", pressed_function=partial(machine.freq, 240000000))
    # TODO: only use for keyboard with int
    virtual_key_board.bind_fn_layer_func("DELETE", released_function=virtual_key_board.phsical_key_board.sleep)
    virtual_key_board.bind_fn_layer_func("Z", pressed_function=screen_manager.stop_animate)
    virtual_key_board.bind_fn_layer_func("X", pressed_function=screen_manager.prepare_animate)
    virtual_key_board.bind_fn_layer_func("C", pressed_function=screen_manager.pause_animate)

    virtual_key_board.bind_fn_layer_func("P", pressed_function=debug_switch)

    screen_manager.prepare_animate()
    texts = ["MicroKeyboard", "Piano Mode", getattr(virtual_key_board, "mode", "")]

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

    # scan_timer.init(mode=Timer.PERIODIC, freq=128, callback=scan_callback)
    debug_switch(True)
    virtual_key_board.scan(activate=True)

    while True:
        scan_start_us = time.ticks_us()
        # midi_player.play(play_func)
        screen_manager.step_animate(texts=texts)
        scan()
        # micropython.schedule(scan, None)

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

