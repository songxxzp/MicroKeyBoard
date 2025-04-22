import time

from machine import Pin
from machine import I2S
from typing import Optional
from ulab import numpy as np


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
        ibuf: int = 16384,
        max_voices: int = 8,
        buffer_samples: int = 1024,
    ):
        if bits != 16 or format != I2S.MONO:
             raise ValueError("Supports only 16-bit MONO audio")

        self.BUFFER_SAMPLES = buffer_samples
        self.BUFFER_BYTES = self.BUFFER_SAMPLES * 2

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
        self.active_voices = []
        self.disabled_voices = {}
        self._all_voices_fully_processed = True # True when no voices are active

        # Simple Delay Effect State - REMOVED

        # I2S Interrupt setup
        self.audio_out.irq(self._i2s_callback)

    def load_wav(self, wav_file: str):
        """Loads WAV file data into memory cache."""
        if wav_file in self._loaded_wavs:
            print(f"'{wav_file}' already loaded.")
            return self._loaded_wavs[wav_file]

        print(f"Loading '{wav_file}'...")
        with open(wav_file, "rb") as f:
            f.seek(44) # Skip WAV header
            wav_data = bytearray(f.read())

        self._loaded_wavs[wav_file] = wav_data
        print(f"Loaded '{wav_file}' ({len(wav_data)} bytes).")
        return wav_data

    def _prepare_buffer(self, buffer_idx: int):
        """Mixes active voices (from memory) using NumPy."""
        target_buffer_np = self.audio_buffers[buffer_idx]
        target_buffer_np[:] = 0 # Clear target NumPy buffer

        total_samples_mixed = 0
        voices_finished_this_chunk = []

        # Iterate through active voices [loaded_data, current_pos_bytes]
        i = 0
        while i < len(self.active_voices):
            voice_info = self.active_voices[i]
            loaded_data = voice_info[0] # The bytearray data
            current_pos_bytes = voice_info[1] # Current read position in bytes
            voice_name = voice_info[2]
            start_time = voice_info[3]

            # Get memory slice for the current chunk (bytes)
            chunk_bytes_mv = memoryview(loaded_data)[current_pos_bytes : current_pos_bytes + self.BUFFER_BYTES]
            num_read_bytes = len(chunk_bytes_mv)
            num_read_samples = num_read_bytes // self.bytes_per_sample if self.bytes_per_sample > 0 else 0

            if num_read_samples > 0:
                # Convert bytes chunk (memoryview) to int16 NumPy array
                # Assumes np.frombuffer works on memoryview
                temp_int16_chunk = np.frombuffer(chunk_bytes_mv, dtype=np.int16)

                # Mix into the target buffer using NumPy addition
                # Ensure slices match size
                target_buffer_np[:num_read_samples] += temp_int16_chunk[:num_read_samples]

                total_samples_mixed = max(total_samples_mixed, num_read_samples)
                # Update position for this voice (in bytes)
                voice_info[1] += num_read_bytes


            # Check if this voice finished reading (reached end of loaded data)
            if current_pos_bytes + num_read_bytes >= len(loaded_data):
                voices_finished_this_chunk.append(i)
            if voice_name in self.disabled_voices and self.disabled_voices[voice_name] > start_time:
                voices_finished_this_chunk.append(i)

            i += 1

        # Remove finished voices
        for i in sorted(voices_finished_this_chunk, reverse=True):
             if i < len(self.active_voices):
                 del self.active_voices[i]

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
            return

        play_idx = self.buffer_to_play_idx
        samples_to_play = self.valid_samples[play_idx]
        prep_idx = (play_idx + 1) % 2

        # Write the prepared buffer to I2S if it has data
        if samples_to_play > 0:
            # Convert NumPy int16 slice to bytes
            # Assumes ndarray.tobytes() exists
            byte_data = self.audio_buffers[play_idx][:samples_to_play].tobytes()
            self.audio_out.write(byte_data)

        # Update state for the next IRQ
        self.buffer_to_play_idx = prep_idx
        # Trigger preparation of the NEXT buffer
        self._prepare_buffer(prep_idx)

        # Check if playback should stop
        # Stops if _is_playing is False or if all voices processed AND the buffer just played was empty
        if not self._is_playing or (self._all_voices_fully_processed and samples_to_play == 0):
             self.stop_all()

    def play_note(self, wav_file: str, nickname: Optional[str] = None):
        """Plays a note (non-blocking). Adds the WAV file data (from cache) to active voices."""

        # Ensure file is loaded into memory cache first
        # load_wav will raise an error if file not found, stopping execution as requested
        if wav_file not in self._loaded_wavs:
             self.load_wav(wav_file)

        # Get loaded data from cache
        loaded_data = self._loaded_wavs[wav_file]

        # Max voices check
        if len(self.active_voices) >= self.max_voices:
            if self.active_voices:
                # Oldest voice is [loaded_data, current_pos_bytes]
                oldest_voice = self.active_voices.pop(0)
                # No file object to close

        # Add new voice with loaded data and start position 0
        # Position is in bytes
        self.active_voices.append([loaded_data, 0, wav_file, time.time()])
        print(f"startting '{wav_file}' at {time.time()}. len(self.active_voices): {len(self.active_voices)}")

        # If not playing, start the process
        if not self._is_playing:
            self._is_playing = True
            self._all_voices_fully_processed = False

            # Prepare the initial two buffers (in main thread)
            self._prepare_buffer(0)
            self._prepare_buffer(1) # Prepare the second buffer immediately after writing the first

            # Initiate playback by writing the first buffer
            # IRQ callback is already set up in __init__ and will be triggered
            # when the I2S buffer needs data after this write.
            samples_to_write_init = self.valid_samples[0]
            if samples_to_write_init > 0:
                # Convert NumPy int16 slice to bytes for initial write
                byte_data_init = self.audio_buffers[0][:samples_to_write_init].tobytes()
                self.audio_out.write(byte_data_init)
                self.buffer_to_play_idx = 1 # Next IRQ plays buffer 1
            else:
                # If the first buffer prepared was empty, stop immediately.
                self.stop_all()
                self.buffer_to_play_idx = 0 # Ensure index is reset

    def stop_note(self, wav_file: str):
        self.disabled_voices[wav_file] = time.time()
        print(f"stopping '{wav_file}'  at {time.time()}.")

    def stop_all(self):
        """Stops all voices and playback."""
        # Keep IRQ enabled but rely on _is_playing flag and empty voices/buffers

        if self._is_playing:
            self._is_playing = False

            # Active voices only contain data and position
            self.active_voices.clear()

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
        rate=8000,
        buffer_samples=256
    )

    # Load WAV files into memory first
    print("Loading WAVs...")
    audio_manager.load_wav("wav/piano/8000/C4.wav")
    audio_manager.load_wav("wav/piano/8000/D4.wav")
    audio_manager.load_wav("wav/piano/8000/E4.wav")
    audio_manager.load_wav("wav/piano/8000/F4.wav")
    audio_manager.load_wav("wav/piano/8000/G4.wav")
    audio_manager.load_wav("wav/piano/8000/A4.wav")
    audio_manager.load_wav("wav/piano/8000/B4.wav")
    audio_manager.load_wav("wav/piano/8000/C5.wav")
    print("Loading complete.")

    quarter = 556
    eighth = 278
    sixteenth = 139

    audio_manager.play_note("wav/piano/8000/E4.wav")
    time.sleep_ms(quarter)
    
    audio_manager.play_note("wav/piano/8000/D4.wav")
    audio_manager.stop_note("wav/piano/8000/E4.wav")
    time.sleep_ms(eighth)

    audio_manager.play_note("wav/piano/8000/C4.wav")
    audio_manager.stop_note("wav/piano/8000/D4.wav")
    time.sleep_ms(quarter)

    audio_manager.play_note("wav/piano/8000/D4.wav")
    audio_manager.stop_note("wav/piano/8000/C4.wav")
    time.sleep_ms(eighth)

    audio_manager.play_note("wav/piano/8000/E4.wav")
    audio_manager.stop_note("wav/piano/8000/D4.wav")
    time.sleep_ms(eighth + sixteenth)

    audio_manager.play_note("wav/piano/8000/F4.wav")
    audio_manager.stop_note("wav/piano/8000/E4.wav")
    time.sleep_ms(sixteenth)
    
    audio_manager.play_note("wav/piano/8000/E4.wav")
    audio_manager.stop_note("wav/piano/8000/F4.wav")
    time.sleep_ms(eighth)
    
    audio_manager.play_note("wav/piano/8000/D4.wav")
    audio_manager.stop_note("wav/piano/8000/E4.wav")
    time.sleep_ms(quarter + eighth)
    audio_manager.stop_note("wav/piano/8000/D4.wav")

    audio_manager.stop_all()


if __name__ == "__main__":
    main()
