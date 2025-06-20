# utils.py
import html
from typing import Dict, List, Any
import re

def escape(text: Any) -> str:
    """Escapes HTML special characters in a string."""
    return html.escape(str(text))

def get_table_content(table_ref: str, table_type: str, tabellen_dict_by_table: dict, lang: str = 'de') -> list[dict]:
    """Holt Einträge für eine Tabelle und einen Typ (Case-Insensitive).
    Berücksichtigt die Sprache für den Text."""
    content = []
    # Schlüssel für PAUSCHALEN_Tabellen - anpassen falls nötig!
    TAB_CODE_KEY = 'Code'; TAB_TEXT_KEY = 'Code_Text'; TAB_TYP_KEY = 'Tabelle_Typ'

    table_names = [t.strip() for t in table_ref.split(',') if t.strip()]
    all_entries_for_type = []

    for name in table_names:
        normalized_key = name.lower() # Suche immer mit kleinem Schlüssel
        # print(f"DEBUG (get_table_content): Suche normalisierten Schlüssel '{normalized_key}' für Typ '{table_type}'") # Optional

        if normalized_key in tabellen_dict_by_table:
            # print(f"DEBUG (get_table_content): Schlüssel '{normalized_key}' gefunden.") # Optional
            for entry in tabellen_dict_by_table[normalized_key]: # Greife direkt auf die Liste zu
                entry_typ = entry.get(TAB_TYP_KEY)
                if entry_typ and entry_typ.lower() == table_type.lower():
                    code = entry.get(TAB_CODE_KEY)
                    text = get_lang_field(entry, TAB_TEXT_KEY, lang)
                    if code:
                        all_entries_for_type.append({"Code": code, "Code_Text": text or "N/A"})
        else:
             print(f"WARNUNG (get_table_content): Normalisierter Schlüssel '{normalized_key}' (Original: '{name}') nicht in tabellen_dict_by_table gefunden.")

    unique_content = {item['Code']: item for item in all_entries_for_type}.values()
    return sorted(unique_content, key=lambda x: x.get('Code', ''))

def get_lang_field(entry: Dict[str, Any], base_key: str, lang: str) -> Any:
    """Returns the value for a language-aware key if available."""
    if not isinstance(entry, dict):
        return None
    suffix = {'de': '', 'fr': '_f', 'it': '_i'}.get(str(lang).lower(), '')
    return entry.get(f"{base_key}{suffix}") or entry.get(base_key)


# Einfache Übersetzungsfunktion für Backend-Strings
_TRANSLATIONS: Dict[str, Dict[str, str]] = {
    'conditions_met': {
        'de': '(Bedingungen erfüllt)',
        'fr': '(Conditions remplies)',
        'it': '(Condizioni soddisfatte)'
    },
    'conditions_not_met': {
        'de': '(Bedingungen NICHT erfüllt)',
        'fr': '(Conditions NON remplies)',
        'it': '(Condizioni NON soddisfatte)'
    },
    'conditions_also_met': {
        'de': '(Bedingungen auch erfüllt)',
        'fr': '(Conditions aussi remplies)',
        'it': '(Condizioni pure soddisfatte)'
    },
    'group_conditions': {
        'de': 'Bedingungen (Alle müssen erfüllt sein):',
        'fr': 'Conditions (toutes doivent être remplies) :',
        'it': 'Condizioni (tutte devono essere soddisfatte):'
    },
    'group_additional': {
        'de': 'Zusätzliche Bedingungen (Alle müssen erfüllt sein):',
        'fr': 'Conditions supplémentaires (toutes doivent être remplies) :',
        'it': 'Condizioni supplementari (tutte devono essere soddisfatte):'
    },
    'group_logic': {
        'de': 'Logik-Gruppe {id} (Alle Bedingungen dieser Gruppe müssen erfüllt sein):',
        'fr': 'Groupe logique {id} (toutes les conditions de ce groupe doivent être remplies) :',
        'it': 'Gruppo logico {id} (tutte le condizioni di questo gruppo devono essere soddisfatte):'
    },
    'no_valid_groups': {
        'de': 'Keine gültigen Bedingungsgruppen gefunden.',
        'fr': 'Aucun groupe de conditions valide trouvé.',
        'it': 'Nessun gruppo di condizioni valido trovato.'
    },
    'detail_html_not_generated': {
        'de': 'Detail-HTML für Bedingungen nicht generiert.',
        'fr': "HTML détaillé pour les conditions non généré.",
        'it': 'HTML dettagliato per le condizioni non generato.'
    },
    'require_lkn_list': {
        'de': 'Erfordert LKN aus Liste: ',
        'fr': 'NPL requis depuis une liste : ',
        'it': 'NPL richiesti da una lista: '
    },
    'require_lkn_table': {
        'de': 'Erfordert LKN aus Tabelle(n): ',
        'fr': 'NPL requis depuis table(s) : ',
        'it': 'NPL richiesti da tabella/e: '
    },
    'no_lkns_spec': {
        'de': '(Keine LKNs spezifiziert)',
        'fr': '(Aucun NPL spécifié)',
        'it': '(Nessun NPL specificato)'
    },
    'no_table_name': {
        'de': '(Kein Tabellenname spezifiziert)',
        'fr': '(Aucun nom de table spécifié)',
        'it': '(Nessun nome tabella specificato)'
    },
    'require_icd_table': {
        'de': 'Erfordert ICD aus Tabelle(n): ',
        'fr': 'ICD requis depuis table(s) : ',
        'it': 'ICD richiesti da tabella/e: '
    },
    'require_icd_list': {
        'de': 'Erfordert ICD aus Liste: ',
        'fr': 'ICD requis depuis une liste : ',
        'it': 'ICD richiesti da una lista: '
    },
    'no_icds_spec': {
        'de': '(Keine ICDs spezifiziert)',
        'fr': '(Aucun ICD spécifié)',
        'it': '(Nessun ICD specificato)'
    },
    'require_gtin_list': {
        'de': 'Erfordert GTIN aus Liste: ',
        'fr': 'GTIN requis depuis une liste : ',
        'it': 'GTIN richiesti da una lista: '
    },
    'no_gtins_spec': {
        'de': '(Keine GTINs spezifiziert)',
        'fr': '(Aucune GTIN spécifiée)',
        'it': '(Nessuna GTIN specificata)'
    },
    'patient_condition': {
        'de': 'Patientenbedingung ({field}): {value}',
        'fr': 'Condition patient ({field}) : {value}',
        'it': 'Condizione paziente ({field}) : {value}'
    },
    'anzahl_condition': {
        'de': 'Anzahlbedingung: {value}',
        'fr': 'Condition sur la quantité : {value}',
        'it': 'Condizione sul numero: {value}'
    },
    'seitigkeit_condition': {
        'de': 'Seitigkeitsbedingung: {value}',
        'fr': 'Condition de latéralité : {value}',
        'it': 'Condizione di lateralità: {value}'
    },
    'geschlecht_list': {
        'de': 'Geschlecht aus Liste: ',
        'fr': 'Sexe dans la liste : ',
        'it': 'Sesso in elenco: '
    },
    'no_gender_spec': {
        'de': '(Keine Geschlechter spezifiziert)',
        'fr': '(Aucun sexe spécifié)',
        'it': '(Nessun sesso specificato)'
    },
    'fulfilled_by': {
        'de': '(Erfüllt durch: {items})',
        'fr': '(Rempli par : {items})',
        'it': '(Soddisfatto da: {items})'
    },
    'context_items_not_in_table': {
        'de': '(Kontext-Element(e) {items} nicht in Regel-Tabelle(n) gefunden)',
        'fr': '(Élément(s) du contexte {items} non trouvé(s) dans la/les table(s) de règle)',
        'it': '(Elemento/i di contesto {items} non trovato/i nelle tabelle delle regole)'
    },
    'tables_empty': {
        'de': '(Regel-Tabelle(n) leer oder nicht gefunden)',
        'fr': '(Table(s) de règle vide(s) ou non trouvée(s))',
        'it': '(Tabella/e delle regole vuota/e o non trovata/e)'
    },
    'context_items_not_in_list': {
        'de': '(Kontext-Element(e) {items} nicht in Regel-Liste)',
        'fr': '(Élément(s) du contexte {items} absent(s) de la liste de règle)',
        'it': '(Elemento/i di contesto {items} non presente/i nell\'elenco della regola)'
    },
    'no_context_in_list': {
        'de': '(Kein Kontext-Element in Regel-Liste)',
        'fr': '(Aucun élément du contexte dans la liste de règle)',
        'it': '(Nessun elemento di contesto nell\'elenco della regola)'
    },
    'rule_list_empty': {
        'de': '(Regel-Liste leer)',
        'fr': '(Liste de règle vide)',
        'it': '(Elenco della regola vuoto)'
    },
    'entries_label': {
        'de': 'Einträge',
        'fr': 'entrées',
        'it': 'voci'
    },
    'context_value': {
        'de': '(Kontext: {value})',
        'fr': '(Contexte : {value})',
        'it': '(Contesto: {value})'
    },
    'diff_to': {
        'de': 'Unterschiede zu',
        'fr': 'Différences avec',
        'it': 'Differenze rispetto a'
    },
    'or_separator': {
        'de': 'ODER',
        'fr': 'OU',
        'it': 'OPPURE'
    },
    'rule_qty_exceeded': {
        'de': 'Mengenbeschränkung überschritten (max. {max}, angefragt {req})',
        'fr': 'Limite de quantité dépassée (max. {max}, demandé {req})',
        'it': 'Limite di quantità superata (max. {max}, richiesto {req})'
    },
    'rule_qty_reduced': {
        'de': 'Menge auf {value} reduziert (Mengenbeschränkung)',
        'fr': 'Quantité réduite à {value} (limitation de quantité)',
        'it': 'Quantità ridotta a {value} (limitazione di quantità)'
    },
    'rule_only_supplement': {
        'de': 'Nur als Zuschlag zu {code} zulässig (Basis fehlt)',
        'fr': 'Uniquement comme supplément à {code} (base manquante)',
        'it': 'Solo come supplemento a {code} (base mancante)'
    },
    'rule_not_cumulable': {
        'de': 'Nicht kumulierbar mit: {codes}',
        'fr': 'Non cumulable avec : {codes}',
        'it': 'Non cumulabile con: {codes}'
    },
    'rule_patient_field_missing': {
        'de': 'Patientenbedingung ({field}) nicht erfüllt: Kontextwert fehlt',
        'fr': 'Condition patient ({field}) non remplie : valeur manquante',
        'it': 'Condizione paziente ({field}) non soddisfatta: valore mancante'
    },
    'rule_patient_age': {
        'de': 'Patientenbedingung ({detail}) nicht erfüllt (Patient: {value})',
        'fr': 'Condition patient ({detail}) non remplie (patient : {value})',
        'it': 'Condizione paziente ({detail}) non soddisfatta (paziente: {value})'
    },
    'rule_patient_age_invalid': {
        'de': 'Patientenbedingung (Alter): Ungültiger Alterswert im Fall ({value})',
        'fr': "Condition patient (âge) : valeur d'âge non valide ({value})",
        'it': 'Condizione paziente (età): valore età non valido ({value})'
    },
    'rule_patient_gender_mismatch': {
        'de': 'Patientenbedingung (Geschlecht): erwartet {exp}, gefunden {found}',
        'fr': 'Condition patient (sexe) : attendu {exp}, trouvé {found}',
        'it': 'Condizione paziente (sesso): atteso {exp}, trovato {found}'
    },
    'rule_patient_gender_invalid': {
        'de': 'Patientenbedingung (Geschlecht): Ungültige Werte für Geschlechtsprüfung',
        'fr': 'Condition patient (sexe) : valeurs non valides pour le contrôle du sexe',
        'it': 'Condizione paziente (sesso): valori non validi per il controllo del sesso'
    },
    'rule_patient_gtin_missing': {
        'de': 'Patientenbedingung (GTIN): Erwartet einen von {required}, nicht gefunden',
        'fr': "Condition patient (GTIN) : attendu l'un de {required}, non trouvé",
        'it': 'Condizione paziente (GTIN): previsto uno di {required}, non trovato'
    },
    'rule_diagnosis_missing': {
        'de': 'Erforderliche Diagnose(n) nicht vorhanden (Benötigt: {codes})',
        'fr': 'Diagnostic(s) requis absent(s) (nécessaire : {codes})',
        'it': 'Diagnosi richiesta non presente (necessario: {codes})'
    },
    'rule_pauschale_exclusion': {
        'de': 'Leistung nicht zulässig bei gleichzeitiger Abrechnung der Pauschale(n): {codes}',
        'fr': 'Prestation non admise en cas de facturation simultanée du/des forfait(s) : {codes}',
        'it': 'Prestazione non ammessa con fatturazione simultanea del/i forfait: {codes}'
    },
    'rule_internal_error': {
        'de': 'Interner Fehler bei Regelprüfung: {error}',
        'fr': 'Erreur interne lors du contrôle des règles : {error}',
        'it': 'Errore interno durante il controllo delle regole: {error}'
    },
    'rule_check_not_available': {
        'de': 'Regelprüfung nicht verfügbar.',
        'fr': 'Contrôle des règles non disponible.',
        'it': 'Controllo regole non disponibile.'
    },
    'rule_check_not_performed': {
        'de': 'Regelprüfung nicht durchgeführt.',
        'fr': 'Contrôle des règles non effectué.',
        'it': 'Controllo regole non eseguito.'
    },
    'llm_no_lkn': {
        'de': 'Keine LKN vom LLM identifiziert/validiert.',
        'fr': 'Aucun NPL identifié/validé par le LLM.',
        'it': 'Nessun NPL identificato/validato dal LLM.'
    }

}

# Zusätzliche Übersetzungen für Bedingungstypen
_COND_TYPE_TRANSLATIONS: Dict[str, Dict[str, str]] = {
    'LEISTUNGSPOSITIONEN IN LISTE': {
        'de': 'LEISTUNGSPOSITIONEN IN LISTE',
        'fr': 'Positions de prestation dans une liste',
        'it': 'Posizioni di prestazione in elenco'
    },
    'LEISTUNGSPOSITIONEN IN TABELLE': {
        'de': 'LEISTUNGSPOSITIONEN IN TABELLE',
        'fr': 'Positions de prestation dans une table',
        'it': 'Posizioni di prestazione in tabella'
    },
    'TARIFPOSITIONEN IN TABELLE': {
        'de': 'TARIFPOSITIONEN IN TABELLE',
        'fr': 'Positions tarifaires dans une table',
        'it': 'Posizioni tariffarie in tabella'
    },
    'LKN IN LISTE': {
        'de': 'LKN IN LISTE',
        'fr': 'NPL dans une liste',
        'it': 'NPL in elenco'
    },
    'LKN IN TABELLE': {
        'de': 'LKN IN TABELLE',
        'fr': 'NPL dans une table',
        'it': 'NPL in tabella'
    },
    'ICD IN LISTE': {
        'de': 'ICD IN LISTE',
        'fr': 'ICD dans une liste',
        'it': 'ICD in elenco'
    },
    'ICD IN TABELLE': {
        'de': 'ICD IN TABELLE',
        'fr': 'ICD dans une table',
        'it': 'ICD in tabella'
    },
    'HAUPTDIAGNOSE IN TABELLE': {
        'de': 'HAUPTDIAGNOSE IN TABELLE',
        'fr': 'Diagnostic principal dans une table',
        'it': 'Diagnosi principale in tabella'
    },
    'MEDIKAMENTE IN LISTE': {
        'de': 'MEDIKAMENTE IN LISTE',
        'fr': 'Médicaments dans une liste',
        'it': 'Farmaci in elenco'
    },
    'GESCHLECHT IN LISTE': {
        'de': 'GESCHLECHT IN LISTE',
        'fr': 'Sexe dans la liste',
        'it': 'Sesso in elenco'
    },
    'ALTER IN JAHREN BEI EINTRITT': {
        'de': 'ALTER IN JAHREN BEI EINTRITT',
        'fr': "Âge en années à l'admission",
        'it': "Età in anni all'ingresso"
    },
    'ANZAHL': {
        'de': 'ANZAHL',
        'fr': 'Quantité',
        'it': 'Quantità'
    },
    'SEITIGKEIT': {
        'de': 'SEITIGKEIT',
        'fr': 'Latéralité',
        'it': 'Lateralità'
    }
}

def translate(key: str, lang: str = 'de', **kwargs) -> str:
    """Einfache Übersetzung bestimmter Texte mit Platzhaltern."""
    lang = str(lang).lower()
    template = _TRANSLATIONS.get(key, {}).get(lang) or _TRANSLATIONS.get(key, {}).get('de') or key
    return template.format(**kwargs)

def translate_rule_error_message(msg: str, lang: str = 'de') -> str:
    """Übersetzt häufige Regelprüfer-Meldungen anhand einfacher Muster."""
    if lang == 'de' or not msg:
        return msg
    import re
    patterns = [
        (r'^Mengenbeschränkung überschritten \(max\. (?P<max>\d+), angefragt (?P<req>\d+)\)$', 'rule_qty_exceeded'),
        (r'^Menge auf (?P<value>\d+) reduziert \(Mengenbeschränkung\)$', 'rule_qty_reduced'),
        (r'^Nur als Zuschlag zu (?P<code>[A-Z0-9.]+) zulässig \(Basis fehlt\)$', 'rule_only_supplement'),
        (r'^Nicht kumulierbar mit: (?P<codes>.+)$', 'rule_not_cumulable'),
        (r'^Patientenbedingung \((?P<field>[^)]+)\) nicht erfüllt: Kontextwert fehlt$', 'rule_patient_field_missing'),
        (r'^Patientenbedingung \((?P<detail>[^)]+)\) nicht erfüllt \(Patient: (?P<value>[^)]+)\)$', 'rule_patient_age'),
        (r'^Patientenbedingung \(Alter\): Ungültiger Alterswert im Fall \((?P<value>[^)]+)\)$', 'rule_patient_age_invalid'),
        (r"^Patientenbedingung \(Geschlecht\): erwartet '(?P<exp>[^']+)', gefunden '(?P<found>[^']+)'$", 'rule_patient_gender_mismatch'),
        (r'^Patientenbedingung \(Geschlecht\): Ungültige Werte für Geschlechtsprüfung$', 'rule_patient_gender_invalid'),
        (r"^Patientenbedingung \(GTIN\): Erwartet einen von (?P<required>.+), nicht gefunden$", 'rule_patient_gtin_missing'),
        (r'^Erforderliche Diagnose\(n\) nicht vorhanden \(Benötigt: (?P<codes>.+)\)$', 'rule_diagnosis_missing'),
        (r'^Leistung nicht zulässig bei gleichzeitiger Abrechnung der Pauschale\(n\): (?P<codes>.+)$', 'rule_pauschale_exclusion'),
        (r'^Interner Fehler bei Regelprüfung: (?P<error>.+)$', 'rule_internal_error'),
        (r'^Regelprüfung nicht verfügbar\.$', 'rule_check_not_available'),
        (r'^Regelprüfung nicht durchgeführt\.$', 'rule_check_not_performed'),
        (r'^Keine LKN vom LLM identifiziert/validiert\.$', 'llm_no_lkn'),
    ]
    for pattern, key in patterns:
        m = re.match(pattern, msg)
        if m:
            return translate(key, lang, **m.groupdict())
    return msg

def translate_condition_type(cond_type: str, lang: str = 'de') -> str:
    """Übersetzt bekannte Pauschalen-Bedingungstypen."""
    if not cond_type:
        return cond_type
    translations = _COND_TYPE_TRANSLATIONS.get(cond_type)
    if not translations:
        return cond_type
    lang = str(lang).lower()
    return translations.get(lang, translations.get('de', cond_type))


def expand_compound_words(text: str) -> str:
    """Expand common German compound words with directional prefixes.

    This helps the LLM and rule logic to recognise base terms that might
    be hidden inside compounds (e.g. ``Linksherzkatheter`` -> ``Links herzkatheter``).
    The function appends the decomposed variants to the original text.
    """
    if not isinstance(text, str):
        return text

    prefixes = [
        "links",
        "rechts",
        "ober",
        "unter",
        "innen",
        "aussen",
    ]

    additions: List[str] = []
    for token in re.findall(r"\b\w+\b", text):
        lowered = token.lower()
        for pref in prefixes:
            if lowered.startswith(pref) and len(lowered) > len(pref) + 2:
                base = token[len(pref):]
                additions.append(f"{pref} {base}")
                additions.append(base)
                break

    if additions:
        return text + " " + " ".join(additions)
    return text

