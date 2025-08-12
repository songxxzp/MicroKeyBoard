import gc
import usb
import json

from typing import Optional, Callable, List, Dict, Tuple, Union, Iterator
from usb.device.keyboard import KeyboardInterface, LEDCode

from microkeyboard.utils import debugging, debug_switch, partial, exists, makedirs
from microkeyboard.bluetoothkeyboard import BluetoothKeyboard
from microkeyboard.audio import Sampler, AudioManager
from microkeyboard.keyboards.keys import VirtualKey
from microkeyboard.keyboards.keycodes import KeyCode
from microkeyboard.keyboards.physicalkeyboards import TCA8418KeyBoard, PCA9555KeyBoard, PhysicalKeyBoard, PhysicalKeyBoards, ShiftRegisterKeyBoard


def fn_layer_pressed_function(
    virtual_key_board: "VirtualKeyBoard",
    virtual_key: "VirtualKey",
    layer_codes: Optional[Tuple[str]] = None,
    pressed_function: Optional[Callable] = None,
    original_func: Optional[Callable] = None,
    layer_id: int = 1,
):
    if virtual_key_board.layer == int(layer_id):
        if layer_codes is not None:
            virtual_key.keycode = layer_codes[1]
        if pressed_function is not None:
            pressed_function()
    elif original_func is not None:
        original_func()


def fn_layer_released_function(
    virtual_key_board: "VirtualKeyBoard",
    virtual_key: "VirtualKey",
    layer_codes: Optional[Tuple[str]] = None,
    released_function: Optional[Callable] = None,
    original_func: Optional[Callable] = None,
    layer_id: int = 1,
):
    if layer_codes is not None:
        virtual_key.keycode = layer_codes[0]
    if virtual_key_board.layer == int(layer_id):
        if released_function is not None:
            released_function()
    elif original_func is not None:
        original_func()


class VirtualKeyBoard:

    phsical_key_board: PhysicalKeyBoard = None
    virtual_keys: List[VirtualKey] = None
    
    def __init__(
        self,
        connection_mode: str = "bluetooth",
        mapping_path: str = "/config/virtual_keymaps.json",
        key_config_path: str = "/config/physical_keyboard.json",
        user_config_path: str = "/user.json",
    ):
        # assert key_num >= self.phsical_key_board.used_key_num, "virt key num < phys key num."
        self.user_config_path = user_config_path
        self.mapping_path = mapping_path

        if exists(mapping_path):
            if mapping_path.endswith("json"):
                self.virtual_key_mappings = json.load(open(mapping_path))
                self.virtual_key_name = self.virtual_key_mappings.get("name", "MicroKeyBoard")
            else:
                if exists(user_config_path):
                    user_config = json.load(open(user_config_path))
                    user_system = user_config["system"]
                else:
                    user_system = "win"
                if exists(f"{mapping_path}/{user_system}.json"):
                    self.virtual_key_mappings = json.load(open(f"{mapping_path}/{user_system}.json"))
                    self.virtual_key_name = self.virtual_key_mappings.get("name", "MicroKeyBoard")
                else:
                    print(f"{mapping_path}/{user_system}.json not found.")
                    self.virtual_key_mappings = None
                    self.virtual_key_name = "MicroKeyBoard"
        else:
            print(f"{mapping_path} not found.")
            self.virtual_key_mappings = None
            self.virtual_key_name = "MicroKeyBoard"
        phsical_key_config = json.load(open(key_config_path))
        ktype = phsical_key_config.get("ktype", None)  # TODO: get from phsical keyboard
        if ktype == "tca8418":
            self.phsical_key_board = TCA8418KeyBoard(key_config=phsical_key_config, virtual_keyboard=self)  # TODO: as an arg
        elif ktype == "pca9555":
            self.phsical_key_board = PCA9555KeyBoard(key_config=phsical_key_config, virtual_keyboard=self)
        elif ktype == "mixture":  # TODO: rename
            self.phsical_key_board = PhysicalKeyBoards(key_config=phsical_key_config, virtual_keyboard=self)
        elif ktype == "74hc165":
            self.phsical_key_board = ShiftRegisterKeyBoard(key_config=phsical_key_config, virtual_keyboard=self)  # TODO: as an arg
        else:
            raise NotImplementedError(f"Not implemented ktype: {ktype}")

        self.key_num = self.phsical_key_board.used_key_num

        # editable keyboard state
        self.connection_mode = None
        self.layer = 0

        if self.phsical_key_board.is_pressed():  # TODO: phsical key function
            connection_mode = "debug"

        self.connection_mode = None
        self.ble_interface = None
        self.set_connection_mode(connection_mode)

        self.pressed_keys: List[VirtualKey] = []
        self.keystates = []
        self.prev_keystates = []

        # self.virtual_keys: List[VirtualKey] = None
        self.build_virtual_keys()

    def switch_user_system(self, user_system: str):
        print(f"setting user_system: {user_system}")
        assert user_system in ("mac", "win")
        if exists(self.user_config_path):
            user_config = json.load(open(self.user_config_path))
            user_config["system"] = user_system
        else:
            user_config = {
                "system": user_system
            }

        with open(self.user_config_path, "w") as f:
            json.dump(user_config, f)

        if exists(f"{self.mapping_path}/{user_system}.json"):
            self.virtual_key_mappings = json.load(open(f"{self.mapping_path}/{user_system}.json"))
            self.virtual_key_name = self.virtual_key_mappings.get("name", "MicroKeyBoard")
        else:
            print(f"{self.mapping_path}/{user_system}.json not found.")
            self.virtual_key_mappings = None
            self.virtual_key_name = "MicroKeyBoard"

        self.build_virtual_keys()

        # if self.connection_mode == "bluetooth":
        #     self.ble_interface.stop()
        #     self.ble_interface.device_name = self.virtual_key_name
        #     self.ble_interface.start()

        gc.collect()

    def set_mac_mode(self):
        self.switch_user_system("mac")

    def set_win_mode(self):
        self.switch_user_system("win")

    def set_connection_mode(self, connection_mode: str):
        if connection_mode == self.connection_mode:
            return

        if self.connection_mode == "usb_hid":
            pass
        elif self.connection_mode == "bluetooth":
            if self.ble_interface is not None:
                self.ble_interface.stop()

        self.connection_mode = connection_mode
        if self.connection_mode == "usb_hid":
            print("swiching to usb mode")
            # TODO: USBKeyBoard class
            self.usb_interface = KeyboardInterface()  # wrap interface
            self.usb_device = usb.device.get()
            self.usb_device.init(self.usb_interface, builtin_driver=True)
            self.interface = self.usb_interface
        elif self.connection_mode == "bluetooth":
            print("swiching to ble mode")
            if self.ble_interface is None:
                self.ble_interface = BluetoothKeyboard(
                    device_name=self.virtual_key_name
                )
            self.ble_interface.start()
            self.interface = self.ble_interface
        elif self.connection_mode == "debug":
            # TODO: DebugKeyBoard class
            debug_switch(True)
            self.interface = None
            print("Enabled DEBUG MODE")
        else:
            raise NotImplementedError(f"connection mode {self.connection_mode} not implemented.")

    def build_virtual_keys(self):
        virtual_keys: List[VirtualKey] = []
        for physical_key in self.phsical_key_board.key_iter():
            if physical_key is not None:
                key_code_name = physical_key.key_name
                if self.virtual_key_mappings is not None:
                    key_code_name = self.virtual_key_mappings["layers"]["0"].get(physical_key.key_name, None) or key_code_name
                virtual_key = VirtualKey(
                    key_name=key_code_name,
                    keycode=getattr(KeyCode, key_code_name, None),
                    physical_key=physical_key,
                    pressed_function=None,
                    released_function=None
                )
                virtual_keys.append(virtual_key)
        self.virtual_keys = virtual_keys
        self.build_fn_layer(virtual_keys)

    def build_fn_layer(self, virtual_keys: List[VirtualKey]):
        for layer_id in self.virtual_key_mappings["layers"]:  # TODO: check conflict
            for virtual_key in virtual_keys:
                physical_key = virtual_key.bind_physical
                layer_i_code_name = self.virtual_key_mappings["layers"][layer_id].get(physical_key.key_name, None)
                layer_codes = (virtual_key.keycode, getattr(KeyCode, layer_i_code_name, None) if layer_i_code_name is not None else None)

                if self.virtual_key_mappings is not None and physical_key.key_name in self.virtual_key_mappings["layers"][layer_id]:
                    # Check if subclass wants to handle this key differently
                    if not self._pre_process_layer_mapping(virtual_key, physical_key, int(layer_id), layer_i_code_name):
                        # Normal keycode mapping
                        virtual_key.pressed_function = partial(fn_layer_pressed_function, self, virtual_key, layer_codes, virtual_key.pressed_function, original_func=virtual_key.pressed_function, layer_id=int(layer_id))
                        virtual_key.released_function = partial(fn_layer_released_function, self, virtual_key, layer_codes, virtual_key.released_function, original_func=virtual_key.released_function, layer_id=int(layer_id))
                    # else virtual_key.pressed_function & virtual_key.released_function is handled by self._pre_process_layer_mapping.

        # Handle special keys
        self._handle_special_keys(virtual_keys)

    def _pre_process_layer_mapping(self, virtual_key: VirtualKey, physical_key, layer_id: int, layer_i_code_name: str):
        """Override this in subclasses to handle specific layer mappings differently.
        Return True if handled, False to use default behavior."""

        if layer_i_code_name == f"FN{layer_id + 1}":  # if layer_id == 1 and layer_i_code_name == "FN2":
            def fn_pressed_function(virtual_key_board: "VirtualKeyBoard"):
                print("change to layer 2")
                virtual_key_board.layer = 2
            def fn_released_function(virtual_key_board: "VirtualKeyBoard"):
                print("change to layer 0")
                virtual_key_board.layer = 0  # TODO: change to last layer

            layer_codes = (virtual_key.keycode, None)

            virtual_key.pressed_function = partial(fn_layer_pressed_function, self, virtual_key, layer_codes, partial(fn_pressed_function, self), original_func=virtual_key.pressed_function, layer_id=int(layer_id))
            virtual_key.released_function = partial(fn_layer_released_function, self, virtual_key, layer_codes, partial(fn_released_function, self), original_func=virtual_key.released_function, layer_id=int(layer_id))
            # virtual_key.pressed_function = partial(fn_pressed_function, self)
            # virtual_key.released_function = partial(fn_released_function, self)
            return True
        return False

    def _handle_special_keys(self, virtual_keys: List[VirtualKey]):
        """Handle special keys that need custom behavior."""
        # Handle special keys (FN, FN2, Q, W, E, R, L, N, P, A, S)
        for virtual_key in virtual_keys:
            physical_key = virtual_key.bind_physical
            if physical_key.key_name == "FN":  # TODO: create ".py" file or build from file. Or use Function Mark in keymaps.
                def fn_pressed_function(virtual_key_board: "VirtualKeyBoard"):
                    print("change to layer 1")
                    virtual_key_board.layer = 1
                def fn_released_function(virtual_key_board: "VirtualKeyBoard"):
                    print("change to layer 0")
                    virtual_key_board.layer = 0
                virtual_key.pressed_function = partial(fn_pressed_function, self)
                virtual_key.released_function = partial(fn_released_function, self)
            elif physical_key.key_name == "FN2":
                def fn_pressed_function(virtual_key_board: "VirtualKeyBoard"):
                    print("change to layer 2")
                    virtual_key_board.layer = 2
                def fn_released_function(virtual_key_board: "VirtualKeyBoard"):
                    print("change to layer 0")
                    virtual_key_board.layer = 0  # TODO: change to last layer
                virtual_key.pressed_function = partial(fn_pressed_function, self)
                virtual_key.released_function = partial(fn_released_function, self)
            elif physical_key.key_name == "Q":
                def ble_pressed_function(virtual_key_board: "VirtualKeyBoard", original_func: Callable = None):
                    if virtual_key_board.layer == 1:
                        virtual_key_board.set_connection_mode("bluetooth")
                    elif original_func:
                        original_func()
                virtual_key.pressed_function = partial(ble_pressed_function, self, virtual_key.pressed_function)
            elif physical_key.key_name == "W":
                def usb_pressed_function(virtual_key_board: "VirtualKeyBoard", original_func: Callable = None):
                    if virtual_key_board.layer == 1:
                        virtual_key_board.set_connection_mode("usb_hid")
                    elif original_func:
                        original_func()
                virtual_key.pressed_function = partial(usb_pressed_function, self, virtual_key.pressed_function)
            elif physical_key.key_name == "E":
                def debug_pressed_function(virtual_key_board: "VirtualKeyBoard", original_func: Callable = None):
                    if virtual_key_board.layer == 1:
                        virtual_key_board.set_connection_mode("debug")
                    elif original_func:
                        original_func()
                virtual_key.pressed_function = partial(debug_pressed_function, self, virtual_key.pressed_function)
            elif physical_key.key_name == "R":
                def clear_ble_pressed_function(virtual_key_board: "VirtualKeyBoard", original_func: Callable = None):
                    if virtual_key_board.layer == 1:
                        if self.ble_interface:
                            self.ble_interface.clear_paired_devices()
                    elif original_func:
                        original_func()
                virtual_key.pressed_function = partial(clear_ble_pressed_function, self, virtual_key.pressed_function)

        self.bind_fn_layer_func("L", pressed_function=self.phsical_key_board.led_manager.switch)
        self.bind_fn_layer_func("N", pressed_function=self.phsical_key_board.led_manager.next_background)
        self.bind_fn_layer_func("P", pressed_function=debug_switch)
        self.bind_fn_layer_func("A", pressed_function=self.set_win_mode)
        self.bind_fn_layer_func("S", pressed_function=self.set_mac_mode)

    def bind_fn_layer_func(self, key_name: str, layer_id: int = 1, pressed_function: Optional[Callable] = None, released_function: Optional[Callable] = None):
        for virtual_key in self.virtual_keys:
            physical_key = virtual_key.bind_physical
            layer_i_code_name = self.virtual_key_mappings["layers"][str(layer_id)].get(physical_key.key_name, None)
            layer_codes = (virtual_key.keycode, getattr(KeyCode, layer_i_code_name, None) if layer_i_code_name is not None else None)
            if physical_key.key_name == key_name:  # TODO: build a mapping dict
                virtual_key.pressed_function = partial(fn_layer_pressed_function, self, virtual_key, layer_codes, pressed_function, virtual_key.pressed_function, layer_id=layer_id)
                virtual_key.released_function = partial(fn_layer_released_function, self, virtual_key, layer_codes, released_function, virtual_key.released_function, layer_id=layer_id)

    def scan(self, activate: bool = False) -> bool:
        if self.phsical_key_board is None or (not self.phsical_key_board.scan(activate=activate)):
            return False

        self.keystates.clear()
        self.pressed_keys.clear()
        virtual_keys = self.virtual_keys
        for virtual_key in virtual_keys:
            if virtual_key.pressed and virtual_key.keycode is not None:
                self.pressed_keys.append(virtual_key)

        self.pressed_keys.sort(key=lambda k:k.press_time, reverse=True)
        self.keystates = [k.keycode for k in self.pressed_keys[:6]]  # TODO: Don't use list.
        if self.keystates != self.prev_keystates:
            self.prev_keystates.clear()
            self.prev_keystates.extend(self.keystates)
            if debugging():
                print(self.keystates)
            if self.interface is not None:
                self.interface.send_keys(self.keystates)
        return True


class MusicKeyBoard(VirtualKeyBoard):
    def __init__(self, 
        music_mapping_path: str,
        audio_manager: Optional[AudioManager] = None,
        mode: str = "C Major",
        note_wav_path: str = "/wav/piano/16000_2s",
        note_cache_path: Optional[str] = None,
        key_config_path: str = "/config/physical_keyboard.json",
        *args,
        **kwargs
    ):
        if exists(music_mapping_path) and exists(key_config_path):
            self.music_enabled = True
            self.music_mapping_path = music_mapping_path
            self.sampler = Sampler(note_wav_path)  # TODO: add wav_data_start, add audio source config.
            self.music_mappings = json.load(open(self.music_mapping_path))
            self.mode = mode
            self.music_mapping = self.music_mappings[mode]

            # Define the circle of fifths order for scale cycling
            self.scale_order = ['C Major', 'G Major', 'D Major', 'A Major', 'E Major', 'B Major', 'F Major']
            # Filter to only include scales that exist in the music mappings
            self.available_scales = [scale for scale in self.scale_order if scale in self.music_mappings]
            self.current_scale_index = self.available_scales.index(mode) if mode in self.available_scales else 0

            key_config = json.load(open(key_config_path))
            sck_pin, ws_pin, sd_pin, en_pin = 48, 47, 45, 38
            if "i2s" in key_config:
                sck_pin = key_config["i2s"].get("sck_pin", None)
                ws_pin = key_config["i2s"].get("ws_pin", None)
                sd_pin = key_config["i2s"].get("sd_pin", None)
                en_pin = key_config["i2s"].get("en_pin", None)

            if audio_manager is None:
                audio_manager = AudioManager(
                    rate=16000,
                    buffer_samples=1024,
                    i2s_buf_samples=2048,
                    always_play=True,
                    sck_pin=sck_pin,
                    ws_pin=ws_pin,
                    sd_pin=sd_pin,
                    en_pin=en_pin,
                    volume_factor=-3
                )

            self.audio_manager = audio_manager

            self.note_key_mapping = {}
            self.note_cache_path = note_cache_path

            if note_cache_path is not None and not exists(note_cache_path):
                makedirs(note_cache_path)
            self._load_mode_notes(self.music_mapping)
        else:
            self.music_enabled = False
            self.music_mapping_path = None
            self.audio_manager = None
            self.music_mapping = {}
            self.note_key_mapping = {}
            self.available_scales = []
            self.current_scale_index = 0

        # Setup function registry after initialization
        self.setup_function_registry()
        
        super().__init__(*args, key_config_path=key_config_path, **kwargs)

    def _load_mode_notes(self, mapping: Dict[str, str]):
        """Load all notes for a given mode mapping."""
        for i, note in enumerate(sorted(list(mapping.values()), key=lambda n: n[-1])):
            if not self.audio_manager.have_wav(note):
                print(f"Loading {i} th note: {note}, alloc: {gc.mem_alloc()}, free: {gc.mem_free()}")
                if self.note_cache_path is not None:
                    if exists(f"{self.note_cache_path}/{note}"):
                        wav_data = open(f"{self.note_cache_path}/{note}", "rb").read()
                    else:
                        wav_data = self.sampler.get_sample(note, duration=1.8)
                        with open(f"{self.note_cache_path}/{note}", "wb") as f:
                            f.write(wav_data)
                else:
                    wav_data = self.sampler.get_sample(note, duration=1.8)
                self.audio_manager.load_wav(note, wav_data)
                gc.collect()

    def enable_switch(self):
        if self.music_enabled:
            if self.audio_manager.is_playing():
                self.audio_manager.stop_all()
            # self.audio_manager.disable_irq()
            self.music_enabled = False
        else:
            # self.audio_manager.enable_irq()
            if self.audio_manager is not None:
                self.music_enabled = True

    def _pre_process_layer_mapping(self, virtual_key: VirtualKey, physical_key, layer_id: int, layer_i_code_name: str):
        """Handle function registry mappings for music keyboard."""
        # Only process function registry on layer 1 (Fn layer)
        if super()._pre_process_layer_mapping(virtual_key, physical_key, layer_id, layer_i_code_name):
            return True

        if layer_id != 2:
            return False

        # Check if this is a function call (defined in function_registry)
        if (self.virtual_key_mappings and 'function_registry' in self.virtual_key_mappings and layer_i_code_name in self.virtual_key_mappings['function_registry']):
            # Get the function name from the registry
            press_func_name, release_func_name = self.virtual_key_mappings['function_registry'][layer_i_code_name]
            # print(f"_pre_process_layer_mapping: {virtual_key.key_name}, {press_func_name}, {release_func_name}")
            # Only handle if we have this function in our registry AND music is enabled
            if hasattr(self, 'function_registry'):
                layer_codes = (virtual_key.keycode, None)  # No keycode change for function calls
                
                press_func = self.function_registry[press_func_name] if (press_func_name and press_func_name in self.function_registry) else None
                release_func = self.function_registry[release_func_name] if (release_func_name and release_func_name in self.function_registry) else None

                virtual_key.pressed_function = partial(fn_layer_pressed_function, self, virtual_key, layer_codes, press_func, original_func=virtual_key.pressed_function, layer_id=int(layer_id))
                virtual_key.released_function = partial(fn_layer_released_function, self, virtual_key, layer_codes, release_func, original_func=virtual_key.released_function, layer_id=int(layer_id))
                return True  # Handled by this method
        
        return False  # Use default behavior

    def build_fn_layer(self, virtual_keys: List[VirtualKey]):
        # Call parent build_fn_layer to handle all mappings including function registry
        super().build_fn_layer(virtual_keys)

        # Add music-specific key bindings
        self.bind_fn_layer_func("M", pressed_function=self.enable_switch)
        self.bind_fn_layer_func("COMMA", pressed_function=self.volume_minus)
        self.bind_fn_layer_func("DOT", pressed_function=self.volume_plus)

    def setup_function_registry(self):
        """Setup the function registry for music-related functions."""
        self.function_registry = {
            "change_scale_to_c_major": lambda: self.change_scale_to("C Major"),
            "change_scale_to_d_major": lambda: self.change_scale_to("D Major"),
            "change_scale_to_e_major": lambda: self.change_scale_to("E Major"),
            "change_scale_to_f_major": lambda: self.change_scale_to("F Major"),
            "change_scale_to_g_major": lambda: self.change_scale_to("G Major"),
            "change_scale_to_a_major": lambda: self.change_scale_to("A Major"),
            "change_scale_to_b_major": lambda: self.change_scale_to("B Major"),
        }

    def change_scale_to(self, scale_name: str):
        """Change to a specific scale if music is enabled."""
        if self.music_enabled and scale_name in self.available_scales:
            self.current_scale_index = self.available_scales.index(scale_name)
            self.music_mapping = self.music_mappings[scale_name]
            self.mode = scale_name
            self._load_mode_notes(self.music_mapping)
            self.build_virtual_keys()
            print(f"Scale changed to: {scale_name}")
        elif not self.music_enabled:
            # If music is disabled, don't change scale
            pass

    def build_virtual_keys(self):
        virtual_keys: List[VirtualKey] = []
        # Clear existing note key mapping
        self.note_key_mapping = {}

        for physical_key in self.phsical_key_board.key_iter():
            if physical_key is not None:
                key_code_name = physical_key.key_name
                if self.virtual_key_mappings is not None:
                    key_code_name = self.virtual_key_mappings["layers"]["0"].get(physical_key.key_name, None) or key_code_name
                if physical_key.key_name in self.music_mapping:
                    current_note = self.music_mapping[physical_key.key_name]
                    self.note_key_mapping[current_note] = physical_key.key_name
                    virtual_key = VirtualKey(
                        key_name=key_code_name,
                        keycode=getattr(KeyCode, key_code_name, None),
                        physical_key=physical_key,
                        pressed_function=None,
                        released_function=None,
                    )
                    def pressed_function(virtual_key_board: "MusicKeyBoard", virtual_key: VirtualKey, note: str):
                        if virtual_key_board.music_enabled:
                            virtual_key.playing_wav_id = self.audio_manager.play_note(note)
                    def released_function(virtual_key: VirtualKey):
                        if hasattr(virtual_key, "playing_wav_id"):
                            self.audio_manager.stop_note(wav_id=virtual_key.playing_wav_id, delay=500)
                    virtual_key.pressed_function = partial(pressed_function, self, virtual_key, current_note)
                    virtual_key.released_function = partial(released_function, virtual_key)
                else:
                    virtual_key = VirtualKey(key_name=key_code_name, keycode=getattr(KeyCode, key_code_name, None), physical_key=physical_key)
                virtual_keys.append(virtual_key)
        self.virtual_keys = virtual_keys
        self.build_fn_layer(virtual_keys)

    def volume_minus(self):
        self.audio_manager.change_volume_factor(self.audio_manager.volume_factor - 1)

    def volume_plus(self):
        self.audio_manager.change_volume_factor(self.audio_manager.volume_factor + 1)
