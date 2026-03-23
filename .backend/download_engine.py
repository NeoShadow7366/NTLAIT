import os
import sys
import json
import urllib.request
import argparse
import time
import logging

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')

class Downloader:
    def __init__(self, root_dir):
        self.cache_dir = os.path.join(root_dir, ".backend", "cache")
        os.makedirs(self.cache_dir, exist_ok=True)
        self.status_file = os.path.join(self.cache_dir, "downloads.json")
    
    def _read_status(self):
        if not os.path.exists(self.status_file):
            return {}
        try:
            with open(self.status_file, "r") as f:
                return json.load(f)
        except:
            return {}

    def _write_status(self, data):
        with open(self.status_file, "w") as f:
            json.dump(data, f)

    def update_job(self, job_id, update_dict):
        status = self._read_status()
        if job_id not in status:
            status[job_id] = {}
        status[job_id].update(update_dict)
        self._write_status(status)

    def download(self, job_id, url, dest_folder, filename, model_name):
        self.update_job(job_id, {
            "model_name": model_name,
            "filename": filename,
            "status": "starting",
            "progress": 0,
            "downloaded": 0,
            "total": 0
        })

        target_path = os.path.join(dest_folder, filename)
        
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'AIManager/1.0'})
            with urllib.request.urlopen(req) as response:
                total_size = int(response.info().get('Content-Length', 0))
                self.update_job(job_id, {"status": "downloading", "total": total_size})
                
                downloaded = 0
                chunk_size = 8192 * 4  # 32KB chunks
                
                # Setup throttle to prevent disk-thrashing the JSON status file
                last_update_time = time.time()
                
                with open(target_path, 'wb') as f:
                    while True:
                        chunk = response.read(chunk_size)
                        if not chunk:
                            break
                        f.write(chunk)
                        downloaded += len(chunk)
                        
                        now = time.time()
                        if now - last_update_time > 0.5:  # update JSON every 500ms max
                            progress = int((downloaded / total_size) * 100) if total_size > 0 else 0
                            self.update_job(job_id, {
                                "progress": progress,
                                "downloaded": downloaded,
                                "status": "downloading"
                            })
                            last_update_time = now

            self.update_job(job_id, {"status": "completed", "progress": 100})
            logging.info(f"Successfully downloaded {filename} to {target_path}")

            # Trigger Vault Crawler to sync new files to SQLite
            try:
                crawler_script = os.path.join(self.cache_dir, "..", "vault_crawler.py")
                python_exe = sys.executable
                import subprocess
                # Run the crawler silently in the background
                kwargs = {}
                if os.name == 'nt':
                     kwargs['creationflags'] = getattr(subprocess, 'CREATE_NEW_PROCESS_GROUP', 512)
                subprocess.Popen([python_exe, crawler_script], **kwargs)
                logging.info("Spawned silent Vault Crawler background sync.")
            except Exception as crawl_err:
                logging.error(f"Failed to spawn vault crawler: {crawl_err}")

        except Exception as e:
            logging.error(f"Download failed for {filename}: {e}")
            self.update_job(job_id, {"status": "error", "message": str(e)})


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--job_id", required=True)
    parser.add_argument("--url", required=True)
    parser.add_argument("--dest_folder", required=True)
    parser.add_argument("--filename", required=True)
    parser.add_argument("--model_name", required=True)
    parser.add_argument("--root_dir", required=True)

    args = parser.parse_args()
    
    # Ensure dest_folder is absolute or resolve relative to root_dir
    if not os.path.isabs(args.dest_folder):
        args.dest_folder = os.path.join(args.root_dir, args.dest_folder)
        
    os.makedirs(args.dest_folder, exist_ok=True)
    
    downloader = Downloader(args.root_dir)
    downloader.download(args.job_id, args.url, args.dest_folder, args.filename, args.model_name)
