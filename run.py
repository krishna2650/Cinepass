import os
import sys

# Ensure backend directory is in python module search path
backend_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "backend")
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from app import create_app

app = create_app()

if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("🎬  Starting Cinepass Production Server")
    print("📍  Local URL:   http://127.0.0.1:5000")
    print("🔐  Admin Login: admin@cinepass.com / CinePass@Admin2026")
    print("=" * 60 + "\n")
    app.run(host="0.0.0.0", port=5000, debug=True)
