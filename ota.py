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

    def check_and_update(self, local_config):
        """
        Checks version.json and downloads only files that have a newer version.
        Returns True if any file was updated (triggering a reboot).
        """

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
                            if 'versions' not in local_config:
                                local_config['versions'] = {}
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
                with open(temp_file, "w") as f:
                    f.write(res.text)
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
        """Saves the updated config and reboots."""
        try:
            with open("config.json", "w") as f:
                json.dump(new_config, f)
            
            with open(".ota_running", "w") as f:
                f.write("1")
                
            print("[OTA] Config updated. Rebooting system...")
            time.sleep(1.5)
            machine.reset()
        except Exception as e:
            print("[OTA] Finalize failed:", e)
