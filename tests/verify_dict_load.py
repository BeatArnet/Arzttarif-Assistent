import sys
import os
import logging

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Mock logging to avoid file locking issues
import logging.handlers
class MockHandler(logging.Handler):
    def emit(self, record):
        pass
logging.handlers.RotatingFileHandler = MockHandler
logging.basicConfig(level=logging.INFO)

try:
    import server
    print("Server module imported.")
    
    # Run load_data
    print("Running load_data()...")
    success = server.load_data()
    
    if not success:
        print("load_data() returned False.")
        sys.exit(1)
        
    print(f"load_data() returned {success}.")
    
    # Check if dict is loaded
    print(f"leistungskatalog_dict length: {len(server.leistungskatalog_dict)}")
    
    if len(server.leistungskatalog_dict) > 0:
        print("SUCCESS: leistungskatalog_dict populated.")
        sys.exit(0)
    else:
        print("FAILURE: leistungskatalog_dict is empty.")
        sys.exit(1)

except Exception as e:
    print(f"An error occurred: {e}")
    sys.exit(1)
