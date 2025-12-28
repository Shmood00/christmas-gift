import machine
import os
import time

FLAG_FILE = ".reset_flag"
WIFI_FILE = "wifi.dat"
OTA_FLAG = ".ota_running"
led = machine.Pin(33, machine.Pin.OUT)

# 1. Check for OTA bypass FIRST
if OTA_FLAG in os.listdir():
    print("[System] Post-OTA Boot: Keeping WiFi credentials.")
    try:
        os.remove(OTA_FLAG)
        if FLAG_FILE in os.listdir():
            os.remove(FLAG_FILE)
    except:
        pass
    # No wiping logic here, just proceed to connect

# 2. Check for "Double Reset" if no OTA bypass is present
elif FLAG_FILE in os.listdir():
    print("!!! Double Reset Detected: Wiping WiFi Credentials !!!")
    
    # Rapid Blink feedback
    for _ in range(15):
        led.value(0) 
        time.sleep_ms(50)
        led.value(1) 
        time.sleep_ms(50)

    try: os.remove(WIFI_FILE)
    except: pass
    
    try: os.remove(FLAG_FILE)
    except: pass
    
    machine.reset()

else:
    # 3. Normal Boot: Create the flag if we have WiFi credentials.
    if WIFI_FILE in os.listdir():
        print("Setting Reset Flag...")
        with open(FLAG_FILE, "w") as f:
            f.write("1")
    else:
        print("No WiFi file found. Setup Mode.")

# 4. Connect to WiFi
from wifimanager import WifiManager
wm = WifiManager(ssid='Family Ornament', password='', reboot=True, debug=True)
wm.connect()
