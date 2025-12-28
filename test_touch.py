from machine import TouchPad, Pin, PWM, reset
from ws_mqtt import MQTTWebSocketClient
import uasyncio as asyncio
import math, time, os, gc, json

# 1. Configuration Loader
def load_config():
    try:
        with open("config.json", "r") as f:
            return json.load(f)
    except:
        return {
            "url": "wss://mqtt.yourdomain.com", 
            "user": "default", "pass": "default", 
            "sub_topics": ["tree/cmd/update"], 
            "pub_topic": "touch_detected"
        }

CONFIG = load_config()
mqtt_state = [0] 
status = {'touch_active': False}
ota_requested = False 
publish_deadline = 0

# 2. Optimized NTP Sync
async def sync_time():
    import ntptime
    print("[System] Syncing time...")
    try:
        ntptime.settime()
        print("[System] Time synced")
    except:
        print("[System] NTP failed")
    gc.collect()

# 3. Direct OTA Download (The "Force" Method)
async def force_update_file(filename):
    import urequests
    # Cache buster to ensure GitHub doesn't serve old code
    url = f"https://raw.githubusercontent.com/Shmood00/christmas-gift/main/{filename}?cb={time.ticks_ms()}"
    
    print(f"[OTA] Pulling {filename}...")
    try:
        res = urequests.get(url, timeout=15)
        if res.status_code == 200:
            new_code = res.text
            res.close()
            with open(filename, "w") as f:
                f.write(new_code)
            return True
        else:
            print(f"[OTA] HTTP Error: {res.status_code}")
            res.close()
    except Exception as e:
        print(f"[OTA] Request failed: {e}")
    return False

# 4. MQTT Callbacks
async def on_msg(topic, payload):
    global ota_requested
    t = topic.decode()
    p = payload.decode()
    print(f"MQTT: {t} -> {p}")
    
    if t == 'tree/cmd/update' or p == 'update':
        ota_requested = True
    elif t in CONFIG['sub_topics']:
        mqtt_state[0] = time.ticks_add(time.ticks_ms(), 5000)

async def pulse_led(led_pwm):
    phase = 0
    while True:
        await asyncio.sleep_ms(20)
        is_active = status['touch_active'] or time.ticks_diff(mqtt_state[0], time.ticks_ms()) > 0
        if is_active:
            led_pwm.duty(int((math.sin(phase)*0.5+0.5)*1023))
            phase += 0.1
        else:
            led_pwm.duty(0)
            phase = 0

# 5. The Main Logic
async def main_loop():
    global publish_deadline, ota_requested
    
    await sync_time()
    
    # Safe Mode Cleanup: Delete flag after 10s of stability
    async def clear_flag():
        await asyncio.sleep(10)
        if ".reset_flag" in os.listdir():
            os.remove(".reset_flag")
            print("[System] Reset flag cleared.")
    asyncio.create_task(clear_flag())
    
    # Hardware
    touch_pin = TouchPad(Pin(27))
    led_pwm = PWM(Pin(33, Pin.OUT), freq=500)
    
    # Calibration
    print("[Touch] Calibrating...")
    total = 0
    for _ in range(20):
        total += touch_pin.read()
        await asyncio.sleep_ms(50)
    touch_threshold = int((total // 20) * 0.8)

    client = MQTTWebSocketClient(
        CONFIG['url'], username=CONFIG['user'], password=CONFIG['pass'], 
        ssl_params={'cert_reqs': 0}, keepalive=30 
    )
    client.set_callback(on_msg)
    asyncio.create_task(pulse_led(led_pwm))

    while True:
        # OTA Triggered?
        if ota_requested:
            try: await client.disconnect()
            except: pass
            gc.collect()
            
            # Since this file IS main.py, we download to main.py
            if await force_update_file("test_touch.py"): 
                # Rename the downloaded file to main.py immediately
                os.rename("test_touch.py", "main.py")
                print("[OTA] Updated main.py. Rebooting...")
                await asyncio.sleep(1)
                reset()
            else:
                ota_requested = False

        # Connection management
        if not client._connected:
            gc.collect()
            try:
                await client.connect()
                for topic in CONFIG['sub_topics']:
                    await client.subscribe(topic)
                await client.subscribe('tree/cmd/update')
                print("[MQTT] Connected.")
            except Exception as e:
                print(f"[MQTT] Error: {e}")
                await asyncio.sleep(5)
                continue

        # Touch Logic
        try:
            if touch_pin.read() < touch_threshold:
                status['touch_active'] = True
                if time.ticks_diff(time.ticks_ms(), publish_deadline) > 0:
                    await client.publish(CONFIG['pub_topic'], "1")
                    publish_deadline = time.ticks_add(time.ticks_ms(), 5000)
            else:
                status['touch_active'] = False
        except:
            client._connected = False

        await asyncio.sleep_ms(50)

if __name__ == '__main__':
    # Double reset protection
    if ".reset_flag" in os.listdir():
        print("SAFE MODE: Delaying 15s...")
        time.sleep(15)
    
    try:
        gc.collect()
        asyncio.run(main_loop())
    except Exception as e:
        print('Fatal:', e)
        time.sleep(5)
        reset()
