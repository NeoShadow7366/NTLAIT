import os
import hashlib
import logging
from concurrent.futures import ThreadPoolExecutor
from metadata_db import MetadataDB

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')

class VaultCrawler:
    """Background worker designed to index massive files optimally and stash references in SQLite."""
    def __init__(self, root_dir: str):
        self.root_dir = os.path.abspath(root_dir)
        self.vault_dir = os.path.join(self.root_dir, "Global_Vault")
        self.db_path = os.path.join(self.root_dir, ".backend", "metadata.sqlite")
        self.db = MetadataDB(self.db_path)
        
        # Extensions we care about tracking
        self.valid_extensions = {".safetensors", ".pt", ".ckpt", ".bin"}
        
    def _calculate_hash(self, file_path: str) -> str:
        """Fast calculation of sha256. For massive files (like 6GB checkpoints), 
           we read in chunks."""
        sha256 = hashlib.sha256()
        try:
            with open(file_path, "rb") as f:
                # Read in 4MB chunks to prevent memory bloat on heavy models
                for chunk in iter(lambda: f.read(4096 * 1024), b""):
                    sha256.update(chunk)
            return sha256.hexdigest()
        except Exception as e:
            logging.error(f"Failed to hash {file_path}: {e}")
            return None

    def _process_file(self, root: str, filename: str):
        if not any(filename.endswith(ext) for ext in self.valid_extensions):
            return
            
        file_path = os.path.join(root, filename)
        
        # Ensure we skip ignored files
        if os.path.exists(os.path.join(root, ".manager_ignore")):
             return
             
        # Determine category based on the immediate folder inside Global_Vault
        rel_path = os.path.relpath(file_path, self.vault_dir)
        category = rel_path.split(os.sep)[0] if os.sep in rel_path else "misc"
        
        logging.info(f"Hashing new file: {filename}...")
        file_hash = self._calculate_hash(file_path)
        if file_hash:
            # We insert it. A foreground network queue can later grab this hash
            # and populate `metadata_json` with its Civitai API results.
            self.db.insert_or_update_model(
                filename=filename,
                vault_category=category,
                file_hash=file_hash
            )
            logging.info(f"Registered {filename} [{file_hash[:8]}] in database.")

    def crawl(self):
        logging.info(f"Starting Vault Crawl in {self.vault_dir}")
        if not os.path.exists(self.vault_dir):
            logging.warning("Vault directory missing; nothing to crawl.")
            return

        tracked_files = self.db.get_all_filenames()

        # Simple thread pool to parallelize hashing for very fast Multi-Channel NVMe SSDs
        with ThreadPoolExecutor(max_workers=4) as executor:
            for root, _, files in os.walk(self.vault_dir):
                for file in files:
                    if file in tracked_files:
                        continue
                    # Submit each file to the worker pool
                    executor.submit(self._process_file, root, file)
                    
        logging.info("Vault Crawl Complete.")

if __name__ == "__main__":
    crawler = VaultCrawler(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    crawler.crawl()
