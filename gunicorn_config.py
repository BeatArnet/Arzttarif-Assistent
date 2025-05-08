# gunicorn_config.py
import sys
import os
import traceback # Für detaillierte Fehlermeldungen

# Stelle sicher, dass das Hauptmodul importiert werden kann
# Normalerweise nicht nötig, wenn gunicorn im Projektstamm läuft
# sys.path.insert(0, os.path.dirname(__file__)) 

# Importiere die Ladefunktion und das Status-Flag aus deinem Server-Modul
try:
    # WICHTIG: Ersetze 'server' durch den tatsächlichen Namen deiner Python-Datei (ohne .py), falls er anders ist
    from server import load_data, daten_geladen, leistungskatalog_dict 
    print("INFO [Gunicorn Hook]: load_data und daten_geladen importiert.")
except ImportError as e:
    print(f"FEHLER [Gunicorn Hook]: Konnte load_data/daten_geladen nicht importieren: {e}")
    load_data = None # Setze Fallback

def post_worker_init(worker):
    """ Wird nach dem Start eines Workers ausgeführt. """
    print(f"INFO [Gunicorn Hook]: Worker {worker.pid} initialisiert. Lade Daten...")
    if load_data:
        try:
            load_data() # Ruft die Ladefunktion auf
            # Überprüfe direkt nach dem Laden
            if daten_geladen and leistungskatalog_dict:
                 print(f"INFO [Gunicorn Hook]: Datenladung für Worker {worker.pid} erfolgreich abgeschlossen. Status: {daten_geladen}")
            else:
                 print(f"FEHLER [Gunicorn Hook]: Datenladung für Worker {worker.pid} schlug fehl (Flag/Dict leer). Status: {daten_geladen}")

        except Exception as e:
            print(f"FEHLER [Gunicorn Hook]: Kritischer Fehler beim Laden der Daten im Worker {worker.pid}: {e}")
            traceback.print_exc()
            # Hier könntest du den Worker beenden, um Fehler zu signalisieren
            # sys.exit(1) 
    else:
         print("FEHLER [Gunicorn Hook]: load_data Funktion nicht verfügbar.")

# --- Optional: Weitere Gunicorn-Einstellungen ---
# Diese werden oft von Render.com über Umgebungsvariablen gesteuert,
# aber du kannst sie hier auch setzen.
# workers = int(os.environ.get('WEB_CONCURRENCY', '1')) # Render setzt WEB_CONCURRENCY
# bind = f"0.0.0.0:{os.environ.get('PORT', '10000')}" # Render setzt PORT
# timeout = 120