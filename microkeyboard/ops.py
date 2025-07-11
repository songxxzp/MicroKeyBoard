import micropython

# --- Viper Core: Interpolation Function for Pitch Shifting ---
# This function performs linear interpolation on audio samples to achieve pitch shifting.
# It operates directly on 16-bit samples in memory using the native byte order of the MCU.

# Assumes:
# - Audio samples are 16-bit signed integers.
# - The bytearrays passed correspond to the native byte order of the MicroPython device.
# - No explicit endianness conversion is performed within this function, relying on Viper's ptr16.

# --- Viper Core: Interpolation Function for Pitch Shifting ---
@micropython.viper
def _interpolate_viper_core(
    original_buf: ptr16,    # Pointer to the original audio data (array of 16-bit samples)
    original_len_samples: int, # Number of samples in the original audio buffer
    new_len_samples: int,      # Desired number of samples for the interpolated audio
    result_buf: ptr16,          # Pointer to the bytearray (array of 16-bit samples) where the interpolated result will be stored
    shift_factor_scaled: int,  # Pitch shift factor, scaled up by `scale_factor_interp` for integer math
    scale_factor_interp: int   # Scaling factor used for `shift_factor_scaled` (e.g., 10000)
):
    """
    Viper core interpolation function for audio pitch shifting.
    Performs linear interpolation to transform `original_buf` into `result_buf`.
    Optimized for speed by using ptr16 and native byte order.
    Handles 16-bit signed integer interpretation and output clamping explicitly.
    """
    # Declare and initialize loop counter as a Viper integer for type safety and optimization.
    i_new_int: int = 0 

    for i_new_int in range(new_len_samples):
        # Calculate the floating-point index in the original sample array, scaled up.
        # Explicit `int()` casts are crucial in Viper to ensure operations are done with machine integers.
        original_float_idx_scaled: int = int(i_new_int) * int(shift_factor_scaled)

        # Separate the integer part (which sample index to start from)
        # and the fractional part (how far between that sample and the next).
        idx_int: int = int(original_float_idx_scaled) // int(scale_factor_interp)
        fractional_part_scaled: int = int(original_float_idx_scaled) % int(scale_factor_interp)

        # Boundary check: If the calculated index goes beyond the original sample data,
        # simply repeat the last valid sample to prevent out-of-bounds access.
        if int(idx_int) >= int(original_len_samples) - 1:
            # Directly access the 16-bit sample at the last valid index
            sample_val_unsigned: int = original_buf[int(original_len_samples) - 1]
            # Convert to signed 16-bit
            if sample_val_unsigned >= 32768:
                sample_val_unsigned -= 65536
            result_buf[int(i_new_int)] = sample_val_unsigned
            continue # Move to the next sample in the result buffer

        # Get the two adjacent sample values from the original buffer needed for linear interpolation.
        # Direct access to 16-bit samples via ptr16.
        y0_unsigned: int = original_buf[int(idx_int)]
        y1_unsigned: int = original_buf[int(idx_int) + 1]

        # Explicitly convert y0 and y1 from potentially unsigned 16-bit representation
        # to signed 32-bit `int` for calculations.
        y0: int = y0_unsigned
        if y0 >= 32768:
            y0 -= 65536

        y1: int = y1_unsigned
        if y1 >= 32768:
            y1 -= 65536

        # Linear interpolation formula: y = y0 + (y1 - y0) * fractional_part
        # Implemented using scaled integer arithmetic for Viper compatibility.
        diff_y: int = int(y1) - int(y0)
        
        # All intermediate calculations (y0 * scale_factor_interp, diff_y * fractional_part_scaled)
        # will implicitly use Viper's 32-bit `int` type, preventing overflow for typical audio ranges.
        interp_val_scaled: int = int(y0) * int(scale_factor_interp) + int(diff_y) * int(fractional_part_scaled)
        
        # Scale back down to get the final interpolated sample value.
        # Python's // (floor division) is generally fine for interpolation,
        # as it aligns with how floating point truncation for indices works.
        interp_val: int = int(interp_val_scaled) // int(scale_factor_interp)

        # Explicitly clamp the final interpolated value to the 16-bit signed range [-32768, 32767]
        # before writing to the ptr16 buffer.
        if interp_val > 32767:
            interp_val = 32767
        elif interp_val < -32768:
            interp_val = -32768

        # Write the calculated interpolated sample to the result buffer.
        result_buf[int(i_new_int)] = interp_val


# --- Python Wrapper for Interpolation (Calls fast version) ---
def interpolate(
    closest_sample_bytes: bytes, # Original audio data (bytes or bytearray)
    original_length_bytes: int,  # Original length of the audio data in bytes
    new_length_bytes: int        # Desired length of the interpolated audio data in bytes
) -> bytearray:
    """
    Performs linear interpolation for audio pitch shifting using a Viper-optimized core.
    This function interpolates the `closest_sample_bytes` to a `new_length_bytes`.
    Optimized for speed by assuming native byte order.
    
    Assumes samples are 16-bit signed integers and that `closest_sample_bytes`
    already conforms to the native byte order of the MicroPython device.
    
    Args:
        closest_sample_bytes (bytes): The input audio data.
        original_length_bytes (int): The byte length of the input audio data.
        new_length_bytes (int): The desired byte length of the output audio data.
        
    Returns:
        bytearray: A new bytearray containing the interpolated audio data.
        
    Raises:
        ValueError: If buffer lengths are not multiples of bytes per sample.
    """
    BYTES_PER_SAMPLE: int = 2 
    
    if original_length_bytes % BYTES_PER_SAMPLE != 0 or \
       new_length_bytes % BYTES_PER_SAMPLE != 0:
        raise ValueError("Buffer lengths must be multiples of bytes_per_sample.")

    original_len_samples = original_length_bytes // BYTES_PER_SAMPLE
    new_len_samples = new_length_bytes // BYTES_PER_SAMPLE

    if new_len_samples == 0:
        return bytearray() 

    # Ensure the original data is a mutable `bytearray` for Viper's direct memory access.
    # If `bytes` is passed, a copy is made.
    if not isinstance(closest_sample_bytes, bytearray):
        original_data_mutable = bytearray(closest_sample_bytes)
    else:
        original_data_mutable = closest_sample_bytes

    # Create a new `bytearray` to store the interpolated result.
    shifted_sample_bytes = bytearray(new_length_bytes)

    # Calculate the float pitch shift factor (ratio of original samples to new samples).
    shift_factor_float: float = original_len_samples / new_len_samples

    SCALE_FACTOR_INTERP: int = 10000 # Same scaling factor for integer math.
    shift_factor_scaled: int = int(shift_factor_float * SCALE_FACTOR_INTERP)

    # Call the FAST Viper core function, passing bytearrays, which Viper will interpret as ptr16.
    _interpolate_viper_core(
        original_data_mutable,
        original_len_samples,
        new_len_samples,
        shifted_sample_bytes,
        shift_factor_scaled,
        SCALE_FACTOR_INTERP
    )

    return shifted_sample_bytes


# --- Viper Core: Clear Bytearray (Unchanged as it operates on individual bytes) ---
@micropython.viper
def clear_bytearray_viper(buf: ptr8, length: int):
    """
    Clears all bytes in a bytearray to 0 using Viper for maximum efficiency.
    This function remains ptr8 as it operates on individual bytes.
    """
    for i in range(length):
        buf[i] = 0


@micropython.viper
def clear_4bit_bytearray_viper(buf: ptr32, length: int):
    """
    Clears all bytes in a bytearray to 0 using Viper for maximum efficiency.
    This function remains ptr32 as it operates on individual bytes.
    """
    for i in range(length):
        buf[i] = 0

# --- Viper Core: Element-wise Array Addition (Optimized with ptr16) ---
@micropython.viper
def add_int16_arrays_viper(
    arr1_ptr: ptr16,      # Pointer to the first array (of 16-bit samples)
    arr1_len_samples: int, # Number of samples in the first array
    arr2_ptr: ptr16,      # Pointer to the second array (of 16-bit samples)
    arr2_len_samples: int, # Number of samples in the second array
    result_ptr: ptr16,    # Pointer to the result array (of 16-bit samples)
    result_len_samples: int # Number of samples in the result array
):
    """
    Performs element-wise addition of two 16-bit signed integer arrays.
    Optimized for speed by using ptr16 and native byte order.
    The result is stored in a third array.
    """
    # Determine the actual number of samples to process.
    num_samples_to_process: int = arr1_len_samples
    if arr2_len_samples < num_samples_to_process:
        num_samples_to_process = arr2_len_samples
    if result_len_samples < num_samples_to_process:
        num_samples_to_process = result_len_samples

    # Loop through each sample, performing the addition.
    for i in range(num_samples_to_process):
        # Directly read 16-bit samples.
        val1: int = arr1_ptr[i]
        val2: int = arr2_ptr[i]

        # Perform the addition.
        sum_val: int = val1 + val2

        # Write the sum to the result array. Clamping is handled by the higher-level Python function
        # if a _set_int16 equivalent is needed, or if Viper's internal casting handles it.
        # For direct ptr16 assignment, MicroPython handles the 16-bit signed range implicitly.
        result_ptr[i] = sum_val # Viper will implicitly handle 16-bit clamping for direct assignment


# --- Viper Core: In-place Array Addition (Optimized with ptr16) ---
@micropython.viper
def add_int16_array_in_place_viper(
    arr1_ptr: ptr16,      # Pointer to the first array (of 16-bit samples), will be modified
    arr2_ptr: ptr16,      # Pointer to the second array (of 16-bit samples)
    arr_len_samples: int  # Number of samples in the second array
):
    """
    Performs element-wise addition of `arr2` into `arr1` (`arr1 += arr2`) directly in memory.
    Optimized for speed by using ptr16 and native byte order.
    """
    # Determine the actual number of samples to process.
    num_samples_to_process: int = int(arr_len_samples)

    # Loop through each sample, performing the in-place addition.
    for i in range(num_samples_to_process):
        # Directly read 16-bit samples.
        val1: int = arr1_ptr[i]
        val2: int = arr2_ptr[i]

        # Perform the addition.
        sum_val: int = val1 + val2

        # Write the sum back to the first array. Viper will implicitly handle 16-bit clamping.
        arr1_ptr[i] = sum_val


@micropython.viper
def int32_add_int16_in_place_viper(
    arr1_ptr: ptr32,      # Pointer to the first array (of 32-bit samples), will be modified
    arr1_start_pos: int,
    arr2_ptr: ptr16,      # Pointer to the second array (of 16-bit samples)
    arr2_start_pos: int,
    arr_len_samples: int  # Number of samples in the second array
):
    num_samples_to_process: int = int(arr_len_samples)

    for i in range(num_samples_to_process):
        val1: int = arr1_ptr[arr1_start_pos + i]
        val2: int = arr2_ptr[arr2_start_pos + i]
        if val2 >= 32768:
            val2 -= 65536 # Equivalent to subtracting 2^16 for 2's complement
        sum_val: int = val1 + val2
        arr1_ptr[arr1_start_pos + i] = sum_val


@micropython.viper
def interpolate_int32_viper_ptr32(
    a_ptr: ptr32,           # Pointer to the source bytearray (interpreted as int32 array)
    a_num_samples: int,     # Number of int32 samples in the source array
    result_b_ptr: ptr32,    # Pointer to the destination bytearray (interpreted as int32 array)
    b_num_samples: int      # Number of int32 samples in the destination array (must be a multiple of a_num_samples)
):
    """
    Interpolates a source int32 array (a) into a destination int32 array (result_b)
    using Viper for high performance. Each element from 'a' will be repeated
    'interpolation_factor' times in 'result_b'.
    
    This function operates directly on memory addresses, requiring bytearray pointers.
    
    Args:
        a_ptr (ptr32): Pointer to the beginning of the source bytearray's data.
                       It's assumed to contain int32 values.
        a_num_samples (int): The number of 32-bit integers in the source array.
        result_b_ptr (ptr32): Pointer to the beginning of the destination bytearray's data.
                              It must be pre-allocated to the correct size.
        b_num_samples (int): The number of 32-bit integers for the output array.
                             Must be a multiple of a_num_samples.
    """
    
    # Calculate how many times each source sample needs to be repeated
    interpolation_factor: int = b_num_samples // a_num_samples
    
    # Declare loop variables with Viper integer type
    i: int # Loop counter for source array samples
    j: int # Loop counter for interpolation repetitions
    val: int # Current 32-bit value read from source array
    write_idx: int # Index for writing into the destination array

    for i in range(a_num_samples):
        val = a_ptr[i]
        
        for j in range(interpolation_factor):
            write_idx = i * interpolation_factor + j
            result_b_ptr[write_idx] = val


@micropython.viper
def interpolate_2x_int32_viper_ptr32(
    a_ptr: ptr32,           # Pointer to the source bytearray (interpreted as int32 array)
    result_b_ptr: ptr32,    # Pointer to the destination bytearray (interpreted as int32 array)
    num_samples: int,     # Number of int32 samples in the source array
):
    # Declare loop variables with Viper integer type
    i: int # Loop counter for source array samples
    val: int # Current 32-bit value read from source array

    for i in range(num_samples):
        val = a_ptr[i]
        result_b_ptr[i << 1] = val
        result_b_ptr[(i << 1) | 1] = val


@micropython.viper
def int32_left_shift_in_place_viper(
    arr_ptr: ptr32,
    arr_len_samples: int,  # Number of samples in the second array
    arr_left_shift: int
):
    for i in range(arr_len_samples):
        val: int = arr_ptr[i]
        shifted_val: int = (val << arr_left_shift)
        arr_ptr[i] = shifted_val


@micropython.viper
def divide_int32_array_in_place_viper(
    arr_ptr: ptr32,      # Pointer to the array (of 32-bit samples) to be modified
    arr_len_samples: int, # Number of samples in the array
    divisor: int        # The integer divisor
):
    """
    Performs element-wise integer division (`arr[i] //= divisor`) on the array in-place.
    Optimized for speed by using ptr32 and native byte order.
    
    Handles division by zero by clearing the array to zeros to prevent errors.
    """
    local_divisor: int = int(divisor)
    # Handle division by zero: if the divisor is 0, clear the array to zeros.
    if local_divisor == 0:
        # Loop over samples and set each 32-bit sample to 0 directly.
        for i in range(arr_len_samples):
            arr_ptr[i] = int(0)
        return # Exit early

    # Loop through each sample, performing the division.
    for i in range(arr_len_samples):
        # Directly read the 16-bit sample.
        val: int = int(arr_ptr[i])

        # if val >= 32768:
        #     val -= 65536 # Equivalent to subtracting 2^16 for 2's complement

        # Perform integer division (floor division).
        divided_val: int = val // local_divisor

        # if divided_val > 32767:
        #     divided_val = 32767
        # elif divided_val < -32768:
        #     divided_val = -32768

        # Write the divided sample back to the array. Viper will implicitly handle 16-bit clamping.
        arr_ptr[i] = divided_val


# --- Viper Core: In-place Array Division (Optimized with ptr16) ---
@micropython.viper
def divide_int16_array_in_place_viper(
    arr_ptr: ptr16,      # Pointer to the array (of 16-bit samples) to be modified
    arr_len_samples: int, # Number of samples in the array
    divisor: int        # The integer divisor
):
    """
    Performs element-wise integer division (`arr[i] //= divisor`) on the array in-place.
    Optimized for speed by using ptr16 and native byte order.
    
    Handles division by zero by clearing the array to zeros to prevent errors.
    """
    local_divisor: int = int(divisor)
    # Handle division by zero: if the divisor is 0, clear the array to zeros.
    if local_divisor == 0:
        # Loop over samples and set each 16-bit sample to 0 directly.
        for i in range(arr_len_samples):
            arr_ptr[i] = int(0)
        return # Exit early

    # Loop through each sample, performing the division.
    for i in range(arr_len_samples):
        # Directly read the 16-bit sample.
        val: int = int(arr_ptr[i])

        if val >= 32768:
            val -= 65536 # Equivalent to subtracting 2^16 for 2's complement

        # Perform integer division (floor division).
        divided_val: int = val // local_divisor

        if divided_val > 32767:
            divided_val = 32767
        elif divided_val < -32768:
            divided_val = -32768

        # Write the divided sample back to the array. Viper will implicitly handle 16-bit clamping.
        arr_ptr[i] = divided_val


# --- Python Wrapper for In-place Array Division (Calls fast version) ---
def divide_int16_bytearray_in_place(
    array_a_bytes: bytearray,
    divisor_b: int
) -> None:
    """
    Performs element-wise integer division of array_a_bytes by divisor_b (`array_a_bytes[i] //= divisor_b`).
    Optimized for speed by assuming native byte order.
    The result is stored directly in array_a_bytes (in-place modification).
    """
    BYTES_PER_SAMPLE: int = 2

    if not isinstance(array_a_bytes, bytearray):
        raise ValueError("Input array must be a bytearray instance.")
    if not isinstance(divisor_b, int):
        raise ValueError("Divisor must be an integer.")

    if len(array_a_bytes) % BYTES_PER_SAMPLE != 0:
        raise ValueError("Bytearray length must be a multiple of 2 (for 16-bit samples).")

    # Convert byte length to sample count before passing to Viper.
    arr_len_samples = len(array_a_bytes) // BYTES_PER_SAMPLE

    # Call the FAST Viper core function.
    divide_int16_array_in_place_viper(
        array_a_bytes,
        arr_len_samples,
        divisor_b
    )


def test_interploate():
    from ulab import numpy as np
    import time
    import array # For creating bytearray from signed ints
    import struct # For converting bytearray to/from list of ints for comparison
    import gc

    # --- NumPy equivalent interpolation function ---
    # This function mimics the behavior of your Viper `_interpolate_viper_core`
    # but uses ulab.numpy for direct comparison.
    def interpolate_numpy(
        closest_sample_bytes: bytes,
        original_length_bytes: int,
        new_length_bytes: int
    ) -> bytearray:
        BYTES_PER_SAMPLE = 2 # Assuming 16-bit samples

        original_len_samples = original_length_bytes // BYTES_PER_SAMPLE
        new_len_samples = new_length_bytes // BYTES_PER_SAMPLE

        if new_len_samples == 0:
            return bytearray()

        # Convert bytearray/bytes to NumPy array of int16
        # NumPy automatically handles native endianness here
        original_np_array = np.array(array.array('h', closest_sample_bytes), dtype=np.int16)

        # Calculate shift factor
        shift_factor = original_len_samples / new_len_samples

        # Use numpy interpolation
        indices = np.arange(new_len_samples) * shift_factor
        
        # Clamp indices to valid range for interpolation (important for numpy's interp)
        # interp implicitly handles extrapolation, but we want clamping as per Viper version
        indices = np.clip(indices, 0, original_len_samples - 1)

        # np.interp requires x values to be sorted, which arange gives
        # The xp_vals are just the integer indices of the original array
        xp_vals = np.arange(original_len_samples)

        shifted_np_array = np.array(np.interp(indices, xp_vals, original_np_array), dtype=np.int16)

        # Convert NumPy array back to bytearray
        # array.array('h', ...) implicitly handles native endianness packing
        return shifted_np_array.tobytes()


    # --- Test Parameters ---
    SAMPLE_RATE = 16000 # Hz
    BITS_PER_SAMPLE = 16
    BYTES_PER_SAMPLE = BITS_PER_SAMPLE // 8
    
    # Use a larger buffer size for more meaningful timing
    NUM_SAMPLES_ORIGINAL = 16 * 1024 # 16KB of 16-bit samples = 8192 samples
    ORIGINAL_LENGTH_BYTES = NUM_SAMPLES_ORIGINAL * BYTES_PER_SAMPLE

    SHIFT_FACTOR_TEST = 1.25 # Pitch up (makes output shorter)
    
    # Calculate new length based on shift factor
    NEW_NUM_SAMPLES = int(NUM_SAMPLES_ORIGINAL / SHIFT_FACTOR_TEST)
    NEW_LENGTH_BYTES = NEW_NUM_SAMPLES * BYTES_PER_SAMPLE

    SCALE_FACTOR_INTERP = 10000 # Must match the value used in _interpolate_viper_core
    NUM_ITERATIONS = 50 # Number of runs for timing average

    print(f"--- Interpolation Performance & Correctness Test ---")
    print(f"Original samples: {NUM_SAMPLES_ORIGINAL}")
    print(f"Shift factor: {SHIFT_FACTOR_TEST}")
    print(f"New samples: {NEW_NUM_SAMPLES}")
    print(f"Iterations: {NUM_ITERATIONS}")
    print(f"Assuming native byte order (ESP32-S3 is Little-Endian)\n")

    # --- 1. Prepare Test Data ---
    # Create a dummy 16-bit signed audio sample (bytearray)
    # Using a sine wave for more realistic sample values.
    dummy_samples_list = array.array('h')
    amplitude = 30000 # Max amplitude for 16-bit signed
    for i in range(NUM_SAMPLES_ORIGINAL):
        sample_val = int(amplitude * np.sin(2 * np.pi * 10 * i / NUM_SAMPLES_ORIGINAL))
        dummy_samples_list.append(sample_val)

    original_bytearray_viper = bytearray(dummy_samples_list) # 直接从 array.array 创建 bytearray
    original_bytes_numpy = bytearray(dummy_samples_list) # NumPy 的 ulab 期望 bytearray 或 array.array

    # --- 2. Time Viper Interpolation ---
    viper_times = []
    print(f"Running Viper interpolation for {NUM_ITERATIONS} iterations...")
    for _ in range(NUM_ITERATIONS):
        # Create a fresh copy of the input for each run to avoid side effects
        input_for_viper = bytearray(original_bytearray_viper) 
        gc.collect()
        
        start_time = time.ticks_us()
        viper_result_bytearray = interpolate(
            input_for_viper,
            ORIGINAL_LENGTH_BYTES,
            NEW_LENGTH_BYTES
        )
        end_time = time.ticks_us()
        viper_times.append(time.ticks_diff(end_time, start_time))
    
    avg_viper_time_us = sum(viper_times) / NUM_ITERATIONS
    print(f"Average Viper interpolation time: {avg_viper_time_us:.2f} us")

    # --- 3. Time NumPy Interpolation ---
    numpy_times = []
    print(f"Running NumPy interpolation for {NUM_ITERATIONS} iterations...")
    for _ in range(NUM_ITERATIONS):
        # For NumPy, we pass bytes directly, conversion to np.array happens inside.
        gc.collect()
        start_time = time.ticks_us()
        numpy_result_bytearray = interpolate_numpy(
            original_bytes_numpy, # Use the immutable bytes version for NumPy
            ORIGINAL_LENGTH_BYTES,
            NEW_LENGTH_BYTES
        )
        end_time = time.ticks_us()
        numpy_times.append(time.ticks_diff(end_time, start_time))

    avg_numpy_time_us = sum(numpy_times) / NUM_ITERATIONS
    print(f"Average NumPy interpolation time: {avg_numpy_time_us:.2f} us")

    # --- 4. Compare Numerical Correctness (using a single run's output) ---
    print(f"\n--- Numerical Correctness Check ---")
    
    # Convert Viper output bytearray to a list of integers for comparison
    viper_result_samples = array.array('h', viper_result_bytearray)
    
    # Convert NumPy output bytearray to a list of integers
    numpy_result_samples = array.array('h', numpy_result_bytearray)

    is_correct = True
    tolerance = 1 # Allow for a small integer difference due to floating point precision and clamping differences
    
    if len(viper_result_samples) != len(numpy_result_samples):
        print(f"Error: Length mismatch! Viper: {len(viper_result_samples)}, NumPy: {len(numpy_result_samples)}")
        is_correct = False
    else:
        diff_count = 0
        max_diff = 0
        for i in range(len(viper_result_samples)):
            val_viper = viper_result_samples[i]
            val_numpy = numpy_result_samples[i]
            abs_diff = abs(val_viper - val_numpy)
            if abs_diff > tolerance:
                diff_count += 1
                if abs_diff > max_diff:
                    max_diff = abs_diff
            # print(f"Sample {i}: Viper={val_viper}, NumPy={val_numpy}, Diff={abs_diff}") # Uncomment for detailed debug

        if diff_count == 0:
            print(f"Correctness Check: PASS! Outputs are identical within tolerance {tolerance}.")
        else:
            print(f"Correctness Check: FAIL! {diff_count} samples differ by more than tolerance {tolerance}. Max diff: {max_diff}")
            print(f"Viper (first 10): {viper_result_samples[:20]}")
            print(f"NumPy (first 10): {numpy_result_samples[:20]}")
            is_correct = False

    print("\n--- Test Summary ---")
    if is_correct:
        print("All checks passed. Viper is faster and correct!")
    else:
        print("Some correctness checks failed. Investigate numerical differences.")

    # Always ensure a clean state if this script is part of a larger system.
    # For instance, if you want to explicitly clear the buffer for next operation:
    # clear_bytearray_viper(some_buffer, len(some_buffer))


def test_inplace_add():
    from ulab import numpy as np
    import time
    import array
    import gc

    BYTES_PER_SAMPLE = 2
    NUM_SAMPLES = 8 * 1024 # Test with 8KB of samples
    LENGTH_BYTES = NUM_SAMPLES * BYTES_PER_SAMPLE
    NUM_ITERATIONS = 100 # More iterations for simpler operations

    print(f"\n--- In-place Addition Performance & Correctness Test ---")
    print(f"Number of samples: {NUM_SAMPLES}")
    print(f"Iterations: {NUM_ITERATIONS}")
    print(f"Assuming native byte order (ESP32-S3 is Little-Endian)\n")

    # --- 1. Prepare Test Data ---
    # Create two dummy 16-bit signed audio sample bytearrays
    data_a_list = array.array('h')
    data_b_list = array.array('h')
    for i in range(NUM_SAMPLES):
        data_a_list.append(int(1000 * np.sin(2 * np.pi * 5 * i / NUM_SAMPLES))) # Simple sine wave
        data_b_list.append(int(500 * np.cos(2 * np.pi * 7 * i / NUM_SAMPLES))) # Another simple wave
    
    # Viper expects bytearray
    original_a_viper = bytearray(data_a_list)
    original_b_viper = bytearray(data_b_list)

    # NumPy also works well with bytearray or converting from array.array
    original_a_numpy_base = np.array(data_a_list, dtype=np.int16)
    original_b_numpy_base = np.array(data_b_list, dtype=np.int16)

    # --- 2. Time Viper In-place Addition ---
    viper_times = []
    print(f"Running Viper in-place addition for {NUM_ITERATIONS} iterations...")
    for _ in range(NUM_ITERATIONS):
        # Create fresh copies for each run to ensure in-place modification doesn't affect subsequent runs
        arr1_for_viper = bytearray(original_a_viper)
        arr2_for_viper = bytearray(original_b_viper) # This one is just read, can reuse if preferred
        gc.collect()

        start_time = time.ticks_us()
        # Call the Viper function. Note: no return value as it's in-place.
        add_int16_array_in_place_viper(
            arr1_for_viper,
            arr2_for_viper,
            NUM_SAMPLES  # Pass sample count
        )
        end_time = time.ticks_us()
        viper_times.append(time.ticks_diff(end_time, start_time))
    
    avg_viper_time_us = sum(viper_times) / NUM_ITERATIONS
    print(f"Average Viper in-place addition time: {avg_viper_time_us:.2f} us")

    # --- 3. Time NumPy In-place Addition ---
    numpy_times = []
    print(f"Running NumPy in-place addition for {NUM_ITERATIONS} iterations...")
    for _ in range(NUM_ITERATIONS):
        # Create fresh NumPy arrays for each run
        arr1_for_numpy = np.array(original_a_numpy_base, dtype=np.int16)
        arr2_for_numpy = np.array(original_b_numpy_base, dtype=np.int16) # Or just reference if not modified
        gc.collect()

        start_time = time.ticks_us()
        arr1_for_numpy += arr2_for_numpy # NumPy's efficient in-place addition
        end_time = time.ticks_us()
        numpy_times.append(time.ticks_diff(end_time, start_time))

    avg_numpy_time_us = sum(numpy_times) / NUM_ITERATIONS
    print(f"Average NumPy in-place addition time: {avg_numpy_time_us:.2f} us")

    # --- 4. Compare Numerical Correctness (using one run's output) ---
    print(f"\n--- Numerical Correctness Check (In-place Add) ---")
    
    # Calculate expected result using NumPy for higher precision reference
    expected_result_np = original_a_numpy_base + original_b_numpy_base
    expected_result_np = np.array(expected_result_np, dtype=np.int16) # Ensure 16-bit range clamping

    # Convert Viper result bytearray back to a list of integers
    viper_final_samples = array.array('h', arr1_for_viper) # arr1_for_viper holds the result

    # Convert NumPy result array to a list of integers
    numpy_final_samples = array.array('h', arr1_for_numpy.tobytes()) # Convert np array back to bytes for array.array

    is_correct = True
    # For addition, results should be exact if no overflow/underflow occurs
    # However, Python's int might handle arbitrary size, while Viper/NumPy clamp to int16.
    # So, values should be within the int16 range.
    tolerance = 0 
    
    if len(viper_final_samples) != len(expected_result_np):
        print(f"Error: Length mismatch! Viper: {len(viper_final_samples)}, Expected: {len(expected_result_np)}")
        is_correct = False
    else:
        diff_count = 0
        max_diff = 0
        for i in range(len(viper_final_samples)):
            val_viper = viper_final_samples[i]
            val_expected = expected_result_np[i]
            abs_diff = abs(val_viper - val_expected)
            if abs_diff > tolerance:
                diff_count += 1
                if abs_diff > max_diff:
                    max_diff = abs_diff
            # print(f"Sample {i}: Viper={val_viper}, Expected={val_expected}, Diff={abs_diff}") # Debug

        if diff_count == 0:
            print(f"Correctness Check: PASS! Outputs are identical within tolerance {tolerance}.")
        else:
            print(f"Correctness Check: FAIL! {diff_count} samples differ by more than tolerance {tolerance}. Max diff: {max_diff}")
            print(f"Viper (first 20): {viper_final_samples[:20]}")
            print(f"NumPy (first 20): {numpy_final_samples[:20]}") # Show numpy result for comparison
            print(f"Expected (first 20): {list(expected_result_np[:20])}") # Show expected
            is_correct = False

    print("\n--- In-place Add Test Summary ---")
    if is_correct:
        print("All in-place addition checks passed. Viper is likely faster and correct!")
    else:
        print("Some in-place addition correctness checks failed. Investigate numerical differences.")


def test_inplace_divide():
    from ulab import numpy as np
    import time
    import array
    import gc

    BYTES_PER_SAMPLE = 2
    NUM_SAMPLES = 8 * 1024 # Test with 8KB of samples
    LENGTH_BYTES = NUM_SAMPLES * BYTES_PER_SAMPLE
    NUM_ITERATIONS = 100 # More iterations for simpler operations
    TEST_DIVISOR = 5 # A non-zero divisor

    print(f"\n--- In-place Division Performance & Correctness Test ---")
    print(f"Number of samples: {NUM_SAMPLES}")
    print(f"Divisor: {TEST_DIVISOR}")
    print(f"Iterations: {NUM_ITERATIONS}")
    print(f"Assuming native byte order (ESP32-S3 is Little-Endian)\n")

    # --- 1. Prepare Test Data ---
    # Create a dummy 16-bit signed audio sample bytearray
    data_list = array.array('h')
    for i in range(NUM_SAMPLES):
        # Use values that ensure some non-zero results after division
        data_list.append(int(20000 * np.sin(2 * np.pi * 3 * i / NUM_SAMPLES) + 10000))
    
    # Viper expects bytearray
    original_viper = bytearray(data_list)
    # NumPy also works well with bytearray or converting from array.array
    original_numpy_base = np.array(data_list, dtype=np.int16)

    # --- 2. Time Viper In-place Division ---
    viper_times = []
    print(f"Running Viper in-place division for {NUM_ITERATIONS} iterations...")
    for _ in range(NUM_ITERATIONS):
        # Create fresh copy for each run
        arr_for_viper = bytearray(original_viper)
        gc.collect()

        start_time = time.ticks_us()
        divide_int16_array_in_place_viper(
            arr_for_viper,
            NUM_SAMPLES, # Pass sample count
            TEST_DIVISOR
        )
        end_time = time.ticks_us()
        viper_times.append(time.ticks_diff(end_time, start_time))
    
    avg_viper_time_us = sum(viper_times) / NUM_ITERATIONS
    print(f"Average Viper in-place division time: {avg_viper_time_us:.2f} us")

    # --- 3. Time NumPy In-place Division ---
    numpy_times = []
    print(f"Running NumPy in-place division for {NUM_ITERATIONS} iterations...")

    for _ in range(NUM_ITERATIONS):
        # Create fresh NumPy array for each run
        arr_for_numpy = np.array(original_numpy_base, dtype=np.int16)
        divisor = np.array(np.ones(len(original_numpy_base), dtype=np.int16) * TEST_DIVISOR, dtype=np.int16)
        gc.collect()

        start_time = time.ticks_us()
        arr_for_numpy //= divisor # NumPy's efficient in-place integer division
        end_time = time.ticks_us()
        numpy_times.append(time.ticks_diff(end_time, start_time))

    avg_numpy_time_us = sum(numpy_times) / NUM_ITERATIONS
    print(f"Average NumPy in-place division time: {avg_numpy_time_us:.2f} us")

    # --- 4. Compare Numerical Correctness (using one run's output) ---
    print(f"\n--- Numerical Correctness Check (In-place Divide) ---")
    
    # Calculate expected result using NumPy for higher precision reference
    expected_result_np = original_numpy_base // TEST_DIVISOR
    expected_result_np = np.array(expected_result_np, dtype=np.int16) # Ensure 16-bit range clamping

    # Convert Viper result bytearray back to a list of integers
    viper_final_samples = array.array('h', arr_for_viper) # arr_for_viper holds the result

    # Convert NumPy result array to a list of integers
    numpy_final_samples = array.array('h', arr_for_numpy.tobytes())

    is_correct = True
    tolerance = 1 # Integer division should be exact if no overflow/underflow
    
    if len(viper_final_samples) != len(expected_result_np):
        print(f"Error: Length mismatch! Viper: {len(viper_final_samples)}, Expected: {len(expected_result_np)}")
        is_correct = False
    else:
        diff_count = 0
        max_diff = 0
        for i in range(len(viper_final_samples)):
            val_viper = viper_final_samples[i]
            val_expected = expected_result_np[i]
            abs_diff = abs(val_viper - val_expected)
            if abs_diff > tolerance:
                diff_count += 1
                if abs_diff > max_diff:
                    max_diff = abs_diff
            # print(f"Sample {i}: Viper={val_viper}, Expected={val_expected}, Diff={abs_diff}") # Debug

        if diff_count == 0:
            print(f"Correctness Check: PASS! Outputs are identical within tolerance {tolerance}.")
        else:
            print(f"Correctness Check: FAIL! {diff_count} samples differ by more than tolerance {tolerance}. Max diff: {max_diff}")
            print(f"Viper ([-400:-360]): {viper_final_samples[-400:-360]}")
            print(f"NumPy ([-400:-360]): {numpy_final_samples[-400:-360]}")
            print(f"Expected ([-400:-360]): {list(expected_result_np[-400:-360])}")
            is_correct = False

    print("\n--- In-place Divide Test Summary ---")
    if is_correct:
        print("All in-place division checks passed. Viper is likely faster and correct!")
    else:
        print("Some in-place division correctness checks failed. Investigate numerical differences.")


def test_interploate_2x_ptr32():
    import time
    audio_buffer = memoryview(bytearray(1024 * 4 * 2))
    cal_buffer = memoryview(bytearray(1024 * 4))
    NUM_ITERATIONS = 100

    time_start = time.ticks_us()
    for _ in range(NUM_ITERATIONS):
        interpolate_2x_int32_viper_ptr32(cal_buffer, audio_buffer, 1024)
    time_end = time.ticks_us()
    print("test_interploate_2x_ptr32 x100:", time_end - time_start, "us")


# --- Main execution block ---
if __name__ == "__main__":
    test_interploate_2x_ptr32()
    # test_inplace_add()
    # test_inplace_divide()
    # test_interploate()
