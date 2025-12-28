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
        self.filenames = filenames # This is your list of files to track

    def _xor_crypt(self, data):
        """Hardware-locked XOR utility."""
        if isinstance(data, str):
            data = data.encode('utf-8')
        key = machine.unique_id()
        return bytes([data[i] ^ key[i % len(key)] for i in range(len(data))])

    def check_and_update(self, local_config):
        """
        Checks version.json and downloads only files that have a newer version.
        Returns True if any file was updated (triggering a reboot).
        """
        if not isinstance(local_config, dict):
            print("[OTA] Error: local_config is not a dictionary")
            return False

        if 'versions' not in local_config:
            print("[OTA] Warning, 'versions' key missing in config. Initializing...")
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

                # Loop through every file we are tracking
                for filename in self.filenames:
                    # Get local version from config, default to 0.0 if not found
                    local_ver = local_config.get('versions', {}).get(filename, 0.0)
                    remote_ver = remote_versions.get(filename, 0.0)

                    if float(remote_ver) > float(local_ver):
                        print("[OTA] New version for {}: {} > {}".format(filename, remote_ver, local_ver))
                        
                        if self._download_file(filename):
                            # Update the local version mapping in memory
                            local_config['versions'][filename] = remote_ver
                            updated_any = True
                    else:
                        print("[OTA] {} is up to date ({})".format(filename, local_ver))

                if updated_any:
                    self._finalize_update(local_config)
                    return True # Signal that a reboot is happening
                
            if res: res.close()
        except Exception as e:
            print("[OTA] Update process failed:", e)
            if res: res.close()
            
        return False

    def _download_file(self, filename):
        """Internal helper to download and replace a single file."""
        gc.collect()
        cache_buster = "?cb={}".format(urandom.getrandbits(24))
        res = None
        try:
            url = "{}/{}{}".format(self.repo_url, filename, cache_buster)
            res = urequests.get(url, timeout=15)
            
            if res.status_code == 200:
                temp_file = "tmp_{}".format(filename)
                # Write file in binary mode for reliability
                with open(temp_file, "wb") as f:
                    f.write(res.content)
                res.close()
                
                try: os.remove(filename)
                except: pass
                
                os.rename(temp_file, filename)
                print("[OTA] Downloaded {}".format(filename))
                return True
            if res: res.close()
        except Exception as e:
            print("[OTA] Error downloading {}: {}".format(filename, e))
        return False

    def _finalize_update(self, new_config):
        """Saves the updated config as encrypted .dat and reboots."""
        try:
            # 1. Convert dict to encrypted bytes
            plain_data = json.dumps(new_config)
            encrypted_data = self._xor_crypt(plain_data)
            
            # 2. Save to the hardware-locked binary file
            with open("config.dat", "wb") as f:
                f.write(encrypted_data)
            
            # 3. Clean up the plaintext file if it exists
            try:
                if "config.json" in os.listdir():
                    os.remove("config.json")
            except:
                pass
            
            with open(".ota_running", "w") as f:
                f.write("1")
                
            print("[OTA] Encrypted config saved. Rebooting system...")
            time.sleep(1.5)
            machine.reset()
        except Exception as e:
            print("[OTA] Finalize failed:", e)
