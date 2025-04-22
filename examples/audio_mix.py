# import _thread # Not needed
import time
# import gc # Not needed
# import ulab.numpy as np  # Not needed

from machine import Pin
from machine import I2S
import os
import struct # For byte conversion


class AudioManager:
    # Use a fixed buffer size in bytes based on original code
    BUFFER_BYTES = 1024

    def __init__(
        self,
        sck_pin: int = 48,
        ws_pin: int = 47,
        sd_pin: int = 45,
        i2s_id: int = 0,
        bits: int = 16,
        format=I2S.MONO,
        rate=16000,
        ibuf: int = 65536, # Using original ibuf default
        max_voices: int = 8
    ):
        if bits != 16 or format != I2S.MONO:
             raise ValueError("Supports only 16-bit MONO 16-bit audio")

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

        # Double buffers (bytearray)
        self.audio_buffers = [
            bytearray(self.BUFFER_BYTES),
            bytearray(self.BUFFER_BYTES),
        ]
        self.valid_bytes = [0, 0] # Valid bytes mixed into each buffer
        self.buffer_to_play_idx = 0 # Index of buffer to play next

        # Temp buffer for reading from file
        self.reading_buffer_bytes = bytearray(self.BUFFER_BYTES)
        self.reading_buffer_mv = memoryview(self.reading_buffer_bytes)

        # Playback state
        self._is_playing = False
        self.active_voices = [] # List of [file_object]
        self._all_voices_fully_processed = True # True when no voices are active

        # I2S Interrupt setup
        self.audio_out.irq(self._i2s_callback)


    def _prepare_buffer(self, buffer_idx: int):
        """Mixes active voices into the specified buffer (byte-level)."""
        # Clear the target buffer
        self.audio_buffers[buffer_idx][:] = b'\x00' * self.BUFFER_BYTES
        total_bytes_mixed = 0
        voices_finished_this_chunk = []

        i = 0
        while i < len(self.active_voices):
            voice_info = self.active_voices[i] # [file_object]
            wav = voice_info[0]

            bytes_to_read = self.BUFFER_BYTES
            num_read_bytes = wav.readinto(self.reading_buffer_mv, bytes_to_read)

            if num_read_bytes > 0:
                # Manually mix bytes from reading_buffer_bytes into audio_buffers[buffer_idx]
                # This assumes 16-bit stereo or mono, stepping by 2 bytes.
                # Adapting _mix_audio logic for mixing into a fresh buffer.

                for j in range(0, num_read_bytes, 2):
                    # Read existing sample from target buffer (initially 0)
                    current_sample_bytes = self.audio_buffers[buffer_idx][j : j + 2]
                    current_sample = struct.unpack('<h', current_sample_bytes)[0]

                    # Read new sample from the voice chunk (reading_buffer_bytes)
                    new_sample_bytes = self.reading_buffer_bytes[j : j + 2]
                    new_sample = struct.unpack('<h', new_sample_bytes)[0]

                    # Mix (add)
                    mixed_sample = current_sample + new_sample

                    # Clip to 16-bit range (-32768 to 32767)
                    mixed_sample = max(-32768, min(32767, mixed_sample))

                    # Write back to target buffer
                    struct.pack_into('<h', self.audio_buffers[buffer_idx], j, mixed_sample)

                total_bytes_mixed = max(total_bytes_mixed, num_read_bytes)

            # Check if this voice finished reading
            if num_read_bytes < bytes_to_read:
                 voices_finished_this_chunk.append(i)

            i += 1

        # Remove finished voices (iterate in reverse)
        for i in sorted(voices_finished_this_chunk, reverse=True):
             if i < len(self.active_voices):
                 voice_info_to_close = self.active_voices[i]
                 # Close the file object
                 if isinstance(voice_info_to_close, list) and len(voice_info_to_close) > 0 and hasattr(voice_info_to_close[0], 'close'):
                     voice_info_to_close[0].close()
                 # Remove from list
                 if i < len(self.active_voices):
                     del self.active_voices[i]


        self.valid_bytes[buffer_idx] = total_bytes_mixed

        # No global clipping needed after the loop, it's done per-sample in mixing.

        self._all_voices_fully_processed = not self.active_voices


    def _i2s_callback(self, caller):
        """I2S IRQ Callback."""
        if not self._is_playing:
            return

        play_idx = self.buffer_to_play_idx
        bytes_to_play = self.valid_bytes[play_idx]
        prep_idx = (play_idx + 1) % 2

        # Write the prepared buffer to I2S if it has data
        if bytes_to_play > 0:
            # Write the byte data directly
            self.audio_out.write(self.audio_buffers[play_idx][:bytes_to_play])

        # Update state for the next IRQ
        self.buffer_to_play_idx = prep_idx

        # Trigger preparation of the NEXT buffer
        self._prepare_buffer(prep_idx)

        # Check if playback should stop
        # Stops if _is_playing is False or if all voices processed AND the buffer just played was empty
        if not self._is_playing or (self._all_voices_fully_processed and bytes_to_play == 0):
             self.stop_all()


    def play_note(self, wav_file: str):
        """Plays a note (non-blocking)."""
        # Max voices check
        if len(self.active_voices) >= self.max_voices:
            if self.active_voices:
                oldest_voice = self.active_voices.pop(0)
                if isinstance(oldest_voice, list) and len(oldest_voice) > 0 and hasattr(oldest_voice[0], 'close'):
                   oldest_voice[0].close()

        # Open WAV file and add to voices
        wav = open(wav_file, "rb")
        wav.seek(44) # Skip header
        self.active_voices.append([wav])

        # If not playing, start the process
        if not self._is_playing:
            self._is_playing = True
            self._all_voices_fully_processed = False
            
            # Prepare the initial two buffers
            self._prepare_buffer(0)
            self._prepare_buffer(1)
            # --- Initiate playback by writing the first buffer ---
            # This first write fills the I2S buffer and should trigger the first IRQ.
            bytes_to_write_init = self.valid_bytes[0]
            if bytes_to_write_init > 0:
                self.audio_out.irq(self._i2s_callback)  # Restore IRQ state
                self.audio_out.write(self.audio_buffers[0][:bytes_to_write_init])
                # Set the next buffer to play to buffer 1, which was just prepared
                self.buffer_to_play_idx = 1
            else:
                # If the first buffer prepared was empty, stop immediately.
                self.stop_all()
                self.buffer_to_play_idx = 0 # Ensure index is reset



    def stop_all(self):
        """Stops all voices and playback."""
        self.audio_out.irq(None)

        if self._is_playing:
            self._is_playing = False

            # Close all active voice files
            for i in range(len(self.active_voices) -1, -1, -1):
                 voice_info = self.active_voices[i]
                 if isinstance(voice_info, list) and len(voice_info) > 0 and hasattr(voice_info[0], 'close'):
                    voice_info[0].close()
                 if i < len(self.active_voices):
                     del self.active_voices[i]

            self.active_voices.clear()

            # Reset buffer state
            self.audio_buffers[0][:] = b'\x00' * self.BUFFER_BYTES
            self.audio_buffers[1][:] = b'\x00' * self.BUFFER_BYTES
            self.valid_bytes = [0, 0]
            self.buffer_to_play_idx = 0
            self._all_voices_fully_processed = True


    def get_is_playing(self):
        """Returns True if playback is active."""
        return self._is_playing

    def __del__(self):
        self.stop_all()
        # self.audio_out.deinit()


# --- Example Usage ---
def main():
    time.sleep_ms(1000) # Sleep before starting audio
    # Create AudioManager instance with default parameters
    audio_manager = AudioManager()

    print("wav/piano/16000/C4vH.wav")
    audio_manager.play_note("wav/piano/16000/C4vH.wav")
    time.sleep_ms(1000)

    print("wav/piano/16000/A3vH.wav")
    audio_manager.play_note("wav/piano/16000/A3vH.wav")
    time.sleep_ms(1000)

    print("wav/piano/16000/A4vH.wav")
    audio_manager.play_note("wav/piano/16000/A4vH.wav")
    time.sleep_ms(4000)
    audio_manager.stop_all()

if __name__ == "__main__":
    # Ensure your WAV files exist at the specified paths (e.g., /sd/wav/piano/16000/C4vH.wav)
    main()
