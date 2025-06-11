from usb.device.keyboard import KeyCode


# TODO: read custom key code json
# Volume Controls
KeyCode.VOLUME_MUTE    = 0xE2  # Mute/Unmute Volume
KeyCode.VOLUME_UP      = 0xE9  # Volume Increment (Volume Up)
KeyCode.VOLUME_DOWN    = 0xEA  # Volume Decrement (Volume Down)

# Playback Controls
KeyCode.PLAY_PAUSE     = 0xCD  # Play/Pause Toggle
KeyCode.SCAN_NEXT_TRACK = 0xB5 # Next Track (Fast Forward)
KeyCode.SCAN_PREV_TRACK = 0xB6 # Previous Track (Rewind)
KeyCode.STOP           = 0xB7  # Stop Playback

# Application Launchers / System Controls
KeyCode.BRIGHTNESS_UP  = 0x6F  # Display Brightness Increment
KeyCode.BRIGHTNESS_DOWN = 0x70 # Display Brightness Decrement
KeyCode.LAUNCH_CALCULATOR = 0x192 # Launch Calculator
KeyCode.LAUNCH_MAIL    = 0x18A # Launch Mail Client
KeyCode.LAUNCH_BROWSER = 0x18B # Launch Web Browser
KeyCode.MY_COMPUTER    = 0x194 # Launch My Computer/File Explorer
KeyCode.POWER          = 0x30  # Power Off
KeyCode.SLEEP          = 0x32  # Sleep
KeyCode.WAKE           = 0x33  # Wake Up

# Navigation/Browser Controls
KeyCode.BROWSER_HOME   = 0x0C2 # Browser Home
KeyCode.BROWSER_BACK   = 0x0C3 # Browser Back
KeyCode.BROWSER_FORWARD = 0x0C4 # Browser Forward
KeyCode.BROWSER_REFRESH = 0x0C7 # Browser Refresh
