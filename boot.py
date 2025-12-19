import machine
import os
import time

FLAG_FILE = ".reset_flag"
WIFI_FILE = "wifi.dat"
led = machine.Pin(33, machine.Pin.OUT)

# 1. Check if the "Double Reset" flag exists from a PREVIOUS boot
if FLAG_FILE in os.listdir():
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
    # 2. First boot attempt: ONLY create the flag if we already have credentials.
    # This prevents the loop when the WiFi Manager reboots after a fresh setup.
    if WIFI_FILE in os.listdir():
        print("Setting Reset Flag...")
        with open(FLAG_FILE, "w") as f:
            f.write("1")
    else:
        print("No WiFi file found. Skipping reset flag (Setup Mode).")

    # 3. Connect to WiFi IMMEDIATELY
    from wifimanager import WifiManager
    wm = WifiManager(ssid='Family Ornament', password='', reboot=True, debug=True)
    
    # This will either connect using wifi.dat or start the portal
    wm.connect()
