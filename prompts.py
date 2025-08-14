from typing import List, Optional


from typing import List, Optional

def get_stage1_prompt(user_input: str, katalog_context: str, lang: str, query_variants: Optional[List[str]] = None) -> str:
    """Return the Stage 1 prompt in the requested language (FR/IT hardened for Regel A, DE wie gehabt)."""
    # Build the synonym block if query_variants are provided and contain more than the original query.
    synonym_block = ""
    if query_variants and len(query_variants) > 1:
        if lang == "fr":
            synonym_list = ", ".join(f"'{v}'" for v in query_variants)
            synonym_block = f"""
**Synonymes importants :** Les termes suivants sont des synonymes et doivent être traités comme fonctionnellement identiques pour trouver le LKN correct : {synonym_list}."""
        elif lang == "it":
            synonym_list = ", ".join(f"'{v}'" for v in query_variants)
            synonym_block = f"""
**Sinonimi importanti:** I seguenti termini sono sinonimi e devono essere trattati come funzionalmente identici per trovare il LKN corretto: {synonym_list}."""
        else:  # de
            synonym_list = ", ".join(f"'{v}'" for v in query_variants)
            synonym_block = f"""
**Wichtige Synonyme:** Die folgenden Begriffe sind Synonyme und bei der Suche nach der korrekten LKN als funktional identisch zu behandeln: {synonym_list}."""

    if lang == "fr":
        return f"""**Rôle :** Vous êtes un expert IA des tarifs médicaux suisses (TARDOC/Forfaits).
**Langue de réponse :** Répondez exclusivement en français neutre.
**Tâche :** Extrayez du "Texte de traitement" les numéros de catalogue de prestations (LKN) corrects, calculez leur quantité et retournez le résultat exactement au format JSON requis. AUCUN bloc de code Markdown dans la réponse finale.
{synonym_block}

**CONTRAINTES NON NÉGOCIABLES (PRIORITÉ MAXIMALE) :**
1) Consultation avec durée totale D > 5 min ⇒ la sortie DOIT contenir exactement :
   - 1× AA/CA.00.0010
   - (D − 5)× AA/CA.00.0020
2) Ne JAMAIS dupliquer .0010 ; ne JAMAIS remplacer .0020 par un autre LKN.
3) Si "médecin de famille" est mentionné ⇒ utiliser CA.* ; sinon AA.*.
4) La sortie doit couvrir 100 % des minutes déclarées (contrôle d’exhaustivité).

**Contexte : LKAAT_Leistungskatalog**
(Ceci est la seule source pour les LKN valides, leurs descriptions et leurs types. N'utilisez **que** des LKN présents ci-dessous.)
--- Leistungskatalog Start ---
{katalog_context}
--- Leistungskatalog Ende ---

**INSTRUCTIONS - Suivez ces étapes à la lettre :**

**Étape 1 : Analyse & Décomposition**
*   Lisez l'intégralité du "Texte de traitement".
*   Identifiez toutes les activités individuelles facturables. Elles sont souvent séparées par des mots comme "plus", "et", "ensuite" ou par la ponctuation.
    *   Exemple A : "Consultation médecin de famille 15 min plus 10 minutes de conseil enfant" -> Activité 1 : "Consultation médecin de famille 15 min", Activité 2 : "10 minutes de conseil enfant".
    *   Exemple B : "Articulation temporo-mandibulaire, luxation. Réposition fermée avec anesthésie par anesthésiste" -> Activité 1 : "Réposition fermée", Activité 2 : "Anesthésie par anesthésiste".
*   Associez toujours les durées à la bonne activité.
*   Si un LKN au format "AA.NN.NNNN" (p.ex. "AA.00.0010") ou "ANN.AA.NNNN" (p.ex. "C08.SA.0700") [A=lettre, N=chiffre] est trouvé, il est priorisé **s'il existe mot à mot dans le contexte**.

**Étape 2 : Identification des LKN (par activité)**
*   Pour chaque activité, trouvez le LKN correspondant **uniquement** dans le catalogue ci-dessus.
*   **Utilisez vos connaissances médicales :** Comprenez les synonymes et périphrases (p.ex. "ablation de verrue" = "exérèse de lésion cutanée bénigne").
*   **Règle d'anesthésie :** Si une anesthésie réalisée par un anesthésiste est décrite, utilisez un code du chapitre WA.10 **présent dans le contexte**. Sans indication de durée -> `WA.10.0010`. Avec indication de durée -> choisissez le `WA.10.00x0` exact disponible.

**Étape 3 : APPLICATION DES RÈGLES DE QUANTITÉ (CRITIQUE !)**
*   **RÈGLE A : Consultations (Chapitres AA & CA)**
    *   **Condition :** L'activité est une "consultation", "entretien", "entretien conseil" avec une durée.
    *   **Choix du chapitre :** `CA` si le texte mentionne "médecin de famille", sinon `AA`.
    *   **Calcul :**
        1.  **LKN de base** (`AA.00.0010` ou `CA.00.0010` "5 premières min") : la `menge` est TOUJOURS `1`.
        2.  **LKN supplémentaire** (`AA.00.0020` ou `CA.00.0020` "chaque min suppl.") : à ajouter UNIQUEMENT si la durée > 5 min. La `menge` est alors exactement : `(durée totale en minutes - 5)`.
    *   **Contrôle "complétude du temps" (obligatoire) :**
        *   Si `durée totale > 5`, la sortie DOIT contenir **exactement** `1× AA/CA.00.0010` **et** `(durée totale − 5)× AA/CA.00.0020`.
        *   Ne **jamais** dupliquer la position de base; ne **jamais** remplacer les minutes supplémentaires par une autre LKN.
        *   Exemples canoniques :
            - 5 min → 1× AA.00.0010 (aucun 0020)
            - 6 min → 1× AA.00.0010 + 1× AA.00.0020
            - 12 min → 1× AA.00.0010 + 7× AA.00.0020
            - 20 min → 1× AA.00.0010 + 15× AA.00.0020

*   **RÈGLE B : Autres prestations basées sur le temps**
    *   **Condition :** La description du LKN contient une unité de temps (p.ex. "par 1 min", "par 5 min") ET ce n'est PAS une consultation selon la Règle A.
    *   **Calcul :** `menge = durée / unité`. Les minutes entamées se **comptent vers le haut** (arrondi à l'unité supérieure).

*   **RÈGLE C : Autres prestations (par défaut)**
    *   **Condition :** Les règles A et B ne s'appliquent pas.
    *   **Calcul :** `menge = 1`. Exception : Si le texte mentionne un nombre clair (p.ex. "trois injections", "deux lésions"), utilisez ce nombre. Pour "bilatéral", `menge = 2` si le LKN est défini unilatéral.

**Étape 4 : Validation stricte**
*   **CRITIQUE :** Pour CHAQUE LKN potentielle, vérifiez qu'elle existe **exactement (sensible à la casse, caractère par caractère)** dans le contexte du catalogue. Rejetez sinon.
*   Reprenez `typ` et `beschreibung` **à l’identique** du catalogue.

**Étape 5 : Extraction des informations contextuelles**
*   Extrayez `dauer_minuten`, `menge_allgemein`, `alter`, etc. UNIQUEMENT si explicitement mentionnés. Sinon, `null`.
*   Déduisez `seitigkeit` si indiqué ("gauche", "droite", "bilatéral"), sinon laissez `"unbekannt"`.
*   Les unités de temps entamées comptent comme une unité entière.

**AUTO-VÉRIFICATION AVANT SORTIE (Check-list)**
- Ai-je extrait une durée D lorsque présente ? (ex. "10 min" ⇒ D=10)
- Si consultation et D>5 ⇒ ai-je EXACTEMENT 1× …0010 et (D-5)× …0020 ?
- Le chapitre (AA vs CA) suit-il la règle "médecin de famille" ⇒ CA ?
- Si un point est manquant, je le CORRIGE avant de répondre.

**Exemples canoniques (sans backticks)**
Exemple 1 — "Consultation 5 minutes":
{{"identified_leistungen":[{{"lkn":"AA.00.0010","typ":"E","menge":1}}],"extracted_info":{{"dauer_minuten":5,"menge_allgemein":null,"alter":null,"geschlecht":null,"seitigkeit":"unbekannt","anzahl_prozeduren":null}},"begruendung_llm":"Consultation 5 min → base uniquement."}}
Exemple 2 — "Consultation 10 minutes":
{{"identified_leistungen":[{{"lkn":"AA.00.0010","typ":"E","menge":1}},{{"lkn":"AA.00.0020","typ":"E","menge":5}}],"extracted_info":{{"dauer_minuten":10,"menge_allgemein":null,"alter":null,"geschlecht":null,"seitigkeit":"unbekannt","anzahl_prozeduren":null}},"begruendung_llm":"Règle A : 1×0010 + (10-5)=5×0020."}}
Exemple 3 — "Médecin de famille 12 minutes":
{{"identified_leistungen":[{{"lkn":"CA.00.0010","typ":"E","menge":1}},{{"lkn":"CA.00.0020","typ":"E","menge":7}}],"extracted_info":{{"dauer_minuten":12,"menge_allgemein":null,"alter":null,"geschlecht":null,"seitigkeit":"unbekannt","anzahl_prozeduren":null}},"begruendung_llm":"Chapitre CA car 'médecin de famille' ; 12→1×0010+7×0020."}}

**Format de sortie : UNIQUEMENT un objet JSON valide (pas de backticks, pas d’autre texte).**
```json
{{
  "identified_leistungen": [
    {{
      "lkn": "LKN_VALIDÉE_1",
      "typ": "TYPE_DU_CATALOGUE_1",
      "menge": QUANTITÉ_CALCULÉE_1
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
  "begruendung_llm": "<Justification courte et précise basée sur les règles>"
}}
Texte de traitement: "{user_input}"
Réponse JSON:"""
    elif lang == "it":
        return f"""**Ruolo:** Sei un esperto AI delle tariffe mediche svizzere (TARDOC/Forfait).
**Lingua di risposta:** Rispondi esclusivamente in italiano neutro.
**Compito:** Estrai dal "Testo di trattamento" i codici LKN corretti, calcola la loro quantità e restituisci il risultato esattamente nel formato JSON richiesto. NESSUN blocco Markdown nel risultato finale.
{synonym_block}

**VINCOLI NON NEGOZIABILI (PRIORITÀ MASSIMA):**
1) Consultazione con durata totale D > 5 min ⇒ l'output DEVE contenere esattamente:
   - 1× AA/CA.00.0010
   - (D − 5)× AA/CA.00.0020
2) NON duplicare mai .0010; NON sostituire .0020 con altri LKN.
3) Se è menzionato "medico di base" ⇒ usare CA.* ; altrimenti AA.*.
4) L'output deve coprire il 100% dei minuti dichiarati (controllo di completezza).

**Contesto: LKAAT_Leistungskatalog**
(Questa è l'unica fonte per LKN validi, descrizioni e tipi. Usa **solo** LKN presenti qui sotto.)
--- Leistungskatalog Start ---
{katalog_context}
--- Leistungskatalog Ende ---

**ISTRUZIONI - Segui questi passaggi alla lettera:**

**Passaggio 1: Analisi e Scomposizione**
*   Leggi l'intero "Testo di trattamento".
*   Identifica tutte le singole attività fatturabili (separate da "più", "e", "dopo" o punteggiatura).
    *   Esempio A: "Consultazione medico di base 15 min più 10 minuti consulenza bambino" -> due attività.
    *   Esempio B: "Articolazione temporo-mandibolare, lussazione. Riduzione chiusa con anestesia da anestesista" -> due attività.
*   Se un LKN nel formato "AA.NN.NNNN" o "ANN.AA.NNNN" è trovato nel testo, prioritizzalo **solo se esiste nel contesto**.

**Passaggio 2: Identificazione LKN (per attività)**
*   Trova l'LKN corrispondente **solo** nel catalogo sopra.
*   **Conoscenza medica:** Comprendi sinonimi e parafrasi (es. "rimozione verruca" = "asportazione lesione cutanea benigna").
*   **Regola Anestesia:** Se è descritta anestesia eseguita da anestesista, usa un codice WA.10 **presente nel contesto**. Senza durata -> `WA.10.0010`. Con durata -> il `WA.10.00x0` esatto disponibile.

**Passaggio 3: REGOLE DI QUANTITÀ (CRITICO!)**
*   **REGOLA A: Consultazioni (AA & CA)**
    *   **Scelta capitolo:** `CA` se citato "medico di base", altrimenti `AA`.
    *   **Calcolo:**
        1.  Base (`AA.00.0010`/`CA.00.0010`, "primi 5 min"): `menge = 1`.
        2.  Aggiuntiva (`AA.00.0020`/`CA.00.0020`, "ogni min successivo"): solo se durata > 5 min, `menge = durata_totale - 5`.
    *   **Controllo completezza tempo (obbligatorio):**
        *   Se `durata_totale > 5`, l'output DEVE contenere **esattamente** `1× AA/CA.00.0010` **e** `(durata_totale − 5)× AA/CA.00.0020`.
        *   Non duplicare mai la posizione base; non sostituire i minuti aggiuntivi con altro LKN.
        *   Esempi canonici:
            - 5 min → 1× AA.00.0010 (nessuna 0020)
            - 6 min → 1× AA.00.0010 + 1× AA.00.0020
            - 12 min → 1× AA.00.0010 + 7× AA.00.0020
            - 20 min → 1× AA.00.0010 + 15× AA.00.0020

*   **REGOLA B: Altre prestazioni a tempo**
    *   `menge = durata / unità`. Arrotonda **per eccesso** alle unità intere.

*   **REGOLA C: Altre prestazioni**
    *   `menge = 1`, salvo numeri espliciti; "bilaterale" -> `menge = 2` se LKN unilaterale.

**Passaggio 4: Validazione rigorosa**
*   Conferma che ogni LKN esista **esattamente** nel contesto. Scarta gli altri.
*   Copia `typ` e `beschreibung` **senza modifiche**.

**Passaggio 5: Estrazione contesto**
*   Estrai solo se esplicito; altrimenti `null`.
*   Imposta `seitigkeit` se indicato ("sinistra", "destra", "bilaterale"), altrimenti `"unbekannt"`.
*   Le unità di tempo iniziate contano come unità intere.

**AUTO-VERIFICA PRIMA DELL’OUTPUT (Check-list)**
- Ho estratto una durata D quando presente? (es. "10 min" ⇒ D=10)
- Se consultazione e D>5 ⇒ ho **esattamente** 1× …0010 e (D-5)× …0020?
- Il capitolo (AA vs CA) segue la regola "medico di base" ⇒ CA?
- Se manca qualcosa, la **correggo** prima di rispondere.

**Esempi canonici (senza backticks)**
Esempio 1 — "Consultazione 5 min":
{{"identified_leistungen":[{{"lkn":"AA.00.0010","typ":"E","menge":1}}],"extracted_info":{{"dauer_minuten":5,"menge_allgemein":null,"alter":null,"geschlecht":null,"seitigkeit":"unbekannt","anzahl_prozeduren":null}},"begruendung_llm":"Consultazione 5 min → solo base."}}
Esempio 2 — "Consultazione 10 minuti":
{{"identified_leistungen":[{{"lkn":"AA.00.0010","typ":"E","menge":1}},{{"lkn":"AA.00.0020","typ":"E","menge":5}}],"extracted_info":{{"dauer_minuten":10,"menge_allgemein":null,"alter":null,"geschlecht":null,"seitigkeit":"unbekannt","anzahl_prozeduren":null}},"begruendung_llm":"Regola A: 1×0010 + (10-5)=5×0020."}}
Esempio 3 — "Medico di base 12 minuti":
{{"identified_leistungen":[{{"lkn":"CA.00.0010","typ":"E","menge":1}},{{"lkn":"CA.00.0020","typ":"E","menge":7}}],"extracted_info":{{"dauer_minuten":12,"menge_allgemein":null,"alter":null,"geschlecht":null,"seitigkeit":"unbekannt","anzahl_prozeduren":null}},"begruendung_llm":"Capitolo CA perché 'medico di base' ; 12→1×0010+7×0020."}}

**Formato di output: SOLO un oggetto JSON valido (niente backtick, nessun altro testo).**
```json
{{
  "identified_leistungen": [
    {{
      "lkn": "LKN_VALIDATO_1",
      "typ": "TIPO_DA_CATALOGO_1",
      "menge": QUANTITÀ_CALCOLATA_1
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
  "begruendung_llm": "<Motivazione breve e precisa basata sulle regole>"
}}
Testo di trattamento: "{user_input}"
Risposta JSON:"""
    else:  # DE (German) - vorhandene optimierte Version beibehalten
        return f"""**Rolle:** Du bist ein KI-Experte für Schweizer Arzttarife (TARDOC/Pauschalen).
**Antwortsprache:** Antworte ausschliesslich auf Deutsch (neutral).
**Aufgabe:** Extrahiere aus dem "Behandlungstext" die korrekten LKNs, berechne ihre Menge und gib **nur** ein gültiges JSON zurück. **Keine** Markdown-Codeblöcke im Output.
{synonym_block}

**Kontext: LKAAT_Leistungskatalog**
(Dies ist die einzige Quelle für gültige LKNs, ihre Beschreibungen und Typen. Verwende **nur** LKNs, die unten vorkommen.)
--- Leistungskatalog Start ---
{katalog_context}
--- Leistungskatalog Ende ---

**ANWEISUNGEN – exakt befolgen:**

**Schritt 1: Analyse & Zerlegung**
*   Lies den gesamten "Behandlungstext".
*   Identifiziere alle abrechenbaren Tätigkeiten (oft getrennt durch "plus", "und", "danach" oder Satzzeichen).
    *   Beispiel A: "Hausärztliche Konsultation 15 Min plus 10 Minuten Beratung Kind" -> zwei Tätigkeiten.
    *   Beispiel B: "Kiefergelenk, Luxation. Geschlossene Reposition mit Anästhesie durch Anästhesistin" -> zwei Tätigkeiten.
*   Beziehe Zeitangaben stets auf die korrekte Tätigkeit.
*   Wenn eine LKN im Format "AA.NN.NNNN" oder "ANN.AA.NNNN" im Text steht, priorisiere sie **nur wenn sie im Kontext exakt vorkommt**.

**Schritt 2: LKN-Identifikation (pro Tätigkeit)**
*   Finde pro Tätigkeit die passende LKN **ausschliesslich** im obigen Katalog.
*   **Medizinisches Wissen nutzen:** Synonyme/Umschreibungen verstehen (z.B. "Warzenentfernung" = "Abtragung benigne Hautläsion").
*   **Anästhesie-Regel:** Bei Anästhesie durch Anästhesist/in verwende einen WA.10-Code, der **im Kontext vorhanden** ist. Ohne Zeitangabe -> `WA.10.0010`. Mit Zeitangabe -> den passenden `WA.10.00x0` Code, der im Kontext existiert.

**Schritt 3: MENGENREGELN (kritisch)**
*   **REGEL A: Konsultationen (AA & CA)**
    *   **Kapitelwahl:** `CA` bei "Hausarzt/hausärztlich", sonst `AA`.
    *   **Berechnung:**
        1.  Basis-LKN (`AA.00.0010`/`CA.00.0010`, "erste 5 Min"): `menge = 1`.
        2.  Zusatz-LKN (`AA.00.0020`/`CA.00.0020`, "jede weitere 1 Min"): nur wenn Dauer > 5 Min, `menge = (Gesamtdauer in Minuten - 5)`.
    *   **Vollstaendigkeits-Check Zeit (obligatorisch):**
        *   Wenn `Gesamtdauer > 5`, MUSS der Output **genau** `1× AA/CA.00.0010` **und** `(Gesamtdauer − 5)× AA/CA.00.0020` enthalten.
        *   Basis nie duplizieren; Zusatzminuten nie durch andere LKN ersetzen.
        *   Kanonische Beispiele:
            - 5 Min → 1× AA.00.0010 (kein 0020)
            - 6 Min → 1× AA.00.0010 + 1× AA.00.0020
            - 12 Min → 1× AA.00.0010 + 7× AA.00.0020
            - 20 Min → 1× AA.00.0010 + 15× AA.00.0020

*   **REGEL B: Andere zeitbasierte Leistungen**
    *   Wenn LKN-Beschreibung eine Zeiteinheit enthaelt und keine Konsultation ist:
        `menge = Dauer / Einheit`, **immer aufrunden** auf volle Einheiten.

*   **REGEL C: Andere Leistungen (Default)**
    *   `menge = 1`. Ausnahme: explizite Anzahl im Text (z.B. "drei Injektionen"); bei "beidseits" `menge = 2`, wenn die LKN einseitig definiert ist.

**Schritt 4: Strikte Validierung**
*   Prüfe für **jede** LKN: exakter Zeichen-für-Zeichen-Treffer im Katalog-Kontext (Gross/Kleinschreibung beachten). Sonst verwerfen.
*   Übernehme `typ` und `beschreibung` **unveraendert** aus dem Katalog.

**Schritt 5: Kontextinformationen extrahieren**
*   `dauer_minuten`, `menge_allgemein`, `alter`, etc. nur bei expliziter Nennung; sonst `null`.
*   `seitigkeit` setzen, falls erkennbar ("links", "rechts", "beidseits"); sonst `"unbekannt"`.
*   Angebrochene Zeiteinheiten gelten als ganze Zeiteinheit (z.B. 20 Min bei 15-Min-Einheiten => Menge 2).

**Schritt 6: JSON erzeugen**
*   Sammle alle validierten LKNs und extrahierten Infos.
*   **Finaler Check (Konsultationen):** wenn Regel A und `dauer_minuten > 5`, sicherstellen, dass **beide** Positionen enthalten sind (Basis + exakte Anzahl `…0020`). Falls fehlend, **hinzufuegen**.
*   `begruendung_llm`: kurze, praezise Begruendung **auf Deutsch**.
*   **WICHTIG:** Wenn keine LKN passt (z.B. nur Pauschale moeglich), gib eine **leere** `identified_leistungen`-Liste zurück.

**Output-Format: NUR ein gültiges JSON-Objekt (ohne Backticks, ohne Zusatztext).**
```json
{{
  "identified_leistungen": [
    {{
      "lkn": "VALIDIERTE_LKN_1",
      "typ": "TYP_AUS_KATALOG_1",
      "menge": BERECHNETE_MENGE_1
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
  "begruendung_llm": "<Kurze, praezise Begruendung basierend auf den Regeln>"
}}
Behandlungstext: "{user_input}"
JSON-Antwort:"""

def get_stage2_mapping_prompt(tardoc_lkn: str, tardoc_desc: str, candidates_text: str, lang: str) -> str:
    """Return the Stage 2 mapping prompt in the requested language."""
    if lang == "fr":
        return f"""Rôle : Expert des mappings TARDOC/Pauschalen.
Tâche : Trouvez dans la « liste des candidats » la/les LKN fonctionnellement équivalentes à la prestation TARDOC donnée (type E/EZ). Ne choisissez **que** parmi les candidats listés.
Prestation TARDOC (type E/EZ) :
LKN: {tardoc_lkn}
Description: {tardoc_desc}
--- Kandidaten Start ---
{candidates_text}
--- Kandidaten Ende ---
Sortie :
Donnez UNIQUEMENT une liste de codes LKN séparés par des virgules (ex. PZ.01.0010,PZ.01.0020). Si aucun n'est adapté, renvoyez exactement NONE. Pas d'explications, pas de Markdown.
Liste priorisée (seulement la liste ou NONE):"""
    elif lang == "it":
        return f"""Ruolo: Esperto di mapping TARDOC/Pauschalen.
Compito: Trova nella "lista dei candidati" le LKN funzionalmente equivalenti alla prestazione TARDOC (tipo E/EZ). Seleziona **solo** tra i candidati elencati.
Prestazione TARDOC (tipo E/EZ):
LKN: {tardoc_lkn}
Descrizione: {tardoc_desc}
--- Kandidaten Start ---
{candidates_text}
--- Kandidaten Ende ---
Output:
Fornisci **solo** un elenco di codici LKN separati da virgola (es. PZ.01.0010,PZ.01.0020). Se nessuno è adatto, restituisci esattamente NONE. Nessuna spiegazione, nessun Markdown.
Elenco prioritario (solo elenco o NONE):"""
    else:  # DE (German) - OPTIMIZED PROMPT
        return f"""Rolle: Experte für TARDOC/Pauschalen-Mapping.
Aufgabe: Finde in der "Kandidatenliste" die LKN, die funktional der gegebenen TARDOC-Leistung (Typ E/EZ) entspricht. Wähle **nur** aus den Kandidaten unten.
TARDOC-Leistung:
LKN: {tardoc_lkn}
Beschreibung: {tardoc_desc}
--- Kandidaten Start ---
{candidates_text}
--- Kandidaten Ende ---
Antwort-Format:
Nur eine kommagetrennte Liste passender LKN-Codes (z.B. PZ.01.0010,PZ.01.0020). Wenn kein Kandidat passt, exakt NONE. Keine Erklärungen, kein Markdown.
Priorisierte Liste (nur Liste oder NONE):"""

def get_stage2_ranking_prompt(user_input: str, potential_pauschalen_text: str, lang: str) -> str:
    """Return the Stage 2 ranking prompt in the requested language."""
    if lang == "fr":
        return f"""Tâche : Classer par pertinence les Pauschalen suivantes pour le "Texte de traitement".
Critère : La meilleure Pauschale est celle dont le 'Pauschale_Text' reflète le plus fidèlement la prestation principale décrite.
Behandlungstext: "{user_input}"
--- Pauschalen Start ---
{potential_pauschalen_text}
--- Pauschalen Ende ---
Sortie :
Donnez UNIQUEMENT les codes Pauschale séparés par des virgules (ex. CODE1,CODE2). Si aucune ne convient, renvoyez NONE. Aucune justification, aucun Markdown.
Codes de Pauschale par ordre de pertinence (liste uniquement):"""
    elif lang == "it":
        return f"""Compito: Ordina per rilevanza le seguenti Pauschalen rispetto al "Testo di trattamento".
Criterio: La Pauschale migliore è quella il cui 'Pauschale_Text' rispecchia più fedelmente la prestazione principale descritta.
Behandlungstext: "{user_input}"
--- Pauschalen Start ---
{potential_pauschalen_text}
--- Pauschalen Ende ---
Output:
Fornisci SOLO i codici Pauschale separati da virgola (es. CODE1,CODE2). Se nessuna è adatta, restituisci NONE. Nessuna spiegazione/Markdown.
Codici Pauschale in ordine di rilevanza (solo elenco):"""
    else:  # DE (German) - OPTIMIZED PROMPT
        return f"""Aufgabe: RANGORDNE die "Potenziellen Pauschalen" nach Relevanz für den "Behandlungstext".
Kriterium: Beste Pauschale = deren 'Pauschale_Text' die Hauptleistung im Behandlungstext am genauesten trifft.
Behandlungstext: "{user_input}"
--- Pauschalen Start ---
{potential_pauschalen_text}
--- Pauschalen Ende ---
Output:
Nur eine kommagetrennte Liste der Pauschalen-Codes, von bester bis schlechtester Übereinstimmung. Wenn keine passt, gib NONE zurück. Keine Begründung, kein Markdown.
Priorisierte Pauschalen-Codes (nur Liste):"""
