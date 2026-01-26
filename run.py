import os
import sys
import subprocess

# --- PATH CONFIGURATION ---
# Add the current directory to sys.path so 'src' can be imported correctly
current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.append(current_dir)

def main():
    """
    Main entry point for the Sentinel Framework.
    """
    print("------------------------------------------------")
    print("   SENTINEL FRAMEWORK - IDENTITY MIDDLEWARE     ")
    print("------------------------------------------------")

    # 1. SSL CERTIFICATE CONFIGURATION
    # Browsers BLOCK webcam access on LAN unless HTTPS is used.
    # Ensure you have 'cert.pem' and 'key.pem' in src/static/cert/
    cert_dir = os.path.join(current_dir, "src", "static", "cert")
    cert_file = os.path.join(cert_dir, "cert.pem")
    key_file = os.path.join(cert_dir, "key.pem")
    
    use_ssl = False
    
    if os.path.exists(cert_file) and os.path.exists(key_file):
        use_ssl = True
        print(f"[INFO] SSL Certificates found in: {cert_dir}")
        print("[INFO] Mode: HTTPS (Secure). Biometrics will work on LAN devices.")
    else:
        print(f"[WARN] No SSL Certificates found in: {cert_dir}")
        print("       You must generate 'cert.pem' and 'key.pem' for camera access on external devices.")
        print("       Command: openssl req -x509 -newkey rsa:4096 -keyout key.pem -out cert.pem -days 365 -nodes")
        print("[INFO] Mode: HTTP (Insecure). Webcam will ONLY work on localhost.")

    # 2. PORT CONFIGURATION
    # User requested port 8080 specifically
    PORT = "8080"

    # 3. BUILD UVICORN COMMAND
    cmd = [
        sys.executable, "-m", "uvicorn", 
        "src.main:app",       # The FastAPI app instance
        "--host", "0.0.0.0",  # Listen on all network interfaces
        "--port", PORT,       # Port 8080
        "--reload"            # Auto-reload on save
    ]

    if use_ssl:
        cmd.extend(["--ssl-certfile", cert_file, "--ssl-keyfile", key_file])

    # 4. START SERVER
    protocol = "https" if use_ssl else "http"
    print(f"\n[START] Server running at: {protocol}://0.0.0.0:{PORT}")
    print(f"[LINK] Local Access:      {protocol}://127.0.0.1:{PORT}")
    
    try:
        subprocess.run(cmd)
    except KeyboardInterrupt:
        print("\n[INFO] Sentinel Server shutting down...")

if __name__ == "__main__":
    main()