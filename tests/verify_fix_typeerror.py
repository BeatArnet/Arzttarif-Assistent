import sys
import os
import logging
import inspect

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Mock logging
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
    
    # Check if _get_tables_for_context_lkn is defined at module level
    if hasattr(server, '_get_tables_for_context_lkn'):
        print("SUCCESS: _get_tables_for_context_lkn is defined at module level.")
    else:
        print("FAILURE: _get_tables_for_context_lkn is NOT defined at module level.")
        sys.exit(1)
        
    # Check _determine_final_billing
    if hasattr(server, '_determine_final_billing'):
        print("SUCCESS: _determine_final_billing is defined.")
        # Inspect source to see if it looks reasonable (not truncated)
        source = inspect.getsource(server._determine_final_billing)
        print(f"Length of _determine_final_billing source: {len(source)} chars")
        if "return finale_abrechnung_obj, llm_stage2_mapping_results" in source:
             print("SUCCESS: _determine_final_billing contains expected return statement.")
        else:
             print("WARNING: Expected return statement not found in source (might be truncated or different formatting).")
    else:
        print("FAILURE: _determine_final_billing is NOT defined.")
        sys.exit(1)

    sys.exit(0)

except Exception as e:
    print(f"An error occurred: {e}")
    sys.exit(1)
