import network
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

    def check_for_updates(self, current_version):
        """Checks if a newer version exists on GitHub."""
        gc.collect()
        res = None
        # Cache Buster: Forces GitHub to serve the absolute latest file
        cache_buster = "?cb={}".format(urandom.getrandbits(24))
        
        try:
            url = "{}/version.json{}".format(self.repo_url, cache_buster)
            print("[OTA] Checking:", url)
            res = urequests.get(url, timeout=10)
            
            if res.status_code == 200:
                data = res.json()
                remote_version = data['version']
                res.close()
                
                # Compare versions as floats
                has_update = float(remote_version) > float(current_version)
                return has_update, remote_version
            
            if res: res.close()
        except Exception as e:
            print("[OTA] Check failed:", e)
            if res: res.close()
            
        return False, current_version

    def download_updates(self, new_version):
        """Downloads all files and updates the local version config."""
        for file in self.filenames:
            gc.collect()
            cache_buster = "?cb={}".format(urandom.getrandbits(24))
            print("[OTA] Downloading {}...".format(file))
            
            res = None
            try:
                url = "{}/{}{}".format(self.repo_url, file, cache_buster)
                res = urequests.get(url, timeout=15)
                
                if res.status_code == 200:
                    # Write to a temporary file first
                    temp_file = "tmp_{}".format(file)
                    with open(temp_file, "w") as f:
                        f.write(res.text)
                    res.close()
                    
                    # Delete the old file to prevent rename conflicts
                    try:
                        os.remove(file)
                    except:
                        pass
                    
                    # Move the new file into place
                    os.rename(temp_file, file)
                    print("[OTA] Updated {} successfully".format(file))
                else:
                    print("[OTA] Error: Status {}".format(res.status_code))
                    if res: res.close()
                    return False
            except Exception as e:
                print("[OTA] Download failed for {}: {}".format(file, e))
                if res: res.close()
                return False

        # --- Update Config Version ---
        try:
            config = {}
            with open("config.json", "r") as f:
                config = json.load(f)
            
            config['version'] = new_version
            
            with open("config.json", "w") as f:
                json.dump(config, f)
            print("[OTA] Config version updated to", new_version)
        except Exception as e:
            print("[OTA] Failed to update config.json:", e)
            # We don't return False here because the code files are already updated

        # --- Prepare for Reboot ---
        try:
            # Create bypass flag for boot.py
            with open(".ota_running", "w") as f:
                f.write("1")
        except:
            pass

        print("[OTA] All files updated. Rebooting system...")
        
        # Flush file system buffers and release hardware
        gc.collect()
        time.sleep(1.5) 
        
        machine.reset()
