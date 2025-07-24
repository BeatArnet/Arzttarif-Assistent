# utils.py
import html
import logging
from typing import Dict, List, Any, Set, Tuple
import re

logger = logging.getLogger(__name__)

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
            for entry in tabellen_dict_by_table[normalized_key]:
                entry_typ = entry.get(TAB_TYP_KEY)
                # If the table entry has no explicit type, assume it matches the
                # requested ``table_type``. This mirrors the simplified mocks in
                # the tests where only the ``Code`` field is provided.
                if entry_typ and entry_typ.lower() != table_type.lower():
                    continue
                code = entry.get(TAB_CODE_KEY)
                text = get_lang_field(entry, TAB_TEXT_KEY, lang)
                if code:
                    all_entries_for_type.append({"Code": code, "Code_Text": text or "N/A"})
        else:
            logger.warning(
                "WARNUNG (get_table_content): Normalisierter Schlüssel '%s' (Original: '%s') nicht in tabellen_dict_by_table gefunden.",
                normalized_key,
                name,
            )

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
    },
    'condition_met_context_generic': {
        'de': 'Bedingung erfüllt', # More direct translation
        'fr': 'Condition remplie',
        'it': 'Condizione soddisfatta'
    },
    'fulfilled_by_lkn': {
        'de': 'erfüllt durch LKN: {lkn_code_link}', # Placeholder for linked LKN
        'fr': 'remplie par NPL : {lkn_code_link}',
        'it': 'soddisfatta da NPL: {lkn_code_link}'
    },
    'fulfilled_by_icd': {
        'de': 'erfüllt durch ICD: {icd_code_link}', # Placeholder for linked ICD
        'fr': 'remplie par CIM : {icd_code_link}',
        'it': 'soddisfatta da ICD: {icd_code_link}'
    },
    'condition_text_lkn_list': { # Used for the main display of LKNs in a list
        'de': '{linked_codes}',
        'fr': '{linked_codes}',
        'it': '{linked_codes}'
    },
    'condition_text_icd_list': { # Used for the main display of ICDs in a list
        'de': '{linked_codes}',
        'fr': '{linked_codes}',
        'it': '{linked_codes}'
    },
    'condition_text_lkn_table': {
        'de': 'aus Tabelle(n): {table_names}',
        'fr': 'de la/des table(s): {table_names}',
        'it': 'da tabella/e: {table_names}'
    },
    'condition_text_icd_table': {
        'de': 'aus Tabelle(n): {table_names}',
        'fr': 'de la/des table(s): {table_names}',
        'it': 'da tabella/e: {table_names}'
    },
    'condition_group': {
        'de': 'Bedingungsgruppe',
        'fr': 'Groupe de conditions',
        'it': 'Gruppo di condizioni'
    },
    'AND': {
        'de': 'UND',
        'fr': 'ET',
        'it': 'E'
    },
    'OR': {
        'de': 'ODER',
        'fr': 'OU',
        'it': 'O'
    },
    'min': {
        'de': 'min.',
        'fr': 'min.',
        'it': 'min.'
    },
    'max': {
        'de': 'max.',
        'fr': 'max.',
        'it': 'max.'
    },
    'not_specified': {
        'de': 'nicht spezifiziert',
        'fr': 'non spécifié',
        'it': 'non specificato'
    },
    'patient_condition_display': { # For "PATIENTENBEDINGUNG" type display
        'de': 'Patient: {field}',
        'fr': 'Patient : {field}',
        'it': 'Paziente: {field}'
    },
    'bilateral': {
        'de': 'beidseits',
        'fr': 'bilatéral',
        'it': 'bilaterale'
    },
    'unilateral': {
        'de': 'einseitig',
        'fr': 'unilatéral',
        'it': 'unilaterale'
    },
    'left': {
        'de': 'links',
        'fr': 'gauche',
        'it': 'sinistra'
    },
    'right': {
        'de': 'rechts',
        'fr': 'droite',
        'it': 'destra'
    },
    'no_conditions_for_pauschale': {
        'de': 'Keine Bedingungen für diese Pauschale definiert.',
        'fr': 'Aucune condition définie pour ce forfait.',
        'it': 'Nessuna condizione definita per questo forfait.'
    }
}

# Zusätzliche Übersetzungen für Bedingungstypen
_COND_TYPE_TRANSLATIONS: Dict[str, Dict[str, str]] = {
    'LEISTUNGSPOSITIONEN IN LISTE': { # Main type key
        'de': 'LKN IN LISTE', # Display value in German
        'fr': 'NPL en liste',
        'it': 'NPL in elenco'
    },
    'LKN': { # Alias for LEISTUNGSPOSITIONEN IN LISTE
        'de': 'LKN IN LISTE',
        'fr': 'NPL en liste',
        'it': 'NPL in elenco'
    },
    'LEISTUNGSPOSITIONEN IN TABELLE': {
        'de': 'LKN', # Geändert von 'LKN AUS TABELLE'
        'fr': 'NPL', # Geändert von 'NPL de table'
        'it': 'NPL'  # Geändert von 'NPL da tabella'
    },
    'TARIFPOSITIONEN IN TABELLE': { # Alias
        'de': 'LKN', # Geändert von 'LKN AUS TABELLE'
        'fr': 'NPL', # Geändert von 'NPL de table'
        'it': 'NPL'  # Geändert von 'NPL da tabella'
    },
    'LKN IN TABELLE': { # Alias
        'de': 'LKN', # Geändert von 'LKN AUS TABELLE'
        'fr': 'NPL', # Geändert von 'NPL de table'
        'it': 'NPL'  # Geändert von 'NPL da tabella'
    },
    'ICD IN LISTE': {
        'de': 'ICD IN LISTE',
        'fr': 'CIM en liste', # CIM is ICD in French
        'it': 'ICD in elenco'
    },
    'HAUPTDIAGNOSE IN LISTE': { # Alias for ICD IN LISTE
        'de': 'ICD IN LISTE',
        'fr': 'CIM en liste',
        'it': 'ICD in elenco'
    },
    'ICD': { # Alias for ICD IN LISTE
        'de': 'ICD IN LISTE',
        'fr': 'CIM en liste',
        'it': 'ICD in elenco'
    },
    'ICD IN TABELLE': {
        'de': 'ICD AUS TABELLE',
        'fr': 'CIM de table',
        'it': 'ICD da tabella'
    },
    'HAUPTDIAGNOSE IN TABELLE': {
        'de': 'ICD AUS TABELLE', # Changed for consistency
        'fr': 'CIM de table',
        'it': 'ICD da tabella'
    },
    'MEDIKAMENTE IN LISTE': {
        'de': 'MEDIKAMENTE IN LISTE',
        'fr': 'Médicaments en liste',
        'it': 'Farmaci in elenco'
    },
    'GTIN': { # Alias
        'de': 'MEDIKAMENTE IN LISTE',
        'fr': 'Médicaments en liste',
        'it': 'Farmaci in elenco'
    },
    'GTIN': { # Alias
        'de': 'MEDIKAMENTE IN LISTE',
        'fr': 'Médicaments en liste',
        'it': 'Farmaci in elenco'
    },
    'GESCHLECHT IN LISTE': {
        'de': 'GESCHLECHT IN LISTE',
        'fr': 'Sexe dans la liste',
        'it': 'Sesso in elenco'
    },
    'PATIENTENBEDINGUNG': { # This will be combined with the 'Feld' for display
        'de': 'PATIENT', # Generic prefix, field will be added
        'fr': 'PATIENT',
        'it': 'PAZIENTE'
    },
    'ALTER IN JAHREN BEI EINTRITT': {
        'de': 'ALTER BEI EINTRITT',
        'fr': "ÂGE À L'ADMISSION",
        'it': "ETÀ ALL'INGRESSO"
    },
    'ANZAHL': {
        'de': 'ANZAHL',
        'fr': 'QUANTITÉ',
        'it': 'QUANTITÀ'
    },
    'SEITIGKEIT': {
        'de': 'SEITIGKEIT',
        'fr': 'LATÉRALITÉ',
        'it': 'LATERALITÀ'
    },
    'AST VERBINDUNGSOPERATOR': { # Internal, not usually displayed directly as a condition type
        'de': 'LOGIK-OPERATOR',
        'fr': 'OPÉRATEUR LOGIQUE',
        'it': 'OPERATORE LOGICO'
    },
    'GESCHLECHT IN LISTE': {
        'de': 'GESCHLECHT IN LISTE',
        'fr': 'Sexe dans la liste',
        'it': 'Sesso in elenco'
    },
    'PATIENTENBEDINGUNG': { # This will be combined with the 'Feld' for display
        'de': 'PATIENT', # Generic prefix, field will be added
        'fr': 'PATIENT',
        'it': 'PAZIENTE'
    },
    'ALTER IN JAHREN BEI EINTRITT': {
        'de': 'ALTER BEI EINTRITT',
        'fr': "ÂGE À L'ADMISSION",
        'it': "ETÀ ALL'INGRESSO"
    },
    'ANZAHL': {
        'de': 'ANZAHL',
        'fr': 'QUANTITÉ',
        'it': 'QUANTITÀ'
    },
    'SEITIGKEIT': {
        'de': 'SEITIGKEIT',
        'fr': 'LATÉRALITÉ',
        'it': 'LATERALITÀ'
    },
    'AST VERBINDUNGSOPERATOR': { # Internal, not usually displayed directly as a condition type
        'de': 'LOGIK-OPERATOR',
        'fr': 'OPÉRATEUR LOGIQUE',
        'it': 'OPERATORE LOGICO'
    }
}

# Entferne die erste, fehlerhafte Definition von translate und _COND_TYPE_TRANSLATIONS
# Die korrekte Definition beginnt weiter unten.

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

from typing import Optional

def create_html_info_link(code: str, data_type: str, display_text: str, data_content: Optional[str] = None) -> str:
    """
    Generates an HTML <a> tag for info links, used by the frontend.
    display_text is already escaped and prepared by the caller.
    """
    escaped_code = escape(code)
    # data_type does not need escaping as it's from a controlled set.
    css_class = "info-link"
    data_attributes = f'data-type="{data_type}" data-code="{escaped_code}"'
    if data_content:
        css_class += " popup-link"
        data_attributes += f" data-content='{escape(data_content)}'"
    return f'<a href="#" class="{css_class}" {data_attributes}>{display_text}</a>'

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

    excluded_words = {"untersuchung", "unterwegs"}

    additions: List[str] = []
    for token in re.findall(r"\b\w+\b", text):
        lowered = token.lower()
        if lowered in excluded_words:
            continue
        for pref in prefixes:
            # Split the token if it begins with one of the known prefixes and
            # has enough characters left for a meaningful base word. The strict
            # check for an uppercase letter after the prefix has been removed to
            # also handle inputs like "Linksherzkatheter".
            if lowered.startswith(pref) and len(lowered) > len(pref) + 2:
                base = token[len(pref):]
                additions.append(f"{pref} {base}")
                additions.append(base)
                break

    if additions:
        return text + " " + " ".join(additions)
    return text


# Sehr allgemeine deutsche Wörter, die bei der Keyword-Extraktion ignoriert
# werden sollen. Nur Kleinschreibung verwenden, da ``extract_keywords`` die
# Tokens bereits konvertiert.
STOPWORDS: Set[str] = {
    "und",
    "oder",
    "die",
    "der",
    "das",
    "des",
    "durch",
    "mit",
    "von",
    "im",
    "in",
    "für",
    "per",
    # Zusätzliche Stopwords um Fehl-Tokens durch expand_compound_words zu vermeiden
    "unter",
    "suchung",
    "untersuchung",
}


# Laienbegriffe und deren häufig verwendete Fachtermini zur Keyword-Erweiterung
SYNONYM_MAP: Dict[str, List[str]] = {
    "blinddarmentfernung": ["appendektomie", "appendix"],
    "appendektomie": ["blinddarmentfernung"],
    "appendix": ["blinddarmentfernung", "blinddarm"],
    "blinddarm": ["appendix"],
    "warze": ["hyperkeratose"],
    "hyperkeratose": ["warze"],
    "warzen": ["hyperkeratosen"],
    "hyperkeratosen": ["warzen"],
    "gross": ["umfassend"],
    "umfassend": ["gross"],
    "grosser": ["umfassender"],
    "umfassender": ["grosser"],
    "entfernung": ["entfernen"],
    "entfernen": ["entfernung"],
    "rheuma": ["rheumatologisch", "rheumatologische"],
    "rheumatologisch": ["rheuma", "rheumatologische"],
    "rheumatologische": ["rheuma", "rheumatologisch"],
}


def extract_keywords(text: str) -> Set[str]:
    """Return significant keywords from ``text``.

    Das Eingabewort wird zunächst mit :func:`expand_compound_words` erweitert.
    Anschliessend werden alle Tokens in Kleinschreibung extrahiert und solche mit
    weniger als vier Buchstaben oder in :data:`STOPWORDS` verworfen.
    """

    expanded = expand_compound_words(text)
    tokens = re.findall(r"\b\w+\b", expanded.lower())
    base_tokens = {t for t in tokens if len(t) >= 4 and t not in STOPWORDS}

    def collect_synonyms(token: str) -> Set[str]:
        """Return ``token`` and all synonyms recursively."""
        collected = {token}
        queue = [token]
        while queue:
            current = queue.pop()
            for syn in SYNONYM_MAP.get(current, []):
                syn = syn.lower()
                if syn not in collected:
                    collected.add(syn)
                    queue.append(syn)
        return collected

    expanded_tokens: Set[str] = set()
    for t in base_tokens:
        expanded_tokens.update(collect_synonyms(t))

    return expanded_tokens


# --- New helper: Extract LKN codes directly from text ---
LKN_CODE_REGEX = re.compile(r"\b[A-Z][A-Z0-9]{1,2}\.[A-Z0-9]{2}\.[0-9]{4}\b", re.IGNORECASE)

def extract_lkn_codes_from_text(text: str) -> List[str]:
    """Return all potential LKN codes found in ``text``.

    The pattern matches codes like ``GG.15.0330`` or ``C08.SA.0700``
    irrespective of case.
    """
    if not isinstance(text, str):
        return []
    return [m.group(0).upper() for m in LKN_CODE_REGEX.finditer(text)]


def compute_token_doc_freq(
    leistungskatalog_dict: Dict[str, Dict[str, Any]],
    token_doc_freq: Dict[str, int],
) -> None:
    """Compute document frequency for tokens across the Leistungskatalog."""
    token_doc_freq.clear()
    for details in leistungskatalog_dict.values():
        texts = []
        for base in [
            "Beschreibung",
            "Beschreibung_f",
            "Beschreibung_i",
            "MedizinischeInterpretation",
            "MedizinischeInterpretation_f",
            "MedizinischeInterpretation_i",
        ]:
            val = details.get(base)
            if val:
                texts.append(str(val))
        combined = " ".join(texts)
        tokens = extract_keywords(combined)
        for t in tokens:
            token_doc_freq[t] = token_doc_freq.get(t, 0) + 1


def rank_leistungskatalog_entries(
    tokens: Set[str],
    leistungskatalog_dict: Dict[str, Dict[str, Any]],
    token_doc_freq: Dict[str, int],
    limit: int = 200,
    return_scores: bool = False,
) -> List[str] | List[Tuple[float, str]]:
    """Return LKN codes ranked by weighted token occurrences.

    If ``return_scores`` is ``True`` the result is a list of ``(score, code)``
    tuples, otherwise just the codes are returned.
    """
    scored: List[Tuple[float, str]] = []
    for lkn_code, details in leistungskatalog_dict.items():
        texts = []
        for base in [
            "Beschreibung",
            "Beschreibung_f",
            "Beschreibung_i",
            "MedizinischeInterpretation",
            "MedizinischeInterpretation_f",
            "MedizinischeInterpretation_i",
        ]:
            val = details.get(base)
            if val:
                texts.append(str(val))
        combined = expand_compound_words(" ".join(texts)).lower()
        score = 0.0
        for t in tokens:
            occ = combined.count(t.lower())
            if occ:
                df = token_doc_freq.get(t, len(leistungskatalog_dict))
                if df:
                    score += occ * (1.0 / df)
        if score > 0:
            scored.append((score, lkn_code))
    scored.sort(key=lambda x: x[0], reverse=True)
    if return_scores:
        return scored[:limit]
    return [code for _, code in scored[:limit]]

