def get_stage1_prompt(user_input: str, katalog_context: str, lang: str) -> str:
    """Return the Stage 1 prompt in the requested language."""
    if lang == "fr":
        return f"""**Tâche :** Analyse avec précision le texte de traitement médical ci-dessous provenant de Suisse. Ta mission consiste à identifier les numéros du catalogue des prestations (LKN), à en déterminer la quantité et à extraire les informations contextuelles. Appuie-toi principalement sur le LKAAT_Leistungskatalog fourni, mais tu peux aussi tenir compte de synonymes médicaux courants ou de termes usuels et consulter la table des forfaits.

**Contexte : LKAAT_Leistungskatalog (source de référence pour les LKN, leurs descriptions et les sections "MedizinischeInterpretation" où des synonymes peuvent apparaître ; la table des forfaits peut également être prise en compte.)
--- Leistungskatalog Start ---
{katalog_context}
--- Leistungskatalog Ende ---

**Instructions :** Suis exactement les étapes suivantes :

1.  **Identification des LKN et validation STRICTE:**
    *   Lis le "Behandlungstext" attentivement.
    *   Analyse l'intégralité du texte de traitement. Si plusieurs prestations distinctes sont décrites (p. ex. une consultation suivie d'un acte technique), identifie les LKN pour chaque partie.
    *   Identifie **tous** les codes LKN potentiels (format `XX.##.####`) pouvant représenter les actes décrits.
    *   Note que plusieurs prestations peuvent être documentées dans le texte et que plusieurs LKN peuvent être valides (p. ex. intervention chirurgicale plus anesthésie).
    *   Si une anesthésie ou une narcose réalisée par un anesthésiste est mentionnée, sélectionne explicitement un code du chapitre WA.10 (table ANAST). S'il n'est pas fait mention de la durée, utilise par défaut `WA.10.0010`. Lorsque la durée precise en minutes est indiquée, emploie le code `WA.10.00x0` approprié.
    *   Mets à profit tes connaissances médicales sur les synonymes et termes techniques usuels (p. ex. reconnais que « opération de la cataracte » = « phacoémulsification » / « extraction du cristallin » = « Extractio lentis »). Pour les termes complexes comme "cathétérisme cardiaque gauche", décompose-le en ses composants ("gauche", "cœur", "cathéter") et recherche des LKN correspondantes telles que celles pour la "coronarographie" ou "cathétérisme cardiaque". **Note pour Linksherzkatheter/cathétérisme cardiaque gauche :** Sois particulièrement attentif à ce que les LKN choisies correspondent très précisément à la description textuelle. Si plusieurs LKN semblent possibles, et si une LKN est un déclencheur connu de la Pauschale C05.10B, assure-toi que le texte justifie pleinement cette LKN spécifique et les conditions de cette Pauschale avant de la sélectionner.
    *   Consulte activement le champ "MedizinischeInterpretation" du catalogue, car il contient souvent des indications importantes sur des désignations alternatives ou des synonymes courants pour une prestation.
    *   **Instruction Critique pour Enlèvement de Verrue à la Curette/Cuillère Tranchante :** Si le texte de traitement décrit explicitement l'"enlèvement d'une verrue" (ou synonymes directs) ET mentionne l'utilisation d'une "curette" ou "cuillère tranchante" (ou traductions directes) :
        *   Tu **DOIS IMPÉRATIVEMENT** donner la priorité aux LKN qui décrivent spécifiquement le "curetage de verrue" ou "l'enlèvement de verrue par curetage".
        *   Recherche activement des codes comme `MK.05.0070` (si celui-ci correspond au "curetage de verrues" ou similaire et est présent dans le catalogue fourni).
        *   Cette instruction spécifique pour le curetage de verrues **PRIME** sur les codes plus généraux d'exérèse de lésions cutanées.
        *   Évite les codes pour des procédures non liées (p.ex. biopsies, sutures simples, acupuncture) dans ce contexte spécifique de curetage de verrue.
    *   **Instruction spécifique pour "Conseil/Entretien":** Si le texte mentionne « conseil », « entretien » ou « consultation » (au sens de donner des conseils) avec une durée, recherche activement les LKN correspondantes à cette activité, en particulier celles tarifées à la durée (p. ex. "par 5 min" comme `CG.15.0010`). Assure-toi que la quantité est correctement calculée selon la règle Y/X. Le choix exact de la LKN (p.ex. Chapitre CA pour médecin de famille vs. Chapitre CG pour conseil général) dépend du contexte global du traitement et des LKN disponibles dans le catalogue.
    *   **Remarques administratives:** Ignore les remarques purement administratives ou logistiques (p.ex., "temps de transfert vers la dermatologie", "le patient a attendu") lors de l'identification des LKN cliniques facturables, à moins qu'elles n'informent directement un paramètre facturable (p.ex., durée d'une prestation surveillée).
    *   Utilise également ton sens stylistique : « grand » peut signifier « complet » ou « majeur » ; une formulation comme « grand examen rhumatologique » peut être interprétée comme « examen rhumatologique complet » ou « bilan rhumatologique majeur », l'ordre des mots peut varier et les formes nominales et verbales peuvent être équivalentes (p. ex. « retrait » vs « retirer »).
    *   **ABSOLUMENT CRITIQUE:** Pour CHAQUE code LKN potentiel, vérifie **LETTRE PAR LETTRE et CHIFFRE PAR CHIFFRE** que ce code existe **EXACTEMENT** comme 'LKN:' dans le catalogue ci-dessus. Ce n'est que si le code existe que tu compares la **description du catalogue** avec l'acte décrit.
    *   Crée une liste (`identified_leistungen`) **UNIQUEMENT** avec les LKN ayant passé cette vérification exacte et dont la description correspond au texte.
    *   Reconnais si les prestations relèvent du chapitre CA (médecine de famille). **Ceci est une étape importante pour la sélection correcte des LKN.**

**Instructions spécifiques pour les prestations de consultation:**
*   **Consultations spécifiques à un domaine (p.ex. Médecine de famille/Chapitre CA):** Si le texte de traitement mentionne explicitement un domaine spécifique (p.ex. "consultation de médecine de famille", "chez le médecin de famille", "hausärztliche Konsultation") :
    *   **DONNE LA PRIORITÉ ABSOLUE** aux codes LKN de consultation du chapitre correspondant (p.ex. CA pour la médecine de famille).
    *   **ÉVITE** d'utiliser les codes AA pour la durée de cette consultation spécifique.
    *   Si le chapitre spécifique (p.ex. CA) possède ses propres codes LKN basés sur le temps pour les consultations (p.ex. un code pour les "5 premières minutes" et un autre pour "chaque minute supplémentaire"), applique un calcul de temps analogue à celui des codes AA.
        *   Exemple (hypothétique pour CA, basé sur la structure AA) : Pour une "consultation de médecine de famille de 17 minutes", si `CA.00.0010` = "Consultation méd. fam., 5 prem. min." et `CA.00.0020` = "Consultation méd. fam., chaque min. suppl.", alors facturer :
            *   `CA.00.0010`, `menge`: 1
            *   `CA.00.0020`, `menge`: (17 - 5) / 1 = 12
    *   Recherche attentivement dans le catalogue les codes LKN corrects pour le domaine mentionné et leurs modalités spécifiques de facturation.
*   **Consultations Générales (Chapitre AA) :** Utilise les codes de consultation généraux du chapitre AA **UNIQUEMENT SI** le texte de traitement décrit une "consultation", "entretien" etc. avec une durée, ET **AUCUN domaine médical spécifique** (comme "médecine de famille") n'est explicitement mentionné ou clairement impliqué par le contexte.
    *   Dans ce cas (et seulement dans ce cas) :
        *   `AA.00.0010` ("Consultation, générale ; 5 premières minutes") : la quantité est toujours 1.
        *   `AA.00.0020` ("Consultation, générale ; chaque minute supplémentaire") : la quantité est (`dauer_minuten` de la consultation - 5) / 1.
        *   Exemple : Une "consultation de 25 minutes" (sans autre spécification) donne : 1x `AA.00.0010` + 20x `AA.00.0020`.
*   Assure-toi que `dauer_minuten` est correctement extrait pour toute la consultation avant d'effectuer cette répartition.

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
    *   **Basé sur le temps (Règle principale pour les LKN NON-AA/CA) :** Si la description du catalogue d'une LKN (qui n'est PAS une prestation de consultation des chapitres AA ou CA) indique explicitement une unité de temps (par ex. "par minute", "par 5 min"), ET qu'une durée en minutes (Y) est clairement attribuable à cette LKN spécifique :
        *   Interprétez l'unité de temps de la LKN (X) à partir de sa description dans le catalogue (par ex., X=1 si la description indique "par minute", X=5 si "par 5 min").
        *   **Calcul de la quantité :** La quantité (`menge`) pour cette LKN est alors calculée EXACTEMENT comme Y divisé par X (c.-à-d. `menge = Y / X`).
        *   **Exemple concret :** Si le texte de traitement mentionne "...curetage d'une verrue pendant 5 minutes" et que la LKN `MK.05.0070` est décrite dans le catalogue comme "...par 1 min" (donc X=1), alors la quantité pour `MK.05.0070` est 5 / 1 = 5.
        *   **Autre exemple :** Pour une prestation de 10 minutes qui est facturée "par 5 min" (X=5), la quantité serait 10 / 5 = 2.
        *   Assurez-vous que Y représente bien la durée spécifique de cette prestation individuelle et non la durée totale d'une consultation plus longue (qui serait déjà gérée par les règles spécifiques aux chapitres AA/CA). Le résultat Y/X doit être un entier.
    *   **Général:** si `menge_allgemein` (Z) est extrait ET que la LKN n'est pas basée sur le temps (ou que la règle basée sur le temps ne s'applique pas) ET `anzahl_prozeduren` est `null`, mets `menge` = Z.
    *   **Nombre spécifique de procédures:** si `anzahl_prozeduren` est extrait et se rapporte clairement à la LKN (p. ex. "deux injections"), mets `menge` = `anzahl_prozeduren`. Cela prime sur `menge_allgemein`.
    *   Assure-toi que `menge` >= 1.
    *   Si une procédure requiert une « latéralité », alors pour « beidseits » (des deux côtés), saisis quantité = 2 ET « latéralité » = « beidseits ».

5.  **Justification:**
    *   `begruendung_llm` courte indiquant pourquoi les LKN **validées** ont été choisies. Réfère-toi au texte et aux **descriptions du catalogue**.

**Instruction spécifique pour les consultations :** Si le texte de traitement décrit une « consultation » générale ou un « entretien » avec une durée (p. ex. « consultation 15 minutes ») et qu'AUCUNE spécialité spécifique (comme « médecine de famille ») n'est mentionnée, alors priorise les codes de consultation généraux du chapitre AA (p. ex. `AA.00.0010` pour les 5 premières minutes et `AA.00.0020` pour chaque minute supplémentaire). Assure-toi que les quantités sont correctement calculées en fonction de la durée (p. ex. 15 minutes = 1x `AA.00.0010` + 10x `AA.00.0020`).

**Format de sortie:** **UNIQUEMENT** du JSON valide, **AUCUN** autre texte.
```json
{{
  "identified_leistungen": [
    {{
      "lkn": "VALIDIERTE_LKN_1",
      "typ": "TYP_AUS_KATALOG_1",
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

**Contesto: LKAAT_Leistungskatalog (fonte principale per i LKN, le relative descrizioni e le sezioni "MedizinischeInterpretation" con possibili sinonimi; in aggiunta è disponibile la tabella delle Pauschalen.)
--- Leistungskatalog Start ---
{katalog_context}
--- Leistungskatalog Ende ---

**Istruzioni:** Segui esattamente i passi seguenti:

1.  **Identificazione LKN e convalida STRETTA:**
    *   Leggi attentamente il "Behandlungstext".
    *   Analizza l'intero testo del trattamento. Se vengono descritte più prestazioni distinte (ad es. una consultazione seguita da una procedura), identifica le LKN per ciascuna parte.
    *   Identifica **tutti** i possibili codici LKN (formato `XX.##.####`) che potrebbero rappresentare le attività descritte.
    *   Considera che nel testo possono essere documentate più prestazioni e quindi possono essere valide più LKN (ad es. intervento chirurgico più anestesia).
    *   Se viene menzionata un'anestesia o narcosi eseguita da un anestesista, seleziona esplicitamente un codice del capitolo WA.10 (tabella ANAST). Se non è indicata la durata, usa di default `WA.10.0010`. Quando viene fornita una durata precisa in minuti, impiega il corrispondente codice `WA.10.00x0`.
    *   Sfrutta le tue conoscenze mediche su sinonimi e termini tecnici tipici (ad es. riconosci che « intervento di cataratta » = « facoemulsificazione » / « estrazione del cristallino » = « Extractio lentis »). Per termini complessi come "cateterismo cardiaco sinistro", scomponilo nei suoi componenti ("sinistro", "cuore", "catetere") e cerca LKN corrispondenti come quelle per la "coronarografia" o "cateterismo cardiaco". **Nota per cateterismo cardiaco sinistro (Pauschale C05.10B):** Presta particolare attenzione che le LKN scelte corrispondano molto precisamente alla descrizione testuale. Se diverse LKN sembrano possibili, e se una LKN è un noto attivatore della Pauschale C05.10B, assicurati che il testo giustifichi pienamente questa LKN specifica e le condizioni di tale Pauschale prima di selezionarla.
    *   Consulta attivamente il campo "MedizinischeInterpretation" del catalogo, poiché spesso contiene indicazioni importanti su designazioni alternative o sinonimi comuni per una prestazione.
    *   **Istruzione Critica per Rimozione Verruca con Curette/Cucchiaio Tagliente:** Se il testo del trattamento descrive esplicitamente la "rimozione di una verruca" (o sinonimi diretti) E menziona l'uso di una "curette" o "cucchiaio tagliente" (o traduzioni dirette):
        *   **DEVI IMPERATIVAMENTE** dare priorità alle LKN che descrivono specificamente il "curettage di verruca" o la "rimozione di verruca mediante curettage".
        *   Ricerca attivamente codici come `MK.05.0070` (se questo corrisponde a "curettage di verruche" o simile ed è presente nel catalogo fornito).
        *   Questa istruzione specifica per il curettage di verruche **PREVALE** sui codici più generici di rimozione di lesioni cutanee.
        *   Evita codici per procedure non correlate (ad es. biopsie, suture semplici, agopuntura come `AK.00.0090`) in questo contesto specifico di curettage di verruca.
    *   **Istruzione specifica per "Consulenza/Beratung":** Se il testo menziona « consulenza », « consulto », « colloquio informativo », o « Beratung » (specialmente con una durata e contesto specifico, es. "10 minuti consulenza bambino" **DOVREBBE fortemente puntare a CG.15.0010** se si tratta di una consulenza generale per bambini e CG.15.0010 è "Consulenza... per bambino... pro 5 min." nel catalogo), **DEVI** cercare attivamente e dare priorità a LKN specifiche per queste attività di consulenza tariffate a tempo. Calcola la quantità rigorosamente come Y/X (es. per "10 minuti consulenza bambino" e LKN `CG.15.0010` "pro 5 min", la quantità è 10/5 = 2). Se il contesto è "Medico di Base" e esiste una LKN CA specifica per "Consulenza bambino pro minuto", quella LKN e la quantità Y/1 sarebbero prioritarie.
    *   **Istruzione specifica per "Frattura dito, Inchiodamento" (Pauschale C08.30F):** Se il testo descrive una frattura di un dito trattata con inchiodamento o osteosintesi con chiodo (o termini molto simili come "Nagelung einer Fingerfraktur"):
        *   Sii particolarmente attento nella selezione delle LKN relative sia alla frattura del dito sia alla procedura di inchiodamento/osteosintesi.
        *   Se una LKN identificata è un noto attivatore della Pauschale C08.30F e il testo giustifica pienamente tale LKN e le condizioni della Pauschale, considerala attentamente.
        *   Verifica le descrizioni e le "MedizinischeInterpretation" nel catalogo per trovare le corrispondenze più accurate per queste procedure combinate.
    *   **Note amministrative:** Ignora le osservazioni puramente amministrative o logistiche (ad es. "tempo di trasferimento alla dermatologia", "il paziente ha aspettato") durante l'identificazione delle LKN cliniche fatturabili, a meno che non informino direttamente un parametro fatturabile (ad es. durata di una prestazione supervisionata).
    *   Usa anche il tuo senso stilistico: "grande" può significare "esteso" o "completo"; una dicitura come "grande esame reumatologico" può essere interpretata come "esame reumatologico completo" o "status reumatologico maggiore", l'ordine delle parole può variare e forme sostantivali e verbali possono avere lo stesso significato (es. "rimozione" vs "rimuovere").
    *   **ASSOLUTAMENTE CRITICO:** Per OGNI codice LKN potenziale verifica **LETTERA PER LETTERA e CIFRA PER CIFRA** che esista **ESATTAMENTE** come 'LKN:' nel catalogo sopra. Solo se il codice esiste confronta la **descrizione del catalogo** con l'attività descritta.
    *   Crea un elenco (`identified_leistungen`) **SOLO** con le LKN che hanno superato questa verifica esatta e la cui descrizione corrisponde al testo.
    *   Riconosci se si tratta di prestazioni di medicina di base del capitolo CA. **Questo è un passaggio importante per la corretta selezione delle LKN.**

**Istruzioni specifiche per le prestazioni di consultazione:**
*   **Consultazioni specifiche per area specialistica (es. Medico di Base/Capitolo CA):** Se il testo del trattamento menziona esplicitamente un'area specifica (es. "consultazione dal medico di base", "presso il medico di famiglia", "hausärztliche Konsultation"):
    *   **DAI PRIORITÀ ASSOLUTA** ai codici LKN di consultazione del capitolo corrispondente (es. CA per il medico di base).
    *   **EVITA** di utilizzare i codici AA per la durata di questa consultazione specifica.
    *   Se il capitolo specifico (es. CA) possiede propri codici LKN basati sul tempo per le consultazioni (es. un codice per i "primi 5 minuti" e un altro per "ogni minuto successivo"), applica un calcolo del tempo analogo a quello dei codici AA.
        *   Esempio (ipotetico per CA, basato sulla struttura AA): Per una "consultazione dal medico di base di 17 minuti", se `CA.00.0010` = "Consultazione med. base, primi 5 min." e `CA.00.0020` = "Consultazione med. base, ogni min. succ.", allora fatturare:
            *   `CA.00.0010`, `menge`: 1
            *   `CA.00.0020`, `menge`: (17 - 5) / 1 = 12
    *   Cerca attentamente nel catalogo i codici LKN corretti per l'area menzionata e le loro specifiche modalità di fatturazione.
*   **Consultazioni Generali (Capitolo AA):** Utilizza i codici di consultazione generali del capitolo AA **SOLO SE** il testo del trattamento descrive una "consultazione", "colloquio" ecc. con una durata, E **NESSUNA area medica specifica** (come "medico di base") è esplicitamente menzionata o chiaramente implicata dal contesto.
    *   In questo caso (e solo in questo caso):
        *   `AA.00.0010` ("Consultazione, generale; primi 5 minuti"): la quantità è sempre 1.
        *   `AA.00.0020` ("Consultazione, generale; ogni minuto successivo"): la quantità è (`dauer_minuten` della consultazione - 5) / 1.
        *   Esempio: Una "consultazione di 25 minuti" (senza altra specificazione) comporta: 1x `AA.00.0010` + 20x `AA.00.0020`.
*   Assicurati che `dauer_minuten` sia estratto correttamente per l'intera consultazione prima di effettuare questa suddivisione.

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
    *   **Basato sul tempo (Regola principale per LKN NON-AA/CA):** Se la descrizione nel catalogo di una LKN (che NON è una prestazione di consultazione dei capitoli AA o CA) indica esplicitamente un'unità di tempo (ad es. "per minuto", "per 5 min"), E una durata in minuti (Y) è chiaramente attribuibile a questa LKN specifica:
        *   Interpreti l'unità di tempo della LKN (X) dalla sua descrizione nel catalogo (ad es., X=1 se la descrizione indica "per minuto", X=5 se "per 5 min").
        *   **Calcolo della quantità:** La quantità (`menge`) per questa LKN è quindi calcolata ESATTAMENTE come Y diviso X (cioè `menge = Y / X`).
        *   **Esempio concreto:** Se il testo del trattamento menziona "...curettage di verruca per 5 minuti" e la LKN `MK.05.0070` è descritta nel catalogo come "...per 1 min" (quindi X=1), allora la quantità per `MK.05.0070` è 5 / 1 = 5.
        *   **Altro esempio:** Per una prestazione di 10 minuti che è fatturata "per 5 min" (X=5), la quantità sarebbe 10 / 5 = 2.
        *   Si assicuri che Y rappresenti la durata specifica di questa singola prestazione e non la durata totale di una consultazione più lunga (che sarebbe già gestita dalle regole specifiche dei capitoli AA/CA). Il risultato Y/X deve essere un numero intero.
    *   **Generale:** se `menge_allgemein` (Z) è stato estratto E la LKN non è basata sul tempo (o la regola basata sul tempo non è applicabile) E `anzahl_prozeduren` è `null`, imposta `menge` = Z.
    *   **Numero specifico di procedure:** se `anzahl_prozeduren` è stato estratto e si riferisce chiaramente alla LKN (ad es. "due iniezioni"), imposta `menge` = `anzahl_prozeduren`. Questo prevale su `menge_allgemein`.
    *   Assicurati che `menge` >= 1.
    *   Se una procedura richiede una "lateralità", allora per "beidseits" (entrambi i lati), imposta quantità = 2 E "lateralità" = "beidseits".

5.  **Motivazione:**
    *   `begruendung_llm` breve sul perché le LKN **convalidate** sono state scelte. Fai riferimento al testo e alle **descrizioni del catalogo**.

**Istruzione specifica per le consultazioni:** Se il testo del trattamento descrive una "consultazione" generale o un "colloquio" con una durata (ad es. "consultazione 15 minuti") e NON viene menzionata NESSUNA specializzazione specifica (come "medicina di famiglia"), allora dai priorità ai codici di consultazione generali del capitolo AA (ad es. `AA.00.0010` per i primi 5 minuti e `AA.00.0020` per ogni minuto successivo). Assicurati che le quantità siano calcolate correttamente in base alla durata (ad es. 15 minuti = 1x `AA.00.0010` + 10x `AA.00.0020`).

**Formato di output:** **SOLO** JSON valido, **NESSUN** altro testo.
```json
{{
  "identified_leistungen": [
    {{
      "lkn": "VALIDIERTE_LKN_1",
      "typ": "TYP_AUS_KATALOG_1",
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
    else: # DE (German) - OPTIMIZED PROMPT
        return f"""**Rolle:** Du bist ein KI-Experte für Schweizer Arzttarife (TARDOC/Pauschalen).
**Aufgabe:** Extrahiere aus dem "Behandlungstext" die korrekten LKNs (Leistungs-Katalog-Nummern), berechne ihre Menge und gib das Ergebnis exakt im geforderten JSON-Format aus.

**Kontext: LKAAT_Leistungskatalog**
(Dies ist die einzige Quelle für gültige LKNs, ihre Beschreibungen und Typen)
--- Leistungskatalog Start ---
{katalog_context}
--- Leistungskatalog Ende ---

**ANWEISUNGEN - Folge diesen Schritten exakt:**

**Schritt 1: Analyse & Zerlegung**
*   Lies den gesamten "Behandlungstext".
*   Identifiziere alle einzelnen, abrechenbaren Tätigkeiten. Oft sind sie durch Wörter wie "plus", "und", "danach" oder Satzzeichen getrennt.
    *   Beispiel A: "Hausärztliche Konsultation 15 Min plus 10 Minuten Beratung Kind" -> Tätigkeit 1: "Hausärztliche Konsultation 15 Min", Tätigkeit 2: "10 Minuten Beratung Kind".
    *   Beispiel B: "Kiefergelenk, Luxation. Geschlossene Reposition mit Anästhesie durch Anästhesistin" -> Tätigkeit 1: "Geschlossene Reposition Kiefergelenk", Tätigkeit 2: "Anästhesie durch Anästhesistin".
*   Beziehe Details wie Zeitangaben immer auf die korrekte Tätigkeit.
*   Wenn eine LKN im Format "AA.NN.NNNN" (z.B. "AA.00.0010") oder alternativ "ANN.AA.NNNN" (z.B. "C08.SA.0700") [A=Buchstabe, N=Ziffer] gefunden wird, dann wird diese priorisiert und ausgewählt

**Schritt 2: LKN-Identifikation (pro Tätigkeit)**
*   Finde für jede Tätigkeit die passende LKN im Katalog.
*   **Nutze medizinisches Wissen:** Verstehe Synonyme und Umschreibungen (z.B. "Warzenentfernung" = "Abtragung benigne Hautläsion", "Linksherzkatheter" = "Koronarographie").
*   **Anästhesie-Regel:** Wenn eine Anästhesie durch einen Anästhesisten beschrieben wird, MUSS ein Code aus Kapitel WA.10 verwendet werden. Ohne Zeitangabe -> `WA.10.0010`. Mit Zeitangabe -> der passende `WA.10.00x0` Code.

**Schritt 3: ANWENDUNG DER MENGENREGELN (KRITISCH!)**
Wende für jede gefundene LKN EINE der folgenden Regeln an:

*   **REGEL A: Konsultationen (Kapitel AA & CA)**
    *   **Bedingung:** Die Tätigkeit ist eine "Konsultation", "Sprechstunde", "Gespräch" mit Zeitangabe.
    *   **Kapitelwahl:** Wähle Kapitel `CA` wenn der Text "Hausarzt" oder "hausärztlich" erwähnt, sonst immer Kapitel `AA`.
    *   **Berechnung:**
        1.  **Basis-LKN** (`AA.00.0010` oder `CA.00.0010` "erste 5 Min"): `menge` ist IMMER `1`.
        2.  **Zusatz-LKN** (`AA.00.0020` oder `CA.00.0020` "jede weitere Min"): NUR hinzufügen, wenn Dauer > 5 Min. Die `menge` ist dann exakt: `(Gesamtdauer in Minuten - 5)`.
    *   _Beispiel "Konsultation 15 Min": 1x AA.00.0010 + 10x AA.00.0020_

*   **REGEL B: Andere zeitbasierte Leistungen**
    *   **Bedingung:** Die LKN-Beschreibung im Katalog enthält eine Zeiteinheit (z.B. "pro 1 Min", "pro 5 Min") UND es ist KEINE Konsultation nach Regel A.
    *   **Berechnung:** Die `menge` ist exakt: `Dauer der Tätigkeit / Zeiteinheit der LKN`.
    *   _Beispiel: Tätigkeit dauert 10 Min, LKN ist "pro 5 Min" -> menge = 10 / 5 = 2._

*   **REGEL C: Andere Leistungen (Default)**
    *   **Bedingung:** Regeln A und B treffen nicht zu.
    *   **Berechnung:** Die `menge` ist `1`. Ausnahme: Wenn der Text eine klare Anzahl nennt (z.B. "drei Injektionen", "zwei Läsionen"), verwende diese Zahl. Bei "beidseits" ist die `menge` `2`, wenn die LKN einseitig definiert ist.

**Schritt 4: Strikte Validierung**
*   **ABSOLUT KRITISCH:** Prüfe für JEDE potentielle LKN, ob der Code **exakt (Zeichen für Zeichen)** im Katalog-Kontext existiert. Verwirf alle LKNs, die nicht gefunden werden.
*   Übernehme `typ` und `beschreibung` **ohne Änderung** aus dem Katalog.

**Schritt 5: Extraktion der Kontextinformationen**
*   Extrahiere die Werte `dauer_minuten`, `menge_allgemein`, `alter`, etc. NUR wenn sie explizit im Text stehen. Sonst `null`.
*   Angebrochene Zeiteinheiten gelten als ganze Zeiteinheit (z.B. wenn eine LKN 15 Min. umfasst und ich habe 20 Minuten benötigt, dann ist das eine Menge von 2) ) 

**Schritt 6: JSON-Output erstellen**
*   Stelle alle validierten LKNs und extrahierten Infos im JSON-Format zusammen.
*   `begruendung_llm`: Fasse kurz zusammen, warum du die LKNs gewählt und wie du die Mengen berechnet hast.
*   **WICHTIG:** Wenn keine LKN passt (z.B. bei grossen chirurgischen Eingriffen, die nur als Pauschale existieren), gib eine leere `identified_leistungen`-Liste zurück.

**Output-Format: NUR valides JSON, KEIN anderer Text.**
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
  "begruendung_llm": "<Kurze, präzise Begründung basierend auf den Regeln>"
}}
Behandlungstext: "{user_input}"
JSON-Antwort:"""
def get_stage2_mapping_prompt(tardoc_lkn: str, tardoc_desc: str, candidates_text: str, lang: str) -> str:
    """Return the Stage 2 mapping prompt in the requested language."""
    if lang == "fr":
        return f"""Tâche : Vous êtes un expert des systèmes de facturation médicale en Suisse (TARDOC et Pauschalen). Votre objectif est de trouver, pour la prestation TARDOC indiquée (type E/EZ), la prestation fonctionnellement équivalente dans la « liste des candidats ». Cette liste contient des LKN (souvent P/PZ) utilisés comme conditions dans les Pauschalen potentielles.
Prestation TARDOC donnée (type E/EZ):
LKN: {tardoc_lkn}
Description: {tardoc_desc}
Contexte: Cette prestation a été réalisée dans le cadre d'un traitement pour lequel une facturation par Pauschalen est examinée.
Équivalents possibles (liste des candidats - LKN pour les conditions des Pauschalen) :
Choisissez dans CETTE liste la LKN candidate décrivant le même type d'acte médical que la prestation TARDOC.
--- Kandidaten Start ---
{candidates_text}
--- Kandidaten Ende ---
Analyse et décision :
Comprenez la fonction médicale principale de la prestation TARDOC.
Identifiez les LKN candidates correspondant le mieux à cette fonction.
Classez-les par pertinence.
Réponse :
Donnez une liste simple séparée par des virgules des codes LKN retenus.
Si aucun candidat ne convient, renvoyez exactement NONE.
Aucune autre sortie, pas d'explications.
Liste priorisée (seulement la liste ou NONE):"""
    elif lang == "it":
        return f"""Compito: Sei un esperto dei sistemi di fatturazione medica in Svizzera (TARDOC e Pauschalen). Il tuo obiettivo è individuare, per la prestazione TARDOC indicata (tipo E/EZ), la prestazione funzionalmente equivalente nella "lista dei candidati". Questa lista contiene LKN (spesso P/PZ) utilizzati come condizioni nelle Pauschalen potenzialmente rilevanti.
Prestazione TARDOC fornita (tipo E/EZ):
LKN: {tardoc_lkn}
Descrizione: {tardoc_desc}
Contesto: Questa prestazione è stata eseguita nell'ambito di un trattamento per il quale si verifica una fatturazione a forfait.
Possibili equivalenti (lista dei candidati - LKN per le condizioni delle Pauschalen):
Trova in QUESTA lista la LKN candidata che descrive lo stesso tipo di atto medico della prestazione TARDOC.
--- Kandidaten Start ---
{candidates_text}
--- Kandidaten Ende ---
Analisi e decisione:
Comprendi la funzione medica principale della prestazione TARDOC.
Individua i candidati che rappresentano meglio tale funzione.
Ordinali per pertinenza.
Risposta:
Fornisci un elenco semplice separato da virgole dei codici LKN trovati.
Se nessun candidato è adatto, restituisci esattamente NONE.
Nessun altro testo o spiegazione.
Elenco prioritario (solo elenco o NONE):"""
    else: # DE (German) - OPTIMIZED PROMPT
        return f"""Rolle: Experte für TARDOC/Pauschalen-Mapping.
Aufgabe: Finde in der "Kandidatenliste" die LKN, die funktional identisch mit der gegebenen "TARDOC-Leistung" ist.
Gegebene TARDOC-Leistung (Typ E/EZ):
LKN: {tardoc_lkn}
Beschreibung: {tardoc_desc}
Kandidatenliste (LKNs für Pauschalen-Bedingungen):
(Finde hier die exakte funktionale Entsprechung)
--- Kandidaten Start ---
{candidates_text}
--- Kandidaten Ende ---
Analyse & Entscheidung:
Kernfunktion verstehen: Was ist die medizinische Haupttätigkeit der TARDOC-Leistung? (z.B. "Entfernung einer Hautläsion", "Reposition einer Fraktur").
Abgleichen: Vergleiche diese Kernfunktion mit der Beschreibung JEDES Kandidaten.
Auswählen: Wähle den/die Kandidaten mit der höchsten Übereinstimmung.
Antwort-Format:
Gib NUR eine kommagetrennte Liste der passenden LKN-Codes zurück (z.B. PZ.01.0010,PZ.01.0020).
Wenn absolut kein Kandidat passt, gib exakt NONE zurück.
Keine Erklärungen, kein zusätzlicher text.
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
    else: # DE (German) - OPTIMIZED PROMPT
        return f"""Aufgabe: RANGORDNE die "Potenziellen Pauschalen" nach ihrer Relevanz für den "Behandlungstext".
Kriterien: Die beste Pauschale ist die, deren 'Pauschale_Text' die im Behandlungstext beschriebene Hauptleistung am genauesten widerspiegelt.
Behandlungstext: "{user_input}"
Potenzielle Pauschalen:
--- Pauschalen Start ---
{potential_pauschalen_text}
--- Pauschalen Ende ---
Output:
Gib NUR eine kommagetrennte Liste der Pauschalen-Codes zurück, sortiert von der besten zur schlechtesten Übereinstimmung.
Beispiel: "C01.10A,C05.20B"
KEINE Begründung, KEIN zusätzlicher Text.
Priorisierte Pauschalen-Codes (nur kommagetrennte Liste):"""
