import sys
path = '/home/yourusername/restaurant-manager'
if path not in sys.path:
    sys.path.insert(0, path)

from app import app as application
