import sys
import os
import logging

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Mock logging to avoid file locking issues
import logging.handlers
class MockHandler(logging.Handler):
    def __init__(self, *args, **kwargs):
        super().__init__()
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
    
    # Test _get_tables_for_context_lkn
    test_lkn = "C00.RO.0010"
    expected_table = "C05.35_5"
    
    print(f"Testing _get_tables_for_context_lkn('{test_lkn}')...")
    try:
        tables = server._get_tables_for_context_lkn(test_lkn)
        print(f"Result: {tables}")
        
        if expected_table in tables:
            print("SUCCESS: Function defined and returned expected table.")
            sys.exit(0)
        else:
            print(f"FAILURE: Expected table '{expected_table}' not found in result.")
            sys.exit(1)
            
    except NameError:
        print("FAILURE: NameError: function not defined.")
        sys.exit(1)
    except AttributeError:
        print("FAILURE: AttributeError: function not found in server module.")
        sys.exit(1)

except Exception as e:
    print(f"An error occurred: {e}")
    sys.exit(1)
