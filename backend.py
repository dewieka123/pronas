import http.server
import socketserver
import os
import json
import urllib.parse
import shutil
import re
import subprocess

# --- KONFIGURASI ---
PORT = 8000
HTML_FILE = "drive.html"
# Folder tujuan sudah disesuaikan
STORAGE_ROOT = r"C:\Users\Admin\Project\Drive Cloud"

if not os.path.exists(STORAGE_ROOT):
    os.makedirs(STORAGE_ROOT)

class NASHandler(http.server.SimpleHTTPRequestHandler):
    
    def get_safe_path(self, rel_path):
        if '..' in rel_path: return None
        rel_path = rel_path.replace('/', os.sep).replace('\\', os.sep)
        return os.path.join(STORAGE_ROOT, rel_path.strip(os.sep))

    def do_GET(self):
        if self.path == '/favicon.ico':
            self.send_response(204); self.end_headers(); return

        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)

        if parsed.path == '/':
            try:
                with open(HTML_FILE, 'rb') as f:
                    self.send_response(200)
                    self.send_header('Content-type', 'text/html')
                    self.end_headers()
                    self.wfile.write(f.read())
            except FileNotFoundError:
                self.send_error(404, "HTML tidak ditemukan.")
            return

        if parsed.path == '/api/list':
            rel_path = params.get('path', [''])[0]
            target_dir = self.get_safe_path(rel_path)
            items = []
            if target_dir and os.path.exists(target_dir):
                try:
                    for name in os.listdir(target_dir):
                        full_p = os.path.join(target_dir, name)
                        items.append({'name': name, 'type': 'folder' if os.path.isdir(full_p) else 'file'})
                except PermissionError: pass
            
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps(items).encode())
            return

        if parsed.path == '/api/download':
            rel_path = params.get('path', [''])[0]
            file_path = self.get_safe_path(rel_path)
            if file_path and os.path.exists(file_path) and os.path.isfile(file_path):
                self.send_response(200)
                self.send_header('Content-Type', 'application/octet-stream')
                self.send_header('Content-Disposition', f'attachment; filename="{os.path.basename(file_path)}"')
                self.send_header('Content-Length', str(os.path.getsize(file_path)))
                self.end_headers()
                with open(file_path, 'rb') as f:
                    shutil.copyfileobj(f, self.wfile)
            else: self.send_error(404)
            return
        super().do_GET()

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)

        # UPLOAD MULTIPLE FILES FIX
        if parsed.path == '/api/upload':
            content_type = self.headers.get('Content-Type', '')
            if 'multipart/form-data' in content_type:
                boundary = content_type.split("boundary=")[1].encode()
                content_length = int(self.headers['Content-Length'])
                body = self.rfile.read(content_length)
                parts = body.split(b'--' + boundary)
                
                rel_path = ''
                files_to_save = [] # Array untuk menampung semua file
                
                for part in parts:
                    if not part or part == b'--\r\n': continue
                    if b'\r\n\r\n' in part:
                        head_bytes, value_bytes = part.split(b'\r\n\r\n', 1)
                        head_str = head_bytes.decode(errors='ignore')
                        value_bytes = value_bytes.rstrip(b'\r\n')
                        
                        if 'name="path"' in head_str:
                            rel_path = value_bytes.decode(errors='ignore')
                        elif 'filename="' in head_str:
                            m = re.search(r'filename="([^"]+)"', head_str)
                            if m: 
                                # Simpan ke array, jangan ditimpa
                                files_to_save.append((m.group(1), value_bytes))

                # Proses penyimpanan
                save_dir = self.get_safe_path(rel_path)
                if save_dir:
                    if not os.path.exists(save_dir): os.makedirs(save_dir)
                    for filename, file_content in files_to_save:
                        # Bersihkan nama file agar aman di Windows
                        clean_name = re.sub(r'[^\w\.-]', '_', filename)
                        with open(os.path.join(save_dir, clean_name), 'wb') as f: 
                            f.write(file_content)
                            
                self.send_response(200); self.end_headers(); self.wfile.write(b'OK')
            return

        length = int(self.headers.get('content-length', 0))
        body_data = {}
        if length > 0: body_data = json.loads(self.rfile.read(length))

        if parsed.path == '/api/mkdir':
            target = self.get_safe_path(body_data.get('path', ''))
            if target and not os.path.exists(target): os.makedirs(target)
            self.send_response(200); self.end_headers(); self.wfile.write(b'OK')
            return

        if parsed.path == '/api/delete':
            target = self.get_safe_path(body_data.get('path', ''))
            if target and os.path.exists(target):
                if os.path.isdir(target): shutil.rmtree(target)
                else: os.remove(target)
            self.send_response(200); self.end_headers(); self.wfile.write(b'OK')
            return

        if parsed.path == '/api/paste':
            action = body_data.get('action')
            src_path = self.get_safe_path(body_data.get('source'))
            dest_folder = self.get_safe_path(body_data.get('destination'))
            if src_path and dest_folder:
                dest_path = os.path.join(dest_folder, os.path.basename(src_path))
                try:
                    if action == 'move': shutil.move(src_path, dest_path)
                    elif action == 'copy':
                        if os.path.isdir(src_path): shutil.copytree(src_path, dest_path, dirs_exist_ok=True)
                        else: shutil.copy2(src_path, dest_path)
                except Exception: pass
            self.send_response(200); self.end_headers(); self.wfile.write(b'OK')
            return

        if parsed.path == '/api/rename':
            old_path = self.get_safe_path(body_data.get('old_path'))
            new_name = body_data.get('new_name')
            if old_path and new_name and os.path.exists(old_path):
                new_path = os.path.join(os.path.dirname(old_path), new_name)
                try: os.rename(old_path, new_path)
                except Exception: pass
            self.send_response(200); self.end_headers(); self.wfile.write(b'OK')
            return

        if parsed.path == '/api/cmd':
            command = body_data.get('command', '')
            output_text = ""
            if command.strip():
                try:
                    result = subprocess.run(command, shell=True, capture_output=True, text=True, timeout=15)
                    output_text = result.stdout + result.stderr
                    if not output_text.strip():
                        output_text = "[Perintah selesai tanpa output]"
                except subprocess.TimeoutExpired:
                    output_text = "Error: Eksekusi terlalu lama (Timeout)."
                except Exception as e:
                    output_text = f"System Error: {e}"

            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({'output': output_text}).encode())
            return

socketserver.TCPServer.allow_reuse_address = True
print(f"NAS System & Web Terminal Aktif di http://localhost:{PORT}")
with socketserver.TCPServer(("", PORT), NASHandler) as httpd:
    try: httpd.serve_forever()
    except KeyboardInterrupt: pass