import sys
import os
import logging

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Mock logging to avoid clutter
logging.basicConfig(level=logging.CRITICAL)

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
    
    # Check if data is loaded
    print(f"pauschale_bedingungen_data length: {len(server.pauschale_bedingungen_data)}")
    print(f"leistungskatalog_data length: {len(server.leistungskatalog_data)}")
    
    if len(server.pauschale_bedingungen_data) > 0 and len(server.leistungskatalog_data) > 0:
        print("SUCCESS: Data loaded correctly.")
        sys.exit(0)
    else:
        print("FAILURE: Data lists are empty.")
        sys.exit(1)

except Exception as e:
    print(f"An error occurred: {e}")
    sys.exit(1)
