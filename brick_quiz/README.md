# Breakout Arzttarif – Spiel & Quiz

Ein browserbasiertes Breakout‑Spiel, das medizinische Tarif‑Quizfragen integriert. **Das Spiel ist vollständig in HTML/CSS/JavaScript umgesetzt – Python wird ausschließlich dazu verwendet, per `excel_to_json.py` den Fragenkatalog aus der Excel‑Datei zu erzeugen.** Die Fragen stammen aus einer Excel‑Datei und werden vor Spielstart in eine JSON‑Datei umgewandelt, die das Spiel dann dynamisch lädt.

---

## 🕹️ Spielbeschreibung

Halte den Ball mit dem Paddle im Spiel, zerstöre Bricks und beantworte Quizfragen, die sich hinter speziellen „?-Bricks“ verbergen. Richtige Antworten erhöhen deinen Punktestand, falsche machen das Spiel schneller!

---

## 🎮 Steuerung

| Eingabegerät | Aktion                              |
| ------------ | ----------------------------------- |
| **Maus**     | Paddle horizontal steuern           |
| **← / →**    | Paddle nach links / rechts          |
| **↑ / ↓**    | Im Quiz Antworten wählen            |
| **Enter**    | Antwort bestätigen                  |
| **Esc**      | Quiz verlassen bzw. Spiel abbrechen |

---

## 🌟 Features

* Farbige Bricks, dynamische Ballphysik, wechselnde Paddle‑Farben
* Soundeffekte für alle Kollisionen und Spielende
* Zufällig eingestreute Quiz‑Bricks (Fragen aus **`questions.json`**)
* Punktesystem & Ergebnis‑Popup
* Vollständig tastatur‑ und mausbedienbar

---

## 📂 Verzeichnisstruktur

```
.
├─ Brick.html                    # Einstiegspunkt (enthält Spiel + Styles + JS)
├─ questions.js                  # Fragenkatalog (wird aus der Excel erzeugt)
├─ excel_to_json.py              # Excel → JSON‑Konverter (optional)
└─ Neuer_Arzttarif_Frage_Antwort_Spiel.xlsx  # Quell‑Excel für neue Fragen (optional)
```

---

## ⚙️ Voraussetzungen

| Zweck                                   | Software                                                |
| --------------------------------------- | ------------------------------------------------------- |
| **Spiel ausführen**                     | Moderner Browser (Chrome, Firefox ≥ v100, Edge, Safari) |
| **Fragenkatalog erzeugen** *(optional)* | Python 3.9 +   mit Paketen **pandas** und **openpyxl**  |

### Pakete installieren *(nur für die Konvertierung nötig)*

```bash
python -m pip install pandas openpyxl
```

---

## 🛠️ Excel → JSON konvertieren

1. Lege die Datei **`Neuer_Arzttarif_Frage_Antwort_Spiel.xlsx`** im Projektstamm ab.
2. Führe das Skript aus:

   ```bash
   python excel_to_json.py
   ```

   Das Skript liest die Spalten *Stichwort*, *Frage*, *Antwort\_1 … 3*, *Korrekte\_Antwort* und legt/aktualisiert **`questions.json`**.
3. Starte anschließend das Spiel – das JSON wird vom Browser geladen.

> **Hinweis:** Wenn Spalten fehlen oder der Dateiname abweicht, bricht das Skript mit einer Fehlermeldung ab.

---

## 🚀 Spiel starten

Einfach `Brick.html` im Browser öffnen. Alternativ kannst du lokal einen kleinen Webserver starten:

```bash
python -m http.server 8000
```

Dann im Browser `http://localhost:8000/brick_quiz/Brick.html` aufrufen.

---

## 📝 Lizenz

Dieses Projekt steht unter der MIT‑Lizenz.
