# Development Guide

This short guide explains how to set up the environment for development and run the automated tests.

## Install Dependencies

The test suite requires Flask and the other packages listed in `requirements.txt`. Install them with:

```bash
pip install -r requirements.txt
```

## Running Tests

After the dependencies are installed, execute the tests with:

```bash
pytest -q
```

The tests live in the `tests/` directory and rely on the Flask application defined in `server.py`.
