from machine import TouchPad, Pin, PWM, reset
from ws_mqtt import MQTTWebSocketClient
import uasyncio as asyncio
import math, time, os, gc, json
import senko, ntptime

def load_config():
    try:
        with open("config.json", "r") as f:
            return json.load(f)
    except:
        return {
            "url": "", "user": "", "pass": "", 
            "sub_topics": ["tree/cmd/update"], # Added update trigger as default
            "pub_topic": "touch_detected"
        }

# Configuration and State
CONFIG = load_config()
URL = CONFIG['url']
USER = CONFIG['user']
PASS = CONFIG['pass']
TOPICS = CONFIG['sub_topics']

publish_deadline = 0
mqtt_state = [0] 
status = {'touch_active': False}
ota_requested = False  # Global flag for update trigger

OTA = senko.Senko(
  user="Shmood00",
  repo="christmas-gift",
  branch="main",
  working_dir="",
  files=["test_touch.py"] # Ensure this matches your local filename (usually main.py)
)

async def sync_time():
    print("[System] Syncing time via NTP...")
    try:
        ntptime.settime()
        print("[System] Time synced successfully:", time.localtime())
    except Exception as e:
        print("[System] Time sync failed:", e)

async def clear_reset_flag():
    # Wait 10 seconds to ensure system stability before clearing flag
    await asyncio.sleep(10)
    try:
        if ".reset_flag" in os.listdir():
            os.remove(".reset_flag")
            print("[System] Stable. Reset flag cleared")
    except Exception as e:
        print("[System] Error clearing flag: ", e)

async def calibrate_touch(touch_pin, samples=20):
    print("[Touch] Calibrating...")
    total = 0
    for _ in range(samples):
        total += touch_pin.read()
        await asyncio.sleep_ms(50)
    baseline = total // samples
    threshold = int(baseline * 0.8)
    print(f"[Touch] Baseline: {baseline}, Threshold: {threshold}")
    return threshold

async def on_msg(topic, payload):
    global ota_requested
    t = topic.decode()
    p = payload.decode()
    print(f"[MQTT] Received: {t} -> {p}")
    
    # 1. Check for OTA Trigger
    if t == 'tree/cmd/update' or p == 'update':
        print("[System] OTA Update Request Received!")
        ota_requested = True
        
    # 2. Handle Pulse Logic
    elif t in TOPICS:
        mqtt_state[0] = time.ticks_add(time.ticks_ms(), 5000)

async def pulse_led(led_pwm):
    phase = 0
    while True:
        await asyncio.sleep_ms(20)
        is_touching = status['touch_active']
        is_mqtt_active = time.ticks_diff(mqtt_state[0], time.ticks_ms()) > 0
        
        if is_touching or is_mqtt_active:
            brightness = int((math.sin(phase)*0.5+0.5)*1023)
            led_pwm.duty(brightness)
            phase += 0.1
        else:
            led_pwm.duty(0)
            phase = 0

async def example():
    global publish_deadline, ota_requested

    await sync_time()
    # Note: check_for_updates() on boot removed to prevent asyncio hanging.
    # Updates are now handled via MQTT trigger in the loop below.
    
    asyncio.create_task(clear_reset_flag())
    
    # Setup Hardware
    touch_pin = TouchPad(Pin(27))
    led_pwm = PWM(Pin(33, Pin.OUT), freq=500)
    touch_threshold = await calibrate_touch(touch_pin)
    
    client = MQTTWebSocketClient(
        URL, username=USER, password=PASS, 
        ssl_params={'cert_reqs': 0}, keepalive=30 
    )
    client.set_callback(on_msg)

    asyncio.create_task(pulse_led(led_pwm))

    print("[System] Starting Main Loop...")
    loop_count = 0

    while True:
        loop_count += 1
        
        # 1. Handle OTA Request (Interrupts normal loop)
        if ota_requested:
            print("[OTA] Stopping MQTT and starting update...")
            try: await client.disconnect()
            except: pass
            gc.collect()
            
            try:
                if OTA.update():
                    print("[OTA] Update Success! Rebooting...")
                    reset()
                else:
                    print("[OTA] No changes found on GitHub.")
            except Exception as e:
                print(f"[OTA] Error: {e}")
            
            ota_requested = False # Reset flag and resume if update failed/skipped

        # 2. Maintain MQTT Connection
        if not client._connected:
            try:
                await client.connect()
                for topic in TOPICS:
                    await client.subscribe(topic)
                # Auto-subscribe to the update command topic
                await client.subscribe('tree/cmd/update')
                print("[MQTT] Connected and Ready")
                gc.collect()
            except Exception as e:
                print(f"[MQTT] Failed: {e}. Retrying...")
                await asyncio.sleep(5)
                continue

        # 3. Touch Logic
        try:
            data = touch_pin.read()
            if data < touch_threshold:
                status['touch_active'] = True
                if time.ticks_diff(time.ticks_ms(), publish_deadline) > 0:
                    await client.publish(CONFIG['pub_topic'], str(data))
                    publish_deadline = time.ticks_add(time.ticks_ms(), 5000)
            else:
                status['touch_active'] = False
        except Exception as e:
            client._connected = False

        # 4. Cleanup
        if loop_count % 100 == 0:
            gc.collect()
            print(f"[Health] Free RAM: {gc.mem_free()}")
            loop_count = 0

        await asyncio.sleep_ms(50)

if __name__ == '__main__':
    if ".reset_flag" in os.listdir():
        print("!!! SAFE MODE ACTIVE !!!")
        time.sleep(15)
    
    try:
        gc.threshold(gc.mem_free() // 4 + gc.mem_alloc())
        gc.collect()
        asyncio.run(example())
    except Exception as e:
        print('Fatal Error:', e)
        time.sleep(5)
        reset()
