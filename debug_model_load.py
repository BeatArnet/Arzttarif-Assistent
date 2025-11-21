import sys
import time

print(f"Python Version: {sys.version}")

try:
    import torch
    print(f"Torch Version: {torch.__version__}")
    print(f"CUDA Available: {torch.cuda.is_available()}")
except ImportError as e:
    print(f"Torch Import Error: {e}")

# Default to None so the name is always bound for type checkers and runtime guards.
SentenceTransformer = None

try:
    from sentence_transformers import SentenceTransformer as _SentenceTransformer
    SentenceTransformer = _SentenceTransformer
    print("SentenceTransformers imported successfully.")
except ImportError as e:
    print(f"SentenceTransformers Import Error: {e}")

model_name = "sentence-transformers/paraphrase-multilingual-mpnet-base-v2"

if not SentenceTransformer:
    print("SentenceTransformers not available; skipping model load.")
else:
    print(f"Attempting to load model: {model_name}")
    try:
        start = time.time()
        model = SentenceTransformer(model_name)
        print(f"Model loaded successfully in {time.time() - start:.2f} seconds.")
    except Exception as e:
        print(f"Error loading model: {e}")
    except SystemExit as e:
        print(f"SystemExit caught: {e}")

print("Debug script finished.")
