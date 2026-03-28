import os
import platform
import subprocess
import logging

logging.basicConfig(level=logging.INFO)

def create_safe_directory_link(source_dir: str, target_link: str) -> bool:
    """
    Creates a cross-platform link for directories.
    Windows: Directory Junction (no admin required).
    Unix: Symbolic Link.
    """
    if not os.path.exists(source_dir):
        logging.error(f"Source missing: {source_dir}")
        return False
        
    source_dir = os.path.abspath(source_dir)
    target_link = os.path.abspath(target_link)

    # 1. Conflict Prevention
    if os.path.exists(target_link) or os.path.islink(target_link):
        if os.path.islink(target_link):
            if os.readlink(target_link) == source_dir:
                return True # Already linked correctly
            os.unlink(target_link) # Safe remove if incorrect
        elif os.path.isdir(target_link):
            import shutil
            try:
                shutil.rmtree(target_link)
            except Exception as e:
                logging.error(f"Conflict: Real folder exists at {target_link} and cannot be removed: {e}")
                return False
        else:
            logging.error(f"Conflict: Real file exists at {target_link}. Refusing to overwrite.")
            return False

    os.makedirs(os.path.dirname(target_link), exist_ok=True)

    # 2. Cross-Platform Linking
    try:
        if platform.system() == "Windows":
            cmd = ["cmd.exe", "/c", "mklink", "/J", target_link, source_dir]
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode != 0:
                # Fallback to mklink /D if junction fails (e.g., non-NTFS volumes)
                cmd_d = ["cmd.exe", "/c", "mklink", "/D", target_link, source_dir]
                result_d = subprocess.run(cmd_d, capture_output=True, text=True)
                if result_d.returncode != 0:
                    raise OSError(f"Junction AND Symlink creation failed. J-err: {result.stderr.strip()}, D-err: {result_d.stderr.strip()}")
        else:
            os.symlink(source_dir, target_link, target_is_directory=True)
            
        logging.info(f"Successfully linked {source_dir} -> {target_link}")
        return True
    except OSError as e:
         logging.error(f"OS-level permission error: {e}")
         return False

if __name__ == "__main__":
    pass
