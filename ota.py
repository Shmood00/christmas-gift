import urequests
import os
import machine
import gc
import json
import time
import urandom

class OTAUpdater:
    def __init__(self, repo_url, filenames):
        self.repo_url = repo_url
        self.filenames = filenames 

    def _xor_crypt(self, data):
        if isinstance(data, str):
            data = data.encode('utf-8')
        key = machine.unique_id()
        return bytes([data[i] ^ key[i % len(key)] for i in range(len(data))])

    def check_and_update(self, local_config):
        if not isinstance(local_config, dict):
            print("[OTA] Error: local_config is not a dictionary")
            return False
        if 'versions' not in local_config:
            local_config['versions'] = {}
        
        gc.collect()
        res = None
        updated_any = False
        cache_buster = "?cb={}".format(urandom.getrandbits(24))
        
        try:
            url = "{}/versions.json{}".format(self.repo_url, cache_buster)
            print("[OTA] Checking for updates...")
            res = urequests.get(url, timeout=10)
            
            if res.status_code == 200:
                remote_versions = res.json()
                res.close()

                for filename in self.filenames:
                    local_ver = local_config.get('versions', {}).get(filename, 0.0)
                    remote_ver = remote_versions.get(filename, 0.0)

                    if float(remote_ver) > float(local_ver):
                        print("[OTA] Update found for {}: {} > {}".format(filename, remote_ver, local_ver))
                        if self._download_file(filename):
                            local_config['versions'][filename] = remote_ver
                            updated_any = True
                    else:
                        print("[OTA] {} is up to date.".format(filename))

                if updated_any:
                    self._finalize_update(local_config)
                    return True 
            if res: res.close()
        except Exception as e:
            print("[OTA] Update failed:", e)
            if res: res.close()
        return False

    def _download_file(self, filename):
        """Streaming download to prevent ENOMEM crashes."""
        gc.collect()
        res = None
        try:
            url = "{}/{}".format(self.repo_url, filename)
            res = urequests.get(url, timeout=15, stream=True)
            if res.status_code == 200:
                temp_file = "tmp_{}".format(filename)
                with open(temp_file, "wb") as f:
                    while True:
                        chunk = res.raw.read(128)
                        if not chunk: break
                        f.write(chunk)
                res.close()
                try: os.remove(filename)
                except: pass
                os.rename(temp_file, filename)
                return True
        except: pass
        finally:
            if res: res.close()
        return False

    def _finalize_update(self, new_config):
        """Atomic save and create OTA bypass flag for boot.py."""
        try:
            print("[OTA] Saving config...")
            plain_data = json.dumps(new_config)
            encrypted_data = self._xor_crypt(plain_data)
            
            # Write to temp file first
            with open("config.dat.tmp", "wb") as f:
                f.write(encrypted_data)
            
            # Rename temp to real (Atomic Swap)
            try: os.remove("config.dat")
            except: pass
            os.rename("config.dat.tmp", "config.dat")
            
            # --- CRITICAL ADDITION FOR YOUR BOOT.PY ---
            with open(".ota_running", "w") as f:
                f.write("1")
            # ------------------------------------------

            print("[OTA] Update complete. Rebooting safely...")
            time.sleep(1)
            machine.reset()
        except Exception as e:
            print("[OTA] Save failed:", e)
