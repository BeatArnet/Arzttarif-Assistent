# --- Prompt-Übersetzungen ---
def get_stage1_prompt(user_input: str, katalog_context: str, lang: str) -> str:
    """Return the Stage 1 prompt in the requested language."""
    if lang == "fr":
        return f"""**Tâche :** Analyse avec précision le texte de traitement médical ci-dessous provenant de Suisse. Ta mission consiste à identifier les numéros du catalogue des prestations (LKN), à en déterminer la quantité et à extraire les informations contextuelles. Appuie-toi principalement sur le LKAAT_Leistungskatalog fourni, mais tu peux aussi tenir compte de synonymes médicaux courants ou de termes usuels et consulter la table des forfaits.

**Contexte : LKAAT_Leistungskatalog (source de référence pour les LKN et leurs descriptions ; la table des forfaits peut également être prise en compte.)**
--- Leistungskatalog Start ---
{katalog_context}
--- Leistungskatalog Ende ---

**Instructions :** Suis exactement les étapes suivantes :

1.  **Identification des LKN et validation STRICTE:**
    *   Lis le "Behandlungstext" attentivement.
    *   Identifie **tous** les codes LKN potentiels (format `XX.##.####`) pouvant représenter les actes décrits.
    *   Note que plusieurs prestations peuvent être documentées dans le texte et que plusieurs LKN peuvent être valides (p. ex. intervention chirurgicale plus anesthésie).
    *   Si une anesthésie ou une narcose réalisée par un anesthésiste est mentionnée sans précisions sur la classe d'effort ou la durée, tu peux choisir un code LKN générique d'anesthésie. Utilise dans ce cas, en règle générale, WA.05.0020. Si une durée d'anesthésie précise en minutes est indiquée, emploie plutôt le code LKN correspondant WA.10.00x0.
    *   Mets à profit tes connaissances médicales sur les synonymes et termes techniques usuels (p. ex. reconnais que « opération de la cataracte » = « phacoémulsification » / « extraction du cristallin » = « Extractio lentis »).
    *   **ABSOLUMENT CRITIQUE:** Pour CHAQUE code LKN potentiel, vérifie **LETTRE PAR LETTRE et CHIFFRE PAR CHIFFRE** que ce code existe **EXACTEMENT** comme 'LKN:' dans le catalogue ci-dessus. Ce n'est que si le code existe que tu compares la **description du catalogue** avec l'acte décrit.
    *   Crée une liste (`identified_leistungen`) **UNIQUEMENT** avec les LKN ayant passé cette vérification exacte et dont la description correspond au texte.
    *   Reconnais si les prestations relèvent du chapitre CA (médecine de famille).

2.  **Type et description:**
    *   Pour chaque LKN **validée** de `identified_leistungen`, ajoute le `typ` et la `beschreibung` **directement et sans modification** depuis le contexte du catalogue pour cette LKN.

3.  **Extraction d'informations contextuelles (CRITIQUE pour les conditions supplémentaires):**
    *   Extrait **uniquement** les valeurs explicitement mentionnées dans le "Behandlungstext":
        *   `dauer_minuten` (nombre)
        *   `menge_allgemein` (nombre)
        *   `alter` (nombre)
        *   `geschlecht` ('weiblich', 'männlich', 'divers', 'unbekannt')
        *   `seitigkeit` (chaîne: 'einseitig', 'beidseits', 'links', 'rechts', 'unbekannt')
        *   `anzahl_prozeduren` (nombre ou `null`)
    *   Si une valeur n'est pas mentionnée, définis-la sur `null` (sauf `seitigkeit`, qui peut être 'unbekannt').

4.  **Détermination de la quantité (par LKN validée):**
    *   La quantité par défaut est `1`.
    *   **Basé sur le temps:** si la description du catalogue contient "pro X Min" ET que `dauer_minuten` (Y) est extrait, mets `menge` = Y.
    *   **Général:** si `menge_allgemein` (Z) est extrait ET que la LKN n'est pas basée sur le temps ET `anzahl_prozeduren` est `null`, mets `menge` = Z.
    *   **Nombre spécifique de procédures:** si `anzahl_prozeduren` est extrait et se rapporte clairement à la LKN (p. ex. "deux injections"), mets `menge` = `anzahl_prozeduren`. Cela prime sur `menge_allgemein`.
    *   Assure-toi que `menge` >= 1.

5.  **Justification:**
    *   `begruendung_llm` courte indiquant pourquoi les LKN **validées** ont été choisies. Réfère-toi au texte et aux **descriptions du catalogue**.

**Format de sortie:** **UNIQUEMENT** du JSON valide, **AUCUN** autre texte.
```json
{{
  "identified_leistungen": [
    {{
      "lkn": "VALIDIERTE_LKN_1",
      "typ": "TYP_AUS_KATALOG_1",
      "beschreibung": "BESCHREIBUNG_AUS_KATALOG_1",
      "menge": MENGE_ZAHL_LKN_1
    }}
  ],
  "extracted_info": {{
    "dauer_minuten": null,
    "menge_allgemein": null,
    "alter": null,
    "geschlecht": null,
    "seitigkeit": "unbekannt",
    "anzahl_prozeduren": null
  }},
  "begruendung_llm": "<Begründung>"
}}

Si aucune LKN correspondante n'est trouvée, renvoie un objet JSON avec une liste "identified_leistungen" vide.

Behandlungstext: "{user_input}"

Réponse JSON:"""
    elif lang == "it":
        return f"""**Compito:** Analizza con la massima precisione il testo di trattamento medico seguente proveniente dalla Svizzera. Il tuo obiettivo è identificare i numeri di catalogo delle prestazioni (LKN), determinarne la quantità ed estrarre informazioni contestuali. Basati principalmente sul LKAAT_Leistungskatalog fornito, ma puoi utilizzare sinonimi medici o termini comuni e includere la tabella delle Pauschalen.

**Contesto: LKAAT_Leistungskatalog (fonte principale per i LKN e le relative descrizioni; in aggiunta è disponibile la tabella delle Pauschalen.)**
--- Leistungskatalog Start ---
{katalog_context}
--- Leistungskatalog Ende ---

**Istruzioni:** Segui esattamente i passi seguenti:

1.  **Identificazione LKN e convalida STRETTA:**
    *   Leggi attentamente il "Behandlungstext".
    *   Identifica **tutti** i possibili codici LKN (formato `XX.##.####`) che potrebbero rappresentare le attività descritte.
    *   Considera che nel testo possono essere documentate più prestazioni e quindi possono essere valide più LKN (ad es. intervento chirurgico più anestesia).
    *   Se un anestesista menziona un'anestesia o narcosi senza specificare la classe di impegno o la durata, puoi scegliere un LKN di anestesia generico. Di norma usa WA.05.0020. Se viene indicata una durata di anestesia precisa in minuti, utilizza invece il corrispondente LKN WA.10.00x0.
    *   Sfrutta le tue conoscenze mediche su sinonimi e termini tecnici tipici (ad es. riconosci che « intervento di cataratta » = « facoemulsificazione » / « estrazione del cristallino » = « Extractio lentis »).
    *   **ASSOLUTAMENTE CRITICO:** Per OGNI codice LKN potenziale verifica **LETTERA PER LETTERA e CIFRA PER CIFRA** che esista **ESATTAMENTE** come 'LKN:' nel catalogo sopra. Solo se il codice esiste confronta la **descrizione del catalogo** con l'attività descritta.
    *   Crea un elenco (`identified_leistungen`) **SOLO** con le LKN che hanno superato questa verifica esatta e la cui descrizione corrisponde al testo.
    *   Riconosci se si tratta di prestazioni di medicina di base del capitolo CA.

2.  **Tipo e descrizione:**
    *   Per ogni LKN **convalidata** in `identified_leistungen` aggiungi il `typ` corretto e la `beschreibung` **direttamente e senza modifiche** dal contesto del catalogo per quella LKN.

3.  **Estrazione delle informazioni contestuali (CRITICO per condizioni aggiuntive):**
    *   Estrai **solo** i valori esplicitamente menzionati nel "Behandlungstext":
        *   `dauer_minuten` (numero)
        *   `menge_allgemein` (numero)
        *   `alter` (numero)
        *   `geschlecht` ('weiblich', 'männlich', 'divers', 'unbekannt')
        *   `seitigkeit` (stringa: 'einseitig', 'beidseits', 'links', 'rechts', 'unbekannt')
        *   `anzahl_prozeduren` (numero o `null`)
    *   Se un valore non è menzionato, impostalo su `null` (tranne `seitigkeit`, che può essere 'unbekannt').

4.  **Determinazione della quantità (per LKN convalidata):**
    *   La quantità standard è `1`.
    *   **Basato sul tempo:** se la descrizione del catalogo contiene "pro X Min" E `dauer_minuten` (Y) è stato estratto, imposta `menge` = Y.
    *   **Generale:** se `menge_allgemein` (Z) è stato estratto E la LKN non è basata sul tempo E `anzahl_prozeduren` è `null`, imposta `menge` = Z.
    *   **Numero specifico di procedure:** se `anzahl_prozeduren` è stato estratto e si riferisce chiaramente alla LKN (ad es. "due iniezioni"), imposta `menge` = `anzahl_prozeduren`. Questo prevale su `menge_allgemein`.
    *   Assicurati che `menge` >= 1.

5.  **Motivazione:**
    *   `begruendung_llm` breve sul perché le LKN **convalidate** sono state scelte. Fai riferimento al testo e alle **descrizioni del catalogo**.

**Formato di output:** **SOLO** JSON valido, **NESSUN** altro testo.
```json
{{
  "identified_leistungen": [
    {{
      "lkn": "VALIDIERTE_LKN_1",
      "typ": "TYP_AUS_KATALOG_1",
      "beschreibung": "BESCHREIBUNG_AUS_KATALOG_1",
      "menge": MENGE_ZAHL_LKN_1
    }}
  ],
  "extracted_info": {{
    "dauer_minuten": null,
    "menge_allgemein": null,
    "alter": null,
    "geschlecht": null,
    "seitigkeit": "unbekannt",
    "anzahl_prozeduren": null
  }},
  "begruendung_llm": "<Begründung>"
}}

Se nessuna LKN appropriata viene trovata, restituisci un oggetto JSON con una lista "identified_leistungen" vuota.

Behandlungstext: "{user_input}"

Risposta JSON:"""
    else:
        return f"""**Aufgabe:** Analysiere den folgenden medizinischen Behandlungstext aus der Schweiz äußerst präzise. Deine Aufgabe ist es, relevante Leistungs-Katalog-Nummern (LKN) samt Menge und Kontextinformationen zu bestimmen. Nutze primär den bereitgestellten LKAAT_Leistungskatalog, darfst aber auch medizinische Synonyme oder übliche Begriffe berücksichtigen und die Pauschalen-Tabelle hinzuziehen.

**Kontext: LKAAT_Leistungskatalog (maßgebliche Quelle für gültige LKNs und deren Beschreibungen; ergänzend kann die Pauschalen-Tabelle verwendet werden.)**
--- Leistungskatalog Start ---
{katalog_context}
--- Leistungskatalog Ende ---

**Anweisungen:** Führe die folgenden Schritte exakt aus:

1.  **LKN Identifikation & STRIKTE Validierung:**
    *   Lies den "Behandlungstext" sorgfältig.
    *   Identifiziere **alle** potenziellen LKN-Codes (Format `XX.##.####`), die die beschriebenen Tätigkeiten repräsentieren könnten.
    *   Bedenke, dass im Text mehrere Leistungen dokumentiert  mehrere LKNs gültig sein können (z.B. chirurgischer Eingriff PLUS/und/mit/;/./, Anästhesie).
    *   Wird eine Anästhesie oder Narkose durch einen Anästhesisten erwähnt, aber es fehlen genaue Angaben zur Aufwandklasse oder Dauer, darfst du eine generische Anästhesie‑LKN wählen. Nutze hierfür in der Regel `WA.05.0020`. Wenn eine konkrete Anästhesiezeit in Minuten genannt wird, verwende stattdessen die entsprechende `WA.10.00x0`‑LKN.
    *   Nutze dein ausgeprägtes medizinisches Wissen zu **Synonymen und typischen Fachbegriffen** 
        (z.B. erkenne, dass "Kataraktoperation" = "Phakoemulsifikation"/"Linsenextraktion" = "Extractio lentis" 
        oder dass "Herzkatheter"/"Linksherzkather" = "Koronarographie").
    *   ABSOLUT KRITISCH: Für JEDEN potenziellen LKN-Code prüfe BUCHSTABE FÜR BUCHSTABE und ZIFFER FÜR ZIFFER, dass dieser Code EXAKT als „LKN:“ im obigen Katalog existiert. Nur wenn der Code existiert, vergleichst du die Katalogbeschreibung mit der beschriebenen Leistung.
    *   Erstelle eine Liste (`identified_leistungen`) **AUSSCHLIESSLICH** mit den LKNs, die diese **exakte** Prüfung im Katalog bestanden haben UND deren Beschreibung zum Text passt.
    *   Erkenne, ob es sich um hausärztliche Leistungen im Kapitel CA handelt.

2.  **Typ & Beschreibung hinzufügen:**
    *   Füge für jede **validierte** LKN in der `identified_leistungen`-Liste den korrekten `typ` und die `beschreibung` **direkt und unverändert aus dem bereitgestellten Katalogkontext für DIESE LKN** hinzu.

3.  **Kontextinformationen extrahieren (KRITISCH für Zusatzbedingungen):**
    *   Extrahiere **nur explizit genannte** Werte aus dem "Behandlungstext":
        *   `dauer_minuten` (Zahl, z.B. für Konsultationen)
        *   `menge_allgemein` (Zahl, z.B. "3 Warzen entfernt")
        *   `alter` (Zahl, Alter des Patienten)
        *   `geschlecht` ('weiblich', 'männlich', 'divers', 'unbekannt')
        *   `seitigkeit` (String: 'einseitig', 'beidseits', 'links', 'rechts', 'unbekannt'. Leite 'beidseits' auch von "bds." oder "beide Augen" etc. ab. Wenn keine Angabe, dann 'unbekannt'.)
        *   `anzahl_prozeduren` (Zahl: Falls eine Anzahl von Eingriffen genannt wird, die nicht direkt die Menge einer einzelnen LKN ist, z.B. "zwei Injektionen". Wenn nicht explizit genannt, dann `null`.)
    *   Wenn ein Wert nicht explizit genannt wird, setze ihn auf `null` (außer `seitigkeit`, die 'unbekannt' sein kann).

4.  **Menge bestimmen (pro validierter LKN):**
    *   Standardmenge ist `1`.
    *   **Zeitbasiert:** Wenn Katalog-Beschreibung "pro X Min" enthält UND `dauer_minuten` (Y) extrahiert wurde, setze `menge` = Y.
    *   **Allgemein:** Wenn `menge_allgemein` (Z) extrahiert wurde UND LKN nicht zeitbasiert ist UND `anzahl_prozeduren` `null` ist (oder nicht passt), setze `menge` = Z.
    *   **Spezifische Anzahl Prozeduren:** Wenn `anzahl_prozeduren` extrahiert wurde und sich klar auf die aktuelle LKN bezieht (z.B. "zwei Injektionen" und LKN ist Injektion), setze `menge` = `anzahl_prozeduren`. Dies hat Vorrang vor `menge_allgemein` für diese LKN.
    *   Sicherstellen: `menge` >= 1.
    *   Wenn eine Prozedur "Seitigkeit" verlangt, dann erzeuge bei "beidseits" Menge = 2 UND "Seitigkeit" = "beidseits" .

5.  **Begründung:**
    *   **Kurze** `begruendung_llm`, warum die **validierten** LKNs gewählt wurden. Beziehe dich auf Text und **Katalog-Beschreibungen**.

**Output-Format:** **NUR** valides JSON, **KEIN** anderer Text.
```json
{{
  "identified_leistungen": [
    {{
      "lkn": "VALIDIERTE_LKN_1",
      "typ": "TYP_AUS_KATALOG_1",
      "beschreibung": "BESCHREIBUNG_AUS_KATALOG_1",
      "menge": MENGE_ZAHL_LKN_1
    }}
  ],
  "extracted_info": {{
    "dauer_minuten": null,
    "menge_allgemein": null,
    "alter": null,
    "geschlecht": null,
    "seitigkeit": "unbekannt",
    "anzahl_prozeduren": null
  }},
  "begruendung_llm": "<Begründung>"
}}

Wenn absolut keine passende LKN aus dem Katalog gefunden wird, gib ein JSON-Objekt mit einer leeren "identified_leistungen"-Liste zurück.

Behandlungstext: "{user_input}"

JSON-Antwort:"""

def get_stage2_mapping_prompt(tardoc_lkn: str, tardoc_desc: str, candidates_text: str, lang: str) -> str:
    """Return the Stage 2 mapping prompt in the requested language."""
    if lang == "fr":

        return f"""**Tâche :** Vous êtes un expert des systèmes de facturation médicale en Suisse (TARDOC et Pauschalen). Votre objectif est de trouver, pour la prestation TARDOC indiquée (type E/EZ), la prestation fonctionnellement **équivalente** dans la « liste des candidats ». Cette liste contient des LKN (souvent P/PZ) utilisés comme conditions dans les Pauschalen potentielles.

**Prestation TARDOC donnée (type E/EZ):**
*   LKN: {tardoc_lkn}
*   Description: {tardoc_desc}
*   Contexte: Cette prestation a été réalisée dans le cadre d'un traitement pour lequel une facturation par Pauschalen est examinée.

**Équivalents possibles (liste des candidats - LKN pour les conditions des Pauschalen) :**
Choisissez dans CETTE liste la LKN candidate décrivant **le même type d'acte médical** que la prestation TARDOC.
--- Kandidaten Start ---
{candidates_text}
--- Kandidaten Ende ---

**Analyse et décision :**
1.  Comprenez la **fonction médicale principale** de la prestation TARDOC.
2.  Identifiez les LKN candidates correspondant le mieux à cette fonction.
3.  Classez-les par pertinence.

**Réponse :**
*   Donnez une **liste simple séparée par des virgules** des codes LKN retenus.
*   Si aucun candidat ne convient, renvoyez exactement `NONE`.
*   Aucune autre sortie, pas d'explications.

Liste priorisée (seulement la liste ou NONE):"""
    elif lang == "it":
        return f"""**Compito:** Sei un esperto dei sistemi di fatturazione medica in Svizzera (TARDOC e Pauschalen). Il tuo obiettivo è individuare, per la prestazione TARDOC indicata (tipo E/EZ), la prestazione funzionalmente **equivalente** nella "lista dei candidati". Questa lista contiene LKN (spesso P/PZ) utilizzati come condizioni nelle Pauschalen potenzialmente rilevanti.

**Prestazione TARDOC fornita (tipo E/EZ):**
*   LKN: {tardoc_lkn}
*   Descrizione: {tardoc_desc}
*   Contesto: Questa prestazione è stata eseguita nell'ambito di un trattamento per il quale si verifica una fatturazione a forfait.

**Possibili equivalenti (lista dei candidati - LKN per le condizioni delle Pauschalen):**
Trova in QUESTA lista la LKN candidata che descrive **lo stesso tipo di atto medico** della prestazione TARDOC.
--- Kandidaten Start ---
{candidates_text}
--- Kandidaten Ende ---

**Analisi e decisione:**
1.  Comprendi la **funzione medica principale** della prestazione TARDOC.
2.  Individua i candidati che rappresentano meglio tale funzione.
3.  Ordinali per pertinenza.

**Risposta:**
*   Fornisci un **elenco semplice separato da virgole** dei codici LKN trovati.
*   Se nessun candidato è adatto, restituisci esattamente `NONE`.
*   Nessun altro testo o spiegazione.

Elenco prioritario (solo elenco o NONE):"""
    else:
        return f"""**Aufgabe:** Du bist ein Experte für medizinische Abrechnungssysteme in der Schweiz (TARDOC und Pauschalen). Deine Aufgabe ist es, für die gegebene TARDOC-Einzelleistung (Typ E/EZ) die funktional **äquivalente** Leistung aus der \"Kandidatenliste\" zu finden. Die Kandidatenliste enthält LKNs (aller Typen, oft P/PZ), die als Bedingungen in potenziell relevanten Pauschalen vorkommen.

**Gegebene TARDOC-Leistung (Typ E/EZ):**
*   LKN: {tardoc_lkn}
*   Beschreibung: {tardoc_desc}
*   Kontext: Diese Leistung wurde im Rahmen einer Behandlung erbracht, für die eine Pauschalenabrechnung geprüft wird.

**Mögliche Äquivalente (Kandidatenliste - LKNs für Pauschalen-Bedingungen):**
Finde aus DIESER Liste die Kandidaten-LKN, die die **gleiche Art von medizinischer Tätigkeit** beschreibt.
--- Kandidaten Start ---
{candidates_text}
--- Kandidaten Ende ---

**Analyse & Entscheidung:**
1.  Verstehe die **medizinische Kernfunktion** der gegebenen TARDOC-Leistung.
2.  Identifiziere die Kandidaten-LKN, die diese Kernfunktion am besten repräsentiert, und priorisiere nach Passgenauigkeit.

**Antwort:**
*   Gib eine **reine, kommagetrennte Liste** der LKN-Codes zurück.
*   Wenn keine passt, gib exakt `NONE` aus.
*   Keine weiteren Erklärungen.

Priorisierte Liste (nur Liste oder NONE):"""

def get_stage2_ranking_prompt(user_input: str, potential_pauschalen_text: str, lang: str) -> str:
    """Return the Stage 2 ranking prompt in the requested language."""
    if lang == "fr":
        return f"""Sur la base du texte de traitement suivant, quelle Pauschale listée ci-dessous correspond le mieux au contenu ?
Prends en compte la description de la Pauschale ('Pauschale_Text').
Fournis une liste priorisée des codes de Pauschale en commençant par la meilleure correspondance.
Donne UNIQUEMENT les codes séparés par des virgules (ex. "CODE1,CODE2"). Aucune justification.

Behandlungstext: "{user_input}"

Pauschalen potentielles:
--- Pauschalen Start ---
{potential_pauschalen_text}
--- Pauschalen Ende ---

Codes de Pauschale par ordre de pertinence (liste uniquement):"""
    elif lang == "it":
        return f"""In base al seguente testo di trattamento, quale delle Pauschalen elencate di seguito corrisponde meglio al contenuto?
Tieni conto della descrizione della Pauschale ('Pauschale_Text').
Fornisci un elenco prioritario dei codici Pauschale iniziando dal più adatto.
Fornisci SOLO i codici separati da virgola (es. "CODE1,CODE2"). Nessuna spiegazione.

Behandlungstext: "{user_input}"

Pauschalen potenziali:
--- Pauschalen Start ---
{potential_pauschalen_text}
--- Pauschalen Ende ---

Codici Pauschale in ordine di rilevanza (solo elenco):"""
    else:
        return f"""Basierend auf dem folgenden Behandlungstext, welche der unten aufgeführten Pauschalen passt inhaltlich am besten?
Berücksichtige die Beschreibung der Pauschale ('Pauschale_Text').
Gib eine priorisierte Liste der Pauschalen-Codes zurück, beginnend mit der besten Übereinstimmung.
Gib NUR die Pauschalen-Codes als kommagetrennte Liste zurück (z.B. \"CODE1,CODE2\"). KEINE Begründung.

Behandlungstext: \"{user_input}\"

Potenzielle Pauschalen:
--- Pauschalen Start ---
{potential_pauschalen_text}
--- Pauschalen Ende ---

Priorisierte Pauschalen-Codes (nur kommagetrennte Liste):"""
