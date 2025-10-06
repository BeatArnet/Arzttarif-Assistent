"""Hilfsskript für gezielte Text-Korrekturen in den Prompts.

Das Skript führt definierte ``str.replace``-Operationen auf ``prompts.py`` aus,
damit Änderungen versioniert bleiben und bei Bedarf erneut angewendet werden
können. Vor dem Ersetzen wird geprüft, ob jedes Muster genau einmal vorhanden
ist; bei Abweichungen bricht der Aufruf mit einer aussagekräftigen Fehlermeldung
ab.
"""

from pathlib import Path

text = Path('prompts.py').read_text()

replacements = [
    (
        '*   Associez toujours les durées à la bonne activité.\n',
        '*   Associez toujours les durées à la bonne activité.\n*   Si plusieurs indications de durée décrivent la même consultation (p.ex. "15 min + 10 minutes de conseil"), regroupez-les en une seule activité.\n'
    ),
    (
        '    *   Esempio B: "Articolazione temporo-mandibolare, lussazione. Riduzione chiusa con anestesia da anestesista" -> due attività.\n',
        '    *   Esempio B: "Articolazione temporo-mandibolare, lussazione. Riduzione chiusa con anestesia da anestesista" -> due attività.\n*   Collega sempre le durate alla relativa attività.\n*   Se più indicazioni di durata descrivono la stessa consultazione (es. "15 min + 10 minuti di consulenza"), uniscile in un\'unica attività.\n'
    ),
    (
        '*   Beziehe Zeitangaben stets auf die korrekte Tätigkeit.\n',
        '*   Beziehe Zeitangaben stets auf die korrekte Tätigkeit.\n*   Fasse mehrere Zeitangaben zur selben Konsultation zusammen (z.B. "15 Min + 10 Min Beratung" beschreibt eine Aktivität).\n'
    ),
    (
        '*   **Utilisez vos connaissances médicales :** Comprenez les synonymes et périphrases (p.ex. "ablation de verrue" = "exérèse de lésion cutanée bénigne").\n',
        '*   **Utilisez vos connaissances médicales :** Comprenez les synonymes et périphrases (p.ex. "ablation de verrue" = "exérèse de lésion cutanée bénigne").\n*   Lorsque le texte mentionne "Wechselzeit" ou "temps de changement", ajoute le code Wechselzeit adéquat (p.ex. ).\n'
    ),
    (
        '*   **Conoscenza medica:** Comprendi sinonimi e parafrasi (es. "rimozione verruca" = "asportazione lesione cutanea benigna").\n',
        '*   **Conoscenza medica:** Comprendi sinonimi e parafrasi (es. "rimozione verruca" = "asportazione lesione cutanea benigna").\n*   Se il testo parla di "Wechselzeit"/"tempo di cambio", aggiungi il codice Wechselzeit pertinente (es. ).\n'
    ),
    (
        '*   **Medizinisches Wissen nutzen:** Synonyme/Umschreibungen verstehen (z.B. "Warzenentfernung" = "Abtragung benigne Hautläsion").\n',
        '*   **Medizinisches Wissen nutzen:** Synonyme/Umschreibungen verstehen (z.B. "Warzenentfernung" = "Abtragung benigne Hautläsion").\n*   Bei Hinweis auf eine "Wechselzeit" füge den entsprechenden Wechselzeit-Code hinzu (z.B. ).\n'
    ),
    (
        '        2.  **LKN supplémentaire** ( ou  "chaque min suppl.") : à ajouter UNIQUEMENT si la durée > 5 min. La  est alors exactement .\n',
        '        2.  **LKN supplémentaire** ( ou  "chaque min suppl.") : à ajouter UNIQUEMENT si la durée > 5 min. La  est alors exactement .\n    *   **Cohérence de chapitre :** dès qu\'une consultation est identifiée comme , toutes les minutes associées restent en  (aucun mélange avec ).\n    *   **Respect des suppléments obligatoires :** appliquez les règles "Seulement en supplément de" du catalogue; ne retournez jamais une position de supplément sans sa base correspondante.\n'
    ),
    (
        '        2.  **LKN aggiuntiva** (/, "ogni min successivo"): solo se durata > 5 min,  = durata_totale - 5.\n',
        '        2.  **LKN aggiuntiva** (/, "ogni min successivo"): solo se durata > 5 min,  = durata_totale - 5.\n    *   **Coerenza capitolo:** una volta riconosciuta la consultazione come , tutte le sue minuti restano in  (nessuna combinazione con ).\n    *   **Rispetto delle posizioni supplementari:** applica le regole "Solo come supplemento a" del catalogo; non restituire mai una posizione di supplemento senza la sua base.\n'
    ),
    (
        '        2.  Zusatz-LKN (/, "jede weitere 1 Min"): nur wenn Dauer > 5 Min, .\n',
        '        2.  Zusatz-LKN (/, "jede weitere 1 Min"): nur wenn Dauer > 5 Min, .\n    *   **Kapitel-Konsistenz:** Sobald eine Konsultation als  erkannt ist, bleiben alle zugehörigen Minuten im -Kapitel (kein Mix mit ).\n    *   **Zuschlags-Regel:** Beachte alle Katalogvorgaben "Nur als Zuschlag zu ..." und liefere keine Zusatzposition ohne passende Basis zurück.\n'
    ),
    (
        '*   Confirmez que chaque LKN existe **exactement** dans le contexte (comparaison caractère par caractère, majuscules/minuscules ignorées). Sinon, écartez-la.\n',
        '*   Confirmez que chaque LKN existe **exactement** dans le contexte (comparaison caractère par caractère, majuscules/minuscules ignorées). Sinon, écartez-la.\n*   Tenez compte des règles de cumul du catalogue (p.ex. "Non cumulable ..."); supprimez toute LKN en conflit avec une position déjà retenue.\n'
    ),
    (
        '*   Conferma che ogni LKN esista **esattamente** nel contesto (confronto carattere per carattere, ignorando maiuscole/minuscole). Scarta le altre.\n',
        '*   Conferma che ogni LKN esista **esattamente** nel contesto (confronto carattere per carattere, ignorando maiuscole/minuscole). Scarta le altre.\n*   Rispetta le regole di cumulabilità del catalogo (es. "Non cumulabile ..."): se una LKN è vietata con un\'altra già selezionata, scartala.\n'
    ),
    (
        '*   Prüfe für **jede** LKN: exakter Zeichen-für-Zeichen-Treffer im Katalog-Kontext (Gross-/Kleinschreibung ignorieren). Sonst verwerfen.\n',
        '*   Prüfe für **jede** LKN: exakter Zeichen-für-Zeichen-Treffer im Katalog-Kontext (Gross-/Kleinschreibung ignorieren). Sonst verwerfen.\n*   Beachte die Kumulierungsvorgaben aus dem Katalog (z.B. "Nicht kumulierbar ...") und streiche LKNs, die mit bereits gewählten Positionen kollidieren.\n'
    ),
    (
        '*   **Contrôle final (consultations) :** si la Règle A s\'applique et que , la réponse DOIT contenir exactement  et .\n',
        '*   **Contrôle final (consultations) :** si la Règle A s\'applique et que , la réponse DOIT contenir exactement  et .\n*   Confirmez que chaque position "Seulement en supplément de" est accompagnée de sa position de base.\n'
    ),
    (
        '*   **Controllo finale (consultazioni):** se si applica la Regola A e , l\'output DEVE contenere esattamente  e .\n',
        '*   **Controllo finale (consultazioni):** se si applica la Regola A e , l\'output DEVE contenere esattamente  e .\n*   Assicurati che ogni posizione "Solo come supplemento a" sia accompagnata dalla relativa base.\n'
    ),
    (
        '*   **Finaler Check (Konsultationen):** wenn Regel A und , sicherstellen, dass **beide** Positionen enthalten sind (Basis + exakte Anzahl ). Falls fehlend, **hinzufuegen**.\n',
        '*   **Finaler Check (Konsultationen):** wenn Regel A und , sicherstellen, dass **beide** Positionen enthalten sind (Basis + exakte Anzahl ). Falls fehlend, **hinzufuegen**.\n*   Kontrolliere, dass jede Position mit "Nur als Zuschlag zu" gemeinsam mit ihrer Basisposition ausgegeben wird.\n'
    ),
]

for old, new in replacements:
    if old not in text:
        # Bricht sofort ab, falls sich ``prompts.py`` verändert hat und das Muster fehlt.
        raise SystemExit(f'Pattern not found: {old!r}')
    text = text.replace(old, new, 1)

Path('prompts.py').write_text(text)
