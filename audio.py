import time
import os

from machine import Pin
from machine import I2S
from typing import Optional, List, Dict
from ulab import numpy as np


class Voice:
    def __init__(self,
            voice_id: int,
            loaded_data,
            current_pos_bytes: int,
            voice_name: str,
            start_time: Optional[int] = None,
            finished: bool = False,
            active: bool = False
        ):
        self.voice_id = voice_id
        self.loaded_data = loaded_data
        self.current_pos_bytes = current_pos_bytes
        self.voice_name = voice_name
        self.start_time = start_time or time.ticks_ms()
        self.finished = finished
        self.active = active

        # TODO:
        # self.sustain: Use algorithm for sustain
        # or
        # self.preload: Preload a portion, then load more during reading
        # stop and decay


class Sampler:
    def __init__(self,
        sample_dir : str,
        rate : int = 16000,
        cache_dir : Optional[str] = None
    ):
        """
        Initialize the sampler
        :param sample_dir: Directory where sample files are located
        :param rate: Sampling rate (default 16000)
        """
        self.sample_dir = sample_dir
        self.rate = rate
        self.samples = {}  # Store sample filepath
        self.keys = []     # Store the keys (pitches) of the sample notes
        self.cache_dir = cache_dir
        self.load_samples()

    def load_sample(self, filename, duration: Optional[float] = None):
        """
        Load sample file to memory
        """
        with open(f"{self.sample_dir}/{filename}", "rb") as f:
            f.seek(44)  # Skip the WAV file header
            if duration is not None and duration > 0:
                # Calculate number of samples needed
                num_samples_to_read = int(duration * self.rate)
                # Calculate number of bytes needed (16-bit int = 2 bytes per sample)
                num_bytes_to_read = num_samples_to_read * 2
                
                # Read the specified number of bytes
                raw = np.frombuffer(f.read(num_bytes_to_read), dtype=np.int16)
            else:
                raw = np.frombuffer(f.read(), dtype=np.int16)
        return raw

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
    
    def note_to_midinumber(self, note: str) -> int:  # TODO: move this function
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

    def midinumber_to_note(self, midinumber: int) -> str:  # TODO: move this function
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
            return self.load_sample(self.samples[note], duration=duration)
        else:
            # If the note does not exist, use pitch shifting to generate it
            return self.pitch_shift(note, duration=duration)

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
        closest_sample = self.load_sample(closest_sample_path, duration=None if duration is None else (duration+0.1)*shift_factor)

        # Use numpy interpolation to achieve pitch shifting
        original_length = len(closest_sample)
        new_length = int(original_length / shift_factor)
        indices = np.arange(new_length) * shift_factor
        indices = indices[indices < original_length]  # Ensure indices are within range
        shifted_sample = np.interp(indices, np.arange(original_length), closest_sample)

        if duration is not None and duration > 0:
            target_samples = int(duration * self.rate)
            return np.array(shifted_sample[:target_samples], dtype=np.int16)

        return np.array(shifted_sample, dtype=np.int16)

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
    # Define buffer size in samples
    # Based on user's BUFFER_BYTES = 4096 and bytes_per_sample = 2 (16-bit mono)
    BUFFER_SAMPLES = 1024
    BUFFER_BYTES = BUFFER_SAMPLES * 2 # Calculate bytes based on samples (assuming 16-bit mono)

    def __init__(
        self,
        sck_pin: int = 48,
        ws_pin: int = 47,
        sd_pin: int = 45,
        i2s_id: int = 0,
        bits: int = 16,
        format=I2S.MONO,
        rate=16000,
        ibuf: int = 8192,
        max_voices: int = 8,
        buffer_samples: int = 1024,
        volume_factor: float = 0.2,
        always_play: bool = False,  # Always write to buffer to trigger callback.
    ):
        if bits != 16 or format != I2S.MONO:
             raise ValueError("Supports only 16-bit MONO audio")

        self.BUFFER_SAMPLES = buffer_samples
        self.BUFFER_BYTES = self.BUFFER_SAMPLES * 2
        self.always_play = always_play

        self.audio_out = I2S(
            i2s_id,
            sck=Pin(sck_pin),
            ws=Pin(ws_pin),
            sd=Pin(sd_pin),
            mode=I2S.TX,
            bits=bits,
            format=format,
            rate=rate,
            ibuf=ibuf,
        )

        self.bits = bits
        self.format = format
        self.rate = rate
        self.max_voices = max_voices
        self.bytes_per_sample = (self.bits // 8) * (self.format + 1) # Should be 2
        self.volume_factor = volume_factor

        # Double buffers (NumPy int16 arrays)
        self.audio_buffers = [
            np.zeros(self.BUFFER_SAMPLES, dtype=np.int16),
            np.zeros(self.BUFFER_SAMPLES, dtype=np.int16),
        ]
        # Valid samples mixed into each buffer
        self.valid_samples = [0, 0]
        self.buffer_to_play_idx = 0 # Index of buffer to play next

        # File Caching
        self._loaded_wavs = {} # Stores {filepath: bytearray_data}

        # Temp buffer for reading from file (bytes) and converting (int16)
        self.reading_buffer_bytes = bytearray(self.BUFFER_BYTES)
        self.reading_buffer_mv = memoryview(self.reading_buffer_bytes)
        # Temporary NumPy buffer to convert file bytes to int16 before mixing
        self._reading_temp_buffer_int16 = np.zeros(self.BUFFER_SAMPLES, dtype=np.int16)


        # Playback state
        self._is_playing = False
        # Active voices: List of [loaded_data: bytearray, current_pos_bytes: int]
        # Store position in bytes as data is bytearray
        # TODO: store to slots instead of using list
        self.active_voices: List[Voice] = []
        self.added_voices: List[Voice] = []
        self.disabled_voices: Dict[int, int] = {}
        self.voice_num = 0
        self._all_voices_fully_processed = True # True when no voices are active

        # Simple Delay Effect State - REMOVED

        # I2S Interrupt setup
        self.audio_out.irq(self._i2s_callback)
        if self.always_play:
            self._i2s_callback(self)

    def load_wav(self, wav_file: str, wav_data: Optional[bytearray] = None):
        """Loads WAV file data into memory cache."""
        if wav_file in self._loaded_wavs:
            print(f"'{wav_file}' already loaded.")
            return self._loaded_wavs[wav_file]

        if wav_data is None:
            print(f"Loading '{wav_file}'...")
            with open(wav_file, "rb") as f:
                f.seek(44) # Skip WAV header
                wav_data = bytearray(f.read())

        self._loaded_wavs[wav_file] = wav_data
        print(f"Loaded '{wav_file}' ({len(wav_data)} bytes).")
        return wav_data

    def unload_wav(self, wav_file: str):
        """Pop WAV file data from memory cache."""
        # TODO: FIFO Dict
        self._loaded_wavs.pop(wav_file)

    def _prepare_buffer(self, buffer_idx: int):
        """Mixes active voices (from memory) using NumPy."""
        target_buffer_np = self.audio_buffers[buffer_idx]
        target_buffer_np[:] = 0 # Clear target NumPy buffer

        total_samples_mixed = 0

        for voice in self.added_voices:
            if not (voice.finished or voice.active):
                self.active_voices.append(voice)
                voice.active = True

        # Max voices check
        if len(self.active_voices) >= self.max_voices:
            if self.active_voices:
                # Oldest voice is [loaded_data, current_pos_bytes]
                oldest_voice = self.active_voices.pop(0)
                print(f"pop voice: {oldest_voice.voice_name}")
                # No file object to close

        # Iterate through active voices [loaded_data, current_pos_bytes]
        for voice_info in self.active_voices:
            loaded_data = voice_info.loaded_data # The bytearray data
            current_pos_bytes = voice_info.current_pos_bytes # Current read position in bytes
            voice_name = voice_info.voice_name
            voice_id = voice_info.voice_id
            start_time = voice_info.start_time
            current_ms = time.ticks_ms()

            if voice_info.finished:
                print(f"finished '{voice_name}'  at {current_ms}.")
                continue

            if voice_id in self.disabled_voices and self.disabled_voices[voice_id] > start_time and current_ms > self.disabled_voices[voice_id]:
                voice_info.finished = True
                print(f"stopping '{voice_name}, {voice_id}'  at {current_ms}.")
                continue

            # Get memory slice for the current chunk (bytes)
            # chunk_bytes_mv = memoryview(loaded_data)[current_pos_bytes : current_pos_bytes + self.BUFFER_BYTES]
            chunk_bytes_mv = loaded_data[current_pos_bytes : current_pos_bytes + self.BUFFER_BYTES]
            num_read_bytes = len(chunk_bytes_mv)
            num_read_samples = num_read_bytes // self.bytes_per_sample if self.bytes_per_sample > 0 else 0

            if num_read_samples > 0:
                # Convert bytes chunk (memoryview) to int16 NumPy array
                # Assumes np.frombuffer works on memoryview
                temp_int16_chunk = np.frombuffer(chunk_bytes_mv, dtype=np.int16)

                # Mix into the target buffer using NumPy addition
                # Ensure slices match size
                if self.volume_factor > 0:
                    target_buffer_np[:num_read_samples] += temp_int16_chunk[:num_read_samples] // int(1 / self.volume_factor)
                
                total_samples_mixed = max(total_samples_mixed, num_read_samples)  
                # Update position for this voice (in bytes)
                voice_info.current_pos_bytes += num_read_bytes

            # Check if this voice finished reading (reached end of loaded data)
            if current_pos_bytes + num_read_bytes >= len(loaded_data):
                voice_info.finished = True

        # Remove finished voices
        self.active_voices = [voice for voice in self.active_voices if not voice.finished]

        self.valid_samples[buffer_idx] = total_samples_mixed
        self._all_voices_fully_processed = not self.active_voices

        # Apply Clipping to the mixed buffer (NumPy)
        if total_samples_mixed > 0:
            # Apply clip to the relevant slice of the target buffer
            self.audio_buffers[buffer_idx][:total_samples_mixed] = np.clip(
                self.audio_buffers[buffer_idx][:total_samples_mixed],
                -32768, 32767 # int16 min/max
            )

    def _i2s_callback(self, caller):
        """I2S IRQ Callback."""
        if not self._is_playing:
            print("I2S callback: Not playing.")
            self.stop_all()
            return

        play_idx = self.buffer_to_play_idx
        samples_to_play = self.valid_samples[play_idx]
        prep_idx = (play_idx + 1) % 2

        write_tiggered = False

        # Write the prepared buffer to I2S if it has data
        if samples_to_play > 0:
            # Convert NumPy int16 slice to bytes
            # Assumes ndarray.tobytes() exists
            byte_data = self.audio_buffers[play_idx][:samples_to_play].tobytes()
            self.audio_out.write(byte_data)
            write_tiggered = True
        elif self.always_play:
            byte_data = self.audio_buffers[play_idx][:self.BUFFER_BYTES].tobytes()
            self.audio_out.write(byte_data)
            write_tiggered = True
        # else:
        #     print(f"Nothing write to I2S, stopping... active_voices: {len(self.active_voices)}, added_voices: {len(self.added_voices)}")
        #     self.stop_all()

        # Update state for the next IRQ
        self.buffer_to_play_idx = prep_idx
        # Trigger preparation of the NEXT buffer
        self._prepare_buffer(prep_idx)

        # Check if playback should stop
        # Stops if _is_playing is False or if all voices processed AND the buffer just played was empty
        if self.always_play:
            assert write_tiggered, "write not triggered!"
        elif not (len(self.active_voices) > 0 or write_tiggered):
            self.stop_all()
        elif not write_tiggered:
            print(f"Nothing write to I2S, retriggering...")
            assert caller is not self, "Loop"
            self._i2s_callback(self)


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
        self.added_voices = [voice for voice in self.added_voices if not (voice.active or voice.finished)]
        voice = Voice(self.voice_num, loaded_data, 0, nickname or wav_file, time.ticks_ms())
        self.added_voices.append(voice)
        self.voice_num += 1
        if playtime is not None:
            self.disabled_voices[voice.voice_id] = time.ticks_ms() + playtime
        print(f"starting '{wav_file}' at {time.ticks_ms()}.")

        # If not playing, start the process
        if not self._is_playing:
            self._is_playing = True
            self._all_voices_fully_processed = False

            # Prepare the initial two buffers (in main thread)
            # self._prepare_buffer(0) # blanck buffer
            self.audio_buffers[0][:] = 0
            self.audio_buffers[1][:] = 0
            self.valid_samples = [self.BUFFER_SAMPLES, self.BUFFER_SAMPLES]
            byte_data_init = self.audio_buffers[0][:].tobytes()
            self.audio_out.write(byte_data_init)
            self.buffer_to_play_idx = 1 # Next IRQ plays buffer 1
            # self.buffer_to_play_idx = 0
            # self._i2s_callback(self)
        return voice.voice_id

    def stop_note(self, wav_file: Optional[str] = None, wav_id: Optional[int] = None, delay: Optional[int] = None):
        if wav_id is not None:
            self.disabled_voices[wav_id] = time.ticks_ms() + (delay or 0)
        elif wav_file is not None:
            for voice in self.added_voices:
                if voice.voice_name == wav_file:
                    self.disabled_voices[voice.voice_id] = time.ticks_ms() + (delay or 0)
            for voice in self.active_voices:
                if voice.voice_name == wav_file:
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
            self.active_voices.clear()
            self.disabled_voices.clear()
            for voice in self.added_voices:
                assert voice.active, f"Voice not actived before stop: {voice.voice_name}"
            self.added_voices.clear()

            # Reset buffer state (NumPy buffers)
            self.audio_buffers[0][:] = 0
            self.audio_buffers[1][:] = 0
            self.valid_samples = [0, 0]
            self.buffer_to_play_idx = 0
            self._all_voices_fully_processed = True

            # Reset delay effect state - REMOVED


    def get_is_playing(self):
        """Returns True if playback is active."""
        return self._is_playing

    def __del__(self):
        self.stop_all()


# --- Example Usage ---
def main():
    time.sleep_ms(1000) # Sleep before starting audio
    audio_manager = AudioManager(
        rate=16000,
        buffer_samples=512,
        always_play=False
    )

    # Load WAV files into memory first
    print("Loading WAVs...")
    sampler = Sampler("/wav/piano/16000")
    for note in ["C5", "D5", "E5", "F5", "G5", "A5", "B5", "C6"]:
        audio_manager.load_wav(note, sampler.get_sample(note).tobytes())
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


def midi_example():
    import umidiparser
    from umidiparser import MidiFile, MidiEvent
    file_path = "fukakai – KAF - Treble - Piano.mid"

    time.sleep_ms(1000) # Sleep before starting audio
    audio_manager = AudioManager(
        rate=16000,
        buffer_samples=512,
        always_play=False,
        volume_factor=0.1
    )

    # Load WAV files into memory first
    print("Loading WAVs...")
    sampler = Sampler("/wav/piano/16000")
    for note in ["C", "D", "E", "F", "G", "A", "A#", "B"]:
        for i in range(2, 7):
            audio_manager.load_wav(f"{note}{i}", sampler.get_sample(f"{note}{i}", duration=1.8).tobytes())
    audio_manager.load_wav("A#1", sampler.get_sample("A#1", duration=1.8).tobytes())
    audio_manager.load_wav("C6", sampler.get_sample("C6", duration=1.8).tobytes())
    print("Loading complete.")

    delta_tick_ms = 0.932835

    for event in MidiFile(file_path, reuse_event_object=True).play():
        # .play will sleep, avoiding time drift, before returning the event on time
        # Process the event according to type
        event: MidiEvent
        if event.status == umidiparser.NOTE_ON:
            note = sampler.midinumber_to_note(event.note)  # TODO: mode
            if event.delta_miditicks > 1:
                playtime = int(event.delta_miditicks * delta_tick_ms)
                print(note, playtime)
                # print(f"NOTE_ON({playtime})", event)
                # ... start the note with midi number event.note 
                audio_manager.play_note(note, playtime=playtime)
        # on channel event.channel with event.velocity
        elif event.status == umidiparser.NOTE_OFF :
            print("NOTE_OFF", event)
            # ... stop the note event.note .
        elif event.status == umidiparser.PROGRAM_CHANGE:
            print("PROGRAM_CHANGE", event)
            # ... change midi program to event.program on event.channel ....
        elif event.status == 0x51:
            print("SET_TEMPO", event)
        else:
            # Show all events not processed
            print("other event", event)

if __name__ == "__main__":
    # main()
    midi_example()

