import os
import sys
import sqlite3
import json
import logging
import subprocess
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')

class AIWebServer(BaseHTTPRequestHandler):
    root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    db_path = os.path.join(root_dir, ".backend", "metadata.sqlite")
    static_dir = os.path.join(root_dir, ".backend", "static")

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        
        # API Endpoints
        if path == "/api/models":
            self.send_api_models()
        elif path == "/api/packages":
            self.send_api_packages()
        elif path == "/api/recipes":
            self.send_api_recipes()
        elif path == "/api/downloads":
            self.handle_get_downloads()
        elif path == "/api/comfy_image":
            self.handle_comfy_image()
        elif path == "/api/comfy_upload":
            self.handle_comfy_upload()
        elif path == "/api/stop":
            self.handle_stop()
        else:
            self.serve_static_files(path)

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path
        
        content_length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(content_length) if content_length > 0 else b"{}"
        
        try:
            data = json.loads(body.decode('utf-8'))
        except:
            data = {}

        if path == "/api/install":
            self.handle_install(data)
        elif path == "/api/launch":
            self.handle_launch(data)
        elif path == "/api/uninstall":
            self.handle_uninstall(data)
        elif path == "/api/download":
            self.handle_download(data)
        elif path == "/api/delete_model":
            self.handle_delete_model(data)
        elif path == "/api/open_folder":
            self.handle_open_folder(data)
        elif path == "/api/comfy_proxy":
            self.handle_comfy_proxy(data)
        else:
            self.send_error(404, "Endpoint not found")

    def serve_static_files(self, path):
        # Default to index.html
        if path == "/":
            path = "/index.html"
            
        # Security: Prevent directory traversal
        if ".." in path:
            self.send_error(403, "Forbidden")
            return
            
        # Check if they are requesting a thumbnail
        if path.startswith("/.backend/cache/thumbnails/"):
            filepath = os.path.join(self.root_dir, path.lstrip("/"))
        else:
            filepath = os.path.join(self.static_dir, path.lstrip("/"))
            
        if not os.path.exists(filepath):
            self.send_error(404, "File Not Found")
            return
            
        # Basic MIME types mapping
        ext = filepath.split(".")[-1].lower()
        content_type = "text/plain"
        if ext == "html": content_type = "text/html"
        elif ext == "css": content_type = "text/css"
        elif ext == "js": content_type = "application/javascript"
        elif ext in ["jpg", "jpeg"]: content_type = "image/jpeg"
        elif ext == "png": content_type = "image/png"
        elif ext == "json": content_type = "application/json"
        elif ext == "webp": content_type = "image/webp"
        
        try:
            with open(filepath, "rb") as f:
                content = f.read()
            self.send_response(200)
            self.send_header("Content-type", content_type)
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)
        except Exception as e:
            self.send_error(500, f"Server Error: {str(e)}")

    def send_api_models(self):
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM models ORDER BY id DESC')
            rows = cursor.fetchall()
            conn.close()
            
            # Format rows
            models = []
            for row in rows:
                d = dict(row)
                if d.get("metadata_json"):
                    try:
                        d["metadata"] = json.loads(d["metadata_json"])
                    except:
                        d["metadata"] = None
                del d["metadata_json"]
                models.append(d)
                
            self.send_json_response({"status": "success", "models": models})
        except Exception as e:
            self.send_json_response({"status": "error", "message": str(e)}, 500)

    def send_api_packages(self):
        packages_dir = os.path.join(self.root_dir, "packages")
        packages = []
        if os.path.exists(packages_dir):
            for d in os.listdir(packages_dir):
                app_path = os.path.join(packages_dir, d)
                if os.path.isdir(app_path):
                    manifest_path = os.path.join(app_path, "manifest.json")
                    pkg_info = {"id": d, "name": d.capitalize()}
                    
                    if os.path.exists(manifest_path):
                        try:
                            with open(manifest_path, 'r', encoding='utf-8') as f:
                                manifest = json.load(f)
                                pkg_info["name"] = manifest.get("name", d.capitalize())
                        except:
                            pass
                    packages.append(pkg_info)
                    
        self.send_json_response({"status": "success", "packages": packages})

    def send_api_recipes(self):
        recipes_dir = os.path.join(self.root_dir, ".backend", "recipes")
        recipes = []
        if os.path.exists(recipes_dir):
            for file in os.listdir(recipes_dir):
                if file.endswith(".json"):
                    try:
                        with open(os.path.join(recipes_dir, file), 'r', encoding='utf-8') as f:
                            recipe = json.load(f)
                            recipes.append({
                                "id": file,
                                "app_id": recipe.get("app_id"),
                                "name": recipe.get("name", file),
                                "repository": recipe.get("repository", "")
                            })
                    except Exception as e:
                        logging.error(f"Error reading recipe {file}: {e}")
                        
        self.send_json_response({"status": "success", "recipes": recipes})

    def handle_install(self, data):
        recipe_id = data.get("recipe_id")
        if not recipe_id:
            self.send_json_response({"status": "error", "message": "Missing recipe_id"}, 400)
            return
            
        recipe_path = os.path.join(self.root_dir, ".backend", "recipes", recipe_id)
        if not os.path.exists(recipe_path):
            self.send_json_response({"status": "error", "message": "Recipe not found"}, 404)
            return

        installer_script = os.path.join(self.root_dir, ".backend", "installer_engine.py")
        
        logging.info(f"Triggering background installation for {recipe_id}")
        
        # Spawn isolated installation process
        kwargs = {}
        if os.name == 'nt':
            kwargs['creationflags'] = getattr(subprocess, 'CREATE_NEW_PROCESS_GROUP', 512)
            
        subprocess.Popen([sys.executable, installer_script, recipe_path], **kwargs)
        
        self.send_json_response({"status": "success", "message": "Installation started in background"})

    def handle_launch(self, data):
        package_id = data.get("package_id")
        if not package_id:
            self.send_json_response({"status": "error", "message": "Missing package_id"}, 400)
            return

        package_path = os.path.join(self.root_dir, "packages", package_id)
        manifest_path = os.path.join(package_path, "manifest.json")
        app_path = os.path.join(package_path, "app")
        
        if not os.path.exists(manifest_path) or not os.path.exists(app_path):
             self.send_json_response({"status": "error", "message": "Package improperly installed"}, 404)
             return

        try:
            with open(manifest_path, 'r', encoding='utf-8') as f:
                manifest = json.load(f)
        except Exception as e:
            self.send_json_response({"status": "error", "message": f"Could not read manifest: {str(e)}"}, 500)
            return

        launch_cmd = manifest.get("launch_command")
        if not launch_cmd:
            self.send_json_response({"status": "error", "message": "No launch_command found in manifest"}, 400)
            return

        # Determine python executable location
        if os.name == 'nt':
            python_exe = os.path.join(package_path, "env", "Scripts", "python.exe")
        else:
            python_exe = os.path.join(package_path, "env", "bin", "python")
            
        if not os.path.exists(python_exe):
            self.send_json_response({"status": "error", "message": "Isolated python environment not found"}, 404)
            return

        logging.info(f"Launching {package_id}...")
        
        # Explicitly launch in a new window/terminal so the user can see the App's logs
        kwargs = {}
        if os.name == 'nt':
            kwargs['creationflags'] = getattr(subprocess, 'CREATE_NEW_CONSOLE', 16)
            
        # Combine command, e.g. python_exe main.py
        full_command = [python_exe] + launch_cmd.split(" ")
        p = subprocess.Popen(full_command, cwd=app_path, **kwargs)
        AIWebServer.running_processes[package_id] = p
        
        self.send_json_response({"status": "success", "message": "Package starting..."})

    def handle_uninstall(self, data):
        package_id = data.get("package_id")
        if not package_id:
            self.send_json_response({"status": "error", "message": "Missing package_id"}, 400)
            return

        installer_script = os.path.join(self.root_dir, ".backend", "installer_engine.py")
        
        logging.info(f"Triggering background uninstallation for {package_id}")
        
        # We can run uninstall inline optionally, but for UX safety we stick to subprocess
        # Python script expects recipe.json natively.
        # Let's import installer_engine directly for faster deletion without background overhead.
        try:
            sys.path.append(os.path.join(self.root_dir, ".backend"))
            from installer_engine import RecipeInstaller
            installer = RecipeInstaller(self.root_dir)
            success = installer.uninstall(package_id)
            if success:
                self.send_json_response({"status": "success", "message": "Package uninstalled successfully"})
            else:
                self.send_json_response({"status": "error", "message": "Failed to uninstall package"}, 500)
        except Exception as e:
            self.send_json_response({"status": "error", "message": str(e)}, 500)

    def handle_download(self, data):
        url = data.get("url")
        filename = data.get("filename")
        model_name = data.get("model_name")
        dest_folder = data.get("dest_folder")

        if not all([url, filename, model_name, dest_folder]):
            self.send_json_response({"status": "error", "message": "Missing download parameters"}, 400)
            return
            
        import uuid
        job_id = str(uuid.uuid4())
        
        downloader_script = os.path.join(self.root_dir, ".backend", "download_engine.py")
        python_exe = sys.executable

        kwargs = {}
        if os.name == 'nt':
            kwargs['creationflags'] = getattr(subprocess, 'CREATE_NEW_PROCESS_GROUP', 0x00000200)

        cmd = [
            python_exe, downloader_script,
            "--job_id", job_id,
            "--url", url,
            "--dest_folder", dest_folder,
            "--filename", filename,
            "--model_name", model_name,
            "--root_dir", self.root_dir
        ]

        subprocess.Popen(cmd, **kwargs)
        self.send_json_response({"status": "success", "job_id": job_id})

    def handle_get_downloads(self):
        cache_file = os.path.join(self.root_dir, ".backend", "cache", "downloads.json")
        if not os.path.exists(cache_file):
            self.send_json_response({})
            return
        
        try:
            with open(cache_file, "r") as f:
                data = json.load(f)
            self.send_json_response(data)
        except Exception:
            self.send_json_response({})

    def handle_delete_model(self, data):
        filename = data.get("filename")
        category = data.get("category")
        if not filename or not category:
            self.send_json_response({"status": "error", "message": "Missing filename or category"}, 400)
            return
            
        filepath = os.path.join(self.root_dir, "Global_Vault", category, filename)
        if os.path.exists(filepath):
            try:
                os.remove(filepath)
                # Cleanup DB natively using metadata_db
                from metadata_db import MetadataDB
                db = MetadataDB(os.path.join(self.root_dir, ".backend", "metadata.sqlite"))
                db.remove_model_by_filename(filename)
                self.send_json_response({"status": "success", "message": "Model deleted"})
            except Exception as e:
                self.send_json_response({"status": "error", "message": str(e)}, 500)
        else:
            self.send_json_response({"status": "error", "message": "File not found"}, 404)

    def handle_open_folder(self, data):
        category = data.get("category")
        if not category:
            self.send_json_response({"status": "error", "message": "Missing category"}, 400)
            return
            
        folder_path = os.path.normpath(os.path.join(self.root_dir, "Global_Vault", category))
        os.makedirs(folder_path, exist_ok=True)
            
        try:
            if os.name == 'nt':
                subprocess.Popen(['explorer', folder_path])
            else:
                opener = "open" if sys.platform == "darwin" else "xdg-open"
                subprocess.Popen([opener, folder_path])
            self.send_json_response({"status": "success"})
        except Exception as e:
            self.send_json_response({"status": "error", "message": str(e)}, 500)

    def handle_comfy_proxy(self, data):
        endpoint = data.get("endpoint")
        if not endpoint:
            self.send_json_response({"error": "No endpoint specified"}, 400)
            return

        import urllib.request
        url = f"http://127.0.0.1:8188{endpoint}"
        payload = data.get("payload")
        
        try:
            if payload:
                req = urllib.request.Request(url, data=json.dumps(payload).encode('utf-8'), headers={'Content-Type': 'application/json'})
            else:
                req = urllib.request.Request(url)
            
            with urllib.request.urlopen(req) as res:
                content = res.read().decode('utf-8')
                self.send_json_response(json.loads(content))
        except Exception as e:
            self.send_json_response({"error": str(e)}, 500)

    def handle_comfy_image(self):
        # proxy raw image bytes from comfyUI
        import urllib.request
        from urllib.parse import urlparse
        
        parsed = urlparse(self.path)
        qs = parsed.query
        url = f"http://127.0.0.1:8188/view?{qs}"
        
        try:
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req) as res:
                img_data = res.read()
                
            self.send_response(200)
            self.send_header('Content-type', 'image/png')
            self.send_header('Cache-Control', 'no-cache')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(img_data)
        except Exception as e:
            self.send_error(500, str(e))

    def handle_comfy_upload(self):
        import urllib.request
        try:
            content_length = int(self.headers.get('Content-Length', 0))
            post_data = self.rfile.read(content_length)
            
            req = urllib.request.Request("http://127.0.0.1:8188/upload/image", data=post_data, method="POST")
            req.add_header('Content-Type', self.headers.get('Content-Type'))
            req.add_header('Origin', 'http://127.0.0.1:8188')
            req.add_header('Host', '127.0.0.1:8188')
            
            with urllib.request.urlopen(req) as res:
                res_body = res.read().decode('utf-8')
                self.send_response(200)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                self.wfile.write(res_body.encode('utf-8'))
        except Exception as e:
            self.send_json_response({"error": str(e)}, 500)

    def handle_stop(self):
        import subprocess
        import os
        import json
        try:
            content_length = int(self.headers.get('Content-Length', 0))
            post_data = json.loads(self.rfile.read(content_length).decode('utf-8'))
            package_id = post_data.get("package_id")
            
            if package_id in AIWebServer.running_processes:
                p = AIWebServer.running_processes[package_id]
                if os.name == 'nt':
                    subprocess.call(['taskkill', '/F', '/T', '/PID', str(p.pid)])
                else:
                    p.terminate()
                del AIWebServer.running_processes[package_id]
                self.send_json_response({"status": "success"})
            else:
                self.send_json_response({"status": "not_running", "message": "Package algorithm not strictly mapped in server."})
        except Exception as e:
            self.send_json_response({"error": str(e)}, 500)

    def send_json_response(self, data, status=200):
        self.send_response(status)
        self.send_header("Content-type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode("utf-8"))

def run_server(port=8080):
    server_address = ('', port)
    httpd = HTTPServer(server_address, AIWebServer)
    logging.info(f"Starting lightweight Web Server on http://localhost:{port}")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    httpd.server_close()
    logging.info("Server stopped.")

if __name__ == "__main__":
    run_server()
