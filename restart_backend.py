import psutil

def kill_manager():
    try:
        for p in psutil.process_iter(['pid', 'name', 'cmdline']):
            cmd = p.info.get('cmdline') or []
            if not cmd:
                continue
            cmd_str = " ".join(cmd).lower()
            if 'server.py' in cmd_str and '.backend' in cmd_str:
                print(f"Killing Manager: {p.info['pid']}")
                p.kill()
            elif 'main.py' in cmd_str and 'comfyui' in cmd_str:
                print(f"Killing ComfyUI Engine: {p.info['pid']}")
                p.kill()
    except Exception as e:
        print("Error:", e)

if __name__ == "__main__":
    kill_manager()
