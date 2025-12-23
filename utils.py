"""Gemeinsame Hilfsfunktionen, die die Flask-Backend-Komponenten verbinden.

Das Modul liefert HTML-Escaping, sprachabhängige Feldzugriffe, Tabellen-Lookups
für Regelprüfungen, Übersetzungsbausteine fürs Frontend, Tokenstatistiken sowie
Suchhelfer für den RAG-Pfad. Da server, Regelprüfer und Synonym-Tools darauf
zugreifen, sollten Änderungen rückwärtskompatibel bleiben und dokumentiert
werden.
"""

# utils.py
import html
import logging
from contextvars import ContextVar, Token
from typing import (
    Any,
    Dict,
    List,
    Mapping,
    Optional,
    Sequence,
    Set,
    Tuple,
    TYPE_CHECKING,
    TypedDict,
    cast,
)
import re
import unicodedata

logger = logging.getLogger(__name__)

# --- Tabellen-Cache für Request-Lebenszyklen ---------------------------------

TableNameTuple = Tuple[str, ...]
TableContentCacheKey = Tuple[TableNameTuple, str, str]


class _TableCacheEntry(TypedDict):
    source: Mapping[str, Sequence[Dict[str, Any]]]
    data: Dict[TableContentCacheKey, List[Dict[str, Any]]]


TableContentCacheMap = Dict[int, _TableCacheEntry]

_table_content_cache_var: ContextVar[Optional[TableContentCacheMap]] = ContextVar(
    "_table_content_cache",
    default=None,
)


def activate_table_content_cache() -> Optional[Token]:
    """Ensure a fresh table content cache is available for the current context."""
    current = _table_content_cache_var.get()
    if current is not None:
        return None
    cache: TableContentCacheMap = {}
    return _table_content_cache_var.set(cache)


def deactivate_table_content_cache(token: Optional[Token]) -> None:
    """Reset the table content cache for the given activation token."""
    if token is None:
        return
    _table_content_cache_var.reset(token)


def _get_cache_bucket(
    tabellen_dict_by_table: Mapping[str, Sequence[Dict[str, Any]]]
) -> Optional[Dict[TableContentCacheKey, List[Dict[str, Any]]]]:
    cache_map = _table_content_cache_var.get()
    if cache_map is None:
        return None

    dict_id = id(tabellen_dict_by_table)
    entry = cache_map.get(dict_id)
    if entry is None or entry["source"] is not tabellen_dict_by_table:
        cache_data: Dict[TableContentCacheKey, List[Dict[str, Any]]] = {}
        entry = cast(_TableCacheEntry, {
            "source": tabellen_dict_by_table,
            "data": cache_data,
        })
        cache_map[dict_id] = entry

    return entry["data"]


if TYPE_CHECKING:
    import faiss
    import numpy as np

def escape(text: Any) -> str:
    """Maskiert HTML-Sonderzeichen in einem String."""
    return html.escape(str(text))

def get_table_content(
    table_ref: str,
    table_type: str,
    tabellen_dict_by_table: Mapping[str, Sequence[Dict[str, Any]]],
    lang: str = 'de',
) -> List[Dict[str, Any]]:
    """Holt Einträge für eine Tabelle und einen Typ (Case-Insensitive).
    Berücksichtigt die Sprache für den Text."""
    TAB_CODE_KEY = 'Code'; TAB_TEXT_KEY = 'Code_Text'; TAB_TYP_KEY = 'Tabelle_Typ'

    def _normalize_table_type_value(raw_value: Any) -> str:
        if raw_value is None:
            return ''
        value = str(raw_value).strip().lower()
        value = value.replace('-', '').replace('_', '')
        synonyms = {
            '402': 'tariff',
            'tarif': 'tariff',
            'tariff': 'tariff',
            'tarifposition': 'tariff',
            'tarifpositionen': 'tariff',
            'servicecatalog': 'service_catalog',
            'servicekatalog': 'service_catalog',
            'icd': 'icd',
        }
        return synonyms.get(value, value)

    requested_type = _normalize_table_type_value(table_type)
    lang_code = str(lang or 'de').lower()

    raw_table_names = [t.strip() for t in table_ref.split(',') if t.strip()]
    normalized_table_names: TableNameTuple = tuple(name.lower() for name in raw_table_names)

    cache_bucket = _get_cache_bucket(tabellen_dict_by_table)
    cache_key: TableContentCacheKey = (normalized_table_names, requested_type, lang_code)
    if cache_bucket is not None:
        cached_entries = cache_bucket.get(cache_key)
        if cached_entries is not None:
            return cached_entries[:]

    all_entries_for_type: List[Dict[str, Any]] = []
    for name_original, normalized_key in zip(raw_table_names, normalized_table_names):
        if normalized_key in tabellen_dict_by_table:
            for entry in tabellen_dict_by_table[normalized_key]:
                entry_type_normalized = _normalize_table_type_value(entry.get(TAB_TYP_KEY))
                if requested_type and entry_type_normalized and entry_type_normalized != requested_type:
                    continue
                code = entry.get(TAB_CODE_KEY)
                text = get_lang_field(entry, TAB_TEXT_KEY, lang)
                if code:
                    all_entries_for_type.append({"Code": code, "Code_Text": text or "N/A"})
        else:
            logger.info(
                "INFO (get_table_content): Normalisierter Schlüssel '%s' (Original: '%s') nicht in tabellen_dict_by_table gefunden.",
                normalized_key,
                name_original,
            )

    unique_content = {item['Code']: item for item in all_entries_for_type}.values()
    result_list = sorted(unique_content, key=lambda x: x.get('Code', ''))
    if cache_bucket is not None:
        cache_bucket[cache_key] = result_list[:]
    return result_list

def get_lang_field(entry: Dict[str, Any], base_key: str, lang: str) -> Any:
    """Liefert den Wert eines sprachspezifischen Feldes, falls vorhanden."""
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
    'conditions_not_checked': {
        'de': '(Bedingungen nicht geprüft)',
        'fr': '(Conditions non vérifiées)',
        'it': '(Condizioni non verificate)'
    },
    'conditions_also_met': {
        'de': '(Bedingungen auch erfüllt)',
        'fr': '(Conditions aussi remplies)',
        'it': '(Condizioni pure soddisfatte)'
    },
    'prueflogik_header': {
        'de': 'Prüflogik:',
        'fr': 'Logique de vérification :',
        'it': 'Logica di verifica:',
        'en': 'Verification logic:',
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
    'require_medication_list': {
        'de': 'Erfordert Medikamente (ATC) aus Liste: ',
        'fr': 'Medicaments (ATC) requis depuis une liste : ',
        'it': 'Farmaci (ATC) richiesti da una lista: '
    },
    'no_medications_spec': {
        'de': '(Keine Medikamente angegeben)',
        'fr': '(Aucun medicament indique)',
        'it': '(Nessun farmaco indicato)'
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
        'de': 'Patientenbedingung (Geschlecht): Ungueltige Werte fuer Geschlechtspruefung',
        'fr': 'Condition patient (sexe) : valeurs non valides pour le controle du sexe',
        'it': 'Condizione paziente (sesso): valori non validi per il controllo del sesso'
    },
    'rule_patient_medication_missing': {
        'de': 'Patientenbedingung (Medikamente): Erwartet einen von {required}, nicht gefunden',
        'fr': "Condition patient (medicaments) : attendu l'un de {required}, non trouve",
        'it': 'Condizione paziente (farmaci): previsto uno di {required}, non trovato'
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
    'condition_text_medication_list': {
        'de': '{linked_codes}',
        'fr': '{linked_codes}',
        'it': '{linked_codes}'
    },
    'condition_text_lkn_table': {
        'de': '{table_names}',
        'fr': '{table_names}',
        'it': '{table_names}'
    },
    'condition_text_icd_table': {
        'de': '{table_names}',
        'fr': '{table_names}',
        'it': '{table_names}'
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
    'NOT': {
        'de': 'NICHT',
        'fr': 'NON',
        'it': 'NON'
    },
    'AND_NOT': {
        'de': 'UND NICHT',
        'fr': 'ET NON',
        'it': 'E NON'
    },
    'OR_NOT': {
        'de': 'ODER NICHT',
        'fr': 'OU NON',
        'it': 'O NON'
    },
    'logic_variant': {
        'de': 'Variante {index}',
        'fr': 'Variante {index}',
        'it': 'Variante {index}'
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
        (r"^Patientenbedingung \((?:Medikamente|GTIN)\): Erwartet einen von (?P<required>.+), nicht gefunden$", 'rule_patient_medication_missing'),
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
    """Erweitert gängige deutsche Komposita mit Richtungspräfixen.

    So erkennen LLM und Regelwerk Grundbegriffe, die in zusammengesetzten
    Wörtern verborgen sind (z.B. ``Linksherzkatheter`` → ``Links herzkatheter``).
    Die Funktion hängt die zerlegten Varianten an den Originaltext an.
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
    "mann",
    "frau",
    "männlich",
    "weiblich",
    # Unbestimmte Artikel sind semantisch wenig aussagekräftig, führen aber in der
    # Synonymerkennung zu massiven Fehlzuordnungen (z.B. "eines" -> allgemeine
    # Berichtscodes). Daher werden sie bereits bei der Keyword-Erkennung
    # ausgefiltert.
    "eine",
    "einer",
    "eines",
    "einem",
    "einen",
    # Richtungsangaben liefern den LLMs zwar Kontext für die Seitigkeit, sind für
    # die Katalogsuche aber kontraproduktiv, weil sie unzählige Herz-/Gefäss-
    # Prozeduren mit "rechts"/"links" nach vorne spülen.
    "rechts",
    "rechte",
    "rechter",
    "rechten",
    "links",
    "linke",
    "linken",
    "linker",
    "beidseits",
}


def extract_keywords(text: str) -> Set[str]:
    """Liefert relevante Schlüsselwörter aus ``text``.

    Das Eingabewort wird zunächst mit :func:`expand_compound_words` erweitert.
    Anschliessend werden alle Tokens in Kleinschreibung extrahiert und solche mit
    weniger als vier Buchstaben oder in :data:`STOPWORDS` verworfen.
    """

    expanded = expand_compound_words(text)
    tokens = re.findall(r"\b\w+\b", expanded.lower())
    base_tokens = {t for t in tokens if len(t) >= 4 and t not in STOPWORDS}

    return base_tokens



class PatientDemographics(TypedDict, total=False):
    age_value: int | None
    age_operator: str | None
    age_source: str | None
    gender: str | None
    gender_source: str | None


# Patient*innen-Kontext -----------------------------------------------------
_VALID_OPERATORS = {"<", "<=", "=", ">=", ">"}

_FEMALE_TOKENS = {
    "weiblich",
    "frau",
    "patientin",
    "maedchen",
    "madchen",
    "fille",
    "feminin",
    "femminile",
    "femmina",
    "ragazza",
    "donna",
    "female",
    "girl",
}

_MALE_TOKENS = {
    "maennlich",
    "mannlich",
    "mann",
    "patient",
    "junge",
    "knabe",
    "garcon",
    "masculin",
    "maschio",
    "homme",
    "uomo",
    "male",
    "boy",
    "ragazzo",
}

_CHILD_TOKEN_SETS: Tuple[Tuple[Set[str], PatientDemographics], ...] = (
    (
        {"baby", "saeugling", "saeuglinge", "neugeboren", "neonato", "nouveau", "nouveau-ne", "newborn"},
        cast(PatientDemographics, {"age_value": 1, "age_operator": "<=", "age_source": "inferred"}),
    ),
    (
        {"kind", "kinder", "kindern", "kindes", "knabe", "knaben", "maedchen", "madchen", "enfant", "enfants", "bambino", "bambini", "pediatrie", "pediatrisch", "pediatrico", "pediatrica"},
        cast(PatientDemographics, {"age_value": 12, "age_operator": "<=", "age_source": "inferred"}),
    ),
)


def _strip_accents(value: str) -> str:
    return unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")


def extract_patient_demographics(text: str) -> PatientDemographics:
    """Extrahiert Alter- und Geschlechts-Hinweise aus Freitext."""

    result: PatientDemographics = {
        "age_value": None,
        "age_operator": None,
        "age_source": None,
        "gender": None,
        "gender_source": None,
    }
    if not isinstance(text, str) or not text.strip():
        return result

    normalized = _strip_accents(text)
    normalized = normalized.replace("-", " ").replace("/", " ")
    lowered = normalized.lower()
    cleaned = re.sub(r"\s+", " ", lowered)

    best_match: Dict[str, Any] = {"priority": -1, "age_value": None, "age_operator": None, "age_source": None}

    def _update_best(value: int | None, operator: str | None, priority: int, source: str) -> None:
        if value is None:
            return
        if value < 0 or value > 130:
            return
        op = operator if operator in _VALID_OPERATORS else None
        current_priority = best_match["priority"]
        if priority > current_priority:
            best_match.update({"priority": priority, "age_value": value, "age_operator": op, "age_source": source})

    symbol_pattern = re.compile(r"(<=|>=|<|>|=)\s*(\d{1,3})")
    for symbol_match in symbol_pattern.finditer(cleaned):
        value = int(symbol_match.group(2))
        operator = symbol_match.group(1)
        _update_best(value, operator, 3, "text")

    word_patterns = [
        (re.compile(r"\b(?:unter|weniger als|moins de|meno di|piu piccolo di)\s*(\d{1,3})"), "<"),
        (re.compile(r"\b(?:bis|bis zu|maximal|hoechstens|jusqua|jusqu a|jusque a|fino a|al massimo|au plus|au maximum)\s*(\d{1,3})"), "<="),
        (re.compile(r"\b(?:ab|mindestens|minimal|au moins|a partir de|da|desde|minimo)\s*(\d{1,3})"), ">="),
        (re.compile(r"\b(?:ueber|uber|mehr als|plus de|superieur a|piu di|maggiore di)\s*(\d{1,3})"), ">"),
    ]
    for pattern, operator in word_patterns:
        for match in pattern.finditer(cleaned):
            try:
                value = int(match.group(1))
            except ValueError:
                continue
            _update_best(value, operator, 2, "text")

    direct_pattern = re.compile(
        r"\b(\d{1,3})\s*(?:jahre|jahr|jahre alt|jahrig|jaehrig|jaehrige|jaehrigen|anni|anno|anos|ans|an|years?|year old|yo)\b"
    )
    for match in direct_pattern.finditer(cleaned):
        try:
            value = int(match.group(1))
        except ValueError:
            continue
        _update_best(value, "=", 1, "text")

    if best_match["priority"] >= 0:
        result["age_value"] = best_match["age_value"]
        result["age_operator"] = best_match["age_operator"] or "="
        result["age_source"] = best_match["age_source"]
    else:
        tokens = set(cleaned.split())
        for word_set, inferred in _CHILD_TOKEN_SETS:
            if tokens.intersection(word_set):
                if "age_value" in inferred:
                    result["age_value"] = inferred["age_value"]
                if "age_operator" in inferred:
                    result["age_operator"] = inferred["age_operator"]
                if "age_source" in inferred:
                    result["age_source"] = inferred["age_source"]
                if "gender" in inferred:
                    result["gender"] = inferred["gender"]
                if "gender_source" in inferred:
                    result["gender_source"] = inferred["gender_source"]
                break

    gender_detected = False
    for word in _FEMALE_TOKENS:
        if re.search(rf"\b{re.escape(word)}\b", cleaned):
            result["gender"] = "w"
            result["gender_source"] = "text"
            gender_detected = True
            break
    if not gender_detected:
        for word in _MALE_TOKENS:
            if re.search(rf"\b{re.escape(word)}\b", cleaned):
                result["gender"] = "m"
                result["gender_source"] = "text"
                break

    return result


# --- New helper: Extract LKN codes directly from text ---
LKN_CODE_REGEX = re.compile(r"\b[A-Z][A-Z0-9]{1,2}\.[A-Z0-9]{2}\.[0-9]{4}\b", re.IGNORECASE)

def extract_lkn_codes_from_text(text: str) -> List[str]:
    """Liest alle potenziellen LKN-Codes aus ``text`` aus.

    Das Pattern erkennt Einträge wie ``GG.15.0330`` oder ``C08.SA.0700``
    unabhängig von der Schreibweise.
    """
    if not isinstance(text, str):
        return []
    return [m.group(0).upper() for m in LKN_CODE_REGEX.finditer(text)]


def compute_token_doc_freq(
    leistungskatalog_dict: Dict[str, Dict[str, Any]],
    token_doc_freq: Dict[str, int],
) -> None:
    """Berechnet die Dokumenthäufigkeit von Tokens über den Leistungskatalog hinweg."""
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
    *,
    include_medical_interpretation: bool = True,
) -> List[str] | List[Tuple[float, str]]:
    """Return LKN codes ranked by weighted token occurrences.

    If ``return_scores`` is ``True`` the result is a list of ``(score, code)``
    tuples, otherwise just the codes are returned.
    """
    scored: List[Tuple[float, str]] = []
    text_fields = [
        "Beschreibung",
        "Beschreibung_f",
        "Beschreibung_i",
    ]
    if include_medical_interpretation:
        text_fields.extend(
            [
                "MedizinischeInterpretation",
                "MedizinischeInterpretation_f",
                "MedizinischeInterpretation_i",
            ]
        )
    for lkn_code, details in leistungskatalog_dict.items():
        texts = []
        for base in text_fields:
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


def rank_embeddings_entries(
    query_vec: "np.ndarray",
    index: "faiss.Index",
    codes: List[str],
    limit: int = 200,
) -> List[Tuple[float, str]]:
    """Return ``codes`` ranked by cosine similarity to ``query_vec`` using a FAISS index."""
    import numpy as np

    # Sicherstellen, dass der Vektor die richtige Form hat (1, D)
    if query_vec.ndim == 1:
        query_vec = np.expand_dims(query_vec, axis=0)

    # FAISS-Suche
    # ``faiss.Index.search`` akzeptiert optionale Puffer-Argumente für die Ausgabe.
    # Die Pylance-Typstubs markieren sie jedoch als erforderlich, weshalb wir sie
    # explizit mit ``None`` übergeben. Für die Laufzeit hat das keine Auswirkung,
    # da ``None`` der Standardwert ist und FAISS in diesem Fall eigene Puffer
    # allokiert.
    # Cast to ``Any`` because the Pylance stubs still require an ``n`` argument that
    # the Python binding does not expose. We keep passing ``None`` for the optional
    # buffers so FAISS allocates them internally.
    search_fn = cast(Any, index.search)
    query = query_vec.astype(np.float32)
    try:
        distances, indices = search_fn(
            query,
            limit,
            None,
            None,
        )
    except TypeError as exc:
        if "positional arguments" not in str(exc):
            raise
        # Einige FAISS-Builds stellen ``Index.search`` nur mit den Pflichtargumenten bereit.
        # In diesem Fall f�hren wir die Suche ohne optionale Ausgabepuffer erneut aus.
        distances, indices = search_fn(query, limit)

    # Ergebnisse zusammenstellen
    results = []
    for i in range(len(indices[0])):
        idx = indices[0][i]
        if idx != -1:  # -1 bedeutet, dass kein Nachbar gefunden wurde
            score = float(distances[0][i])
            code = codes[idx]
            results.append((score, code))

    return results

TOKEN_REGEX = re.compile(r"\w+|[^\w\s]", re.UNICODE)

def count_tokens(text: str) -> int:
    """Return a naive token count for ``text``."""
    if not text:
        return 0
    return len(TOKEN_REGEX.findall(text))
