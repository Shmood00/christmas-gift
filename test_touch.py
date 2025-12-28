from machine import TouchPad, Pin, PWM, reset
from ws_mqtt import MQTTWebSocketClient
import uasyncio as asyncio
import math, time, os, gc, json

# --- 1. CONFIG & GLOBALS ---
def load_config():
    try:
        with open("config.json", "r") as f:
            return json.load(f)
    except:
        return {"url": "", "user": "", "pass": "", "sub_topics": [], "pub_topic": "touch"}

CONFIG = load_config()
mqtt_state = [0]
status = {'touch_active': False}
ota_requested = False
publish_deadline = 0

# --- 2. OTA & TIME ---
async def sync_time():
    import ntptime
    try:
        ntptime.settime()
        print("[System] Time synced")
    except:
        print("[System] Time sync failed")
    gc.collect()

async def force_update_file(filename):
    import urequests
    url = f"https://raw.githubusercontent.com/Shmood00/christmas-gift/main/{filename}?cb={time.ticks_ms()}"
    try:
        res = urequests.get(url, timeout=15)
        if res.status_code == 200:
            content = res.text
            res.close()
            with open("temp_update.py", "w") as f:
                f.write(content)
            os.rename("temp_update.py", "main.py")
            return True
    except Exception as e:
        print(f"[OTA] Error: {e}")
    return False

# --- 3. CALLBACKS ---
async def on_msg(topic, payload):
    global ota_requested
    t, p = topic.decode(), payload.decode()
    if t == 'tree/cmd/update' or p == 'update':
        ota_requested = True
    else:
        mqtt_state[0] = time.ticks_add(time.ticks_ms(), 5000)

async def pulse_led(led_pwm):
    phase = 0
    while True:
        await asyncio.sleep_ms(20)
        if status['touch_active'] or time.ticks_diff(mqtt_state[0], time.ticks_ms()) > 0:
            led_pwm.duty(int((math.sin(phase)*0.5+0.5)*1023))
            phase += 0.1
        else:
            led_pwm.duty(0)
            phase = 0

# --- 4. MAIN LOOP ---
async def main_loop():
    global ota_requested, publish_deadline
    
    # Start systems
    await sync_time()
    
    # ONLY CREATE RESET FLAG ONCE WE ARE RUNNING STABLY
    # This prevents the "Safe Mode Loop" if the code crashes at the very start
    with open(".reset_flag", "w") as f: f.write("1")
    
    async def clear_flag():
        await asyncio.sleep(15)
        if ".reset_flag" in os.listdir():
            os.remove(".reset_flag")
            print("[System] Stability confirmed. Flag cleared.")
    asyncio.create_task(clear_flag())

    # Hardware
    touch_pin = TouchPad(Pin(27))
    led_pwm = PWM(Pin(33, Pin.OUT), freq=500)
    
    client = MQTTWebSocketClient(
        CONFIG['url'], username=CONFIG['user'], password=CONFIG['pass'], 
        ssl_params={'cert_reqs': 0}, keepalive=30 
    )
    client.set_callback(on_msg)
    asyncio.create_task(pulse_led(led_pwm))

    while True:
        if ota_requested:
            try: await client.disconnect()
            except: pass
            if await force_update_file("test_touch.py"):
                print("[OTA] Success. Rebooting...")
                reset()
            ota_requested = False

        if not client._connected:
            gc.collect()
            try:
                await client.connect()
                await client.subscribe('tree/cmd/update')
                for t in CONFIG['sub_topics']: await client.subscribe(t)
            except:
                await asyncio.sleep(5)
                continue

        try:
            if touch_pin.read() < 400: # Simple fixed threshold for testing
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
    # Safe mode check
    if ".reset_flag" in os.listdir():
        print("SAFE MODE ACTIVE - 15s delay")
        time.sleep(15)
        # Note: We don't delete it here; clear_flag() does it after boot
        
    try:
        gc.collect()
        asyncio.run(main_loop())
    except Exception as e:
        print('Fatal:', e)
        # If it crashes before creating the flag, it won't trigger safe mode next time
        time.sleep(5)
        reset()
