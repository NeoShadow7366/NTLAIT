import urllib.request
import time
import subprocess

try:
    req = urllib.request.Request(
        'http://localhost:8080/api/launch', 
        data=b'{"package_id": "comfyui"}', 
        headers={'Content-Type': 'application/json'},
        method="POST"
    )
    res = urllib.request.urlopen(req).read().decode()
    print("Manager Launch Request:", res)
except Exception as e:
    print("Start failed via API:", e)

print("Waiting for ComfyUI to start...")
for i in range(15):
    try:
        urllib.request.urlopen('http://127.0.0.1:8188').read()
        print("\nComfyUI is UP!")
        break
    except:
        print(".", end="", flush=True)
        time.sleep(2)

print("\nRunning test_proxy.py...")
subprocess.run(["python", "test_proxy.py"])
