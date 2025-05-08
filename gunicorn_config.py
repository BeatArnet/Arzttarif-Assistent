# gunicorn_config.py
import sys
import os
import traceback # Für detaillierte Fehlermeldungen

# Stelle sicher, dass das Hauptmodul importiert werden kann
# Normalerweise nicht nötig, wenn gunicorn im Projektstamm läuft
# sys.path.insert(0, os.path.dirname(__file__)) 

# Importiere die Ladefunktion und das Status-Flag aus deinem Server-Modul
try:
    from server import load_data, leistungskatalog_dict 
    print("INFO [Gunicorn Hook]: load_data und daten_geladen importiert.")
except ImportError as e:
    print(f"FEHLER [Gunicorn Hook]: Konnte load_data/daten_geladen nicht importieren: {e}")
    load_data = None

def post_worker_init(worker):
    """ Wird nach dem Start eines Workers ausgeführt. """
    print(f"INFO [Gunicorn Hook]: Worker {worker.pid} initialisiert. Lade Daten...")
    if load_data:
        try:
            # Rufe load_data auf und speichere das Ergebnis
            load_successful = load_data()

            # Überprüfe den Rückgabewert UND ob ein kritisches Dict gefüllt ist
            if load_successful and leistungskatalog_dict: # Prüfe Rückgabewert UND ein Dict
                 print(f"INFO [Gunicorn Hook]: Datenladung für Worker {worker.pid} erfolgreich abgeschlossen.")
                 # Setze hier optional ein globales Flag im Server-Modul, wenn du es brauchst
                 # (Importiere 'daten_geladen' und setze server.daten_geladen = True)
                 # from server import daten_geladen # Importiere das Flag
                 # server.daten_geladen = True # Setze das Flag im Modul server
            else:
                 print(f"FEHLER [Gunicorn Hook]: Datenladung für Worker {worker.pid} schlug fehl (load_data gab {load_successful} zurück oder Dict leer).")
                 # Hier ggf. Worker beenden
                 # sys.exit(1)

        except Exception as e:
            print(f"FEHLER [Gunicorn Hook]: Kritischer Fehler beim Laden der Daten im Worker {worker.pid}: {e}")
            traceback.print_exc()
            # sys.exit(1)
    else:
         print("FEHLER [Gunicorn Hook]: load_data Funktion nicht verfügbar.")

# --- Optional: Weitere Gunicorn-Einstellungen ---
# Diese werden oft von Render.com über Umgebungsvariablen gesteuert,
# aber du kannst sie hier auch setzen.
# workers = int(os.environ.get('WEB_CONCURRENCY', '1')) # Render setzt WEB_CONCURRENCY
# bind = f"0.0.0.0:{os.environ.get('PORT', '10000')}" # Render setzt PORT
# timeout = 120