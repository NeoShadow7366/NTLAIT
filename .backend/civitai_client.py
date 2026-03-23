import os
import json
import time
import logging
import urllib.request
import urllib.error
from metadata_db import MetadataDB

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')

class CivitaiClient:
    def __init__(self, root_dir: str):
        self.root_dir = os.path.abspath(root_dir)
        self.db_path = os.path.join(self.root_dir, ".backend", "metadata.sqlite")
        self.db = MetadataDB(self.db_path)
        
        self.thumbnails_dir = os.path.join(self.root_dir, ".backend", "cache", "thumbnails")
        os.makedirs(self.thumbnails_dir, exist_ok=True)
        
        self.headers = {
            "User-Agent": "AIManager/1.0 (Contact: user@example.com)",
            "Accept": "application/json"
        }

    def fetch_model_by_hash(self, file_hash: str):
        url = f"https://civitai.com/api/v1/model-versions/by-hash/{file_hash}"
        req = urllib.request.Request(url, headers=self.headers)
        
        try:
            with urllib.request.urlopen(req, timeout=10) as response:
                if response.status == 200:
                    data = response.read()
                    return json.loads(data.decode('utf-8'))
        except urllib.error.HTTPError as e:
            if e.code == 404:
                logging.warning(f"Hash {file_hash[:8]} not found on Civitai (404).")
                return {"error": "not_found"}
            else:
                logging.error(f"HTTP Error {e.code} for hash {file_hash[:8]}")
        except Exception as e:
            logging.error(f"Error fetching hash {file_hash[:8]}: {str(e)}")
            
        return None

    def download_thumbnail(self, image_url: str, file_hash: str) -> str:
        if not image_url:
            return None
            
        ext = image_url.split(".")[-1].split("?")[0]
        if len(ext) > 4 or not ext:
            ext = "jpg"
            
        filename = f"{file_hash}.{ext}"
        filepath = os.path.join(self.thumbnails_dir, filename)
        
        # Don't re-download if it already exists
        if os.path.exists(filepath):
            return filepath
            
        req = urllib.request.Request(image_url, headers=self.headers)
        try:
            with urllib.request.urlopen(req, timeout=15) as response, open(filepath, 'wb') as f:
                f.write(response.read())
            return filepath
        except Exception as e:
            logging.error(f"Failed to download thumbnail from {image_url}: {e}")
            return None

    def process_unpopulated_models(self):
        logging.info("Checking database for unpopulated models...")
        models = self.db.get_unpopulated_models()
        
        if not models:
            logging.info("All models have metadata. Nothing to do!")
            return
            
        logging.info(f"Found {len(models)} models missing metadata.")
        
        for model in models:
            file_hash = model['file_hash']
            filename = model['filename']
            
            if not file_hash:
                logging.warning(f"Model {filename} has no hash! Skipping.")
                continue
                
            logging.info(f"Fetching metadata for {filename} [{file_hash[:8]}]")
            
            # 1. Fetch from Civitai API
            metadata = self.fetch_model_by_hash(file_hash)
            
            if metadata:
                thumbnail_path = None
                
                # 2. Extract and download preview image if available
                if "images" in metadata and len(metadata["images"]) > 0:
                    image_url = metadata["images"][0].get("url")
                    if image_url:
                        thumbnail_path = self.download_thumbnail(image_url, file_hash)
                        
                # Make thumbnail path relative to root_dir if it exists to keep paths portable
                if thumbnail_path:
                    try:
                        thumbnail_path = os.path.relpath(thumbnail_path, self.root_dir)
                    except ValueError:
                        pass
                
                # 3. Update DB
                self.db.update_model_metadata(
                    file_hash=file_hash,
                    metadata_json=json.dumps(metadata),
                    thumbnail_path=thumbnail_path
                )
                logging.info(f"Successfully populated metadata for {filename}.")
            else:
                logging.warning(f"Failed to fetch metadata for {filename}. Will retry next run.")
                
            # Rate limiting
            time.sleep(1)

if __name__ == "__main__":
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    client = CivitaiClient(root)
    client.process_unpopulated_models()
