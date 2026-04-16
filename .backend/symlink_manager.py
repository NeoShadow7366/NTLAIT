import os
import platform
import subprocess
import logging

logging.basicConfig(level=logging.INFO)

# M-1 fix: NTFS junction detection via ctypes
# os.path.islink() returns False for NTFS directory junctions on Windows,
# even though mklink /J creates them. We need ctypes to check the reparse point flag.
def _is_junction_or_symlink(path: str) -> bool:
    """Detect whether a path is a symlink OR an NTFS directory junction.
    On UNIX, delegates to os.path.islink(). On Windows, checks the
    FILE_ATTRIBUTE_REPARSE_POINT flag via ctypes (catches both symlinks and junctions)."""
    if os.path.islink(path):
        return True
    if os.name == 'nt':
        try:
            import ctypes
            _FILE_ATTRIBUTE_REPARSE_POINT = 0x0400
            attrs = ctypes.windll.kernel32.GetFileAttributesW(str(path))
            if attrs != -1 and bool(attrs & _FILE_ATTRIBUTE_REPARSE_POINT):
                return True
        except Exception:
            pass
    return False


def _get_junction_target(path: str) -> str:
    """Resolve the target of a junction/symlink. Returns the real path or None."""
    try:
        return os.path.realpath(path)
    except (OSError, ValueError):
        return None


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

    # 1. Conflict Prevention (M-1 fix: properly detects NTFS junctions)
    if os.path.exists(target_link) or os.path.islink(target_link) or _is_junction_or_symlink(target_link):
        if _is_junction_or_symlink(target_link):
            # It's a junction or symlink — check if it already points to the right place
            current_target = _get_junction_target(target_link)
            if current_target and os.path.normcase(os.path.normpath(current_target)) == os.path.normcase(os.path.normpath(source_dir)):
                return True  # Already linked correctly
            # Wrong target — remove and re-create
            try:
                os.unlink(target_link)
                logging.info(f"Removed stale junction/symlink at {target_link}")
            except OSError:
                # os.unlink may fail on junctions; try rmdir
                try:
                    os.rmdir(target_link)
                    logging.info(f"Removed stale junction via rmdir at {target_link}")
                except Exception as e:
                    logging.error(f"Cannot remove stale link at {target_link}: {e}")
                    return False
        elif os.path.isdir(target_link):
            # Real directory — only remove if empty to avoid data loss
            try:
                if not os.listdir(target_link):
                    os.rmdir(target_link)
                    logging.info(f"Removed empty conflicting directory at {target_link}")
                else:
                    logging.error(f"Conflict: Non-empty folder exists at {target_link}. Backing up is recommended before overwriting.")
                    return False
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
