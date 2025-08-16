import time
import os
import math
import micropython

import umidiparser

from machine import Pin, I2S
from typing import Optional, List, Dict, Tuple, Callable, Union
from umidiparser import MidiFile, MidiEvent

from microkeyboard.utils import debugging, exists, partial
from microkeyboard.ops import clear_4bit_bytearray_viper, interpolate, divide_int16_array_in_place_viper, int32_add_int16_in_place_viper, int32_left_shift_in_place_viper, interpolate_2x_int32_viper_ptr32, interpolate_4x_int32_viper_ptr32, interpolate_int32_viper_ptr32


def note_to_midinumber(note: str) -> int:
    """
    Convert a note name (e.g., A4, C#3) to its MIDI note number.

    Uses Scientific Pitch Notation (A4=440Hz is MIDI 69).
    C0 is MIDI 12, C-1 is MIDI 0.

    Args:
        note: Note name string (e.g., "C4", "A#5", "F#3", "C-1").

    Returns:
        Corresponding MIDI note number (0-127 range for standard notes),
        or -1 if the note format is invalid.
    """
    note_map = {'C': 0, 'C#': 1, 'D': 2, 'D#': 3, 'E': 4, 'F': 5, 'F#': 6, 'G': 7, 'G#': 8, 'A': 9, 'A#': 10, 'B': 11}

    base_note = ''
    octave_str = ''
    digit_start_index = -1

    # Find the start of the numerical octave part
    for i in range(len(note)):
        if note[i].isdigit() or (note[i] == '-' and i + 1 < len(note) and note[i+1].isdigit()):
            digit_start_index = i
            break

    # Check if parsing found an octave part
    if digit_start_index == -1:
        return -1 # Invalid format

    base_note = note[:digit_start_index]
    octave_str = note[digit_start_index:]

    # Check if base note is valid
    if base_note not in note_map:
        return -1 # Invalid base note name

    # Check if octave string is a valid integer
    try:
        octave = int(octave_str)
    except ValueError:
        return -1 # Invalid octave number format

    base_note_value = note_map[base_note]

    # Calculate MIDI number
    # (octave + 1) * 12 maps written octave 0 to MIDI octave 1 (MIDI notes 12-23)
    # Written octave -1 maps to MIDI octave 0 (MIDI notes 0-11)
    midi_number = (octave + 1) * 12 + base_note_value

    # Return the calculated number (can be outside 0-127)
    # If strictly need 0-127, add check: `if not 0 <= midi_number <= 127: return -1`
    return midi_number


def midinumber_to_note(midinumber: int) -> str:
    """
    Convert a MIDI note number to its note name (e.g., 69 -> A4).

    Uses Scientific Pitch Notation (A4=440Hz is MIDI 69).
    C0 is MIDI 12, C-1 is MIDI 0.

    Args:
        midinumber: MIDI note number (integer).

    Returns:
        Corresponding note name string (e.g., "A4", "C-1"),
        or "Out of Range" if the number is outside the standard 0-127 MIDI range.
    """
    # Standard MIDI note numbers are 0-127
    if not 0 <= midinumber <= 127:
        return "Out of Range"

    # Note names indexed by their value (0-11)
    note_names = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']

    # Calculate the base note value (0-11)
    base_note_value = midinumber % 12

    # Calculate the written octave number
    # (midinumber // 12) gives 0 for 0-11, 1 for 12-23 etc., which is the MIDI octave.
    # Written octave = MIDI octave - 1.
    written_octave = (midinumber // 12) - 1

    note_name = note_names[base_note_value]

    return f"{note_name}{written_octave}"


class Voice:
    def __init__(
            self,
            voice_id: Optional[int] = None,
            loaded_data: Optional[Union[bytes, bytearray, memoryview]] = None,
            current_pos: Optional[int] = None,
            voice_name: Optional[str] = None,
            start_time: Optional[int] = None,
            finished: bool = False,
            active: bool = False,
            valid: bool = True,
        ):
        self.voice_id = voice_id
        self.loaded_data = loaded_data if isinstance(loaded_data, memoryview) or loaded_data is None else memoryview(loaded_data)
        self.current_pos = current_pos
        self.voice_name = voice_name
        self.start_time = start_time or time.ticks_ms()
        self.finished = finished
        self.active = active
        self.valid = valid

        # TODO:
        # self.sustain: Use algorithm for sustain
        # or
        # self.preload: Preload a portion, then load more during reading
        # stop and decay
    
    def reinit(
            self,
            voice_id: int,
            loaded_data: Union[bytearray, memoryview],
            current_pos: int,
            voice_name: Optional[str] = None,
            start_time: Optional[int] = None,
            finished: bool = False,
            active: bool = False,
            valid: bool = True,
        ):
        self.voice_id = voice_id
        self.loaded_data = loaded_data if isinstance(loaded_data, memoryview) else memoryview(loaded_data)
        self.current_pos = current_pos
        self.voice_name = voice_name
        self.start_time = start_time or time.ticks_ms()
        self.finished = finished
        self.active = active
        self.valid = valid

    def copy(self, voice: "Voice"):
        self.voice_id = voice.voice_id
        self.loaded_data = voice.loaded_data
        self.current_pos = voice.current_pos
        self.voice_name = voice.voice_name
        self.start_time = voice.start_time
        self.finished = voice.finished
        self.active = voice.active
        self.valid = voice.valid


class Sampler:
    def __init__(self,
        sample_dir : str,
        rate : int = 16000,
        # volume_factor: int = 0,
        wav_data_start: int = 78
    ):
        """
        Initialize the sampler
        :param sample_dir: Directory where sample files are located
        :param rate: Sampling rate (default 16000)
        """
        self.sample_dir = sample_dir
        self.rate = rate
        # self.volume_factor = volume_factor
        self.samples = {}  # Store sample filepath
        self.keys = []     # Store the keys (pitches) of the sample notes
        self.sample_cache = None
        self.sample_cache_name = None
        self.wav_data_start = wav_data_start
        self.load_samples()

    def load_sample(self, filename, duration: Optional[float] = None) -> bytes:
        """
        Load sample file to memory
        """
        filepath = f"{self.sample_dir}/{filename}"
        # print(f"load_sample({filepath})")
        if self.sample_cache_name == filepath:
            # print("load_sample cache hit")
            return memoryview(bytearray(self.sample_cache) )
        with open(filepath, "rb") as f:
            f.seek(self.wav_data_start)  # Skip the WAV file header
            if duration is not None and duration > 0:
                # Calculate number of samples needed
                num_samples_to_read = int(duration * self.rate)
                # Calculate number of bytes needed (16-bit int = 2 bytes per sample)
                num_bytes_to_read = num_samples_to_read * 2

                # Read the specified number of bytes
                raw = f.read(num_bytes_to_read)
            else:
                raw = f.read()
        self.sample_cache_name = filepath
        self.sample_cache = raw
        return memoryview(bytearray(raw))

    def load_samples(self, dummy=True):
        """
        Load sample files
        """
        # Get the note names of the sample files and load the data
        for filename in os.listdir(self.sample_dir):
            if filename.endswith("vH.wav"):
                print(f"Sampler found {filename}.")
                note = filename.split("vH")[0]
                self.samples[note] = filename
                self.keys.append(note)
        # Sort the notes by pitch (assuming the note format is standard like A3, C4)
        self.keys = sorted(self.keys, key=self.note_to_frequency)

    def note_to_frequency(self, note: str):
        """
        Convert a note name to frequency
        :param note: Note name (e.g., A4, C#3)
        :return: Corresponding frequency (Hz)
        """
        # Note frequency calculation formula: f = 440 * 2^((n - 69) / 12)
        # Where n is the MIDI note number
        note_map = {'C': 0, 'C#': 1, 'D': 2, 'D#': 3, 'E': 4, 'F': 5, 'F#': 6, 'G': 7, 'G#': 8, 'A': 9, 'A#': 10, 'B': 11}
        octave = int(note[-1])  # Get the octave
        base_note = note[:-1]   # Get the note
        midi_number = (octave + 1) * 12 + note_map[base_note]
        frequency = 440.0 * (2 ** ((midi_number - 69) / 12))
        return frequency

    def get_sample(self, note, duration: Optional[float] = None):
        """
        Get the audio data for a specified note
        :param note: Target note name (e.g., A4, C#3)
        :return: Audio data (numpy array)
        """
        if note in self.samples:
            # If the note directly exists in the samples, return the sample data
            sample = self.load_sample(self.samples[note], duration=duration)
        else:
            # If the note does not exist, use pitch shifting to generate it
            sample = self.pitch_shift(note, duration=duration)
        # TODO: consider pad to length
        # if self.volume_factor > 0 and self.volume_factor != 1:
        #     divide_int16_array_in_place_viper(sample, len(sample) // 2, int(1 / self.volume_factor))
        return sample

    def pitch_shift(self, note, duration: Optional[float] = None):
        """
        Use pitch shifting to generate the target note
        :param note: Target note name (e.g., A4, C#3)
        :return: Generated audio data (numpy array)
        """
        # Find the closest sample note
        target_freq = self.note_to_frequency(note)
        closest_sample_path, closest_freq = self.find_closest_sample(target_freq)

        # Calculate the pitch shift factor
        shift_factor = target_freq / closest_freq

        # Load closest sample
        closest_sample: Union[bytes, bytearray] = self.load_sample(closest_sample_path, duration=None if duration is None else (duration+0.1)*shift_factor)

        # Use numpy interpolation to achieve pitch shifting
        original_length = len(closest_sample)
        new_length = int(original_length / shift_factor)

        # raise NotImplementedError("Viper interpolate not checked!")
        shifted_sample = interpolate(closest_sample, original_length * 2, new_length * 2)
        # TODO: interpolate_inplace

        if duration is not None and duration > 0:
            target_samples = int(duration * self.rate)
            return shifted_sample[:2 * target_samples]  # np.array(shifted_sample[:target_samples], dtype=np.int16)

        return memoryview(shifted_sample)  # np.array(shifted_sample, dtype=np.int16)

    def find_closest_sample(self, target_freq):
        """
        Find the closest sample note to the target frequency
        :param target_freq: Target frequency (Hz)
        :return: The closest sample note data and frequency
        """
        closest_key = None
        closest_freq = None
        min_diff = float('inf')

        for key in self.keys:
            freq = self.note_to_frequency(key)
            diff = abs(freq - target_freq)
            if diff < min_diff:
                min_diff = diff
                closest_key = key
                closest_freq = freq

        return self.samples[closest_key], closest_freq


class AudioManager:
    """
    Process 16-bit mono audio.
    Use 32-bit I2S to prevent overflow during processing.
    """

    BUFFER_SAMPLES = 1024
    BUFFER_BIT = 2
    BUFFER_BYTES = BUFFER_SAMPLES * BUFFER_BIT # Calculate bytes based on samples (assuming 16-bit mono)
    I2S_BUFFER_BIT = 4
    I2S_BUFFER_BYTES = BUFFER_SAMPLES * I2S_BUFFER_BIT
    I2S_INTERPOLATE = 2

    def __init__(
        self,
        sck_pin: int = 48,
        ws_pin: int = 47,
        sd_pin: int = 45,
        en_pin: int = 38,
        i2s_id: int = 0,
        bits: int = 16,
        format=I2S.MONO,
        rate=16000,
        max_voices: int = 8,
        buffer_samples: int = 1024,
        i2s_buf_samples: int = 4096,
        i2s_rate: int = 32000,
        volume_factor: int = -3,  # log(volume value)
        always_play: bool = False,  # Always write to buffer to trigger callback.
    ):  # TODO: read json config
        if bits != 16 or format != I2S.MONO:
             raise ValueError("Supports only 16-bit MONO audio")
        assert i2s_rate % rate == 0, f"i2s_rate({i2s_rate}) mod rate({rate}) != 0"

        self.BUFFER_SAMPLES = buffer_samples
        self.I2S_RATE = i2s_rate
        self.I2S_INTERPOLATE = (i2s_rate // rate)
        # self.BUFFER_BYTES = self.BUFFER_SAMPLES * self.BUFFER_BIT
        self.I2S_BUFFER_BYTES = self.BUFFER_SAMPLES * self.I2S_BUFFER_BIT

        self.always_play = always_play
        self.last_irq = time.ticks_ms()
        self.last_write = time.ticks_ms()

        if en_pin is None:
            self.en = None
        else:
            self.en = Pin(en_pin, Pin.OUT, value=1)

        self.audio_out = I2S(
            i2s_id,
            sck=Pin(sck_pin),
            ws=Pin(ws_pin),
            sd=Pin(sd_pin),
            mode=I2S.TX,
            bits=self.I2S_BUFFER_BIT * 8,  # I2S use 32 bit to prevent overflow
            format=format,
            rate=self.I2S_RATE,
            ibuf=i2s_buf_samples * self.I2S_BUFFER_BIT * self.I2S_INTERPOLATE,
        )

        self.RATE = rate
        self.bits = bits
        self.format = format
        self.max_voices = max_voices
        self.bytes_per_sample = (self.bits // 8) * (self.format + 1)  # Should be 2

        # TODO: add software volume controll
        self.volume_factor = volume_factor  # TODO: use for es8156 or es8311 hardware volume
        self.volume_shift = max(int(13 + self.volume_factor), 0)

        # Double buffers (NumPy int16 arrays)
        self.audio_buffers = (
            memoryview(bytearray(self.BUFFER_SAMPLES * self.I2S_BUFFER_BIT * self.I2S_INTERPOLATE)),
            memoryview(bytearray(self.BUFFER_SAMPLES * self.I2S_BUFFER_BIT * self.I2S_INTERPOLATE))
        )
        self.audio_cal_buffer = memoryview(bytearray(self.BUFFER_SAMPLES * self.I2S_BUFFER_BIT))
        # self.cal_buffer = memoryview(bytearray(self.BUFFER_SAMPLES * self.I2S_BUFFER_BIT * self.I2S_INTERPOLATE))

        # Valid samples mixed into each buffer
        self.valid_samples = [0, 0]
        self.buffer_to_play_idx = 0 # Index of buffer to play next

        # File Caching
        self._loaded_wavs: Dict[str, Union[bytearray, memoryview]] = {} # Stores {filepath: bytearray_data}

        # Playback state
        self._is_playing = False
        self.active_voices: Tuple[Voice] = tuple([Voice(valid=False) for _ in range(self.max_voices)])
        self.added_voices: Tuple[Voice] = tuple([Voice(valid=False) for _ in range(self.max_voices)])
        self.disabled_voices: Dict[int, int] = {}
        self.voice_num = 0

        # Simple Delay Effect State - REMOVED

        # I2S Interrupt setup
        self.audio_out.irq(self._i2s_callback)
        if self.always_play:
            self._i2s_callback(self)

    def change_volume_factor(self, volume_factor: int):
        self.volume_factor = min(max(volume_factor, -13), 0)
        self.volume_shift = max(int(13 + self.volume_factor), 0)

    def enable_irq(self):
        self.audio_out.irq(self._i2s_callback)

    def disable_irq(self):
        self.audio_out.irq(None)

    def list_wav(self) -> List[str]:
        return list(self._loaded_wavs.keys())
    
    def have_wav(self, wav_file: str) -> bool:
        return wav_file in self._loaded_wavs

    def load_wav(self, wav_file: str, wav_data: Optional[Union[memoryview, bytearray, bytes]] = None, wav_data_start: int = 44):
        """Loads WAV file data into memory cache."""
        if wav_file in self._loaded_wavs:
            print(f"'{wav_file}' already loaded.")
            return self._loaded_wavs[wav_file]

        if wav_data is None:
            print(f"Loading '{wav_file}'...")
            with open(wav_file, "rb") as f:
                f.seek(wav_data_start)
                wav_data = memoryview(bytearray(f.read()))  # TODO: use readinto
        loaded_np_array = memoryview(wav_data)
        self._loaded_wavs[wav_file] = loaded_np_array
        print(f"Loaded '{wav_file}' ({len(loaded_np_array)} bytes).")
        return wav_data

    def unload_wav(self, wav_file: str):
        """Pop WAV file data from memory cache."""
        # TODO: FIFO Dict
        self._loaded_wavs.pop(wav_file)

    def _prepare_buffer(self, buffer_idx: int):
        """Mixes active voices (from memory) using NumPy."""
        target_buffer_np = self.audio_cal_buffer  # self.audio_buffers[buffer_idx]
        clear_4bit_bytearray_viper(target_buffer_np, self.BUFFER_SAMPLES)

        total_samples_mixed = 0

        for voice in self.added_voices:
            if voice.valid and not (voice.finished or voice.active):
                new_voice_added = False
                for active_voice in self.active_voices:
                    if not active_voice.valid:
                        active_voice.copy(voice)
                        # print(f"active {active_voice.voice_name}, {active_voice.current_pos}, {active_voice.valid}")
                        new_voice_added = True
                        break
                if not new_voice_added:
                    if debugging():
                        print("active_voices fulled")
                    oldest_voice = self.active_voices[0]
                    for active_voice in self.active_voices:
                        if oldest_voice.start_time > active_voice.start_time:
                            oldest_voice = active_voice
                    oldest_voice.copy(voice)
                    new_voice_added = True
                voice.active = True

        # Iterate through active voices [loaded_data, current_pos]
        for voice_info in self.active_voices:
            if not voice_info.valid:
                continue
            loaded_data = voice_info.loaded_data # The bytearray data
            current_pos = voice_info.current_pos # Current read position in bytes
            voice_id = voice_info.voice_id
            start_time = voice_info.start_time
            current_ms = time.ticks_ms()

            # if voice_info.finished:
            #     print(f"finished '{voice_id}'  at {current_ms}.")
            #     continue

            if voice_id in self.disabled_voices and self.disabled_voices[voice_id] > start_time and current_ms > self.disabled_voices[voice_id]:
                voice_info.finished = True
                if debugging():
                    print(f"stopping '{voice_info.voice_name}, {voice_id}' at {current_ms}.")
                continue

            num_data_samples = len(loaded_data) // self.BUFFER_BIT
            num_read_samples = min(self.BUFFER_SAMPLES, num_data_samples - current_pos)

            if num_read_samples > 0:
                # Mix into the target buffer using addition
                # Ensure slices match size
                # TODO: target(int32) += data[start : end](int16) * volume(float)

                int32_add_int16_in_place_viper(target_buffer_np, 0, loaded_data, current_pos, num_read_samples)

                total_samples_mixed = max(total_samples_mixed, num_read_samples)  
                # Update position for this voice (in bytes)
                voice_info.current_pos += num_read_samples

            # Check if this voice finished reading (reached end of loaded data)
            if current_pos + num_read_samples >= num_data_samples:
                voice_info.finished = True
                # print(f"finished reading '{voice_id}'  at {current_ms}, {(current_pos, num_read_bytes, num_data_samples)}")

        # control voice volumn
        int32_left_shift_in_place_viper(target_buffer_np, self.BUFFER_SAMPLES, self.volume_shift)

        # interpolate
        if self.I2S_INTERPOLATE == 2:
            interpolate_2x_int32_viper_ptr32(target_buffer_np, self.audio_buffers[buffer_idx], self.BUFFER_SAMPLES)
        elif self.I2S_INTERPOLATE == 4:
            interpolate_4x_int32_viper_ptr32(target_buffer_np, self.audio_buffers[buffer_idx], self.BUFFER_SAMPLES)
        else:
            interpolate_int32_viper_ptr32(target_buffer_np, self.audio_buffers[buffer_idx], self.BUFFER_SAMPLES, self.I2S_INTERPOLATE)

        # Remove finished voices
        for active_voice in self.active_voices:
            if active_voice.finished:
                active_voice.valid = False

        self.valid_samples[buffer_idx] = total_samples_mixed

    def _i2s_callback(self, caller):
        """I2S IRQ Callback."""
        self.last_irq = time.ticks_us()
        if not self._is_playing:
            if debugging():
                print("I2S callback: Not playing.")
            # self.stop_all()
            return

        play_idx = self.buffer_to_play_idx
        samples_to_play = self.valid_samples[play_idx]
        prep_idx = (play_idx + 1) % 2

        write_tiggered = False

        # Write the prepared buffer to I2S if it has data
        if self.always_play or samples_to_play == self.BUFFER_SAMPLES:
            byte_data = self.audio_buffers[play_idx]
            # interpolate_2x_int32_viper_ptr32(byte_data, self.cal_buffer, self.BUFFER_SAMPLES)
            # self.audio_out.write(self.cal_buffer)
            self.audio_out.write(byte_data)
            write_tiggered = True
            self.last_write = time.ticks_us()
        elif samples_to_play > 0:
            byte_data = self.audio_buffers[play_idx][:samples_to_play * self.I2S_BUFFER_BIT * self.I2S_INTERPOLATE]
            # interpolate_2x_int32_viper_ptr32(byte_data, self.cal_buffer, self.BUFFER_SAMPLES)
            # self.audio_out.write(self.cal_buffer[:samples_to_play * self.I2S_BUFFER_BIT * self.I2S_RATE // self.RATE])
            self.audio_out.write(byte_data)
            write_tiggered = True
            self.last_write = time.ticks_us()

        # Update state for the next IRQ
        self.buffer_to_play_idx = prep_idx
        # Trigger preparation of the NEXT buffer
        self._prepare_buffer(prep_idx)

        # Check if playback should stop
        # Stops if _is_playing is False or if all voices processed AND the buffer just played was empty
        if self.always_play:
            assert write_tiggered, "write not triggered!"
            # micropython.schedule(self._prepare_buffer, prep_idx)
        elif not (any(voice.valid for voice in self.active_voices) > 0 or write_tiggered):
            self.stop_all()
        elif not write_tiggered:
            print(f"Nothing write to I2S, retriggering...")
            assert caller is not self, "Loop"
            self._i2s_callback(self)
        else:
            # micropython.schedule(self._prepare_buffer, prep_idx)
            pass

    def play_note(self, wav_file: str, nickname: Optional[str] = None, playtime: Optional[int] = None) -> int:
        """Plays a note (non-blocking). Adds the WAV file data (from cache) to active voices."""

        # Ensure file is loaded into memory cache first
        # load_wav will raise an error if file not found, stopping execution as requested
        if wav_file not in self._loaded_wavs:
            self.load_wav(wav_file)

        # Get loaded data from cache
        loaded_data = self._loaded_wavs[wav_file]

        # Add new voice with loaded data and start position 0
        # Position is in bytes
        for voice in self.added_voices:
            if voice.active or voice.finished:
                voice.valid = False
        new_voice_id = self.voice_num
        new_voice_added = False
        for voice in self.added_voices:
            if not voice.valid:
                voice.reinit(
                    new_voice_id, loaded_data, 0, nickname or wav_file, time.ticks_ms(), valid=True
                )
                self.voice_num += 1
                if playtime is not None:
                    self.disabled_voices[voice.voice_id] = time.ticks_ms() + playtime
                new_voice_added = True
                if debugging():
                    print(f"starting '{voice.voice_name}, {voice.voice_id}' at {time.ticks_ms()}. Last irq: {self.last_irq}, last write: {self.last_write}.")
                break
        if not new_voice_added:
            oldest_voice = self.added_voices[0]
            for voice in self.added_voices:
                if oldest_voice.start_time > voice.start_time:
                    oldest_voice = voice
            oldest_voice.reinit(
                new_voice_id, loaded_data, 0, nickname or wav_file, time.ticks_ms(), valid=True
            )
            new_voice_added = True
            if debugging():
                print(f"starting '{voice.voice_name}, {voice.voice_id}' at {time.ticks_ms()}, replace {oldest_voice.voice_name}, {oldest_voice.voice_id}. Last irq: {self.last_irq}, last write: {self.last_write}.")

        # If not playing, start the process
        if not self._is_playing:
            self._is_playing = True

            # Prepare the initial two buffers (in main thread)
            audio_buffer_a, audio_buffer_b = self.audio_buffers
            clear_4bit_bytearray_viper(audio_buffer_a, self.BUFFER_SAMPLES)
            clear_4bit_bytearray_viper(audio_buffer_b, self.BUFFER_SAMPLES)
            self.valid_samples[0] = self.BUFFER_SAMPLES
            self.valid_samples[1] = self.BUFFER_SAMPLES
            byte_data_init = self.audio_buffers[0]
            self.audio_out.write(byte_data_init)
            self.buffer_to_play_idx = 1 # Next IRQ plays buffer 1
        return new_voice_id

    def stop_note(self, wav_file: Optional[str] = None, wav_id: Optional[int] = None, delay: Optional[int] = None):
        if wav_id is not None:
            self.disabled_voices[wav_id] = time.ticks_ms() + (delay or 0)
        elif wav_file is not None:
            for voice in self.added_voices:
                if voice.valid and voice.voice_name == wav_file:
                    self.disabled_voices[voice.voice_id] = time.ticks_ms() + (delay or 0)
            for voice in self.active_voices:
                if voice.valid and voice.voice_name == wav_file:
                    self.disabled_voices[voice.voice_id] = time.ticks_ms() + (delay or 0)
        else:
            raise ValueError("wav_file is None and wav_id is None")

    def stop_all(self):
        """Stops all voices and playback."""
        # Keep IRQ enabled but rely on _is_playing flag and empty voices/buffers
        # assert self.always_play == False
        # self.always_play = False

        if self._is_playing:
            self._is_playing = False

            # Active voices only contain data and position
            for voice in self.active_voices:
                voice.valid = False
            self.disabled_voices.clear()
            for voice in self.added_voices:
                if voice.valid:
                    assert voice.active, f"Voice not actived before stop: {voice.voice_name}"
                voice.valid = False

            # Reset buffer state (NumPy buffers)
            audio_buffer_a, audio_buffer_b = self.audio_buffers
            clear_4bit_bytearray_viper(audio_buffer_a, self.BUFFER_SAMPLES)
            clear_4bit_bytearray_viper(audio_buffer_b, self.BUFFER_SAMPLES)
            self.valid_samples = [0, 0]
            self.buffer_to_play_idx = 0

    def is_playing(self):
        """Returns True if playback is active."""
        return self._is_playing

    def __del__(self):
        self.stop_all()


class MIDIPlayer():
    def __init__(
        self,
        file_path: str,
    ):
        self.events: List[Tuple[Union[int, float], str, bool]] = []
        self.idx = 0
        self.playing = False
        self.start_time = time.ticks_ms()
        self.shift_delay_ms = 500
        self.time_multiplayer = 1.0

        if exists(file_path):  # TODO: recognize simultaneously play
            start_time_ms = 0
            for event in MidiFile(file_path, reuse_event_object=True):
                delta_ms = event.delta_us // 1000
                start_time_ms += delta_ms
                if event.status == umidiparser.NOTE_ON:
                    note = midinumber_to_note(event.note)
                    if event.velocity > 0:
                        self.events.append((float(start_time_ms), note, True))
                    else:
                        self.events.append((float(start_time_ms), note, False))
                # on channel event.channel with event.velocity
                elif event.status == umidiparser.NOTE_OFF :
                    note = midinumber_to_note(event.note)
                    self.events.append((float(start_time_ms), note, False))
                    # ... stop the note event.note .
        
        self.event_length = len(self.events)

    def play(self, play_func: Callable) -> bool:  # TODO: return next play time
        if self.playing and self.idx < self.event_length:
            current_time = time.ticks_ms()
            if current_time - self.start_time >= int(self.events[self.idx][0] * self.time_multiplayer) + self.shift_delay_ms:
                # print(self.events[self.idx])
                play_func(self.idx, self.events)
                self.idx += 1
            return True
        else:
            self.playing = False
        return False

    def start(self):
        self.idx = 0
        self.start_time = time.ticks_ms()
        self.playing = True

    def resume(self):  # TODO
        pass

    def stop(self):
        self.playing = False

    def reset(self):
        self.idx = 0
        self.playing = False


def main(audio_manager):
    time.sleep_ms(1000) # Sleep before starting audio

    # Load WAV files into memory first
    print("Loading WAVs...")
    sampler = Sampler("/wav/piano/16000_2s", wav_data_start=78)
    # note_cache_path: Optional[str] = "/cache/piano/16000_1.8s"
    note_cache_path: Optional[str] = "/cache/piano/16000"
    for note in ["C5", "D5", "E5", "F5", "G5", "A5", "B5", "C6"]:
        if exists(f"{note_cache_path}/{note}"):
            with open(f"{note_cache_path}/{note}", "rb") as f:
                wav_data = f.read()
        else:
            wav_data = sampler.get_sample(f"{note}", duration=1.8)
        audio_manager.load_wav(note, wav_data)
    print("Loading complete.")

    quarter = 556
    eighth = 278
    sixteenth = 139

    audio_manager.play_note("E5", playtime=quarter)
    time.sleep_ms(quarter)
    
    audio_manager.play_note("D5", playtime=eighth)
    # audio_manager.stop_note("E5")
    time.sleep_ms(eighth)

    audio_manager.play_note("C5")
    audio_manager.stop_note("D5")
    time.sleep_ms(quarter)

    audio_manager.play_note("D5")
    audio_manager.stop_note("C5")
    time.sleep_ms(eighth)

    audio_manager.play_note("E5")
    audio_manager.stop_note("D5")
    time.sleep_ms(eighth + sixteenth)

    audio_manager.play_note("F5")
    audio_manager.stop_note("E5")
    time.sleep_ms(sixteenth)
    
    audio_manager.play_note("E5")
    audio_manager.stop_note("F5")
    time.sleep_ms(eighth)
    
    audio_manager.play_note("D5")
    audio_manager.stop_note("E5")
    time.sleep_ms(quarter + eighth)
    audio_manager.stop_note("D5")

    audio_manager.stop_all()


def midi_example(audio_manager, file_path = "mid/fukakai - KAF - Piano.mid"):
    import gc

    time.sleep_ms(1000) # Sleep before starting audio

    # Load WAV files into memory first
    print("Loading WAVs...")
    sampler = Sampler("/wav/piano/16000_2s", wav_data_start=78)
    # note_cache_path: Optional[str] = "/cache/piano/16000_1.8s"
    note_cache_path: Optional[str] = "/cache/piano/16000"

    start_time = time.ticks_us()
    for i in range(2, 6):
        for note in ["C", "D", "E", "F", "G", "A", "A#", "B"]:
            if exists(f"{note_cache_path}/{note}{i}"):
                wav_data = open(f"{note_cache_path}/{note}{i}", "rb").read()
            else:
                wav_data = sampler.get_sample(f"{note}{i}", duration=1.8)
            audio_manager.load_wav(f"{note}{i}", wav_data)

    for note in ["A1", "A#1", "D#3", "D#4", "C6", "D6", "E6", "F6", "D#5", "G#5"]:  # ["C6", "D6", "E6", "F6"]:
        if exists(f"{note_cache_path}/{note}"):
            wav_data = open(f"{note_cache_path}/{note}", "rb").read()
        else:
            wav_data = sampler.get_sample(f"{note}", duration=1.8)
        audio_manager.load_wav(note, wav_data)
    end_time = time.ticks_us()
    print(f"Loading complete. {time.ticks_diff(end_time, start_time)}us")

    gc.collect()

    midi_player = MIDIPlayer(
        file_path=file_path
    )

    def play_note(idx: int, events: List[Tuple[int, str, bool]], audio_manager: AudioManager = audio_manager):
        _, note, play = events[idx]
        if play:
            audio_manager.play_note(note)
        else:
            audio_manager.stop_note(note, delay=500)
    play_func = partial(play_note)

    count = 0
    max_scan_gap = 0
    start_time = time.ticks_ms()
    current_time = time.ticks_ms()
    midi_player.start()
    while True:
        if not midi_player.play(play_func):
            break
        time.sleep_ms(4)
        max_scan_gap = max(max_scan_gap, time.ticks_ms() - current_time)
        current_time = time.ticks_ms()
        if current_time - start_time >= 1000:
            print(f"scan speed: {count}/s, gap {max_scan_gap}ms, mem_free: {gc.mem_free()}")
            count = 0
            max_scan_gap = 0
            start_time = current_time

    for event in MidiFile(file_path, reuse_event_object=True).play():
        if event.status == umidiparser.NOTE_ON:
            note = midinumber_to_note(event.note)  # TODO: mode
            if debugging():
                print(note, event)
            if event.velocity > 0:
                # playtime = event.delta_us // 1000
                audio_manager.play_note(note)
                # time.sleep_us(event.delta_us)
                # audio_manager.play_note(note, playtime=playtime)
            else:
                audio_manager.stop_note(note, delay=500)
                # time.sleep_us(event.delta_us)
        # on channel event.channel with event.velocity
        elif event.status == umidiparser.NOTE_OFF :
            if debugging():
                print("NOTE_OFF", event)
            note = midinumber_to_note(event.note)  # TODO: mode
            audio_manager.stop_note(note, delay=500)
            # ... stop the note event.note .
        elif event.status == umidiparser.PROGRAM_CHANGE:
            if debugging():
                print("PROGRAM_CHANGE", event)
            # ... change midi program to event.program on event.channel ....
        elif event.status == 0x51:
            if debugging():
                print("SET_TEMPO", event)
        else:
            # Show all events not processed
            if debugging():
                print("other event", event)


if __name__ == "__main__":
    import machine

    from microkeyboard.utils import debug_switch
    from microkeyboard.module.pca9555 import PCA9555

    machine.freq(240000000)
    
    i2c_bus = machine.I2C(0, scl=17, sda=18, freq=400000)
    gpio_expander = PCA9555(i2c_bus, address=0x20)
    gpio_expander.digital_write(0, 1)
    gpio_expander.digital_write(1, 1)
    gpio_expander.digital_write(5, 1)
    gpio_expander.digital_write(15, 0)
    gpio_expander.set_pin_mode(0, 0)
    gpio_expander.set_pin_mode(1, 0)
    gpio_expander.set_pin_mode(5, 0)
    gpio_expander.set_pin_mode(15, 0)

    # debug_switch(True)

    # audio_manager = AudioManager(
    #     sck_pin = 42,
    #     ws_pin = 40,
    #     sd_pin = 41,
    #     rate=16000,
    #     buffer_samples=1024,
    #     i2s_rate=32000,
    #     i2s_buf_samples=4096,
    #     always_play=True,
    #     volume_factor=-1
    # )
    # main(audio_manager)

    audio_manager = AudioManager(
        sck_pin = 42,
        ws_pin = 40,
        sd_pin = 41,
        rate=16000,
        i2s_rate=32000,
        buffer_samples=1024,
        i2s_buf_samples=2048,
        always_play=True,
        volume_factor=-3
    )
    midi_example(audio_manager)
