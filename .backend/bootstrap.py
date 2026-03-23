import os
import sys
import logging

logging.basicConfig(level=logging.INFO)

def main():
    logging.info("Executing Python bootstrap step...")
    root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    logging.info(f"Project root identified as: {root_dir}")
    
    # Initialize necessary subdirectories for Global Vault
    vault_dirs = ["checkpoints", "loras", "vaes", "controlnet"]
    for d in vault_dirs:
        target_dir = os.path.join(root_dir, "Global_Vault", d)
        os.makedirs(target_dir, exist_ok=True)
        logging.info(f"Initialized vault directory: {target_dir}")
        
    logging.info("Project directory mapping initialized successfully.")

if __name__ == "__main__":
    main()
