// calculator.js - Vollständige Version (06.05.2025)
console.info('calculator.js build 2025-09-23T1245 loaded');
// Arbeitet mit zweistufigem Backend (Mapping-Ansatz). Holt lokale Details zur Anzeige.
// Mit Mouse Spinner & strukturierter Ausgabe

// --- Übersetzungen ---------------------------------------------------------
let translations = {};
function loadTranslations(){
    if(Object.keys(translations).length) return Promise.resolve(translations);
    return fetch('translations.json')
        .then(r=>r.json())
        .then(data=>{
            const base=data.de||{};
            for(const [lang,vals] of Object.entries(data)){
                translations[lang]={...base,...vals};
            }
            return translations;
        });
}
function t(key, lang){
    lang = lang || (typeof currentLang !== 'undefined' ? currentLang : 'de');
    const langMap = translations[lang];
    const defaultMap = translations.de;
    if (langMap && Object.prototype.hasOwnProperty.call(langMap, key) && langMap[key] != null) {
        return langMap[key];
    }
    if (defaultMap && Object.prototype.hasOwnProperty.call(defaultMap, key) && defaultMap[key] != null) {
        return defaultMap[key];
    }
    return key;
}

// ─── 0 · Globale Datencontainer ─────────────────────────────────────────────
let data_leistungskatalog = [];
let data_pauschaleLeistungsposition = [];
let data_pauschalen = [];
let data_pauschaleBedingungen = [];
let data_tardocGesamt = [];
let data_tabellen = [];
let data_interpretationen = {};
let data_dignitaeten = []; // For DIGNITAETEN.json
let interpretationMap = {};
let groupInfoMap = {};
let dignitaetenMap = {}; // For mapping dignity codes to text
let lknPauschaleMap = new Map();
let pauschalenLookup = new Map();
let tableRowsLookup = new Map();
let tableDataCache = new Map();
let tableDisplayNameLookup = new Map();
let tpwData = {};
let tpwState = { scope: 'tardoc', kanton: '', bereich: '', periodIndex: 0, currentValue: '' };
let lastTardocTotalTp = null;
const TPW_STORAGE_KEY = 'tpwSelection';

// Zusätzliche Pauschalen-Infos
let selectedPauschaleDetails = null;
let selectedPauschaleConditionHtml = '';
let evaluatedPauschalenList = [];
let lastBackendResponse = null; // Speichert die letzte Serverantwort für Feedback
let lastUserInput = "";
let pauschaleConditionsContext = null; // Kontext, um Pauschalen-Bedingungen on demand neu zu rendern
let progressTimes = {};
let elapsedTimer = null;
let llm1BarInterval = null;
let currentProgressPercent = 0;
let progressHintTimeouts = [];
// ICD-Filtermodus: 'all' | 'pauschale'
let icdFilterMode = 'all';
// Spiegeln auf window, damit inline-Scripts (index.html) darauf zugreifen können
window.icdFilterMode = icdFilterMode;
window.selectedPauschaleDetails = selectedPauschaleDetails;
window.selectedPauschaleConditionHtml = selectedPauschaleConditionHtml;
let pdfExportInProgress = false;

function getHiddenIcdToggleInput(){
    return document.getElementById('icdToggleState');
}

function loadSavedIcdToggleMode(){
    try {
        const saved = localStorage.getItem('icdToggleState');
        return saved === '1' ? 'pauschale' : 'all';
    } catch (err) {
        console.warn('Unable to read icdToggleState from localStorage:', err);
        return 'all';
    }
}

function persistIcdToggleMode(mode){
    const hidden = getHiddenIcdToggleInput();
    const v = (mode === 'pauschale') ? '1' : '0';
    if (hidden) hidden.value = v;
    try { localStorage.setItem('icdToggleState', v); } catch(_) {}
}

function setIcdFilterMode(mode){
    icdFilterMode = (mode === 'pauschale') ? 'pauschale' : 'all';
    window.icdFilterMode = icdFilterMode;
    const btn = document.getElementById('icdFilterToggle');
    if (btn) {
        btn.textContent = t('icdToggleMatching');
        btn.setAttribute('aria-pressed', icdFilterMode === 'pauschale' ? 'true' : 'false');
    }
    persistIcdToggleMode(icdFilterMode);
    // Nach Umschalten nur aktualisieren, wenn die Liste bereits offen ist
    try { if (typeof window.refreshIcdIfOpen === 'function') window.refreshIcdIfOpen(); } catch(_){}
}

function showIcdToggle(show){
    const btn = document.getElementById('icdFilterToggle');
    if (!btn) return;
    btn.style.display = show ? 'inline-block' : 'none';
    if (show) {
        btn.onclick = () => setIcdFilterMode(icdFilterMode === 'pauschale' ? 'all' : 'pauschale');
        // Bei Anzeige initialen Zustand aus localStorage übernehmen
        const initialMode = loadSavedIcdToggleMode();
        setIcdFilterMode(initialMode);
    }
}

function updateSelectedPauschaleDetails(details, conditionHtml = ''){
    selectedPauschaleDetails = details || null;
    selectedPauschaleConditionHtml = typeof conditionHtml === 'string' ? conditionHtml : '';
    window.selectedPauschaleDetails = selectedPauschaleDetails;
    window.selectedPauschaleConditionHtml = selectedPauschaleConditionHtml;
}

function exportPageAsPdf(){
    if (pdfExportInProgress) {
        return;
    }
    pdfExportInProgress = true;
    const body = document.body;
    const exportButton = document.getElementById('exportPdfButton');
    if (exportButton) {
        exportButton.disabled = true;
    }
    const detailNodes = Array.from(document.querySelectorAll('details'));
    const openStates = detailNodes.map(detail => detail.open);
    detailNodes.forEach(detail => {
        detail.open = true;
    });
    body.classList.add('pdf-export-active');
    let mediaQueryList = null;
    let fallbackTimer = null;
    function cleanup(){
        if (!pdfExportInProgress) {
            return;
        }
        pdfExportInProgress = false;
        if (fallbackTimer) {
            clearTimeout(fallbackTimer);
            fallbackTimer = null;
        }
        detailNodes.forEach((detail, index) => {
            detail.open = !!openStates[index];
        });
        body.classList.remove('pdf-export-active');
        window.removeEventListener('afterprint', handleAfterPrint);
        document.removeEventListener('visibilitychange', handleVisibilityChange);
        if (mediaQueryList) {
            if (typeof mediaQueryList.removeEventListener === 'function') {
                mediaQueryList.removeEventListener('change', handleMediaChange);
            } else if (typeof mediaQueryList.removeListener === 'function') {
                mediaQueryList.removeListener(handleMediaChange);
            }
        }
        if (exportButton) {
            exportButton.disabled = false;
        }
    }
    function handleAfterPrint(){
        cleanup();
    }
    function handleMediaChange(event){
        if (!event.matches) {
            cleanup();
        }
    }
    function handleVisibilityChange(){
        if (typeof document.hidden === 'boolean') {
            if (!document.hidden) {
                cleanup();
            }
        } else {
            cleanup();
        }
    }
    window.addEventListener('afterprint', handleAfterPrint);
    document.addEventListener('visibilitychange', handleVisibilityChange);
    if (typeof window.matchMedia === 'function') {
        try {
            mediaQueryList = window.matchMedia('print');
            if (mediaQueryList) {
                if (typeof mediaQueryList.addEventListener === 'function') {
                    mediaQueryList.addEventListener('change', handleMediaChange);
                } else if (typeof mediaQueryList.addListener === 'function') {
                    mediaQueryList.addListener(handleMediaChange);
                }
            }
        } catch (err) {
            console.debug('PDF export: matchMedia not available', err);
        }
    }
    setTimeout(() => {
        try {
            window.print();
        } catch (err) {
            console.error('PDF export: unable to open print dialog', err);
            cleanup();
        }
    }, 50);
    fallbackTimer = setTimeout(() => {
        cleanup();
    }, 60000);
}
window.exportPageAsPdf = exportPageAsPdf;

// Exporte für index.html Inline-Skript
window.setIcdFilterMode = setIcdFilterMode;
window.showIcdToggle = showIcdToggle;
window.updateSelectedPauschaleDetails = updateSelectedPauschaleDetails;

function stripHtml(input) {
    const tmp = document.createElement('div');
    tmp.innerHTML = input;
    return tmp.textContent || tmp.innerText || '';
}

function logFrontendInteraction(eventType, payload = {}) {
    try {
        const body = JSON.stringify({
            eventType,
            payload,
            timestamp: Date.now()
        });
        const url = '/api/frontend-log';
        console.debug('[frontend-log]', eventType, payload);
        if (typeof fetch === 'function') {
            fetch(url, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body,
                keepalive: true
            }).catch((err) => {
                console.warn('Unable to send frontend log via fetch:', err);
            });
        } else if (typeof navigator !== 'undefined' && typeof navigator.sendBeacon === 'function') {
            const ok = navigator.sendBeacon(url, body);
            if (!ok) {
                console.warn('navigator.sendBeacon returned false for frontend log');
            }
        } else {
            console.debug('No available transport for frontend log.');
        }
    } catch (err) {
        console.warn('Unable to send frontend log:', err);
    }
}


// Dynamische Übersetzungen
const DYN_TEXT = {
    de: {
        spinnerWorking: 'Prüfung läuft...',
        loadingData: 'Lade Tarifdaten...',
        dataLoaded: 'Daten geladen. Bereit zur Prüfung.',
        pleaseEnter: 'Bitte Leistungsbeschreibung eingeben.',
        resultFor: 'Ergebnis für',
        billingPauschale: 'Abrechnung als Pauschale.',
        billingTardoc: 'Abrechnung als TARDOC-Einzelleistung(en).',
        billingError: 'Abrechnung nicht möglich oder Fehler aufgetreten.',
        billingUnknown: 'Unbekannter Abrechnungstyp vom Server.',
        noTardoc: 'Keine TARDOC-Positionen zur Abrechnung übermittelt.',
        errorPauschaleMissing: 'Fehler: Pauschalendetails fehlen.',
        tardocDetails: 'Details TARDOC Abrechnung',
        tardocRule: 'TARDOC-Regel:',
        thLkn: 'LKN', thLeistung: 'Leistung', thAl: 'AL', thIpl: 'IPL',
        thAnzahl: 'Anzahl', thTotal: 'Total TP', thRegeln: 'Regeln/Hinweise',
        none: 'Keine', gesamtTp: 'Gesamt TARDOC TP:',
        llmDetails1: 'Details KI-Analyse (Stufe 1)',
        llmIdent: 'Die von der KI identifizierte(n) LKN(s):',
        llmNoneIdent: 'Keine LKN durch KI identifiziert.',
        llmExtr: 'Vom KI extrahierte Details:',
        llmNoneExtr: 'Keine zusätzlichen Details von der KI extrahiert.',
        llmReason: 'Begründung KI (Stufe 1):',
        llmRankedLkns: 'Weitere mögliche LKN (Ranking):',
        llmDetails2: 'Details KI-Analyse Stufe 2 (TARDOC-zu-Pauschalen-LKN Mapping)',
        mappingIntro: 'Folgende TARDOC LKNs wurden versucht, auf äquivalente Pauschalen-Bedingungs-LKNs zu mappen:',
        ruleDetails: 'Details Regelprüfung',
        ruleNotBill: 'Nicht abrechnungsfähig.',
        ruleHints: 'Hinweise / Anpassungen:',
        ruleOk: 'Regelprüfung OK.',
        ruleNone: 'Kein Regelprüfungsergebnis vorhanden.',
        pauschaleCode: 'Pauschale',
        description: 'Beschreibung',
        taxpoints: 'Taxpunkte',
        pauschaleSummaryTitle: 'Pauschalen-Details',
        reasonPauschale: 'Begründung Pauschalenauswahl',
        pauschaleDetails: 'Details Pauschale',
        condDetails: 'Details Pauschalen-Bedingungsprüfung',
        overallOk: 'Gesamtlogik erfüllt',
        overallNotOk: 'Gesamtlogik NICHT erfüllt',
        logicOk: '(Logik erfüllt)',
        logicNotOk: '(Logik NICHT erfüllt)',
        logicStatusLabel: 'Logikstatus',
        dignitiesNone: 'Keine Dignitäten hinterlegt.',
        implantsNotIncluded: 'Keine Implantate enthalten.',
        errorLkn: 'Fehler: Details für LKN {lkn} nicht gefunden!',
        noData: 'Keine Daten vorhanden.',
        groupNoData: 'Keine Daten zur Leistungsgruppe {code}.',
        potentialIcds: 'Mögliche ICD-Diagnosen',
        thIcdCode: 'ICD Code',
        thIcdText: 'Beschreibung',
        diffTaxpoints: 'Differenz Taxpunkte',
        implantsLabel: 'Implantate',
        implantsIncluded: 'Implantate inbegriffen',
        implantsIncludedHint: 'Implantate sind Bestandteil dieser Pauschale.',
        dignitiesLabel: 'Dignitäten',
        lknInterpretation: 'Medizinische Interpretation',
        lknGroupsTitle: 'Leistungsgruppen',
        lknRulesTitle: 'Regelhinweise',
        lknRelatedPauschalen: 'Weitere Pauschalen mit dieser LKN',
        lknRelatedPauschalenNone: 'Keine weiteren Pauschalen mit dieser LKN gefunden.',
        lknRelatedPauschalenMore: '... und {count} weitere.',
        lknRelatedDirect: 'Direkte Zuordnungen',
        lknRelatedTableRefs: 'Tabellenreferenzen',
        lknPauschaleTableSourceSingle: 'Quelle: Tabelle {table}',
        lknPauschaleTableSourceMulti: 'Quelle: Tabellen {tables}',
        pauschaleRuleLogicTitle: 'Prüflogik',
        logicOperatorAnd: 'UND',
        logicOperatorOr: 'ODER',
        logicOperatorNot: 'NICHT',
        lknTableGroupSummary: 'Tabelle {table} ({count} Pauschalen)',
        lknTableBodyIntro: 'Aus Tabelle {table}:',
        lknTableShowAll: 'Komplette Tabelle anzeigen',
        lknTableNoEntries: 'Keine Pauschalen aus dieser Tabelle gefunden.',
        lknMetaTotalLabel: 'Total (AL + IPL)',
        descriptionNotFound: 'Beschreibung nicht gefunden',
        progressHintPrepare: 'Anfrage an die KI wird vorbereitet',
        progressHintLlm1Processing: 'Anfrage an die KI gestellt und wird verarbeitet',
        progressHintLlm1Review: 'Antwort der KI erhalten; Prüfung läuft',
        progressHintLlm2Processing: 'Vertiefte Analyse läuft',
        progressHintRuleCheck: 'Regellogik wird ausgeführt',
        progressHintFinalizing: 'Ergebnisdarstellung wird aufgebaut',
        progressHintDone: 'Analyse abgeschlossen'
    },
    fr: {
        spinnerWorking: 'Vérification en cours...',
        loadingData: 'Chargement des données tarifaires...',
        dataLoaded: 'Données chargées. Prêt pour l\'analyse.',
        pleaseEnter: 'Veuillez saisir la description de la prestation.',
        resultFor: 'Résultat pour',
        billingPauschale: 'Facturation comme forfait.',
        billingTardoc: 'Facturation comme prestation TARDOC.',
        billingError: 'Facturation impossible ou erreur survenue.',
        billingUnknown: 'Type de facturation inconnu du serveur.',
        noTardoc: 'Aucune position TARDOC à facturer.',
        errorPauschaleMissing: 'Erreur : détails du forfait manquants.',
        tardocDetails: 'Détails facturation TARDOC',
        tardocRule: 'Règle TARDOC :',
        thLkn: 'NPL', thLeistung: 'Prestation', thAl: 'AL', thIpl: 'IPL',
        thAnzahl: 'Quantité', thTotal: 'Total PT', thRegeln: 'Règles/Remarques',
        none: 'Aucun', gesamtTp: 'Total TP TARDOC:',
        llmDetails1: 'Détails analyse IA (Niveau 1)',
        llmIdent: 'NPL identifié(s) par IA :',
        llmNoneIdent: 'Aucun NPL identifié par IA.',
        llmExtr: 'Détails extraits par IA :',
        llmNoneExtr: 'Aucun détail supplémentaire extrait par IA.',
        llmReason: 'Justification IA (Niveau 1) :',
        llmRankedLkns: 'Autres NPL possibles (classement) :',
        llmDetails2: 'Détails analyse IA niveau 2 (mappage TARDOC vers forfaits)',
        mappingIntro: 'Les NPL TARDOC suivants ont été mis en correspondance avec des NPL de conditions de forfait :',
        ruleDetails: 'Détails contrôle des règles',
        ruleNotBill: 'Non facturable.',
        ruleHints: 'Remarques / ajustements :',
        ruleOk: 'Contrôle des règles OK.',
        ruleNone: 'Aucun résultat de contrôle des règles.',
        pauschaleCode: 'Code forfait',
        description: 'Description',
        taxpoints: 'Points',
        pauschaleSummaryTitle: 'Détails du forfait',
        reasonPauschale: 'Justification du choix du forfait',
        pauschaleDetails: 'Détails forfait',
        condDetails: 'Détails vérification des conditions du forfait',
        overallOk: 'Logique globale remplie',
        overallNotOk: 'Logique globale NON remplie',
        logicOk: '(Logique remplie)',
        logicNotOk: '(Logique NON remplie)',
        logicStatusLabel: 'Statut logique',
        dignitiesNone: 'Aucune dignité définie.',
        implantsNotIncluded: 'Aucun implant inclus.',
        errorLkn: 'Erreur : détails pour NPL {lkn} introuvables !',
        noData: 'Aucune donnée disponible.',
        groupNoData: 'Aucune donnée pour le groupe de prestations {code}.',
        potentialIcds: 'Diagnostics ICD possibles',
        thIcdCode: 'Code ICD',
        thIcdText: 'Description',
        diffTaxpoints: 'Différence points tarifaires',
        implantsLabel: 'Implants',
        implantsIncluded: 'Implants inclus',
        implantsIncludedHint: 'Les implants sont inclus dans ce forfait.',
        dignitiesLabel: 'Dignités',
        lknInterpretation: 'Interprétation médicale',
        lknGroupsTitle: 'Groupes de prestations',
        lknRulesTitle: 'Indications des règles',
        lknRelatedPauschalen: 'Autres forfaits contenant ce code',
        lknRelatedPauschalenNone: 'Aucun autre forfait contenant ce code.',
        lknRelatedPauschalenMore: '... et {count} autres.',
        lknRelatedDirect: 'Correspondances directes',
        lknRelatedTableRefs: 'Références de table',
        lknPauschaleTableSourceSingle: 'Source : table {table}',
        lknPauschaleTableSourceMulti: 'Source : tables {tables}',
        pauschaleRuleLogicTitle: 'Logique de vérification',
        logicOperatorAnd: 'ET',
        logicOperatorOr: 'OU',
        logicOperatorNot: 'NON',
        lknTableGroupSummary: 'Table {table} ({count} forfaits)',
        lknTableBodyIntro: 'Depuis la table {table} :',
        lknTableShowAll: 'Afficher la table complète',
        lknTableNoEntries: 'Aucun forfait trouvé dans cette table.',
        lknMetaTotalLabel: 'Total (AL + IPL)',
        descriptionNotFound: 'Description non trouvée',
        progressHintPrepare: 'La requête à l\'IA est en préparation',
        progressHintLlm1Processing: 'Requête envoyée à l\'IA; traitement en cours',
        progressHintLlm1Review: 'Réponse de l\'IA reçue; vérification en cours',
        progressHintLlm2Processing: 'Analyse approfondie en cours',
        progressHintRuleCheck: 'Logique de contrôle en cours d\'exécution',
        progressHintFinalizing: 'Préparation de la présentation du résultat',
        progressHintDone: 'Analyse terminée'
    },
    it: {
        spinnerWorking: 'Verifica in corso...',
        loadingData: 'Caricamento dati tariffari...',
        dataLoaded: 'Dati caricati. Pronto per l\'analisi.',
        pleaseEnter: 'Inserire la descrizione della prestazione.',
        resultFor: 'Risultato per',
        billingPauschale: 'Fatturazione come forfait.',
        billingTardoc: 'Fatturazione come prestazione TARDOC.',
        billingError: 'Fatturazione non possibile o errore.',
        billingUnknown: 'Tipo di fatturazione sconosciuto dal server.',
        noTardoc: 'Nessuna posizione TARDOC da fatturare.',
        errorPauschaleMissing: 'Errore: dettagli forfait mancanti.',
        tardocDetails: 'Dettagli fatturazione TARDOC',
        tardocRule: 'Regola TARDOC:',
        thLkn: 'NPL', thLeistung: 'Prestazione', thAl: 'AL', thIpl: 'IPL',
        thAnzahl: 'Quantità', thTotal: 'Totale PT', thRegeln: 'Regole/Note',
        none: 'Nessuno', gesamtTp: 'Totale TP TARDOC:',
        llmDetails1: 'Dettagli analisi IA (Livello 1)',
        llmIdent: 'NPL identificato/i dal IA:',
        llmNoneIdent: 'Nessun NPL identificato dal IA.',
        llmExtr: 'Dettagli estratti dal IA:',
        llmNoneExtr: 'Nessun dettaglio aggiuntivo estratto dal IA.',
        llmReason: 'Motivazione IA (Livello 1):',
        llmRankedLkns: 'Altri NPL possibili (classifica):',
        llmDetails2: 'Dettagli analisi IA livello 2 (mappatura TARDOC a forfait)',
        mappingIntro: 'I seguenti NPL TARDOC sono stati mappati su NPL di condizioni forfait:',
        ruleDetails: 'Dettagli verifica regole',
        ruleNotBill: 'Non fatturabile.',
        ruleHints: 'Suggerimenti / adattamenti:',
        ruleOk: 'Verifica delle regole OK.',
        ruleNone: 'Nessun risultato di verifica delle regole.',
        pauschaleCode: 'Codice forfait',
        description: 'Descrizione',
        taxpoints: 'Punti',
        pauschaleSummaryTitle: 'Dettagli forfait',
        reasonPauschale: 'Motivazione scelta forfait',
        pauschaleDetails: 'Dettagli forfait',
        condDetails: 'Dettagli verifica condizioni forfait',
        overallOk: 'Logica complessiva soddisfatta',
        overallNotOk: 'Logica complessiva NON soddisfatta',
        logicOk: '(Logica soddisfatta)',
        logicNotOk: '(Logica NON soddisfatta)',
        logicStatusLabel: 'Stato logico',
        dignitiesNone: 'Nessuna dignità definita.',
        implantsNotIncluded: 'Nessun impianto incluso.',
        errorLkn: 'Errore: dettagli per NPL {lkn} non trovati!',
        noData: 'Nessun dato disponibile.',
        groupNoData: 'Nessun dato per il gruppo di prestazioni {code}.',
        potentialIcds: 'Possibili diagnosi ICD',
        thIcdCode: 'Codice ICD',
        thIcdText: 'Descrizione',
        diffTaxpoints: 'Differenza punti tariffari',
        implantsLabel: 'Impianti',
        implantsIncluded: 'Impianti inclusi',
        implantsIncludedHint: 'Gli impianti sono inclusi in questo forfait.',
        dignitiesLabel: 'Dignità',
        lknInterpretation: 'Interpretazione medica',
        lknGroupsTitle: 'Gruppi di prestazioni',
        lknRulesTitle: 'Indicazioni sulle regole',
        lknRelatedPauschalen: 'Altri forfait con questo codice',
        lknRelatedPauschalenNone: 'Nessun altro forfait con questo codice.',
        lknRelatedPauschalenMore: '... e altri {count}.',
        lknRelatedDirect: 'Corrispondenze dirette',
        lknRelatedTableRefs: 'Riferimenti tabella',
        lknPauschaleTableSourceSingle: 'Fonte: tabella {table}',
        lknPauschaleTableSourceMulti: 'Fonte: tabelle {tables}',
        pauschaleRuleLogicTitle: 'Logica di verifica',
        logicOperatorAnd: 'E',
        logicOperatorOr: 'OPPURE',
        logicOperatorNot: 'NON',
        lknTableGroupSummary: 'Tabella {table} ({count} forfait)',
        lknTableBodyIntro: 'Dalla tabella {table}:',
        lknTableShowAll: 'Mostra tabella completa',
        lknTableNoEntries: 'Nessun forfait trovato in questa tabella.',
        lknMetaTotalLabel: 'Totale (AL + IPL)',
        descriptionNotFound: 'Descrizione non trovata',
        progressHintPrepare: 'Richiesta all\'IA in preparazione',
        progressHintLlm1Processing: 'Richiesta inviata all\'IA; elaborazione in corso',
        progressHintLlm1Review: 'Risposta dell\'IA ricevuta; verifica in corso',
        progressHintLlm2Processing: 'Analisi approfondita in corso',
        progressHintRuleCheck: 'Logica di controllo in esecuzione',
        progressHintFinalizing: 'Preparazione della visualizzazione del risultato',
        progressHintDone: 'Analisi completata'
    }
};

const RULE_TRANSLATIONS = {
    fr: {
        'Mengenbeschränkung': 'Limite de quantité',
        'Mögliche Zusatzpositionen': 'Positions supplémentaires possibles',
        'Nicht kumulierbar (E, V) mit': 'Non cumulable (E, V) avec',
        'Nicht kumulierbar (E, L) mit': 'Non cumulable (E, L) avec',
        'Nur als Zuschlag zu': 'Uniquement comme supplément à',
        'Kumulierbar (I, V) mit': 'Cumulable (I, V) avec',
        'Nur kumulierbar (X, L) mit': 'Cumulable uniquement (X, L) avec',
        'Nur kumulierbar (X, V) mit': 'Cumulable uniquement (X, V) avec'
    },
    it: {
        'Mengenbeschränkung': 'Limitazione di quantità',
        'Mögliche Zusatzpositionen': 'Possibili posizioni aggiuntive',
        'Nicht kumulierbar (E, V) mit': 'Non cumulabile (E, V) con',
        'Nicht kumulierbar (E, L) mit': 'Non cumulabile (E, L) con',
        'Nur als Zuschlag zu': 'Solo come supplemento a',
        'Kumulierbar (I, V) mit': 'Cumulabile (I, V) con',
        'Nur kumulierbar (X, L) mit': 'Cumulabile solo (X, L) con',
        'Nur kumulierbar (X, V) mit': 'Cumulabile solo (X, V) con'
    }
};

const ZEITRAUM_TRANSLATIONS = {
    fr: {
        'pro Sitzung': 'par séance',
        'pro Tag': 'par jour',
        'pro 30 Tage': 'tous les 30 jours',
        'pro 60 Tage': 'tous les 60 jours',
        'pro 90 Tage': 'tous les 90 jours',
        'pro 180 Tage': 'tous les 180 jours',
        'pro 360 Tage': 'tous les 360 jours',
        'pro Sitzung pro 120 Tage': 'par séance tous les 120 jours',
        'pro Sitzung pro 180 Tage': 'par séance tous les 180 jours',
        'pro Sitzung pro 360 Tage': 'par séance tous les 360 jours',
        'pro Schwangerschaft': 'par grossesse',
        'pro Kind': 'par enfant',
        'pro Patient': 'par patient',
        'pro Hauptleistung': 'par prestation principale',
        'pro Objektträger': 'par lame',
        'pro Probe': 'par échantillon',
        'pro Seite': 'par côté',
        'pro Region und Seite': 'par région et côté',
        'pro Gelenkregion und Seite': 'par région articulaire et côté',
        'pro Eingriff': 'par intervention',
        'pro Antikörper': 'par anticorps',
        'pro Extremität': 'par membre',
        'pro Extremitätenabschnitt': 'par section de membre',
        'pro Geburt': 'par accouchement',
        'pro Lokalisation und Sitzung': 'par localisation et séance',
        'pro Sitzung pro Schwangerschaft': 'par séance par grossesse'
    },
    it: {
        'pro Sitzung': 'per seduta',
        'pro Tag': 'al giorno',
        'pro 30 Tage': 'ogni 30 giorni',
        'pro 60 Tage': 'ogni 60 giorni',
        'pro 90 Tage': 'ogni 90 giorni',
        'pro 180 Tage': 'ogni 180 giorni',
        'pro 360 Tage': 'ogni 360 giorni',
        'pro Sitzung pro 120 Tage': 'per seduta ogni 120 giorni',
        'pro Sitzung pro 180 Tage': 'per seduta ogni 180 giorni',
        'pro Sitzung pro 360 Tage': 'per seduta ogni 360 giorni',
        'pro Schwangerschaft': 'per gravidanza',
        'pro Kind': 'per bambino',
        'pro Patient': 'per paziente',
        'pro Hauptleistung': 'per prestazione principale',
        'pro Objektträger': 'per vetrino',
        'pro Probe': 'per campione',
        'pro Seite': 'per lato',
        'pro Region und Seite': 'per regione e lato',
        'pro Gelenkregion und Seite': 'per regione articolare e lato',
        'pro Eingriff': 'per intervento',
        'pro Antikörper': 'per anticorpo',
        'pro Extremität': 'per arto',
        'pro Extremitätenabschnitt': 'per sezione di arto',
        'pro Geburt': 'per parto',
        'pro Lokalisation und Sitzung': 'per localizzazione e seduta',
        'pro Sitzung pro Schwangerschaft': 'per seduta per gravidanza'
    }
};

function tDyn(key, params = {}) {
    const lang = (typeof currentLang === 'undefined') ? 'de' : currentLang;
    const template = (DYN_TEXT[lang] && DYN_TEXT[lang][key]) || DYN_TEXT['de'][key] || key;
    return template.replace(/\{(\w+)\}/g, (_, k) => params[k] || '');
}

// Pfade zu den lokalen JSON-Daten
const DATA_PATHS = {
    leistungskatalog: 'data/LKAAT_Leistungskatalog.json',
    pauschaleLP: 'data/PAUSCHALEN_Leistungspositionen.json',
    pauschalen: 'data/PAUSCHALEN_Pauschalen.json',
    pauschaleBedingungen: 'data/PAUSCHALEN_Bedingungen.json',
    tardocGesamt: 'data/TARDOC_Tarifpositionen.json',
    tabellen: 'data/PAUSCHALEN_Tabellen.json',
    interpretationen: 'data/TARDOC_Interpretationen.json',
    dignitaeten: 'data/DIGNITAETEN.json', // Path for the new dignities file
    tpw: '/api/tpw'
};

// ─── 1 · Utility‑Funktionen ────────────────────────────────────────────────
function $(id) { return document.getElementById(id); }

function escapeHtml(s) {
    if (s === null || s === undefined) return "";
    return String(s)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, "&#39;");
}

function sanitizeInlineLink(html) {
    if (typeof document === 'undefined' || !html) {
        return '';
    }
    try {
        const template = document.createElement('template');
        template.innerHTML = String(html).trim();
        const anchor = template.content.querySelector('a');
        if (!anchor) {
            return escapeHtml(html);
        }

        const allowedAttrs = new Set(['href', 'target', 'rel', 'title']);
        Array.from(anchor.attributes).forEach(attr => {
            const name = attr.name.toLowerCase();
            if (!allowedAttrs.has(name)) {
                anchor.removeAttribute(attr.name);
                return;
            }
            if (name === 'href') {
                const hrefVal = anchor.getAttribute('href') || '';
                if (!/^(https?:|mailto:)/i.test(hrefVal)) {
                    anchor.removeAttribute('href');
                }
            }
        });

        if (anchor.hasAttribute('target') && anchor.getAttribute('target').toLowerCase() === '_blank') {
            anchor.setAttribute('rel', 'noopener noreferrer');
        }

        return anchor.outerHTML;
    } catch (err) {
        console.warn('sanitizeInlineLink failed', err);
        return escapeHtml(html);
    }
}

function formatMultiline(text) {
    if (!text) return "";
    const input = String(text);
    const placeholders = [];
    const withTokens = input.replace(/<a\b[^>]*>[\s\S]*?<\/a>/gi, match => {
        const token = `__LINK_PLACEHOLDER_${placeholders.length}__`;
        const safeLink = sanitizeInlineLink(match);
        placeholders.push({ token, html: safeLink });
        return token;
    });

    let escaped = escapeHtml(withTokens);
    placeholders.forEach(({ token, html }) => {
        escaped = escaped.split(token).join(html);
    });

    return escaped
        .replace(/\r\n/g, '\n')
        .replace(/\n{2,}/g, '<br><br>')
        .replace(/\n/g, '<br>');
}

function parseDecimal(value) {
    if (value === null || value === undefined) return 0;
    if (typeof value === 'number') return Number.isFinite(value) ? value : 0;
    const normalized = String(value).replace(',', '.');
    const parsed = parseFloat(normalized);
    return Number.isFinite(parsed) ? parsed : 0;
}

// --- TPW Helper ------------------------------------------------------------
function normalizeTpwPayload(raw) {
    if (raw && typeof raw === 'object' && !Array.isArray(raw)) {
        return (raw.data && typeof raw.data === 'object' && !Array.isArray(raw.data)) ? raw.data : raw;
    }
    return {};
}

function getTpwScope(scopeKey = tpwState.scope) {
    const scope = (tpwData && typeof tpwData === 'object' && tpwData[scopeKey]) ? tpwData[scopeKey] : {};
    const kantone = (scope && typeof scope === 'object') ? (scope.kantone || scope.cantons || {}) : {};
    return { kantone };
}

function listTpwKantone(scopeKey = tpwState.scope) {
    const { kantone } = getTpwScope(scopeKey);
    return Object.keys(kantone || {}).sort();
}

function listTpwBereiche(kanton, scopeKey = tpwState.scope) {
    const { kantone } = getTpwScope(scopeKey);
    const entry = kantone && kantone[kanton];
    if (!entry || typeof entry !== 'object') return [];
    return Object.keys(entry);
}

function getTpwPeriods(scopeKey = tpwState.scope, kanton = tpwState.kanton, bereich = tpwState.bereich) {
    const { kantone } = getTpwScope(scopeKey);
    const entry = kantone && kantone[kanton];
    if (!entry || typeof entry !== 'object') return [];
    const periods = entry[bereich];
    return Array.isArray(periods) ? periods : [];
}

function parseDateSafe(raw) {
    if (!raw || typeof raw !== 'string') return null;
    const trimmed = raw.trim();
    if (!trimmed || trimmed.toUpperCase() === 'YYYY-MM-DD') return null;
    const parsed = new Date(trimmed);
    return Number.isNaN(parsed.getTime()) ? null : parsed;
}

function isPeriodActive(period, refDate = new Date()) {
    if (!period || typeof period !== 'object') return false;
    const from = parseDateSafe(period.gueltig_von);
    const to = parseDateSafe(period.gueltig_bis);
    if (from && refDate < from) return false;
    if (to && refDate > to) return false;
    return true;
}

function pickDefaultPeriodIndex(periods) {
    if (!Array.isArray(periods) || periods.length === 0) return 0;
    const today = new Date();
    const activeIdx = periods.findIndex(p => isPeriodActive(p, today));
    if (activeIdx >= 0) return activeIdx;
    return periods.length - 1;
}

function formatTpwRange(period) {
    if (!period || typeof period !== 'object') return t('tpwNoValue', currentLang);
    const openText = t('tpwOpenEnd', currentLang);
    const from = (period.gueltig_von && period.gueltig_von.toString().trim()) || openText;
    const bisRaw = period.gueltig_bis;
    const to = (bisRaw === null || bisRaw === undefined || bisRaw === '') ? openText : String(bisRaw);
    const base = `${from} – ${to}`;
    return isPeriodActive(period) ? `${base} (${t('tpwCurrent', currentLang)})` : base;
}

function loadStoredTpwSelection() {
    try {
        const raw = localStorage.getItem(TPW_STORAGE_KEY);
        if (!raw) return null;
        const parsed = JSON.parse(raw);
        if (parsed && typeof parsed === 'object') return parsed;
    } catch (err) {
        console.warn('Unable to read stored TPW selection:', err);
    }
    return null;
}

function persistTpwSelection() {
    try {
        const payload = {
            scope: tpwState.scope,
            kanton: tpwState.kanton,
            bereich: tpwState.bereich,
            periodIndex: tpwState.periodIndex
        };
        localStorage.setItem(TPW_STORAGE_KEY, JSON.stringify(payload));
    } catch (err) {
        console.warn('Unable to persist TPW selection:', err);
    }
}

function ensureTpwStateDefaults() {
    let kantone = listTpwKantone(tpwState.scope);
    if (!kantone.length && tpwData && typeof tpwData === 'object') {
        for (const scopeKey of Object.keys(tpwData)) {
            const candidate = listTpwKantone(scopeKey);
            if (candidate.length) {
                tpwState.scope = scopeKey;
                kantone = candidate;
                break;
            }
        }
    }
    if (!tpwState.kanton || !kantone.includes(tpwState.kanton)) {
        tpwState.kanton = kantone[0] || '';
    }
    const bereiche = listTpwBereiche(tpwState.kanton);
    if (!tpwState.bereich || !bereiche.includes(tpwState.bereich)) {
        tpwState.bereich = bereiche[0] || '';
    }
    const periods = getTpwPeriods(tpwState.scope, tpwState.kanton, tpwState.bereich);
    if (!periods.length) {
        tpwState.periodIndex = 0;
    } else if (tpwState.periodIndex >= periods.length || tpwState.periodIndex < 0) {
        tpwState.periodIndex = pickDefaultPeriodIndex(periods);
    }
}

function getSelectedTpwPeriod() {
    const periods = getTpwPeriods();
    if (!Array.isArray(periods) || periods.length === 0) return null;
    const idx = Math.min(Math.max(0, tpwState.periodIndex | 0), periods.length - 1);
    return periods[idx];
}

function getDefaultTpwValueForSelection() {
    const period = getSelectedTpwPeriod();
    if (!period) return '';
    if (period.tpw === null || period.tpw === undefined || period.tpw === '') return '';
    const numeric = typeof period.tpw === 'number' ? period.tpw : parseDecimal(period.tpw);
    return Number.isFinite(numeric) ? String(numeric) : '';
}

function setTpwValueFromSelection() {
    tpwState.currentValue = getDefaultTpwValueForSelection();
    const input = $('tpwValueInput');
    if (input) {
        input.value = tpwState.currentValue || '';
        input.placeholder = t('tpwNoValue', currentLang);
    }
}

function rebuildTpwSelectors() {
    ensureTpwStateDefaults();
    const kantonSelect = $('tpwKantonSelect');
    const bereichSelect = $('tpwBereichSelect');
    const periodSelect = $('tpwPeriodSelect');

    if (kantonSelect) {
        const kantone = listTpwKantone();
        kantonSelect.innerHTML = '';
        kantone.forEach(k => {
            const opt = document.createElement('option');
            opt.value = k;
            opt.textContent = k;
            if (k === tpwState.kanton) opt.selected = true;
            kantonSelect.appendChild(opt);
        });
    }

    if (bereichSelect) {
        const bereiche = listTpwBereiche(tpwState.kanton);
        bereichSelect.innerHTML = '';
        bereiche.forEach(b => {
            const opt = document.createElement('option');
            opt.value = b;
            const labelKey = b.toUpperCase() === 'OKP' ? 'tpwBereichOkp' : (b.toUpperCase() === 'MTK' ? 'tpwBereichMtk' : b);
            const label = t(labelKey, currentLang);
            opt.textContent = label || b;
            if (b === tpwState.bereich) opt.selected = true;
            bereichSelect.appendChild(opt);
        });
    }

    if (periodSelect) {
        const periods = getTpwPeriods();
        periodSelect.innerHTML = '';
        const defaultIdx = pickDefaultPeriodIndex(periods);
        if (tpwState.periodIndex >= periods.length) {
            tpwState.periodIndex = defaultIdx;
        }
        periods.forEach((p, idx) => {
            const opt = document.createElement('option');
            opt.value = String(idx);
            opt.textContent = formatTpwRange(p);
            if (idx === tpwState.periodIndex) opt.selected = true;
            periodSelect.appendChild(opt);
        });
    }
}

function formatChf(amount) {
    if (amount === null || amount === undefined || Number.isNaN(amount)) return '–';
    try {
        const locale = currentLang === 'fr' ? 'fr-CH' : (currentLang === 'it' ? 'it-CH' : 'de-CH');
        return new Intl.NumberFormat(locale, { style: 'currency', currency: 'CHF', minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(amount);
    } catch (err) {
        const fixed = Number.isFinite(amount) ? amount.toFixed(2) : '0.00';
        return `CHF ${fixed}`;
    }
}

function refreshTpwSummary() {
    const totalNode = $('tpwTotalValue');
    const amountNode = $('tpwAmountValue');
    const totalTp = (typeof lastTardocTotalTp === 'number' && Number.isFinite(lastTardocTotalTp)) ? lastTardocTotalTp : null;
    const normalizedTpw = (tpwState.currentValue === null || tpwState.currentValue === undefined) ? '' : String(tpwState.currentValue).trim();
    const tpwValue = normalizedTpw ? Number.parseFloat(normalizedTpw.replace(',', '.')) : NaN;
    const hasTpw = Number.isFinite(tpwValue);

    if (totalNode) {
        if (totalTp !== null) {
            totalNode.textContent = totalTp.toFixed(2);
        } else {
            totalNode.textContent = t('tpwNoTaxpoints', currentLang);
        }
    }

    if (amountNode) {
        if (totalTp !== null && hasTpw) {
            amountNode.textContent = formatChf(totalTp * tpwValue);
        } else if (totalTp !== null) {
            amountNode.textContent = t('tpwNoValue', currentLang);
        } else {
            amountNode.textContent = t('tpwNoTaxpoints', currentLang);
        }
    }
}

function handleTpwSelectionChange(kind, value) {
    if (kind === 'kanton') {
        tpwState.kanton = value;
        tpwState.periodIndex = 0;
    } else if (kind === 'bereich') {
        tpwState.bereich = value;
        tpwState.periodIndex = 0;
    } else if (kind === 'periode') {
        tpwState.periodIndex = parseInt(value, 10) || 0;
    }
    ensureTpwStateDefaults();
    setTpwValueFromSelection();
    rebuildTpwSelectors();
    refreshTpwSummary();
    persistTpwSelection();
}

function initTpwPanelFromData() {
    const stored = loadStoredTpwSelection();
    if (stored) {
        tpwState.scope = stored.scope || tpwState.scope;
        tpwState.kanton = stored.kanton || tpwState.kanton;
        tpwState.bereich = stored.bereich || tpwState.bereich;
        tpwState.periodIndex = stored.periodIndex || 0;
    }
    ensureTpwStateDefaults();
    setTpwValueFromSelection();
    rebuildTpwSelectors();
    refreshTpwSummary();
}

function createInfoLink(code, type) {
    return `<a href="#" class="info-link" data-type="${type}" data-code="${escapeHtml(code)}">${escapeHtml(code)}</a>`;
}

function createPauschaleLink(code) {
    const value = String(code || '').trim();
    if (!value) {
        return `<span class="info-muted">${escapeHtml(tDyn('noData'))}</span>`;
    }
    return `<a href="#" class="pauschale-exp-link info-link" data-code="${escapeHtml(value)}">${escapeHtml(value)}</a>`;
}

function tryParseJSON(raw) {
    if (typeof raw !== 'string') return null;
    const trimmed = raw.trim();
    if (!trimmed) return null;
    try {
        return JSON.parse(trimmed);
    } catch (err) {
        console.debug('Unable to parse JSON content for mapping purposes', err);
        return null;
    }
}

const SINGLE_LKN_REGEX = /^[A-Z0-9]{2,3}\.[A-Z0-9]{2}\.[A-Z0-9]{4}$/;

function resetLknPauschalenMaps() {
    lknPauschaleMap = new Map();
}

function addLeistungspositionRelation(lknCode, pauschaleCode, tableName) {
    const lkn = String(lknCode || '').toUpperCase();
    const pauschale = String(pauschaleCode || '').toUpperCase();
    if (!lkn || !pauschale) return;

    if (!lknPauschaleMap.has(lkn)) {
        lknPauschaleMap.set(lkn, new Map());
    }

    const pauschalenMap = lknPauschaleMap.get(lkn);
    if (!pauschalenMap.has(pauschale)) {
        pauschalenMap.set(pauschale, {
            code: pauschale,
            tables: new Set()
        });
    }

    const tableRaw = String(tableName || '').trim();
    if (tableRaw && tableRaw.toUpperCase() !== lkn) {
        pauschalenMap.get(pauschale).tables.add(tableRaw);
    }
}

function buildLknPauschaleMap() {
    resetLknPauschalenMaps();
    if (Array.isArray(data_pauschaleLeistungsposition)) {
        data_pauschaleLeistungsposition.forEach(entry => {
            if (!entry || !entry.Pauschale || !entry.Leistungsposition) return;
            const rawLeistung = String(entry.Leistungsposition).trim();
            const lknCandidate = rawLeistung.toUpperCase();
            if (!SINGLE_LKN_REGEX.test(lknCandidate)) return;
            const tableName = entry.Tabelle ? String(entry.Tabelle).trim() : '';
            addLeistungspositionRelation(lknCandidate, entry.Pauschale, tableName);
        });
    }
}

function getPauschaleDisplayInfo(code) {
    const norm = String(code || '').toUpperCase();
    if (!norm) return { code: '', text: '' };
    const entry = pauschalenLookup.get(norm);
    if (!entry) {
        return { code: norm, text: '' };
    }
    const text = getLangField(entry, 'Pauschale_Text') || entry.Pauschale_Text || '';
    return { code: norm, text };
}

function getPauschalenForLkn(lknCode) {
    const details = getDetailedRelatedPauschalen(lknCode);
    return details.entries;
}

function getDetailedRelatedPauschalen(lknCode) {
    const norm = String(lknCode || '').toUpperCase();
    const relations = lknPauschaleMap.get(norm);
    if (!relations) {
        return { entries: [], uniqueCount: 0 };
    }

    const entries = Array.from(relations.values()).map(item => {
        const info = getPauschaleDisplayInfo(item.code);
        const tables = Array.from(item.tables || [])
            .map(tbl => {
                const key = String(tbl || '').toUpperCase();
                return tableDisplayNameLookup.get(key) || tbl;
            })
            .filter(Boolean)
            .sort((a, b) => a.localeCompare(b));
        return { ...info, tables };
    }).sort((a, b) => a.code.localeCompare(b.code));

    return { entries, uniqueCount: entries.length };
}

function getTableRows(tableName) {
    const key = String(tableName || '').toUpperCase();
    if (!key) return [];
    return tableRowsLookup.get(key) || [];
}

function getSerializedTableData(tableName) {
    const key = String(tableName || '').toUpperCase();
    if (!key) return '';
    if (!tableDataCache.has(key)) {
        const rows = getTableRows(key);
        tableDataCache.set(key, JSON.stringify(rows || []));
    }
    return tableDataCache.get(key) || '';
}

function buildTableInfoLink(tableKey, displayName) {
    const dataContent = getSerializedTableData(tableKey);
    if (!dataContent) return '';
    return `<a href="#" class="info-link table-link" data-type="lkn_table" data-code="${escapeHtml(displayName || tableKey)}" data-content="${escapeHtml(dataContent)}">${escapeHtml(tDyn('lknTableShowAll'))}</a>`;
}

function renderTableGroup(group) {
    const summaryText = tDyn('lknTableGroupSummary', { table: group.table, count: group.total });
    const introText = tDyn('lknTableBodyIntro', { table: group.table });
    const tableLink = buildTableInfoLink(group.key, group.table);
    const listHtml = renderRelatedPauschalenList((group.pauschalen || []).map(item => ({ ...item, tables: [] })))
        || `<p class="info-muted">${escapeHtml(tDyn('lknTableNoEntries'))}</p>`;
    const introHtml = `<p class="info-muted">${escapeHtml(introText)}${tableLink ? ` · ${tableLink}` : ''}</p>`;
    const openAttr = group.isLarge ? '' : ' open';
    return `<details class="info-table-details"${openAttr}><summary>${escapeHtml(summaryText)}</summary><div class="table-details-body">${introHtml}${listHtml}</div></details>`;
}

function buildTableLookups() {
    tableRowsLookup = new Map();
    tableDataCache = new Map();
    tableDisplayNameLookup = new Map();
    if (!Array.isArray(data_tabellen)) return;
    data_tabellen.forEach(row => {
        if (!row || !row.Tabelle) return;
        const raw = String(row.Tabelle).trim();
        if (!raw) return;
        const key = raw.toUpperCase();
        if (!tableRowsLookup.has(key)) {
            tableRowsLookup.set(key, []);
        }
        tableRowsLookup.get(key).push(row);
        if (!tableDisplayNameLookup.has(key)) {
            tableDisplayNameLookup.set(key, raw);
        }
    });
}

const MODAL_PREF_PREFIX = 'modal-pref:';

function readModalPreferences(modalId) {
    if (!modalId) return null;
    try {
        const raw = localStorage.getItem(`${MODAL_PREF_PREFIX}${modalId}`);
        if (!raw) return null;
        return JSON.parse(raw);
    } catch (err) {
        console.warn('Unable to read modal preferences', modalId, err);
        return null;
    }
}

function writeModalPreferences(modalId, data) {
    if (!modalId) return;
    try {
        localStorage.setItem(`${MODAL_PREF_PREFIX}${modalId}`, JSON.stringify(data));
    } catch (err) {
        console.warn('Unable to persist modal preferences', modalId, err);
    }
}

function applySavedModalState(modalElement) {
    if (!modalElement) return;
    const modalId = modalElement.id;
    const prefs = modalId ? readModalPreferences(modalId) : null;
    const pos = prefs && prefs.position ? prefs.position : { x: 0, y: 0 };
    const parsedX = Number(pos.x);
    const parsedY = Number(pos.y);
    const x = Number.isFinite(parsedX) ? parsedX : 0;
    const y = Number.isFinite(parsedY) ? parsedY : 0;
    modalElement.style.transform = `translate(${x}px, ${y}px)`;
    const clamped = clampModalToViewport(modalElement);
    if (clamped && modalElement.id) {
        persistModalPosition(modalElement, clamped.x, clamped.y);
    }
}

function persistModalPosition(modalElement, x, y) {
    if (!modalElement || !modalElement.id) return;
    const prefs = readModalPreferences(modalElement.id) || {};
    const parsedX = Number(x);
    const parsedY = Number(y);
    prefs.position = {
        x: Number.isFinite(parsedX) ? parsedX : 0,
        y: Number.isFinite(parsedY) ? parsedY : 0
    };
    writeModalPreferences(modalElement.id, prefs);
}

function clampModalToViewport(modalElement, margin = 16) {
    if (!modalElement || typeof window === 'undefined') return null;
    const viewportWidth = window.innerWidth || (document.documentElement && document.documentElement.clientWidth) || 0;
    const viewportHeight = window.innerHeight || (document.documentElement && document.documentElement.clientHeight) || 0;
    if (!viewportWidth || !viewportHeight) return null;
    const rect = modalElement.getBoundingClientRect();
    if (!rect || (!rect.width && !rect.height)) return null;

    let deltaX = 0;
    let deltaY = 0;
    if (rect.left < margin) {
        deltaX = margin - rect.left;
    } else if (rect.right > viewportWidth - margin) {
        deltaX = -(rect.right - (viewportWidth - margin));
    }
    if (rect.top < margin) {
        deltaY = margin - rect.top;
    } else if (rect.bottom > viewportHeight - margin) {
        deltaY = -(rect.bottom - (viewportHeight - margin));
    }
    if (!deltaX && !deltaY) return null;

    const style = window.getComputedStyle(modalElement);
    const matrix = new DOMMatrix(style.transform && style.transform !== 'none' ? style.transform : undefined);
    const newX = matrix.m41 + deltaX;
    const newY = matrix.m42 + deltaY;
    modalElement.style.transform = `translate(${newX}px, ${newY}px)`;
    return { x: newX, y: newY };
}

const NESTED_MODAL_OVERLAY_ID = 'infoModalNestedOverlay';
const NESTED_MODAL_CONTENT_ID = 'infoModalNestedContent';
const NESTED_MODAL_BACK_BUTTON_ID = 'infoModalNestedBack';
const NESTED_MODAL_HISTORY_LIMIT = 25;
const nestedModalHistory = [];

function updateNestedBackButton() {
    const backButton = document.getElementById(NESTED_MODAL_BACK_BUTTON_ID);
    if (!backButton) return;
    const hasHistory = nestedModalHistory.length > 0;
    backButton.style.visibility = hasHistory ? 'visible' : 'hidden';
    backButton.style.pointerEvents = hasHistory ? 'auto' : 'none';
    backButton.tabIndex = hasHistory ? 0 : -1;
    backButton.setAttribute('aria-hidden', hasHistory ? 'false' : 'true');
    if (!hasHistory && document.activeElement === backButton) {
        backButton.blur();
    }
}

function clearNestedModalHistory() {
    nestedModalHistory.length = 0;
    updateNestedBackButton();
}

function pushNestedModalHistory(state) {
    if (!state || typeof state.html !== 'string') return;
    nestedModalHistory.push(state);
    if (nestedModalHistory.length > NESTED_MODAL_HISTORY_LIMIT) {
        nestedModalHistory.shift();
    }
    updateNestedBackButton();
}

function popNestedModalHistory() {
    const state = nestedModalHistory.pop();
    updateNestedBackButton();
    return state;
}

function showModal(modalOverlayId, htmlContent) {
    logFrontendInteraction('modal-open-attempt', { modalOverlayId });
    const modalOverlay = $(modalOverlayId);
    if (!modalOverlay) {
        const message = `Modal overlay with ID ${modalOverlayId} not found.`;
        console.error(message);
        logFrontendInteraction('modal-open-failed', { modalOverlayId, reason: 'overlay-not-found' });
        if (typeof window !== 'undefined' && typeof window.alert === 'function') {
            window.alert(stripHtml(htmlContent) || 'Information nicht verfuegbar.');
        }
        return;
    }
    const contentDiv = modalOverlay.querySelector('.info-modal > div[id$="Content"]');
    if (!contentDiv) {
        const message = `Content div not found within ${modalOverlayId}.`;
        console.error(message);
        logFrontendInteraction('modal-open-failed', { modalOverlayId, reason: 'content-not-found' });
        if (typeof window !== 'undefined' && typeof window.alert === 'function') {
            window.alert(stripHtml(htmlContent) || 'Information nicht verfuegbar.');
        }
        return;
    }

    const isNestedModal = modalOverlayId === NESTED_MODAL_OVERLAY_ID;
    const overlayWasVisible = window.getComputedStyle(modalOverlay).display !== 'none';

    if (isNestedModal) {
        if (overlayWasVisible) {
            const previousState = {
                html: contentDiv.innerHTML,
                scrollTop: contentDiv.scrollTop || 0
            };
            pushNestedModalHistory(previousState);
            logFrontendInteraction('modal-history-push', {
                modalOverlayId,
                historyLength: nestedModalHistory.length
            });
        } else {
            clearNestedModalHistory();
        }
    }

    contentDiv.innerHTML = htmlContent;
    if (isNestedModal) {
        contentDiv.scrollTop = 0;
    }
    modalOverlay.style.display = 'block';
    console.debug('[modal] opened', modalOverlayId);
    logFrontendInteraction('modal-open-success', { modalOverlayId });

    const modalDialog = modalOverlay.querySelector('.info-modal');
    if (modalDialog) {
        applySavedModalState(modalDialog);
        if (!modalDialog.classList.contains('draggable-initialized')) {
            makeModalDraggable(modalDialog);
            modalDialog.classList.add('draggable-initialized');
        }
    }

    if (isNestedModal) {
        updateNestedBackButton();
    }
}

function showInfoModal(htmlContent, overlayId = 'infoModalDetailOverlay') {
    showModal(overlayId, htmlContent);
}

function hideModal(modalOverlayId) {
    const modalOverlay = $(modalOverlayId);
    if (modalOverlay) {
        modalOverlay.style.display = 'none';
        if (modalOverlayId === NESTED_MODAL_OVERLAY_ID) {
            clearNestedModalHistory();
        }
    }
}

// Globale Variable zur Verfolgung des Resize-Zustands
let isResizing = false;
const MODAL_RESIZE_HANDLE_CONFIG = [
    { name: 'top', classNames: ['modal-resize-top'] },
    { name: 'right', classNames: ['modal-resize-right'] },
    { name: 'bottom', classNames: ['modal-resize-bottom'] },
    { name: 'left', classNames: ['modal-resize-left'] },
    { name: 'top-left', classNames: ['modal-resize-corner', 'modal-resize-top-left'] },
    { name: 'top-right', classNames: ['modal-resize-corner', 'modal-resize-top-right'] },
    { name: 'bottom-left', classNames: ['modal-resize-corner', 'modal-resize-bottom-left'] },
    { name: 'bottom-right', classNames: ['modal-resize-corner', 'modal-resize-bottom-right'] }
];
const MODAL_RESIZE_CURSOR_MAP = {
    top: 'ns-resize',
    right: 'ew-resize',
    bottom: 'ns-resize',
    left: 'ew-resize',
    'top-left': 'nwse-resize',
    'top-right': 'nesw-resize',
    'bottom-left': 'nesw-resize',
    'bottom-right': 'nwse-resize'
};

function ensureModalResizeHandles(modalElement) {
    if (!modalElement || modalElement.classList.contains('modal-resize-ready')) return;
    MODAL_RESIZE_HANDLE_CONFIG.forEach(cfg => {
        const handle = document.createElement('div');
        handle.classList.add('modal-resize-handle', ...cfg.classNames);
        handle.dataset.handle = cfg.name;
        handle.setAttribute('role', 'presentation');
        modalElement.appendChild(handle);
    });
    modalElement.classList.add('modal-resize-ready');
}

function isModalInteractiveElement(node) {
    if (!node) return false;
    return Boolean(node.closest('button, a, input, select, textarea, summary, [contenteditable=\"true\"], [data-modal-no-drag=\"true\"]'));
}

function makeModalDraggable(modalElement) {
    if (!modalElement) return;
    ensureModalResizeHandles(modalElement);
    const handle = modalElement.querySelector('.modal-header') || modalElement;
    const MIN_WIDTH = 320;
    const MIN_HEIGHT = 240;
    let isDragging = false;
    let startX = 0;
    let startY = 0;
    let x = 0;
    let y = 0;
    let lastKnownX = 0;
    let lastKnownY = 0;
    let activePointerId = null;
    let resizeState = null;
    let bodyCursorBackup = null;

    function getCurrentTransform() {
        const style = window.getComputedStyle(modalElement);
        const matrix = new DOMMatrix(style.transform && style.transform !== 'none' ? style.transform : undefined);
        x = matrix.m41;
        y = matrix.m42;
        lastKnownX = x;
        lastKnownY = y;
    }

    function ensurePixelDimensions() {
        const rect = modalElement.getBoundingClientRect();
        modalElement.style.width = `${rect.width}px`;
        modalElement.style.height = `${rect.height}px`;
    }

    function setModalTransform(newX, newY) {
        lastKnownX = newX;
        lastKnownY = newY;
        modalElement.style.transform = `translate(${newX}px, ${newY}px)`;
    }

    function startDragging(e) {
        if (isModalInteractiveElement(e.target)) return;
        isDragging = true;
        activePointerId = e.pointerId;
        getCurrentTransform();
        startX = e.clientX;
        startY = e.clientY;
        handle.style.cursor = 'grabbing';
        modalElement.setPointerCapture(e.pointerId);
        e.preventDefault();
    }

    function startResizing(handleName, e) {
        isResizing = true;
        getCurrentTransform();
        const rect = modalElement.getBoundingClientRect();
        resizeState = {
            handle: handleName,
            startX: e.clientX,
            startY: e.clientY,
            startWidth: rect.width,
            startHeight: rect.height,
            startXOffset: lastKnownX,
            startYOffset: lastKnownY
        };
        activePointerId = e.pointerId;
        ensurePixelDimensions();
        modalElement.setPointerCapture(e.pointerId);
        applyResizeCursor(handleName);
        e.preventDefault();
    }

    function applyResizeCursor(handleName) {
        const cursor = MODAL_RESIZE_CURSOR_MAP[handleName];
        if (!cursor) return;
        if (document && document.body) {
            if (bodyCursorBackup === null) {
                bodyCursorBackup = document.body.style.cursor || '';
            }
            document.body.style.cursor = cursor;
        }
        modalElement.style.cursor = cursor;
    }

    function clearResizeCursor() {
        if (document && document.body && bodyCursorBackup !== null) {
            document.body.style.cursor = bodyCursorBackup;
        }
        modalElement.style.cursor = '';
        bodyCursorBackup = null;
    }

    function handlePointerDown(e) {
        if (e.button !== undefined && e.button !== 0) return;
        const resizeHandle = e.target.closest('.modal-resize-handle');
        if (resizeHandle) {
            if (!resizeHandle.dataset.handle || activePointerId !== null) return;
            startResizing(resizeHandle.dataset.handle, e);
            return;
        }
        if (!handle.contains(e.target)) return;
        if (activePointerId !== null) return;
        startDragging(e);
    }

    function updateDrag(e) {
        const dx = e.clientX - startX;
        const dy = e.clientY - startY;
        setModalTransform(x + dx, y + dy);
    }

    function updateResize(e) {
        if (!resizeState) return;
        const handlesHorizontal = resizeState.handle.includes('left') || resizeState.handle.includes('right');
        const handlesVertical = resizeState.handle.includes('top') || resizeState.handle.includes('bottom');
        const dx = handlesHorizontal ? (e.clientX - resizeState.startX) : 0;
        const dy = handlesVertical ? (e.clientY - resizeState.startY) : 0;
        let newWidth = resizeState.startWidth;
        let newHeight = resizeState.startHeight;
        let newX = resizeState.startXOffset;
        let newY = resizeState.startYOffset;

        if (resizeState.handle.includes('right')) {
            newWidth = Math.max(MIN_WIDTH, resizeState.startWidth + dx);
        }
        if (resizeState.handle.includes('left')) {
            const rawWidth = resizeState.startWidth - dx;
            const clampedWidth = Math.max(MIN_WIDTH, rawWidth);
            const appliedDelta = resizeState.startWidth - clampedWidth;
            newWidth = clampedWidth;
            newX = resizeState.startXOffset + appliedDelta;
        }
        if (resizeState.handle.includes('bottom')) {
            newHeight = Math.max(MIN_HEIGHT, resizeState.startHeight + dy);
        }
        if (resizeState.handle.includes('top')) {
            const rawHeight = resizeState.startHeight - dy;
            const clampedHeight = Math.max(MIN_HEIGHT, rawHeight);
            const appliedDelta = resizeState.startHeight - clampedHeight;
            newHeight = clampedHeight;
            newY = resizeState.startYOffset + appliedDelta;
        }

        modalElement.style.width = `${Math.round(newWidth)}px`;
        modalElement.style.height = `${Math.round(newHeight)}px`;
        setModalTransform(newX, newY);
    }

    function stopInteractions() {
        if (activePointerId !== null && typeof modalElement.releasePointerCapture === 'function') {
            try {
                modalElement.releasePointerCapture(activePointerId);
            } catch (err) {
                // ignore release errors
            }
        }
        activePointerId = null;
        const clamped = clampModalToViewport(modalElement);
        if (clamped) {
            x = clamped.x;
            y = clamped.y;
            lastKnownX = clamped.x;
            lastKnownY = clamped.y;
        }
        if (isDragging || resizeState) {
            persistModalPosition(modalElement, lastKnownX, lastKnownY);
        }
        isDragging = false;
        resizeState = null;
        handle.style.cursor = 'grab';
        if (isResizing) {
            isResizing = false;
        }
        clearResizeCursor();
    }

    function onPointerMove(e) {
        if (activePointerId === null || e.pointerId !== activePointerId) return;
        if (resizeState) {
            updateResize(e);
            return;
        }
        if (isDragging) {
            updateDrag(e);
        }
    }

    function onPointerUp(e) {
        if (activePointerId === null || e.pointerId !== activePointerId) return;
        stopInteractions();
    }

    handle.addEventListener('pointerdown', handlePointerDown);
    modalElement.addEventListener('pointerdown', (e) => {
        if (activePointerId !== null) return;
        const resizeHandle = e.target.closest('.modal-resize-handle');
        if (resizeHandle && resizeHandle.dataset.handle) {
            startResizing(resizeHandle.dataset.handle, e);
        }
    });
    modalElement.addEventListener('pointermove', onPointerMove);
    modalElement.addEventListener('pointerup', onPointerUp);
    modalElement.addEventListener('pointercancel', onPointerUp);
    handle.style.cursor = 'grab';
}

function isMedicationTableEntry(entry) {
    if (!entry || entry.Tabelle_Typ === undefined || entry.Tabelle_Typ === null) return false;
    return String(entry.Tabelle_Typ).trim() === '402';
}

function getMedicationEntriesByTable(tableName) {
    if (!Array.isArray(data_tabellen)) return [];
    const key = String(tableName || '').trim().toUpperCase();
    if (!key) return [];
    return data_tabellen.filter(item =>
        isMedicationTableEntry(item) &&
        item.Tabelle &&
        String(item.Tabelle).trim().toUpperCase() === key
    );
}

function findMedicationEntryByCode(code) {
    if (!Array.isArray(data_tabellen)) return null;
    const normCode = String(code || '').trim().toUpperCase();
    if (!normCode) return null;
    return data_tabellen.find(item =>
        isMedicationTableEntry(item) &&
        item.Code !== undefined &&
        item.Code !== null &&
        String(item.Code).trim().toUpperCase() === normCode
    ) || null;
}

function renderMedicationInfoSections(entries, tableName) {
    if (!Array.isArray(entries) || entries.length === 0) return '';
    const noDataLabel = tDyn('noData');
    const descriptionLabel = tDyn('description');
    return entries.map(entry => {
        const atcCode = entry && entry.Code !== undefined && entry.Code !== null ? String(entry.Code).trim() : '';
        const description = getLangField(entry, 'Code_Text') || getLangField(entry, 'Beschreibung') || '';
        const tableValue = entry && entry.Tabelle ? String(entry.Tabelle).trim() : (tableName ? String(tableName).trim() : '');
        const heading = description || atcCode || 'Medikament';
        let html = `<section class="info-section"><h3>${escapeHtml(heading)}</h3>`;
        html += `<p><strong>ATC-Code:</strong> ${escapeHtml(atcCode || noDataLabel)}</p>`;
        html += `<p><strong>${escapeHtml(descriptionLabel)}</strong>: ${escapeHtml(description || noDataLabel)}</p>`;
        if (tableValue) {
            html += `<p><strong>Tabelle:</strong> ${escapeHtml(tableValue)}</p>`;
        }
        html += '</section>';
        return html;
    }).join('');
}

function buildMedicationInfoHtmlFromTable(tableName) {
    const entries = getMedicationEntriesByTable(tableName);
    if (!entries.length) return `<p>${tDyn('noData')}</p>`;
    return renderMedicationInfoSections(entries, tableName);
}

function buildMedicationInfoHtmlFromCode(code, tableName) {
    const entry = findMedicationEntryByCode(code);
    if (entry) {
        return renderMedicationInfoSections([entry], entry.Tabelle || tableName);
    }
    const fallbackEntries = getMedicationEntriesByTable(tableName || code);
    if (fallbackEntries.length) {
        return renderMedicationInfoSections(fallbackEntries, tableName || code);
    }
    return `<p>${tDyn('noData')}</p>`;
}

function buildDiagnosisInfoHtmlFromCode(code) {
    const normCode = String(code || '').trim().toUpperCase();
    let description = '';
    let found = false;

    // Attempt to find description in data_tabellen (assuming some tables might be ICD catalogs)
    // This is a simplified search. A dedicated ICD data structure would be better.
    if (Array.isArray(data_tabellen)) {
        const entry = data_tabellen.find(item =>
            item && typeof item.Code === 'string' &&
            item.Code.toUpperCase() === normCode &&
            item.Tabelle_Typ === 'icd'
        );
        if (entry) {
            description = getLangField(entry, 'Code_Text') || getLangField(entry, 'Beschreibung');
            if (description) found = true;
        }
    }

    if (!found) {
        // Fallback: try to find in data_leistungskatalog if it happens to have ICDs (less likely structured this way)
        // This part is less likely to yield results for pure ICD codes but included for broader search
        const catEntry = findCatalogEntry(normCode); // findCatalogEntry searches data_leistungskatalog
        if (catEntry && (catEntry.KapitelNummer === normCode || catEntry.LKN === normCode)) { // Heuristic: check if it's a chapter or LKN that might be an ICD
            description = getLangField(catEntry, 'Beschreibung');
             if (description) found = true;
        }
    }

    let html = `<h3>${tDyn('thIcdCode')}: ${escapeHtml(normCode)}</h3>`;
    if (description) {
        html += `<p><b>${tDyn('description')}</b>: ${escapeHtml(description)}</p>`;
    } else {
        html += `<p><i>${tDyn('descriptionNotFound')}</i></p>`;
    }
    // Potential further details: "Part of table X", "Related LKNs", etc. - requires more complex data linking.
    return html;
}

function getLangSuffix() {
    if (typeof currentLang === 'undefined') return '';
    if (currentLang === 'fr') return '_f';
    if (currentLang === 'it') return '_i';
    return '';
}

function getLangField(obj, baseKey) {
    if (!obj) return undefined;
    const suffix = getLangSuffix();
    return obj[baseKey + suffix] || obj[baseKey];
}

function translateZeitraum(value, lang) {
    if (!value) return '';
    const dict = ZEITRAUM_TRANSLATIONS[lang] || {};
    if (dict[value]) return dict[value];

    let m = value.match(/^pro (\d+) Tage$/);
    if (m) {
        const n = m[1];
        if (lang === 'fr') return `tous les ${n} jours`;
        if (lang === 'it') return `ogni ${n} giorni`;
    }
    m = value.match(/^pro (\d+) Sitzungen$/);
    if (m) {
        const n = m[1];
        if (lang === 'fr') return `toutes les ${n} séances`;
        if (lang === 'it') return `ogni ${n} sedute`;
    }
    m = value.match(/^pro Sitzung pro (\d+) Tage$/);
    if (m) {
        const n = m[1];
        if (lang === 'fr') return `par séance tous les ${n} jours`;
        if (lang === 'it') return `per seduta ogni ${n} giorni`;
    }
    return value;
}


function beschreibungZuLKN(lkn) {
    // Stellt sicher, dass data_leistungskatalog geladen ist und ein Array ist
    if (!Array.isArray(data_leistungskatalog) || data_leistungskatalog.length === 0 || typeof lkn !== 'string') {
        // console.warn(`beschreibungZuLKN: Daten nicht bereit oder ungültige LKN für ${lkn}`);
        return lkn; // Gibt LKN zurück, wenn keine Beschreibung gefunden wird
    }
    // Case-insensitive Suche
    const hit = data_leistungskatalog.find(e => e.LKN?.toUpperCase() === lkn.toUpperCase());
    // Gibt Beschreibung zurück oder LKN selbst, wenn keine Beschreibung vorhanden ist
    return hit ? (getLangField(hit, 'Beschreibung') || lkn) : lkn;
}

function findTardocPosition(lkn) {
    if (!Array.isArray(data_tardocGesamt)) return null;
    if (typeof lkn !== 'string') return null;
    const code = lkn.trim().toUpperCase();
    return data_tardocGesamt.find(item => item && item.LKN && String(item.LKN).toUpperCase() === code);
}

function findCatalogEntry(lkn) {
    if (!Array.isArray(data_leistungskatalog)) return null;
    if (typeof lkn !== 'string') return null;
    const code = lkn.trim().toUpperCase();
    return data_leistungskatalog.find(item => item && item.LKN && String(item.LKN).toUpperCase() === code);
}

function formatRules(ruleData) {
    if (!ruleData) return '';
    if (!Array.isArray(ruleData)) {
        return typeof ruleData === 'string' ? escapeHtml(ruleData) : JSON.stringify(ruleData);
    }
    const lang = (typeof currentLang === 'undefined') ? 'de' : currentLang;
    const parts = ruleData.map(rule => {
        const translatedType = (RULE_TRANSLATIONS[lang] && RULE_TRANSLATIONS[lang][rule.Typ]) || rule.Typ || '';
        let txt = escapeHtml(translatedType);
        if (rule.MaxMenge !== undefined) {
            txt += ` max. ${rule.MaxMenge}`;
            if (rule.Zeitraum) {
                const zt = translateZeitraum(rule.Zeitraum, lang);
                txt += ` ${escapeHtml(zt)}`;
            }
        }
        const items = [];
        if (rule.LKN) items.push(createInfoLink(rule.LKN, 'lkn'));
        if (Array.isArray(rule.LKNs)) {
            rule.LKNs.forEach(item => {
                if (typeof item !== 'string') return;
                if (item.startsWith('Kapitel ')) {
                    const code = item.replace('Kapitel ', '').trim();
                    items.push('Kapitel ' + createInfoLink(code, 'chapter'));
                } else if (item.startsWith('Leistungsgruppe ')) {
                    const code = item.replace('Leistungsgruppe ', '').trim();
                    items.push('Leistungsgruppe ' + createInfoLink(code, 'group'));
                } else {
                    items.push(createInfoLink(item, 'lkn'));
                }
            });
        }
        if (rule.Gruppe) items.push(createInfoLink(rule.Gruppe, 'group'));
        if (items.length > 0) txt += ' ' + items.join(', ');
        if (rule.Hinweis) txt += ` ${escapeHtml(rule.Hinweis)}`;
        return txt.trim();
    });
    return parts.join('; ');
}

function renderMetaItem({ label, value, valueHtml }) {
    if (!label && !value && !valueHtml) return '';
    const safeLabel = escapeHtml(label || '');
    const safeValue = valueHtml !== undefined ? valueHtml : escapeHtml(value || '');
    return `<div class="info-meta-item"><span class="info-meta-label">${safeLabel}</span><span class="info-meta-value">${safeValue}</span></div>`;
}

function renderLknHeaderSection(lkn, description, metaItems = []) {
    const safeMeta = Array.isArray(metaItems) ? metaItems.filter(item => item && (item.label || item.value)) : [];
    const metaHtml = safeMeta.length > 0
        ? `<div class="info-meta-grid">${safeMeta.map(renderMetaItem).join('')}</div>`
        : '';
    return `
        <section class="info-section info-section-head">
            <div class="info-headline">
                <h2>${escapeHtml(lkn)}</h2>
                ${description ? `<p class="info-subtitle">${escapeHtml(description)}</p>` : ''}
            </div>
            ${metaHtml}
        </section>
    `;
}

function renderInterpretationSection(text) {
    if (!text) return '';
    return `<section class="info-section"><h3>${tDyn('lknInterpretation')}</h3><p>${formatMultiline(text)}</p></section>`;
}

function renderRelatedPauschalenList(entries) {
    if (!Array.isArray(entries) || entries.length === 0) return '';
    const items = entries.map(entry => {
        const codeHtml = `<a href="#" class="tag-code info-link" data-type="pauschale" data-code="${escapeHtml(entry.code)}">${escapeHtml(entry.code)}</a>`;
        const textHtml = entry.text ? `<span class="tag-text">${escapeHtml(entry.text)}</span>` : '';
        let tableHtml = '';
        if (Array.isArray(entry.tables) && entry.tables.length > 0) {
            const labelKey = entry.tables.length === 1 ? 'lknPauschaleTableSourceSingle' : 'lknPauschaleTableSourceMulti';
            const label = tDyn(labelKey, {
                table: entry.tables[0],
                tables: entry.tables.join(', ')
            });
            tableHtml = `<span class="info-muted">${escapeHtml(label)}</span>`;
        }
        return `<li>${codeHtml}${textHtml ? ` · ${textHtml}` : ''}${tableHtml ? `${tableHtml}` : ''}</li>`;
    }).join('');
    return `<ul class="tag-list">${items}</ul>`;
}

function buildRelatedPauschalenSection(lkn) {
    const details = getDetailedRelatedPauschalen(lkn);
    const heading = `${tDyn('lknRelatedPauschalen')} (${details.uniqueCount})`;
    if (details.uniqueCount === 0) {
        return `<section class="info-section"><h3>${escapeHtml(heading)}</h3><p class="info-muted">${escapeHtml(tDyn('lknRelatedPauschalenNone'))}</p></section>`;
    }

    const listHtml = renderRelatedPauschalenList(details.entries);
    return `<section class="info-section"><h3>${escapeHtml(heading)}</h3>${listHtml}</section>`;
}

function buildLknInfoHtml(pos, options = {}) {
    if (!pos) return `<p>${tDyn('noData')}</p>`;
    const lkn = String(pos.LKN || '');
    const desc = getLangField(pos, 'Bezeichnung') || '';
    const al = parseDecimal(pos['AL_(normiert)']);
    const ipl = parseDecimal(pos['IPL_(normiert)']);
    const { includeRelated = true } = options;
    const metaItems = [
        { label: tDyn('thAl'), value: al.toFixed(2) },
        { label: tDyn('thIpl'), value: ipl.toFixed(2) },
        { label: tDyn('lknMetaTotalLabel'), value: (al + ipl).toFixed(2) }
    ];
    const dignities = Array.isArray(pos.Qualitative_Dignität)
        ? pos.Qualitative_Dignität.map(d => escapeHtml(d.DignitaetText)).join(', ')
        : '';
    let groups = '';
    if (Array.isArray(pos.Leistungsgruppen)) {
        groups = pos.Leistungsgruppen.map(g => `${createInfoLink(g.Gruppe,'group')}: ${escapeHtml(g.Text || '')}`).join('<br>');
    }
    const rules = formatRules(pos.Regeln);
    const interpretation = getInterpretation(lkn, false);

    const sections = [
        renderLknHeaderSection(lkn, desc, metaItems),
        renderInterpretationSection(interpretation),
        dignities ? `<section class="info-section"><h3>${escapeHtml(tDyn('dignitiesLabel'))}</h3><p>${dignities}</p></section>` : '',
        groups ? `<section class="info-section"><h3>${tDyn('lknGroupsTitle')}</h3><p>${groups}</p></section>` : '',
        rules ? `<section class="info-section"><h3>${tDyn('lknRulesTitle')}</h3><p>${rules}</p></section>` : '',
        includeRelated ? buildRelatedPauschalenSection(lkn) : ''
    ];

    return sections.filter(Boolean).join('');
}

function buildLknInfoHtmlFromCode(code) {
    const pos = findTardocPosition(code);
    if (pos) return buildLknInfoHtml(pos, { includeRelated: false });

    const cat = findCatalogEntry(code);
    if (cat) {
        const lkn = String(cat.LKN || code || '');
        const desc = getLangField(cat, 'Beschreibung') || '';
        const interpretation = getLangField(cat, 'MedizinischeInterpretation');
        const sections = [
            renderLknHeaderSection(lkn, desc),
            renderInterpretationSection(interpretation),
            buildRelatedPauschalenSection(lkn)
        ];
        return sections.filter(Boolean).join('');
    }
    const medicationEntries = getMedicationEntriesByTable(code);
    if (medicationEntries.length) {
        return renderMedicationInfoSections(medicationEntries, code);
    }
    return `<p>${tDyn('noData')}</p>`;
}

function normalizePrueflogikExpression(raw) {
    if (!raw) return '';
    return raw
        .replace(/\s+/g, ' ')
        .replace(/\bUND\b/gi, 'AND')
        .replace(/\bODER\b/gi, 'OR')
        .replace(/\bNICHT\b/gi, 'NOT')
        .trim();
}

function stripOuterParensIfBalanced(str) {
    let s = (str || '').trim();
    if (!s) return '';
    let changed = true;
    while (changed && s.startsWith('(') && s.endsWith(')')) {
        changed = false;
        let depth = 0;
        let balanced = true;
        for (let i = 0; i < s.length; i++) {
            const ch = s[i];
            if (ch === '(') {
                depth++;
            } else if (ch === ')') {
                depth--;
                if (depth < 0) {
                    balanced = false;
                    break;
                }
                if (depth === 0 && i < s.length - 1) {
                    balanced = false;
                    break;
                }
            }
        }
        if (balanced && depth === 0) {
            s = s.slice(1, -1).trim();
            changed = true;
        }
    }
    return s;
}

function splitPrueflogikTopLevel(str, operator) {
    const s = (str || '').trim();
    if (!s) return [];
    const parts = [];
    let depth = 0;
    let buffer = '';
    const op = operator;
    const opLen = op.length;

    for (let i = 0; i < s.length; ) {
        const ch = s[i];
        if (ch === '(') {
            depth++;
            buffer += ch;
            i++;
            continue;
        }
        if (ch === ')') {
            depth = Math.max(0, depth - 1);
            buffer += ch;
            i++;
            continue;
        }
        if (depth === 0 && s.slice(i, i + opLen) === op) {
            const before = i === 0 ? '' : s[i - 1];
            const after = i + opLen >= s.length ? '' : s[i + opLen];
            const beforeOk = i === 0 || /[\s()\[\]]/.test(before);
            const afterOk = i + opLen >= s.length || /[\s()\[\]]/.test(after);
            if (beforeOk && afterOk) {
                const trimmed = buffer.trim();
                if (trimmed) parts.push(trimmed);
                buffer = '';
                i += opLen;
                while (i < s.length && s[i] === ' ') i++;
                continue;
            }
        }
        buffer += ch;
        i++;
    }

    const tail = buffer.trim();
    if (tail) parts.push(tail);
    return parts;
}

function parsePrueflogikNode(input) {
    let s = stripOuterParensIfBalanced(input);
    if (!s) return null;

    if (s.startsWith('NOT')) {
        const remainder = s.slice(3).trim();
        if (remainder) {
            const child = parsePrueflogikNode(remainder);
            if (child) {
                return { type: 'NOT', children: [child] };
            }
        }
    }

    const orParts = splitPrueflogikTopLevel(s, 'OR');
    if (orParts.length > 1) {
        const children = orParts.map(parsePrueflogikNode).filter(Boolean);
        if (children.length === 1) return children[0];
        if (children.length > 1) {
            return { type: 'OR', children };
        }
    }

    const andParts = splitPrueflogikTopLevel(s, 'AND');
    if (andParts.length > 1) {
        const children = andParts.map(parsePrueflogikNode).filter(Boolean);
        if (children.length === 1) return children[0];
        if (children.length > 1) {
            return { type: 'AND', children };
        }
    }

    return { type: 'CLAUSE', text: s };
}

function normalizeClauseReferenceItem(rawItem) {
    if (typeof rawItem !== 'string') return '';
    return rawItem
        .replace(/where.+$/i, '')
        .replace(/^['\"]|['\"]$/g, '')
        .trim();
}

function renderClauseReference(keyword, rawItem) {
    const cleaned = normalizeClauseReferenceItem(rawItem);
    if (!cleaned) return '';
    const upper = cleaned.toUpperCase();

    let linkHtml = '';

    if (tableRowsLookup && tableRowsLookup.has(upper)) {
        const displayName = tableDisplayNameLookup.get(upper) || cleaned;
        const dataContent = getSerializedTableData(upper);
        if (dataContent) {
            linkHtml = `<a href="#" class="info-link" data-type="lkn_table" data-code="${escapeHtml(displayName)}" data-content="${escapeHtml(dataContent)}">${escapeHtml(displayName)}</a>`;
        }
    } else if (SINGLE_LKN_REGEX.test(upper)) {
        linkHtml = createInfoLink(cleaned, 'lkn');
    }

    return linkHtml || escapeHtml(cleaned);
}

function renderPrueflogikClauseContent(text) {
    if (!text) return { bodyHtml: '', linksHtml: '' };
    const normalized = text
        .replace(/\bAND\b/g, 'und')
        .replace(/\bOR\b/g, 'oder')
        .replace(/\bNOT\b/g, 'nicht');

    const parts = [];
    const regex = /(Tabelle|Liste)\s*\(([^\)]*)\)/gi;
    let lastIndex = 0;
    let match;

    while ((match = regex.exec(normalized)) !== null) {
        const [fullMatch, keyword, inner] = match;
        const before = normalized.slice(lastIndex, match.index);
        if (before) {
            parts.push(escapeHtml(before));
        }

        const items = inner
            .split(',')
            .map(item => {
                const rendered = renderClauseReference(keyword, item);
                return rendered ? `<span class="logic-chip">${rendered}</span>` : '';
            })
            .filter(Boolean);
        const chipsHtml = items.length > 0 ? `<span class="logic-chip-group">${items.join('')}</span>` : '';
        const keywordHtml = escapeHtml(keyword);
        parts.push(chipsHtml ? `${keywordHtml} ${chipsHtml}` : keywordHtml);
        lastIndex = match.index + fullMatch.length;
    }

    const remainder = normalized.slice(lastIndex);
    if (remainder) {
        parts.push(escapeHtml(remainder));
    }

    return {
        bodyHtml: parts.join(''),
        linksHtml: ''
    };
}

function renderPrueflogikNode(node, isRoot = false) {
    if (!node) return '';
    if (node.type === 'CLAUSE') {
        const { bodyHtml, linksHtml } = renderPrueflogikClauseContent(node.text);
        const clause = `<div class="logic-clause">${bodyHtml}${linksHtml}</div>`;
        return isRoot ? `<div class="logic-root">${clause}</div>` : clause;
    }

    if (node.type === 'NOT') {
        const childHtml = renderPrueflogikNode(node.children && node.children[0]);
        if (!childHtml) return '';
        const block = `
            <div class="logic-node logic-node-not">
                <div class="logic-connector logic-connector-inline">${escapeHtml(tDyn('logicOperatorNot'))}</div>
                <div class="logic-branch">${childHtml}</div>
            </div>
        `;
        return isRoot ? `<div class="logic-root">${block}</div>` : block;
    }

    if (node.type === 'AND' || node.type === 'OR') {
        const labelKey = node.type === 'AND' ? 'logicOperatorAnd' : 'logicOperatorOr';
        const operatorLabel = escapeHtml(tDyn(labelKey));
        const className = node.type === 'AND' ? 'logic-node logic-node-and' : 'logic-node logic-node-or';
        const children = (node.children || []).map(child => renderPrueflogikNode(child)).filter(Boolean);
        if (children.length === 0) return '';

        let html = '';
        children.forEach((childHtml, index) => {
            if (index > 0) {
                html += `<div class="logic-connector logic-connector-between">${operatorLabel}</div>`;
            }
            html += `<div class="logic-branch">${childHtml}</div>`;
        });

        if (isRoot) {
            return `<div class="logic-root">${html}</div>`;
        }

        return `<div class="${className}">${html}</div>`;
    }

    return '';
}

function renderPrueflogikSection(prueflogikRaw) {
    if (!prueflogikRaw) return '';
    try {
        const normalized = normalizePrueflogikExpression(prueflogikRaw);
        if (!normalized) {
            return '';
        }
        const tree = parsePrueflogikNode(normalized);
        const rendered = renderPrueflogikNode(tree, true);
        if (!rendered) {
            return '';
        }
        return `<section class="info-section"><h3>${escapeHtml(tDyn('pauschaleRuleLogicTitle'))}</h3><div class="logic-tree">${rendered}</div></section>`;
    } catch (err) {
        console.warn('Unable to render Prüflogik semigraphically', err);
        return '';
    }
}

function buildDignitiesAttributeContent(details) {
    const dignitaetenString = details && typeof details.Dignitaeten === 'string' ? details.Dignitaeten : '';
    if (!dignitaetenString.trim()) {
        return `<span class="info-muted">${escapeHtml(tDyn('dignitiesNone'))}</span>`;
    }

    const dignityCodes = dignitaetenString.split('|').map(code => String(code).trim()).filter(Boolean);
    if (dignityCodes.length === 0) {
        return `<span class="info-muted">${escapeHtml(tDyn('dignitiesNone'))}</span>`;
    }

    const lang = (typeof currentLang === 'undefined') ? 'de' : currentLang;
    const items = dignityCodes.map(code => {
        const detail = dignitaetenMap[String(code)];
        let description = '';
        if (detail) {
            if (lang === 'fr') {
                description = detail.DignitaetText_f || detail.DignitaetText || '';
            } else if (lang === 'it') {
                description = detail.DignitaetText_i || detail.DignitaetText || '';
            } else {
                description = detail.DignitaetText || '';
            }
        } else if (Object.keys(dignitaetenMap).length > 0) {
            console.warn(`No dignityDetail found in dignitaetenMap for code '${code}'.`);
        }

        const safeDescription = description ? escapeHtml(description) : escapeHtml(tDyn('descriptionNotFound', { code }));
        return `<li><span class="info-dignity-code">${escapeHtml(code)}</span> &ndash; <span class="info-dignity-text">${safeDescription}</span></li>`;
    });

    return `<ul class="info-chip-list">${items.join('')}</ul>`;
}

function buildImplantAttributeContent(details) {
    if (details && details.Implantate_inbegriffen === true) {
        return `<span class="status-pill status-positive">${escapeHtml(tDyn('implantsIncluded'))}</span>`;
    }
    return `<span class="status-pill status-negative">${escapeHtml(tDyn('implantsNotIncluded'))}</span>`;
}

function formatTaxpointsDisplay(raw) {
    if (raw === null || raw === undefined) return '';
    const rawString = String(raw).trim();
    if (!rawString) return '';
    const parsed = parseDecimal(rawString);
    if (Number.isFinite(parsed)) {
        return parsed.toFixed(2);
    }
    return rawString;
}

function stripOuterParens(text) {
    if (!text) return text;
    const trimmed = String(text).trim();
    if (trimmed.startsWith('(') && trimmed.endsWith(')')) {
        return trimmed.slice(1, -1).trim();
    }
    return trimmed;
}

function renderPauschaleSummarySection({ code, codeHtml, description, descriptionHtml, taxpoints, taxpointsHtml, metaItems = [] }) {
    const hasCodeValue = code !== undefined && code !== null && String(code).trim() !== '';
    const hasDescriptionValue = description !== undefined && description !== null && String(description).trim() !== '';
    const hasTaxpointValue = taxpoints !== undefined && taxpoints !== null && String(taxpoints).trim() !== '';

    const normalizedCode = hasCodeValue ? String(code).trim() : '';
    const codeDataAttr = normalizedCode ? ` data-pauschale-code="${escapeHtml(normalizedCode)}"` : '';

    const safeCode = codeHtml !== undefined
        ? codeHtml
        : (hasCodeValue ? escapeHtml(String(code)) : `<span class="info-muted">${escapeHtml(tDyn('noData'))}</span>`);
    const safeDescription = descriptionHtml !== undefined
        ? descriptionHtml
        : (hasDescriptionValue ? escapeHtml(String(description)) : `<span class="info-muted">${escapeHtml(tDyn('noData'))}</span>`);
    const safeTaxpoints = taxpointsHtml !== undefined
        ? taxpointsHtml
        : (hasTaxpointValue ? escapeHtml(String(taxpoints)) : `<span class="info-muted">${escapeHtml(tDyn('noData'))}</span>`);

    const filteredMeta = Array.isArray(metaItems) ? metaItems.filter(item => item && (item.label || item.value)) : [];
    const metaHtml = filteredMeta.length > 0
        ? `<div class="info-meta-grid">${filteredMeta.map(renderMetaItem).join('')}</div>`
        : '';

    return `
        <section class="info-section info-section-summary">
            <div class="info-summary-heading">
                <h2>${escapeHtml(tDyn('pauschaleSummaryTitle'))}</h2>
            </div>
            <div class="info-summary-table-wrapper">
                <table class="info-summary-table">
                    <thead>
                        <tr>
                            <th>${escapeHtml(tDyn('pauschaleCode'))}</th>
                            <th>${escapeHtml(tDyn('description'))}</th>
                            <th class="info-summary-tax-header">${escapeHtml(tDyn('taxpoints'))}</th>
                        </tr>
                    </thead>
                    <tbody>
                        <tr>
                            <td class="info-summary-code"${codeDataAttr}>${safeCode}</td>
                            <td>${safeDescription}</td>
                            <td class="info-summary-tax">${safeTaxpoints}</td>
                        </tr>
                    </tbody>
                </table>
            </div>
            ${metaHtml}
        </section>
    `;
}

function renderPauschaleInfoContentFromDetails(details, options = {}) {
    if (!details) {
        return `<p>${tDyn('noData')}</p>`;
    }

    const code = details.Pauschale || '';
    const description = getLangField(details, 'Pauschale_Text') || details.Pauschale_Text || '';
    const taxpointsDisplay = formatTaxpointsDisplay(details.Taxpunkte);
    const metaItems = [];
    const hasStructuredLogic = Boolean(options.hasStructuredLogic);
    if (Array.isArray(options.extraMetaItems)) {
        options.extraMetaItems.forEach(item => {
            if (item && (item.label || item.value)) {
                metaItems.push(item);
            }
        });
    }

    const sections = [];
    sections.push(renderPauschaleSummarySection({
        code,
        codeHtml: createPauschaleLink(code),
        description,
        taxpoints: taxpointsDisplay,
        metaItems
    }));

    const attributeCards = [];
    attributeCards.push(`
        <div class="info-attribute-card">
            <div class="info-attribute-label">${escapeHtml(tDyn('dignitiesLabel'))}</div>
            <div class="info-attribute-value">${buildDignitiesAttributeContent(details)}</div>
        </div>
    `);
    attributeCards.push(`
        <div class="info-attribute-card">
            <div class="info-attribute-label">${escapeHtml(tDyn('implantsLabel'))}</div>
            <div class="info-attribute-value">${buildImplantAttributeContent(details)}</div>
        </div>
    `);

    if (attributeCards.some(Boolean)) {
        sections.push(`
            <section class="info-section info-section-attributes">
                <div class="info-attribute-list">${attributeCards.join('')}</div>
            </section>
        `);
    }

    if (details.pauschale_erklaerung_html && options.includeExplanation !== false) {
        sections.push(`
            <section class="info-section info-section-explanation">
                <h3>${escapeHtml(tDyn('reasonPauschale'))}</h3>
                ${details.pauschale_erklaerung_html}
            </section>
        `);
    }

    const prueflogikRaw = options.prueflogikOverride !== undefined ? options.prueflogikOverride : details['Prüflogik'];
    if (!hasStructuredLogic && prueflogikRaw) {
        const logicSection = renderPrueflogikSection(prueflogikRaw);
        if (logicSection) {
            sections.push(logicSection);
        }
    }

    if (Array.isArray(options.extraSections)) {
        options.extraSections.filter(Boolean).forEach(sectionHtml => sections.push(sectionHtml));
    }

    return sections.filter(Boolean).join('');
}

function buildPauschaleInfoHtmlFromCode(code) {
    const norm = String(code || '').toUpperCase();
    if (!norm) return `<p>${tDyn('noData')}</p>`;
    const entry = pauschalenLookup.get(norm);
    if (!entry) {
        return `<p>${tDyn('noData')}</p>`;
    }

    const extraSections = [];
    const hasStructuredLogic = Boolean(entry.bedingungs_pruef_html);
    if (hasStructuredLogic) {
        extraSections.push(`<section class="info-section info-section-conditions">${entry.bedingungs_pruef_html}</section>`);
    }

    return renderPauschaleInfoContentFromDetails(entry, { extraSections, hasStructuredLogic });
}

function buildChapterInfoHtml(code) {
    const info = getChapterInfo(code);
    return `<h3>Kapitel ${escapeHtml(code)}${info.name ? ' - ' + escapeHtml(info.name) : ''}</h3>` + (info.interpretation ? `<p>${escapeHtml(info.interpretation)}</p>` : '');
}

function buildGroupInfoHtml(code) {
    const key = (code || '').trim();
    const info = groupInfoMap[key];
    if (!info) return `<p>${tDyn('groupNoData',{code: escapeHtml(key)})}</p>`;
    const lkns = Array.from(info.lkns).sort();
    const links = lkns.map(l => createInfoLink(l,'lkn')).join(', ');
    return `<h3>Leistungsgruppe ${escapeHtml(key)}</h3>` +
           (info.text ? `<p>${escapeHtml(info.text)}</p>` : '') +
           `<p><b>Enthaltene LKN:</b> ${links}</p>`;
}

function getInterpretation(code, allowFallback = true) {
    const normCode = String(code || '').toUpperCase();
    let entry;

    // 1) Suche Interpretation direkt in den Tarifpositionen
    if (Array.isArray(data_tardocGesamt)) {
        const pos = data_tardocGesamt.find(p => p && p.LKN && String(p.LKN).toUpperCase() === normCode);
        if (pos) {
            entry = getLangField(pos, 'Medizinische Interpretation') || getLangField(pos, 'Interpretation');
            if (entry) return entry;
        }
    }

    // 2) Fallback auf separate Interpretationen
    if (allowFallback && interpretationMap) {
        const mapEntry = interpretationMap[normCode] || interpretationMap[normCode.split('.')[0]];
        if (mapEntry) {
            entry = getLangField(mapEntry, 'Interpretation');
            if (entry) return entry;
        }
    }

    return '';
}

function getChapterInfo(kapitelCode) {
    const info = { name: '', interpretation: '' };
    const pos = data_tardocGesamt.find(item => item.KapitelNummer === kapitelCode);
    if (pos) info.name = pos.Kapitel || '';

    info.interpretation = getInterpretation(kapitelCode);
    return info;
}

async function fetchPauschaleConditionsHtml(code) {
    const normCode = String(code || '').trim();
    if (!normCode || !pauschaleConditionsContext) return null;
    try {
        const res = await fetch('/api/pauschale-conditions-html', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                code: normCode,
                lang: currentLang,
                context: pauschaleConditionsContext
            })
        });
        if (!res.ok) {
            console.warn('fetchPauschaleConditionsHtml response not ok', res.status);
            return null;
        }
        const data = await res.json();
        return data;
    } catch (err) {
        console.error('fetchPauschaleConditionsHtml failed', err);
        return null;
    }
}

function buildPauschaleInfoHtml(idx) {
    const entry = evaluatedPauschalenList[idx];
    if (!entry) return '';

    const baseDetails = entry.details || {};
    const extraMeta = [];
    if (typeof entry.is_valid_structured === 'boolean') {
        const logicStatusKey = entry.is_valid_structured ? 'logicOk' : 'logicNotOk';
        const logicStatusText = stripOuterParens(tDyn(logicStatusKey));
        const pillClass = entry.is_valid_structured ? 'status-positive' : 'status-negative';
        const pillHtml = `<span class="status-pill ${pillClass}">${escapeHtml(logicStatusText)}</span>`;
        extraMeta.push({ label: tDyn('logicStatusLabel'), valueHtml: pillHtml });
    }
    const rawSelectedTax = selectedPauschaleDetails?.Taxpunkte;
    const rawOtherTax = baseDetails.Taxpunkte;
    const hasSelectedTax = rawSelectedTax !== undefined && rawSelectedTax !== null && String(rawSelectedTax).trim() !== '';
    const hasOtherTax = rawOtherTax !== undefined && rawOtherTax !== null && String(rawOtherTax).trim() !== '';
    if (hasSelectedTax && hasOtherTax) {
        const selectedTax = parseDecimal(rawSelectedTax);
        const otherTax = parseDecimal(rawOtherTax);
        if (Number.isFinite(selectedTax) && Number.isFinite(otherTax)) {
            const diff = otherTax - selectedTax;
            extraMeta.push({ label: tDyn('diffTaxpoints'), value: `${diff >= 0 ? '+' : ''}${diff.toFixed(2)}` });
        }
    }

    const extraSections = [];
    const hasStructuredLogic = Boolean(entry.bedingungs_pruef_html);
    if (hasStructuredLogic) {
        extraSections.push(`<section class="info-section info-section-conditions">${entry.bedingungs_pruef_html}</section>`);
    }

    return renderPauschaleInfoContentFromDetails(baseDetails, { extraMetaItems: extraMeta, extraSections, hasStructuredLogic });
}

async function showPauschaleInfoByCode(code) {
    const norm = String(code || '').toUpperCase();
    let html = '';
    let titleKey = 'condDetails';

    const idx = evaluatedPauschalenList.findIndex(p => String(p.details?.Pauschale || '').toUpperCase() === norm);
    if (idx !== -1) {
        const entry = evaluatedPauschalenList[idx];
        const needsOnDemand = pauschaleConditionsContext && (!entry.bedingungs_pruef_html || !String(entry.bedingungs_pruef_html).trim());
        if (needsOnDemand) {
            try {
                showModal('infoModalDetailOverlay', `<p>${escapeHtml(tDyn('loadingData'))}</p>`);
            } catch (_) {}
            const fetched = await fetchPauschaleConditionsHtml(norm);
            if (fetched && typeof fetched.html === 'string') {
                entry.bedingungs_pruef_html = fetched.html;
                entry.conditions_structured = fetched.conditions_structured || entry.conditions_structured;
                entry.bedingungs_fehler = fetched.errors || entry.bedingungs_fehler;
                if (typeof fetched.is_valid_structured === 'boolean') {
                    entry.is_valid_structured = fetched.is_valid_structured;
                }
                evaluatedPauschalenList[idx] = entry;
            }
        }
        html = buildPauschaleInfoHtml(idx);
    } else if (selectedPauschaleDetails && String(selectedPauschaleDetails.Pauschale || '').toUpperCase() === norm) {
        const extraSections = [];
        const hasStructuredLogic = Boolean(selectedPauschaleConditionHtml && selectedPauschaleConditionHtml.trim());
        if (hasStructuredLogic) {
            extraSections.push(`<section class="info-section info-section-conditions">${selectedPauschaleConditionHtml}</section>`);
        }
        html = renderPauschaleInfoContentFromDetails(selectedPauschaleDetails, {
            extraSections,
            hasStructuredLogic
        });
    } else {
        html = buildPauschaleInfoHtmlFromCode(norm);
        titleKey = 'pauschaleDetails';
    }

    if (!html || !String(html).trim()) {
        html = `<p>${tDyn('noData')}</p>`;
    }

    const detailTitle = $('infoModalDetailTitle');
    if (detailTitle) {
        detailTitle.textContent = `${tDyn(titleKey)} (${code})`;
    }
    showInfoModal(html);
    return Boolean(html);
}

function buildTablePopup(data, tableName) {
    let rows = Array.isArray(data) ? data.slice() : [];
    if ((rows.length === 0) && tableName) {
        const medicationFallback = getMedicationEntriesByTable(tableName);
        if (medicationFallback.length) {
            rows = medicationFallback;
        }
    }

    let tableHtml = `<div class="info-modal-header" style="cursor: grab;"><h2>Tabelle: ${escapeHtml(tableName)}</h2></div>`;
    tableHtml += `<div class="info-modal-body" style="max-height: calc(0.75 * 100vh); overflow-y: auto;">`;
    tableHtml += '<table><thead><tr><th>Code</th><th>Text</th></tr></thead><tbody>';
    rows.forEach(row => {
        const code = row && row.Code !== undefined && row.Code !== null ? String(row.Code) : '';
        const text = row && row.Code_Text !== undefined && row.Code_Text !== null ? row.Code_Text : '';
        const tableTypeRaw = row && row.Tabelle_Typ !== undefined && row.Tabelle_Typ !== null ? String(row.Tabelle_Typ).trim() : '';
        const isServiceCatalog = tableTypeRaw === 'service_catalog';
        const isMedication = tableTypeRaw === '402';
        const isIcd = tableTypeRaw === 'icd';
        const tableKeyRaw = row && row.Tabelle ? row.Tabelle : tableName;
        const tableAttr = tableKeyRaw ? ` data-table="${escapeHtml(String(tableKeyRaw))}"` : '';

        let style = '';
        let codeDisplay = escapeHtml(code);

        if (isServiceCatalog) {
            style = 'font-weight: bold;';
        } else if (isMedication) {
            codeDisplay = `<a href="#" class="info-link" data-type="medication" data-code="${escapeHtml(code)}"${tableAttr}>${escapeHtml(code)}</a>`;
        } else {
            codeDisplay = `<a href="#" class="info-link" data-type="${isIcd ? 'diagnosis' : 'lkn'}" data-code="${escapeHtml(code)}">${escapeHtml(code)}</a>`;
        }
        
        tableHtml += `<tr><td style="${style}">${codeDisplay}</td><td>${escapeHtml(text)}</td></tr>`;
    });
    tableHtml += '</tbody></table></div>';
    return tableHtml;
}


function displayOutput(html, type = "info") {
    const out = $("output");
    if (!out) { console.error("Output element not found!"); return; }
    out.innerHTML = html;
    // Output-Typ-Klasse wird nicht mehr gesetzt, Styling erfolgt über Klassen im HTML.
}

const busyTabTrapHandler = (event) => {
    if (event.key === 'Tab') {
        event.preventDefault();
    }
};

let busyPreviousFocus = null;

function setBusyState(isBusy) {
    const overlay = $('interactionBlocker');
    const shell = document.querySelector('.app-shell');

    if (isBusy) {
        if (document.activeElement instanceof HTMLElement) {
            busyPreviousFocus = document.activeElement;
        } else {
            busyPreviousFocus = null;
        }

        document.body.classList.add('is-busy');
        if (shell) shell.setAttribute('aria-busy', 'true');

        if (document.activeElement && typeof document.activeElement.blur === 'function') {
            try { document.activeElement.blur(); } catch (_) {}
        }

        if (overlay) {
            overlay.style.display = 'block';
            overlay.setAttribute('tabindex', '-1');
            overlay.addEventListener('keydown', busyTabTrapHandler, true);
            setTimeout(() => {
                try { overlay.focus({ preventScroll: true }); } catch (_) {}
            }, 0);
        }
    } else {
        document.body.classList.remove('is-busy');
        if (shell) shell.setAttribute('aria-busy', 'false');

        if (overlay) {
            overlay.style.display = 'none';
            overlay.removeEventListener('keydown', busyTabTrapHandler, true);
            overlay.removeAttribute('tabindex');
        }

        if (busyPreviousFocus && typeof busyPreviousFocus.focus === 'function') {
            const target = busyPreviousFocus;
            busyPreviousFocus = null;
            setTimeout(() => {
                try { target.focus({ preventScroll: true }); } catch (_) {}
            }, 0);
        } else {
            busyPreviousFocus = null;
        }
    }
}

function showSpinner(text = tDyn('spinnerWorking')) {
    const spinner = $('spinner');
    const spinnerText = $('spinnerText');
    const button = $('analyzeButton');

    if (spinnerText) spinnerText.textContent = text;
    if (spinner) spinner.style.display = 'block';
    if (button) button.disabled = true;
    setBusyState(true);
}

function hideSpinner() {
    const spinner = $('spinner');
    const spinnerText = $('spinnerText');
    const button = $('analyzeButton');

    if (spinnerText) spinnerText.textContent = '';
    if (spinner) spinner.style.display = 'none';
    if (button) button.disabled = false;
    setBusyState(false);
}

let flyingDoctorWanderMap = new Map();
const flyingDoctorStuntClasses = ['is-flipping', 'is-wiggling', 'is-boosting'];
const flyingDoctorStuntWeighted = ['is-flipping', 'is-flipping', 'is-wiggling', 'is-boosting'];

function flyingDoctorRand(min, max) {
    return min + Math.random() * (max - min);
}

function flyingDoctorRandInt(min, max) {
    return Math.floor(flyingDoctorRand(min, max + 1));
}

function flyingDoctorPick(list) {
    return list[Math.floor(Math.random() * list.length)];
}

function flyingDoctorBounds(el) {
    const width = window.innerWidth || 0;
    const height = window.innerHeight || 0;
    const rect = el.getBoundingClientRect();
    const spriteWidth = rect.width || 200;
    const spriteHeight = rect.height || 150;
    const padX = Math.min(90, Math.max(20, spriteWidth * 0.25));
    const padY = Math.min(80, Math.max(20, spriteHeight * 0.25));
    const minX = padX;
    const minY = padY;
    const maxX = Math.max(minX, width - spriteWidth - padX);
    const maxY = Math.max(minY, height - spriteHeight - padY);
    return { width, height, spriteWidth, spriteHeight, minX, maxX, minY, maxY };
}

function flyingDoctorEdgePoint(side, bounds) {
    const margin = Math.max(120, Math.min(bounds.width, bounds.height) * 0.25);
    if (side === 'left') {
        return { x: -bounds.spriteWidth - margin, y: flyingDoctorRand(bounds.minY, bounds.maxY) };
    }
    if (side === 'right') {
        return { x: bounds.width + margin, y: flyingDoctorRand(bounds.minY, bounds.maxY) };
    }
    if (side === 'top') {
        return { x: flyingDoctorRand(bounds.minX, bounds.maxX), y: -bounds.spriteHeight - margin };
    }
    return { x: flyingDoctorRand(bounds.minX, bounds.maxX), y: bounds.height + margin };
}

function flyingDoctorInteriorPoint(bounds) {
    return { x: flyingDoctorRand(bounds.minX, bounds.maxX), y: flyingDoctorRand(bounds.minY, bounds.maxY) };
}

function flyingDoctorPath(points) {
    if (!points || points.length < 2) return '';
    const parts = [`M ${points[0].x.toFixed(1)} ${points[0].y.toFixed(1)}`];
    for (let i = 0; i < points.length - 1; i++) {
        const p0 = points[i - 1] || points[i];
        const p1 = points[i];
        const p2 = points[i + 1];
        const p3 = points[i + 2] || p2;
        const c1x = p1.x + (p2.x - p0.x) / 6;
        const c1y = p1.y + (p2.y - p0.y) / 6;
        const c2x = p2.x - (p3.x - p1.x) / 6;
        const c2y = p2.y - (p3.y - p1.y) / 6;
        parts.push(`C ${c1x.toFixed(1)} ${c1y.toFixed(1)} ${c2x.toFixed(1)} ${c2y.toFixed(1)} ${p2.x.toFixed(1)} ${p2.y.toFixed(1)}`);
    }
    return parts.join(' ');
}

function buildFlyingDoctorFlight(el) {
    const bounds = flyingDoctorBounds(el);
    if (!bounds.width || !bounds.height) return null;
    const sides = ['left', 'right', 'top', 'bottom'];
    const entrySide = flyingDoctorPick(sides);
    let exitSide = flyingDoctorPick(sides);
    if (exitSide === entrySide) {
        exitSide = flyingDoctorPick(sides.filter(side => side !== entrySide));
    }

    const points = [flyingDoctorEdgePoint(entrySide, bounds)];
    const midCount = flyingDoctorRandInt(2, 4);
    for (let i = 0; i < midCount; i++) {
        points.push(flyingDoctorInteriorPoint(bounds));
    }
    points.push(flyingDoctorEdgePoint(exitSide, bounds));

    if (Math.random() < 0.35 && points.length > 3) {
        const pauseIndex = flyingDoctorRandInt(1, points.length - 2);
        points.splice(pauseIndex, 0, { ...points[pauseIndex] });
    }

    const facing = points[0].x < points[points.length - 1].x ? 1 : -1;
    const baseScale = flyingDoctorRand(0.85, 1.1);
    const tiltBase = flyingDoctorRand(-6, 6);
    const tiltStart = tiltBase + flyingDoctorRand(-12, 12);
    const tiltMid = tiltBase + flyingDoctorRand(-8, 8);
    const tiltEnd = tiltBase + flyingDoctorRand(-12, 12);
    const keyframes = points.map((point, index) => {
        const progress = points.length > 1 ? index / (points.length - 1) : 1;
        let opacity = 1;
        if (progress < 0.12) {
            opacity = progress / 0.12;
        } else if (progress > 0.88) {
            opacity = (1 - progress) / 0.12;
        }
        opacity = Math.max(0, Math.min(1, opacity));
        const tilt = tiltBase + flyingDoctorRand(-10, 10);
        return {
            transform: `translate3d(${Math.round(point.x)}px, ${Math.round(point.y)}px, 0) rotate(${tilt.toFixed(1)}deg) scale(${baseScale.toFixed(2)}) scaleX(${facing})`,
            opacity: Number(opacity.toFixed(2))
        };
    });

    return {
        path: flyingDoctorPath(points),
        keyframes,
        duration: flyingDoctorRandInt(14000, 26000),
        idle: flyingDoctorRandInt(200, 1200),
        facing,
        baseScale,
        tiltStart,
        tiltMid,
        tiltEnd
    };
}

function clearFlyingDoctorTimers(state) {
    if (!state) return;
    if (state.startTimer) {
        clearTimeout(state.startTimer);
        state.startTimer = null;
    }
    if (state.timers && state.timers.length) {
        state.timers.forEach(timer => clearTimeout(timer));
        state.timers = [];
    }
}

function clearFlyingDoctorStunts(state) {
    if (!state || !state.timers || !state.timers.length) return;
    state.timers.forEach(timer => clearTimeout(timer));
    state.timers = [];
}

function supportsFlyingDoctorOffsetPath() {
    return typeof CSS !== 'undefined'
        && typeof CSS.supports === 'function'
        && CSS.supports('offset-path', 'path("M 0 0 L 1 1")');
}

function scheduleFlyingDoctorStunts(el, duration, idle) {
    const state = flyingDoctorWanderMap.get(el);
    if (!state || !state.active) return;
    const roll = Math.random();
    let stuntCount = 0;
    if (roll < 0.45) {
        stuntCount = 1;
    } else if (roll < 0.6) {
        stuntCount = 2;
    }
    if (!stuntCount) return;

    for (let i = 0; i < stuntCount; i++) {
        const delay = Math.round((idle || 0) + flyingDoctorRand(duration * 0.2, duration * 0.85));
        const className = flyingDoctorPick(flyingDoctorStuntWeighted);
        const timer = setTimeout(() => {
            if (!state.active) return;
            el.classList.remove(...flyingDoctorStuntClasses);
            el.classList.add(className);
            const cleanupDelay = className === 'is-flipping' ? 950 : 700;
            const cleanupTimer = setTimeout(() => {
                el.classList.remove(className);
            }, cleanupDelay);
            state.timers.push(cleanupTimer);
        }, delay);
        state.timers.push(timer);
    }
}

function runFlyingDoctorFlight(el) {
    const state = flyingDoctorWanderMap.get(el);
    if (!state || !state.active || typeof el.animate !== 'function') return;
    clearFlyingDoctorStunts(state);
    el.classList.remove(...flyingDoctorStuntClasses);
    const flight = buildFlyingDoctorFlight(el);
    if (!flight) return;
    const easing = flyingDoctorPick(['linear', 'ease-in-out', 'cubic-bezier(0.45, 0, 0.25, 1)']);
    let animation = null;
    if (flight.path && supportsFlyingDoctorOffsetPath()) {
        el.style.offsetPath = `path("${flight.path}")`;
        el.style.offsetRotate = '0deg';
        el.style.offsetAnchor = 'center';
        const baseTransform = `scale(${flight.baseScale.toFixed(2)}) scaleX(${flight.facing})`;
        animation = el.animate([
            { offset: 0, offsetDistance: '0%', opacity: 0, transform: `${baseTransform} rotate(${flight.tiltStart.toFixed(1)}deg)` },
            { offset: 0.12, offsetDistance: '12%', opacity: 1, transform: `${baseTransform} rotate(${flight.tiltMid.toFixed(1)}deg)` },
            { offset: 0.88, offsetDistance: '88%', opacity: 1, transform: `${baseTransform} rotate(${flight.tiltMid.toFixed(1)}deg)` },
            { offset: 1, offsetDistance: '100%', opacity: 0, transform: `${baseTransform} rotate(${flight.tiltEnd.toFixed(1)}deg)` }
        ], {
            duration: flight.duration,
            easing,
            delay: flight.idle,
            fill: 'both'
        });
    } else {
        el.style.offsetPath = '';
        el.style.offsetDistance = '';
        el.style.offsetRotate = '';
        el.style.offsetAnchor = '';
        animation = el.animate(flight.keyframes, {
            duration: flight.duration,
            easing,
            delay: flight.idle,
            fill: 'both'
        });
    }
    state.animation = animation;
    scheduleFlyingDoctorStunts(el, flight.duration, flight.idle);
    animation.onfinish = () => {
        if (state.active) runFlyingDoctorFlight(el);
    };
}

function startFlyingDoctorWander(el) {
    if (!el || typeof el.animate !== 'function') {
        if (el) el.classList.remove('is-wandering');
        return;
    }
    let state = flyingDoctorWanderMap.get(el);
    if (!state) {
        state = { active: false, animation: null, startTimer: null, timers: [] };
        flyingDoctorWanderMap.set(el, state);
    }
    state.active = true;
    clearFlyingDoctorTimers(state);
    if (state.animation) {
        try { state.animation.cancel(); } catch (_) {}
        state.animation = null;
    }
    el.classList.add('is-wandering');
    runFlyingDoctorFlight(el);
}

function stopFlyingDoctorWander(el) {
    if (!el) return;
    const state = flyingDoctorWanderMap.get(el);
    if (state) {
        state.active = false;
        clearFlyingDoctorTimers(state);
        if (state.animation) {
            try { state.animation.cancel(); } catch (_) {}
        }
        flyingDoctorWanderMap.delete(el);
    }
    el.classList.remove('is-wandering', 'is-flipping', 'is-wiggling', 'is-boosting');
    el.style.offsetPath = '';
    el.style.offsetDistance = '';
    el.style.offsetRotate = '';
    el.style.offsetAnchor = '';
}

function setFlyingDoctorsActive(active){
    const layer = $('flyingDoctorLayer');
    const doctors = document.querySelectorAll('.flying-doctor');
    if (layer) {
        layer.classList.toggle('is-active', !!active);
    }
    doctors.forEach(el => {
        el.classList.toggle('is-active', !!active);
    });
}

function startFlyingDoctors(){
    setFlyingDoctorsActive(true);
    const doctors = document.querySelectorAll('.flying-doctor');
    doctors.forEach(el => startFlyingDoctorWander(el));
}

function stopFlyingDoctors(){
    const doctors = document.querySelectorAll('.flying-doctor');
    doctors.forEach(el => stopFlyingDoctorWander(el));
    setFlyingDoctorsActive(false);
}

// --- Fortschrittsbalken Funktionen ---
function startProgress() {
    const c = $('progressContainer');
    const bar = $('progressBar');
    const timer = $('progressTimer');
    startFlyingDoctors();
    if (c) c.style.display = 'block';
    if (bar) bar.style.width = '0%';
    currentProgressPercent = 0;
    clearProgressHintTimeouts();
    setProgressHint(null);
    if (timer) {
        timer.textContent = '0 s';
        timer.style.display = 'block';
    }
    progressTimes = {start: performance.now()};
    if (elapsedTimer) clearInterval(elapsedTimer);
    elapsedTimer = setInterval(() => {
        if (timer) {
            const sec = ((performance.now() - progressTimes.start) / 1000).toFixed(0);
            timer.textContent = sec + ' s';
        }
    }, 1000);
}

function setProgressMessage(message) {
    const text = $('progressText');
    if (!text) return;
    let wrapper = text.querySelector('.progress-text-wrapper');
    if (!wrapper) {
        text.textContent = '';
        wrapper = document.createElement('span');
        wrapper.className = 'progress-text-wrapper';
        text.appendChild(wrapper);
    }
    let base = wrapper.querySelector('.progress-text-base');
    if (!base) {
        base = document.createElement('span');
        base.className = 'progress-text-base';
        wrapper.appendChild(base);
    }
    let overlay = wrapper.querySelector('.progress-text-overlay');
    if (!overlay) {
        overlay = document.createElement('span');
        overlay.className = 'progress-text-overlay';
        wrapper.appendChild(overlay);
    }
    const content = message || '';
    base.textContent = content;
    overlay.textContent = content;
    updateProgressTextOverlay();
}

function waitForRender() {
    return new Promise(resolve => {
        if (typeof requestAnimationFrame === 'function') {
            requestAnimationFrame(() => resolve());
        } else {
            setTimeout(resolve, 0);
        }
    });
}

function setProgressHint(textKey) {
    if (!textKey) {
        setProgressMessage('');
        return;
    }
    setProgressMessage(tDyn(textKey));
}

function updateProgress(percent, textKey = null) {
    const bar = $('progressBar');
    currentProgressPercent = Math.max(currentProgressPercent, percent);
    if (bar) bar.style.width = currentProgressPercent + '%';
    if (textKey) {
        setProgressHint(textKey);
    }
    updateProgressTextOverlay();
}

function updateProgressTextOverlay() {
    const text = $('progressText');
    const container = $('progressContainer');
    if (!text || !container) return;
    const wrapper = text.querySelector('.progress-text-wrapper');
    if (!wrapper) return;
    const overlay = wrapper.querySelector('.progress-text-overlay');
    const base = wrapper.querySelector('.progress-text-base');
    if (!overlay || !base) return;
    const bar = $('progressBar');
    if (!bar) return;
    const containerWidth = container.clientWidth;
    const barWidth = bar.offsetWidth;
    const textWidth = wrapper.offsetWidth;
    if (containerWidth === 0 || textWidth === 0) {
        overlay.style.clipPath = 'inset(0 100% 0 0)';
        overlay.style.webkitClipPath = 'inset(0 100% 0 0)';
        base.style.clipPath = 'inset(0 0 0 0)';
        base.style.webkitClipPath = 'inset(0 0 0 0)';
        return;
    }
    const textLeft = (containerWidth - textWidth) / 2;
    const overlapPx = Math.max(0, Math.min(barWidth - textLeft, textWidth));
    const overlayRightClip = Math.max(textWidth - overlapPx, 0);
    const baseLeftClip = Math.max(overlapPx, 0);
    const overlayClip = `inset(0 ${overlayRightClip}px 0 0)`;
    const baseClip = `inset(0 0 0 ${baseLeftClip}px)`;
    overlay.style.clipPath = overlayClip;
    overlay.style.webkitClipPath = overlayClip;
    base.style.clipPath = baseClip;
    base.style.webkitClipPath = baseClip;
}

function scheduleProgressHint(percent, textKey, delayMs) {
    if (!delayMs || delayMs <= 0) return;
    const handle = setTimeout(() => {
        progressHintTimeouts = progressHintTimeouts.filter(h => h !== handle);
        if (currentProgressPercent < percent) {
            updateProgress(percent, textKey);
        }
    }, delayMs);
    progressHintTimeouts.push(handle);
}

function clearProgressHintTimeouts() {
    if (!progressHintTimeouts.length) return;
    for (const handle of progressHintTimeouts) {
        clearTimeout(handle);
    }
    progressHintTimeouts = [];
}

function delay(ms) {
    return new Promise(resolve => setTimeout(resolve, ms));
}

async function showProgressStep(percent, textKey, minVisibleMs = 0) {
    updateProgress(percent, textKey);
    await waitForRender();
    if (minVisibleMs && minVisibleMs > 0) {
        await delay(minVisibleMs);
    }
}

function finishProgress() {
    const c = $('progressContainer');
    const timer = $('progressTimer');
    if (c) c.style.display = 'none';
    if (timer) timer.style.display = 'none';
    stopFlyingDoctors();
    if (elapsedTimer) { clearInterval(elapsedTimer); elapsedTimer = null; }
    if (llm1BarInterval) { clearInterval(llm1BarInterval); llm1BarInterval = null; }
    clearProgressHintTimeouts();
}

function startLlm1Progress() {
    if (llm1BarInterval) clearInterval(llm1BarInterval);
    let percent = 10;
    llm1BarInterval = setInterval(() => {
        percent = Math.min(percent + 1, 28);
        updateProgress(percent);
    }, 1000);
}

function stopLlm1Progress() {
    if (llm1BarInterval) { clearInterval(llm1BarInterval); llm1BarInterval = null; }
}

function armLlmProgressFallbacks() {
    clearProgressHintTimeouts();
    scheduleProgressHint(45, 'progressHintLlm1Review', 3500);
    scheduleProgressHint(60, 'progressHintLlm2Processing', 6500);
}

// --- Ende Fortschrittsbalken Funktionen ---


// ─── 2 · Daten laden ─────────────────────────────────────────────────────────
async function fetchJSON(path) {
    try {
        const r = await fetch(path);
        if (!r.ok) {
            let errorText = r.statusText;
            try { const errorJson = await r.json(); errorText = errorJson.error || errorJson.message || r.statusText; } catch (e) { /* Ignore */ }
            throw new Error(`HTTP ${r.status}: ${errorText} beim Laden von ${path}`);
        }
        return await r.json();
    } catch (e) {
        console.warn(`Fehler beim Laden oder Parsen von ${path}:`, e);
        return []; // Leeres Array zurückgeben, damit Promise.all nicht fehlschlägt
    }
}


async function loadData() {
    console.log("Lade Frontend-Daten vom Server...");
    const initialSpinnerMsg = tDyn('loadingData');
    showSpinner(initialSpinnerMsg);
    const outputDiv = $("output");
    if (outputDiv) outputDiv.innerHTML = "";

    let loadedDataArray = [];
    let loadError = null;

    try {
        loadedDataArray = await Promise.all([
            fetchJSON(DATA_PATHS.leistungskatalog),
            fetchJSON(DATA_PATHS.pauschaleLP),
            fetchJSON(DATA_PATHS.pauschalen),
            fetchJSON(DATA_PATHS.pauschaleBedingungen),
            fetchJSON(DATA_PATHS.tardocGesamt),
            fetchJSON(DATA_PATHS.tabellen),
            fetchJSON(DATA_PATHS.interpretationen),
            fetchJSON(DATA_PATHS.dignitaeten), // Fetch dignities
            fetchJSON(DATA_PATHS.tpw)
        ]);

        [ data_leistungskatalog, data_pauschaleLeistungsposition, data_pauschalen,
          data_pauschaleBedingungen, data_tardocGesamt, data_tabellen,
          data_interpretationen, data_dignitaeten, tpwData ] = loadedDataArray; // Assign dignities & TPW data

        tpwData = normalizeTpwPayload(tpwData);

        interpretationMap = {};
        if (data_interpretationen) {
            const all = [];
            if (Array.isArray(data_interpretationen)) {
                all.push(...data_interpretationen);
            } else {
                if (Array.isArray(data_interpretationen.Kapitelinterpretationen)) {
                    all.push(...data_interpretationen.Kapitelinterpretationen);
                }
                if (Array.isArray(data_interpretationen.GenerelleInterpretationen)) {
                    all.push(...data_interpretationen.GenerelleInterpretationen);
                }
                if (Array.isArray(data_interpretationen.AllgemeineDefinitionen)) {
                    all.push(...data_interpretationen.AllgemeineDefinitionen);
                }
            }
            all.forEach(entry => {
                if (entry && entry.KNR) interpretationMap[entry.KNR] = entry;
            });
        }

        let missingDataErrors = [];
        if (!Array.isArray(data_leistungskatalog) || data_leistungskatalog.length === 0) missingDataErrors.push("Leistungskatalog");
        if (!Array.isArray(data_tardocGesamt) || data_tardocGesamt.length === 0) missingDataErrors.push("TARDOC-Daten");
        if (!Array.isArray(data_pauschalen) || data_pauschalen.length === 0) missingDataErrors.push("Pauschalen");
        if (!Array.isArray(data_pauschaleBedingungen) || data_pauschaleBedingungen.length === 0) missingDataErrors.push("Pauschalen-Bedingungen");
        if (!Array.isArray(data_tabellen) || data_tabellen.length === 0) missingDataErrors.push("Referenz-Tabellen");
        if (!interpretationMap || Object.keys(interpretationMap).length === 0) missingDataErrors.push("Interpretationen");
        if (!Array.isArray(data_dignitaeten) || data_dignitaeten.length === 0) missingDataErrors.push("Dignitäten"); // Check dignities data
        if (missingDataErrors.length > 0) {
             throw new Error(`Folgende kritische Daten fehlen oder konnten nicht geladen werden: ${missingDataErrors.join(', ')}.`);
        }
        if (!tpwData || typeof tpwData !== 'object' || Object.keys(tpwData).length === 0) {
            console.warn("Taxpunktwerte konnten nicht geladen werden oder sind leer.");
        } else {
            initTpwPanelFromData();
        }

        buildTableLookups();

        pauschalenLookup = new Map();
        if (Array.isArray(data_pauschalen)) {
            data_pauschalen.forEach(entry => {
                if (entry && entry.Pauschale) {
                    pauschalenLookup.set(String(entry.Pauschale).toUpperCase(), entry);
                }
            });
        }
        buildLknPauschaleMap();

        // DignitaetenMap aufbauen
        dignitaetenMap = {};
        if (Array.isArray(data_dignitaeten) && data_dignitaeten.length > 0) {
            data_dignitaeten.forEach(dignity => {
                if (dignity && dignity.DignitaetCode) {
                    dignitaetenMap[String(dignity.DignitaetCode).trim()] = dignity;
                }
            });
            if (Object.keys(dignitaetenMap).length === 0) {
                console.warn("DignitaetenMap is empty after processing data_dignitaeten. Check DignitaetCode fields in the JSON.");
            }
        } else {
            // This warning will now also catch the case where data_dignitaeten is an empty array.
            console.warn("data_dignitaeten is not a non-empty array. DignitaetenMap will be empty. Ensure 'data/DIGNITAETEN.json' is loaded correctly and contains data.");
        }
        // Leistungsgruppen-Übersicht aufbauen
        groupInfoMap = {};
        data_tardocGesamt.forEach(item => {
            if (Array.isArray(item.Leistungsgruppen)) {
                item.Leistungsgruppen.forEach(g => {
                    if (!groupInfoMap[g.Gruppe]) {
                        groupInfoMap[g.Gruppe] = { text: g.Text || '', lkns: new Set() };
                    } else if (g.Text && !groupInfoMap[g.Gruppe].text) {
                        groupInfoMap[g.Gruppe].text = g.Text;
                    }
                    groupInfoMap[g.Gruppe].lkns.add(item.LKN);
                });
            }
        });

        console.log("Frontend-Daten vom Server geladen.");

        displayOutput(`<p class='success'>${tDyn('dataLoaded')}</p>`);
        hideSpinner();
        setTimeout(() => {
            const currentOutput = $("output");
            if (currentOutput && currentOutput.querySelector('p.success')) {
                 displayOutput("");
            }
        }, 2500);

    } catch (error) {
         loadError = error;
         console.error("Schwerwiegender Fehler beim Laden der Frontend-Daten:", error);
         displayOutput(`<p class="error">Fehler beim Laden der notwendigen Frontend-Daten: ${escapeHtml(error.message)}. Funktionalität eingeschränkt. Bitte Seite neu laden.</p>`);
         hideSpinner();
    }
}

document.addEventListener("DOMContentLoaded", () => {
    console.debug('popup instrumentation ready');
    logFrontendInteraction('frontend-init', { href: window.location.href });
    loadTranslations().then(() => {
        try {
            setIcdFilterMode(icdFilterMode);
        } catch (err) {
            console.warn('Unable to apply translations during init:', err);
        }
    }).catch((err) => console.error('Failed to load translations:', err));
    loadIcdCheckboxState();
    loadData();
    // Initial: Umschalter verbergen bis Ergebnis vorliegt
    showIcdToggle(false);
    setIcdFilterMode('all');
    // TPW-Events binden
    const tpwKantonSelect = $('tpwKantonSelect');
    if (tpwKantonSelect) {
        tpwKantonSelect.addEventListener('change', (e) => handleTpwSelectionChange('kanton', e.target.value));
    }
    const tpwBereichSelect = $('tpwBereichSelect');
    if (tpwBereichSelect) {
        tpwBereichSelect.addEventListener('change', (e) => handleTpwSelectionChange('bereich', e.target.value));
    }
    const tpwPeriodSelect = $('tpwPeriodSelect');
    if (tpwPeriodSelect) {
        tpwPeriodSelect.addEventListener('change', (e) => handleTpwSelectionChange('periode', e.target.value));
    }
    const tpwValueInput = $('tpwValueInput');
    if (tpwValueInput) {
        tpwValueInput.addEventListener('input', (e) => {
            tpwState.currentValue = e.target.value;
            refreshTpwSummary();
        });
    }

    // --- Modal Close Handlers ---
    const modals = [
        { id: 'infoModalMain', overlayId: 'infoModalMainOverlay', closeId: 'infoModalMainClose' },
        { id: 'infoModalDetail', overlayId: 'infoModalDetailOverlay', closeId: 'infoModalDetailClose' },
        { id: 'infoModalNested', overlayId: 'infoModalNestedOverlay', closeId: 'infoModalNestedClose' }
    ];

    modals.forEach(modal => {
        const closeButton = $(modal.closeId);
        const overlay = $(modal.overlayId);
        if (closeButton) closeButton.addEventListener('click', () => hideModal(modal.overlayId));
        if (overlay) overlay.addEventListener('click', (e) => {
            // Verhindere das Schliessen, wenn gerade die Grösse geändert wurde.
            if (e.target === overlay && !isResizing) {
                hideModal(modal.overlayId);
            }
        });
    });

    const nestedBackButton = document.getElementById(NESTED_MODAL_BACK_BUTTON_ID);
    if (nestedBackButton) {
        nestedBackButton.addEventListener('click', (e) => {
            e.preventDefault();
            const previousState = popNestedModalHistory();
            if (!previousState) {
                return;
            }
            const contentDiv = document.getElementById(NESTED_MODAL_CONTENT_ID);
            if (!contentDiv) {
                clearNestedModalHistory();
                return;
            }
            contentDiv.innerHTML = previousState.html;
            logFrontendInteraction('modal-history-back', {
                modalOverlayId: NESTED_MODAL_OVERLAY_ID,
                remainingHistory: nestedModalHistory.length
            });
            requestAnimationFrame(() => {
                contentDiv.scrollTop = previousState.scrollTop || 0;
            });
        });
    }
    updateNestedBackButton();

    // --- ESC Key to close top-most modal ---
    document.addEventListener('keydown', (e) => {
        if (e.key === "Escape") {
            if ($('infoModalNestedOverlay').style.display !== 'none') {
                hideModal('infoModalNestedOverlay');
            } else if ($('infoModalDetailOverlay').style.display !== 'none') {
                hideModal('infoModalDetailOverlay');
            } else if ($('infoModalMainOverlay').style.display !== 'none') {
                hideModal('infoModalMainOverlay');
            }
        }
    });


    // --- General Click Handler for Info Links ---
    document.addEventListener('click', async (e) => {
        const pauschaleLink = e.target.closest('a.pauschale-exp-link');
        if (pauschaleLink) {
            e.preventDefault();
            try {
                const code = (pauschaleLink.dataset.code || '').trim();
                if (!code) {
                    return;
                }
                logFrontendInteraction('pauschale-expansion-click', { code });
                const success = await showPauschaleInfoByCode(code);
                if (!success) {
                    const fallback = `<p>${escapeHtml(tDyn('noData'))}</p>`;
                    const detailTitle = $('infoModalDetailTitle');
                    if (detailTitle) {
                        detailTitle.textContent = `${tDyn('pauschaleDetails')} (${code})`;
                    }
                    showModal('infoModalDetailOverlay', fallback);
                }
            } catch (handlerError) {
                console.error('pauschale-exp-link handler failed', handlerError);
                logFrontendInteraction('pauschale-expansion-error', { message: (handlerError && handlerError.message) ? handlerError.message : String(handlerError) });
            }
            return;
        }

        const link = e.target.closest('a.info-link');
        if (link) {
            e.preventDefault();
            try {
                const code = (link.dataset.code || '').trim();
                const type = link.dataset.type;
                const dataContent = link.dataset.content;
                console.debug('[info-link] click', { type, code });
                logFrontendInteraction('info-link-click', {
                    type,
                    code,
                    hasContent: Boolean(dataContent),
                    contentLength: dataContent ? dataContent.length : 0
                });
                let html = '';

                // --- Build HTML content based on link type ---
                if (type === 'lkn') {
                    html = buildLknInfoHtmlFromCode(code);
                } else if (type === 'chapter') {
                    html = buildChapterInfoHtml(code);
                } else if (type === 'group') {
                    html = buildGroupInfoHtml(code);
                } else if (type === 'pauschale') {
                    html = buildPauschaleInfoHtmlFromCode(code);
                } else if (type === 'diagnosis') {
                    html = buildDiagnosisInfoHtmlFromCode(code);
                } else if (type === 'medication') {
                    html = buildMedicationInfoHtmlFromCode(code, link.dataset.table);
                } else if (type === 'lkn_table' || type === 'icd_table') {
                    if (dataContent) {
                        try {
                            const jsonData = JSON.parse(dataContent);
                            html = buildTablePopup(jsonData, code);
                        } catch (err) {
                            console.error("Error parsing JSON data for popup: ", err);
                            logFrontendInteraction('info-link-json-error', {
                                type,
                                code,
                                contentLength: dataContent.length,
                                message: (err && err.message) ? err.message : String(err)
                            });
                            html = `<p>Error loading table data.</p>`;
                        }
                    } else {
                        html = `<p>No data available for this table.</p>`;
                    }
                } else {
                    console.warn(`Unknown info-link type: ${type} for code: ${code}`);
                    logFrontendInteraction('info-link-unknown-type', { type, code });
                    html = `<p>Information for code ${escapeHtml(code)} (type: ${escapeHtml(type)}) not available.</p>`;
                }

                // --- Decide which modal to show ---
                const isInsideModal = e.target.closest('.info-modal');
                if (isInsideModal) {
                    logFrontendInteraction('info-link-open-modal', { target: 'nested', type, code });
                    // If the click is inside any modal, open the nested one
                    showModal('infoModalNestedOverlay', html);
                } else {
                    logFrontendInteraction('info-link-open-modal', { target: 'detail', type, code });
                    // Otherwise, open the first-level detail modal
                    showModal('infoModalDetailOverlay', html);
                }
            } catch (handlerError) {
                console.error('info-link handler failed', handlerError);
                logFrontendInteraction('info-link-handler-error', { message: (handlerError && handlerError.message) ? handlerError.message : String(handlerError) });
            }
        }
    });
});

// ─── 3 · Hauptlogik (Button‑Click) ────────────────────────────────────────
async function getBillingAnalysis() {
    // Vor einem neuen Request: Pauschalen-Kontext zurücksetzen
    try { showIcdToggle(false); } catch(e) {}
    try { setIcdFilterMode('all'); } catch(e) {}
    try { updateSelectedPauschaleDetails(null); } catch(e) {}
    lastTardocTotalTp = null;
    refreshTpwSummary();
    // Offene Dropdowns schliessen, damit Analyse nicht automatisch eine Liste öffnet
    try { if (typeof window.hideIcdDropdown === 'function') window.hideIcdDropdown(); } catch(e) {}
    try { if (typeof window.hideChopDropdown === 'function') window.hideChopDropdown(); } catch(e) {}
    console.log("[getBillingAnalysis] Funktion gestartet.");
    const userInput = $("userInput").value.trim();
    let mappedInput = userInput;
    try {
        if (Array.isArray(examplesData)) {
            const langKey = "value_" + currentLang.toUpperCase();
            const extKey = "extendedValue_" + currentLang.toUpperCase();
            const ex = examplesData.find(e => e[langKey] === userInput);
            if (ex && ex[extKey]) {
                mappedInput = ex[extKey];
            }
        }
    } catch (err) {
        console.error("[getBillingAnalysis] Example mapping failed:", err);
    }
    const icdInput = $("icdInput").value.trim().split(",").map(s => s.trim().toUpperCase()).filter(Boolean);
    const medicationInput = ($("medicationInput") ? $("medicationInput").value.trim().split(",").map(s => s.trim()).filter(Boolean) : []);
    const useIcdCheckbox = $('useIcdCheckbox')?.checked ?? true;
    const shouldSendUseIcd = icdInput.length > 0 || !useIcdCheckbox;
    const ageInput = $('ageInput')?.value; // Bleibt vorerst auskommentiert im HTML
    const age = ageInput ? parseInt(ageInput, 10) : null;
    const gender = $('genderSelect')?.value || null; // Bleibt vorerst auskommentiert im HTML
    const useIcdLogValue = shouldSendUseIcd ? useIcdCheckbox : false;
    console.log(`[getBillingAnalysis] Kontext: useIcd=${useIcdLogValue}, Age=${age}, Gender=${gender}`);
    console.log(`[getBillingAnalysis] ICD-Prüfung berücksichtigen: ${useIcdLogValue}${shouldSendUseIcd ? '' : ' (implizit deaktiviert, keine ICD-Angaben)'}`);
    let backendResponse = null;
    let rawResponseText = "";
    let htmlOutput = "";

    const outputDiv = $("output");
    if (!outputDiv) { console.error("Output element not found!"); return; }
    if (!userInput) { displayOutput(`<p class='error'>${tDyn('pleaseEnter')}</p>`); return; }

    showSpinner(tDyn('spinnerWorking'));
    displayOutput(`
        <div id="progressContainer">
            <div class="progress-track"></div>
            <div id="progressBar"></div>
            <div id="progressText"></div>
            <div id="progressTimer"></div>
        </div>
        `, 'info');
    startProgress();
    await showProgressStep(0, 'progressHintPrepare', 220);
    await showProgressStep(10, 'progressHintLlm1Processing');
    startLlm1Progress();
    armLlmProgressFallbacks();

    try {
        console.log("[getBillingAnalysis] Sende Anfrage an Backend...");
        const requestBody = {
            inputText: mappedInput,
            icd: icdInput,
            medications: medicationInput,
            age: age,
            gender: gender,
            lang: currentLang
        };
        if (shouldSendUseIcd) {
            requestBody.useIcd = useIcdCheckbox;
        }
        const res = await fetch("/api/analyze-billing", { method: "POST", headers: {"Content-Type":"application/json"}, body: JSON.stringify(requestBody) });
        rawResponseText = await res.text();
        stopLlm1Progress();
        clearProgressHintTimeouts();
        await showProgressStep(45, 'progressHintLlm1Review');
        // console.log("[getBillingAnalysis] Raw Response vom Backend erhalten:", rawResponseText.substring(0, 500) + "..."); // Gekürzt loggen
        if (!res.ok) { throw new Error(`Server antwortete mit ${res.status}`); }
        backendResponse = JSON.parse(rawResponseText);
        lastBackendResponse = backendResponse; // Für spätere Feedback-Übermittlung
        lastUserInput = userInput;
        pauschaleConditionsContext = backendResponse?.pauschale_context || null;
        console.log("[getBillingAnalysis] Backend-Antwort geparst.");
        console.log("[getBillingAnalysis] Empfangene Backend-Daten (Ausschnitt):", {
            begruendung_llm_stufe1: backendResponse?.llm_ergebnis_stufe1?.begruendung_llm}); // Logge spezifisch die Begründung       
        // console.log("[getBillingAnalysis] Empfangene Backend-Daten:", JSON.stringify(backendResponse, null, 2)); // Detailliertes Log

        // Strukturprüfung
        if (!backendResponse || !backendResponse.llm_ergebnis_stufe1 || !backendResponse.abrechnung || !backendResponse.abrechnung.type || !backendResponse.regel_ergebnisse_details || !backendResponse.llm_ergebnis_stufe2) {
             console.error("Unerwartete Hauptstruktur vom Server:", backendResponse);
             throw new Error("Unerwartete Hauptstruktur vom Server erhalten.");
        }
        console.log("[getBillingAnalysis] Backend-Antwortstruktur ist OK.");
        await showProgressStep(60, 'progressHintLlm2Processing', 180);

    } catch (e) {
        console.error("Fehler bei Backend-Anfrage oder Verarbeitung:", e);
        let msg = `<p class="error">Server-Fehler: ${escapeHtml(e.message)}</p>`;
        if (rawResponseText && (e instanceof SyntaxError || rawResponseText.length < 1000) && !e.message.includes(rawResponseText.substring(0,50))) {
             msg += `<details style="margin-top:1em"><summary>Raw Response (gekürzt)</summary><pre>${escapeHtml(rawResponseText.substring(0,1000))}${rawResponseText.length > 1000 ? '...' : ''}</pre></details>`;
        }
        displayOutput(msg);
        finishProgress();
        hideSpinner();
        return;
    }

    // --- Ergebnisse verarbeiten und anzeigen ---
    try {
        console.log("[getBillingAnalysis] Starte Ergebnisverarbeitung.");
        const llmResultStufe1 = backendResponse.llm_ergebnis_stufe1;
        const llmResultStufe2 = backendResponse.llm_ergebnis_stufe2; // Stufe 2 Ergebnisse holen
        // console.log("[getBillingAnalysis] LLM Stufe 2 Daten für Anzeige:", llmResultStufe2); // Detailliertes Log
        const abrechnung = backendResponse.abrechnung;
        const regelErgebnisseDetails = backendResponse.regel_ergebnisse_details || [];

        // --- Baue das FINALE HTML für den Output-Bereich ---
        htmlOutput = `<h2>${tDyn('resultFor')} «${escapeHtml(userInput)}»</h2>`;

        let finalResultHeader = "";
        let finalResultDetailsHtml = "";

        // 1. Hauptergebnis bestimmen und formatieren
        switch (abrechnung.type) {
            case "Pauschale":
                console.log("[getBillingAnalysis] Abrechnungstyp: Pauschale", abrechnung.details?.Pauschale);
                finalResultHeader = `<p class="final-result-header success"><b>${tDyn('billingPauschale')}</b></p>`;
                if (abrechnung.details) {
                    finalResultDetailsHtml = displayPauschale(abrechnung);
                    updateSelectedPauschaleDetails(abrechnung.details, abrechnung.bedingungs_pruef_html || '');
                    evaluatedPauschalenList = Array.isArray(abrechnung.evaluated_pauschalen) ? abrechnung.evaluated_pauschalen : [];
                    // Toggle nur anzeigen, wenn sinnvolle ICD-Liste vorhanden
                    const hasPotential = Array.isArray(selectedPauschaleDetails?.potential_icds) && selectedPauschaleDetails.potential_icds.length > 0;
                    showIcdToggle(!!hasPotential);
                    if (hasPotential) {
                        // Wähle gespeicherten Zustand (1 = pauschale) oder default 'all'
                        const savedMode = loadSavedIcdToggleMode();
                        setIcdFilterMode(savedMode);
                    } else {
                        setIcdFilterMode('all');
                    }
                } else {
                    finalResultDetailsHtml = `<p class='error'>${tDyn('errorPauschaleMissing')}</p>`;
                    updateSelectedPauschaleDetails(null);
                    evaluatedPauschalenList = [];
                    showIcdToggle(false);
                    setIcdFilterMode('all');
                }
                break;
            case "TARDOC":
                 console.log("[getBillingAnalysis] Abrechnungstyp: TARDOC");
                 finalResultHeader = `<p class="final-result-header success"><b>${tDyn('billingTardoc')}</b></p>`;
                 if (abrechnung.leistungen && abrechnung.leistungen.length > 0) {
                     finalResultDetailsHtml = displayTardocTable(abrechnung.leistungen, regelErgebnisseDetails);
                 } else {
                     finalResultDetailsHtml = `<p><i>${tDyn('noTardoc')}</i></p>`;
                 }
                 // Kein Umschalter für TARDOC
                 updateSelectedPauschaleDetails(null);
                 evaluatedPauschalenList = [];
                 showIcdToggle(false);
                 setIcdFilterMode('all');
                break;
            case "Error":
                console.error("[getBillingAnalysis] Abrechnungstyp: Error", abrechnung.message);
                finalResultHeader = `<p class="final-result-header error"><b>${tDyn('billingError')}</b></p>`;
                finalResultDetailsHtml = `<p><i>Grund: ${escapeHtml(abrechnung.message || 'Unbekannter Fehler')}</i></p>`;
                break;
            default:
                console.error("[getBillingAnalysis] Unbekannter Abrechnungstyp:", abrechnung.type);
                finalResultHeader = `<p class="final-result-header error"><b>${tDyn('billingUnknown')}</b></p>`;
                finalResultDetailsHtml = `<p class='error'>Interner Fehler: Unbekannter Abrechnungstyp '${escapeHtml(abrechnung.type)}'.</p>`;
        }

        // Füge Hauptergebnis zum Output hinzu
        htmlOutput += finalResultHeader;
        // 2. Details zur finalen Abrechnung (Pauschale/TARDOC) hinzufügen
        htmlOutput += finalResultDetailsHtml;
        await showProgressStep(70, 'progressHintLlm2Processing', 150);
        // 3. LLM Stufe 1 Ergebnisse
        htmlOutput += generateLlmStage1Details(llmResultStufe1);
        // 4. LLM Stufe 2 Ergebnisse (Mapping)
        const stage2Html = generateLlmStage2Details(llmResultStufe2); // Ergebnis holen
        await showProgressStep(80, 'progressHintRuleCheck', 150);
        // console.log("[getBillingAnalysis] Ergebnis von generateLlmStage2Details:", stage2Html.substring(0, 100) + "..."); // Loggen
        htmlOutput += stage2Html; // Hinzufügen
        // 5. Regelprüfungsdetails
        htmlOutput += generateRuleCheckDetails(regelErgebnisseDetails, abrechnung.type === "Error");
        await showProgressStep(90, 'progressHintFinalizing', 180);
        await showProgressStep(100, 'progressHintDone', 600);

        // --- Finalen Output anzeigen ---
        displayOutput(htmlOutput);
        setTimeout(finishProgress, 900);
        console.log("[getBillingAnalysis] Frontend-Verarbeitung abgeschlossen.");
        hideSpinner();

    } catch (error) {
         console.error("[getBillingAnalysis] Unerwarteter Fehler bei Ergebnisverarbeitung im Frontend:", error);
        displayOutput(`<p class="error">Ein interner Fehler im Frontend ist aufgetreten: ${escapeHtml(error.message)}</p><pre>${escapeHtml(error.stack)}</pre>`);
        finishProgress();
        hideSpinner();
    }
}

// ─── 4 · Hilfsfunktionen zur ANZEIGE ────────────────────────────────────────

// Funktion zum Speichern/Laden des Checkbox-Status
function saveIcdCheckboxState() {
    const checkbox = $('useIcdCheckbox');
    if (!checkbox) return;
    try {
        localStorage.setItem('useIcdRelevance', checkbox.checked ? 'true' : 'false');
    } catch (err) {
        console.warn('Unable to persist useIcdRelevance in localStorage:', err);
    }
}

function loadIcdCheckboxState() {
    const checkbox = $('useIcdCheckbox');
    if (!checkbox) return;
    let savedState = null;
    try {
        savedState = localStorage.getItem('useIcdRelevance');
    } catch (err) {
        console.warn('Unable to read useIcdRelevance from localStorage:', err);
    }
    checkbox.checked = (savedState === null || savedState === 'true');
    checkbox.addEventListener('change', saveIcdCheckboxState);
}

// Generiert den <details> Block für LLM Stufe 1 Ergebnisse
function generateLlmStage1Details(llmResult) {
    if (!llmResult) return "";

    const identifiedLeistungen = llmResult.identified_leistungen || [];
    const extractedInfo = llmResult.extracted_info || {};
    const begruendung = llmResult.begruendung_llm || 'N/A';

    let detailsHtml = `<details><summary>${tDyn('llmDetails1')}</summary>`;
    detailsHtml += `<div>`;

    if (identifiedLeistungen.length > 0) {
        detailsHtml += `<p><b>${tDyn('llmIdent')}</b></p><ul>`;
        identifiedLeistungen.forEach(l => {
            // Hole Beschreibung aus lokalen Daten, wenn möglich
            const desc = beschreibungZuLKN(l.lkn);
            const mengeText = l.menge !== null && l.menge !== 1 ? ` (Menge: ${l.menge})` : ''; // Menge nur anzeigen wenn != 1
            const lknLink = createInfoLink(l.lkn, 'lkn');
            detailsHtml += `<li><b>LKN ${lknLink}:</b> ${escapeHtml(desc)}${mengeText}</li>`;
        });
        detailsHtml += `</ul>`;
    } else {
        detailsHtml += `<p><i>${tDyn('llmNoneIdent')}</i></p>`;
    }

    const rankedList = llmResult.ranking_candidates || [];
    if (Array.isArray(rankedList) && rankedList.length > 1) {
        detailsHtml += `<p><b>${tDyn('llmRankedLkns')}</b></p><ol>`;
        rankedList.forEach(code => {
            const desc = beschreibungZuLKN(code);
            detailsHtml += `<li>${createInfoLink(code,'lkn')} ${escapeHtml(desc)}</li>`;
        });
        detailsHtml += `</ol>`;
    }

    let extractedDetails = [];
    if (extractedInfo.dauer_minuten !== null) extractedDetails.push(`Dauer: ${extractedInfo.dauer_minuten} Min.`);
    if (extractedInfo.menge_allgemein !== null && extractedInfo.menge_allgemein !== 0) extractedDetails.push(`Menge: ${extractedInfo.menge_allgemein}`);
    if (extractedInfo.geschlecht !== null && extractedInfo.geschlecht !== 'null' && extractedInfo.geschlecht !== 'unbekannt') extractedDetails.push(`Geschlecht: ${extractedInfo.geschlecht}`);

    if (extractedDetails.length > 0) {
        detailsHtml += `<p><b>${tDyn('llmExtr')}</b> ${extractedDetails.join(', ')}</p>`;
    } else {
        detailsHtml += `<p><i>${tDyn('llmNoneExtr')}</i></p>`
    }

    detailsHtml += `<p><b>${tDyn('llmReason')}</b></p><p style="white-space: pre-wrap;">${escapeHtml(begruendung)}</p>`;
    detailsHtml += `</div></details>`;
    return detailsHtml;
}

// Generiert den <details> Block für LLM Stufe 2 Ergebnisse (Mapping)
function generateLlmStage2Details(llmResultStufe2) {
    // console.log("generateLlmStage2Details aufgerufen mit:", llmResultStufe2);

    // Prüft auf die korrekte Struktur für Mapping-Ergebnisse
    if (!llmResultStufe2 || !llmResultStufe2.mapping_results || !Array.isArray(llmResultStufe2.mapping_results) || llmResultStufe2.mapping_results.length === 0) {
        // console.log("generateLlmStage2Details: Keine gültigen Mapping-Ergebnisse gefunden, gebe leeren String zurück.");
        return ""; // Nichts anzeigen, wenn keine Mapping-Ergebnisse vorhanden sind
    }

    const mappingResults = llmResultStufe2.mapping_results;
    let detailsHtml = `<details><summary>${tDyn('llmDetails2')}</summary>`;
    detailsHtml += `<div>`;
    detailsHtml += `<p>${tDyn('mappingIntro')}</p><ul>`;

    try {
        mappingResults.forEach(map => {
            const tardocLkn = escapeHtml(map.tardoc_lkn || 'N/A');
            // Hole Beschreibung für TARDOC LKN aus lokalen Daten
            const tardocDesc = beschreibungZuLKN(map.tardoc_lkn);
            const mappedLkn = map.mapped_lkn ? escapeHtml(map.mapped_lkn) : null;
            // Hole Beschreibung für gemappte LKN aus lokalen Daten
            const mappedDesc = mappedLkn ? beschreibungZuLKN(mappedLkn) : '';

            detailsHtml += `<li><b>TARDOC LKN: ${tardocLkn}</b> (${escapeHtml(tardocDesc)})`;
            if (mappedLkn) {
                detailsHtml += `<br>→ Gemappt auf: <b style="color:var(--accent);">${mappedLkn}</b>${mappedDesc !== mappedLkn ? ' (' + escapeHtml(mappedDesc) + ')' : ''}`;
            } else {
                detailsHtml += `<br>→ <i style="color:var(--danger);">Kein passendes Mapping gefunden.</i>`;
                if(map.error) { // Zeige Fehler, falls vom Backend gesendet
                    detailsHtml += ` <span style="font-size:0.9em; color:#888;">(Fehler: ${escapeHtml(map.error)})</span>`;
                }
            }
            detailsHtml += `</li>`;
        });
    } catch (e) {
        console.error("Fehler in generateLlmStage2Details forEach:", e);
        detailsHtml += "<li>Fehler bei der Anzeige der Mapping-Details.</li>";
    }

    detailsHtml += `</ul>`;
    detailsHtml += `</div></details>`;
    // console.log("generateLlmStage2Details: Generiertes HTML (gekürzt):", detailsHtml.substring(0, 200) + "...");
    return detailsHtml;
}


// Generiert den <details> Block für Regelprüfungsdetails
function generateRuleCheckDetails(regelErgebnisse, isErrorCase = false) {
    if (!regelErgebnisse || regelErgebnisse.length === 0) return "";

    const hasRelevantInfo = regelErgebnisse.some(r => r.regelpruefung && r.regelpruefung.fehler && r.regelpruefung.fehler.length > 0);
    const hasOnlyNoLknError = regelErgebnisse.length === 1 && regelErgebnisse[0].lkn === null && regelErgebnisse[0]?.regelpruefung?.fehler?.[0]?.includes("Keine gültige LKN");

    // Zeige nur, wenn relevante Infos da sind, es ein Fehlerfall ist, oder der einzige Fehler "Keine LKN" ist.
    if (!hasRelevantInfo && !isErrorCase && !hasOnlyNoLknError) {
         return "";
    }

    let detailsHtml = `<details ${isErrorCase || hasOnlyNoLknError ? 'open' : ''}><summary>${tDyn('ruleDetails')}</summary><div>`;

    regelErgebnisse.forEach((resultItem) => {
        const lkn = resultItem.lkn || 'N/A';
        // const initialMenge = resultItem.initiale_menge || 'N/A'; // Wird aktuell nicht angezeigt
        const finalMenge = resultItem.finale_menge;
        const regelpruefung = resultItem.regelpruefung;

        // Zeige LKN nur, wenn sie nicht null ist (für den "Keine LKN gefunden" Fall)
        if (lkn !== 'N/A') {
             detailsHtml += `<h5 style="margin-bottom: 2px; margin-top: 8px;">LKN: ${escapeHtml(lkn)} (Finale Menge: ${finalMenge})</h5>`;
        }

        if (regelpruefung) {
            if (!regelpruefung.abrechnungsfaehig) {
                 detailsHtml += `<p style="color: var(--danger);"><b>${tDyn('ruleNotBill')}</b></p>`; // Grund wird in Fehlern gelistet
                 if (regelpruefung.fehler && regelpruefung.fehler.length > 0) {
                      detailsHtml += `<ul>`;
                      regelpruefung.fehler.forEach(fehler => { detailsHtml += `<li class="error">${escapeHtml(fehler)}</li>`; });
                      detailsHtml += `</ul>`;
                 } else if (lkn !== 'N/A') { // Nur anzeigen, wenn es eine LKN gab
                      detailsHtml += `<p><i>Kein spezifischer Grund angegeben.</i></p>`;
                 }
            } else if (regelpruefung.fehler && regelpruefung.fehler.length > 0) {
                 detailsHtml += `<p><b>${tDyn('ruleHints')}</b></p><ul>`;
                 regelpruefung.fehler.forEach(hinweis => {
                      const lcHint = hinweis.toLowerCase();
                      const isReduction = lcHint.includes("menge auf") || lcHint.includes("quantité réduite") || lcHint.includes("quantità ridotta");
                      const style = isReduction ? "color: var(--danger); font-weight: bold;" : "";
                      detailsHtml += `<li style="${style}">${escapeHtml(hinweis)}</li>`;
                 });
                 detailsHtml += `</ul>`;
            } else if (lkn !== 'N/A') { // Nur anzeigen, wenn es eine LKN gab
                 detailsHtml += `<p style="color: var(--accent);"><i>${tDyn('ruleOk')}</i></p>`;
            }
        } else if (lkn !== 'N/A') { // Nur anzeigen, wenn es eine LKN gab
             detailsHtml += `<p><i>${tDyn('ruleNone')}</i></p>`;
        }
    });

    detailsHtml += `</div></details>`;
    return detailsHtml;
}


// Zeigt Pauschalen-Details an
function displayPauschale(abrechnungsObjekt) {
    const pauschaleDetails = abrechnungsObjekt.details;
    const bedingungsHtml = abrechnungsObjekt.bedingungs_pruef_html || '';
    const bedingungsFehler = Array.isArray(abrechnungsObjekt.bedingungs_fehler) ? abrechnungsObjekt.bedingungs_fehler : [];
    const conditions_met_structured = (abrechnungsObjekt.conditions_met === true) || (abrechnungsObjekt.is_valid_structured === true);

    if (!pauschaleDetails) return `<p class='error'>${tDyn('errorPauschaleMissing')}</p>`;

    // Steuer die TPW-Zusammenfassung auch bei Pauschalen (Taxpunkte anzeigen)
    let parsedTaxpoints = NaN;
    if (pauschaleDetails.Taxpunkte !== undefined && pauschaleDetails.Taxpunkte !== null) {
        const norm = String(pauschaleDetails.Taxpunkte).replace(',', '.').trim();
        if (norm !== '') {
            parsedTaxpoints = Number.parseFloat(norm);
        }
    }
    lastTardocTotalTp = Number.isFinite(parsedTaxpoints) ? parsedTaxpoints : null;
    refreshTpwSummary();

    const hasConditionsHtml = typeof bedingungsHtml === 'string' && bedingungsHtml.trim() !== '';
    const metaItems = [];
    const logicStatusKey = conditions_met_structured ? 'logicOk' : 'logicNotOk';
    const logicStatusText = stripOuterParens(tDyn(logicStatusKey));
    const logicPillClass = conditions_met_structured ? 'status-positive' : 'status-negative';
    metaItems.push({
        label: tDyn('logicStatusLabel'),
        valueHtml: `<span class="status-pill ${logicPillClass}">${escapeHtml(logicStatusText)}</span>`
    });

    const extraSections = [];
    if (bedingungsFehler.length > 0) {
        const statusLabelKey = conditions_met_structured ? 'overallOk' : 'overallNotOk';
        const statusHeading = `${tDyn('condDetails')} (${tDyn(statusLabelKey)})`;
        const listItems = bedingungsFehler.map(item => `<li>${escapeHtml(item)}</li>`).join('');
        extraSections.push(`
            <section class="info-section info-section-status">
                <h3>${escapeHtml(statusHeading)}</h3>
                <ul class="info-hint-list">${listItems}</ul>
            </section>
        `);
    }

    const summaryHtml = renderPauschaleInfoContentFromDetails(pauschaleDetails, {
        extraMetaItems: metaItems,
        extraSections,
        hasStructuredLogic: hasConditionsHtml,
    });

    return `<div class="selected-pauschale-block">${summaryHtml}</div>`;
}


// Zeigt TARDOC-Tabelle an
function displayTardocTable(tardocLeistungen, ruleResultsDetailsList = []) {
    if (!tardocLeistungen || tardocLeistungen.length === 0) {
        lastTardocTotalTp = null;
        refreshTpwSummary();
        return `<p><i>${tDyn('noTardoc')}</i></p>`;
    }

    let tardocTableBody = "";
    let gesamtTP = 0;
    let hasHintsOverall = false;

    const sortedLeistungen = [...tardocLeistungen].sort((a, b) => String(a.lkn).localeCompare(String(b.lkn)));

    for (const leistung of sortedLeistungen) {
        const lkn = leistung.lkn;
        const anzahl = leistung.menge;
        const tardocDetails = processTardocLookup(lkn); // Lokale Suche

        if (!tardocDetails.applicable) {
             tardocTableBody += `<tr><td colspan="7" class="error">${tDyn('errorLkn',{lkn: escapeHtml(lkn)})}</td></tr>`;
             continue;
        }

        const name = leistung.beschreibung || tardocDetails.leistungsname || 'N/A';
        const al = tardocDetails.al;
        const ipl = tardocDetails.ipl;
        let regelnHtml = tardocDetails.regeln ? `<p><b>${tDyn('tardocRule')}</b> ${tardocDetails.regeln}</p>` : '';
        const interpretationText = getInterpretation(String(lkn), false);
        if (interpretationText) {
            if (regelnHtml) regelnHtml += "<hr style='margin: 5px 0; border-color: #eee;'>";
            regelnHtml += `<p><b>Interpretation:</b> ${escapeHtml(interpretationText)}</p>`;
        }

        const ruleResult = ruleResultsDetailsList.find(r => r.lkn === lkn);
        let hasHintForThisLKN = false;
        if (ruleResult && ruleResult.regelpruefung && ruleResult.regelpruefung.fehler && ruleResult.regelpruefung.fehler.length > 0) {
             if (regelnHtml) regelnHtml += "<hr style='margin: 5px 0; border-color: #eee;'>";
             regelnHtml += `<p><b>${tDyn('ruleHints')}</b></p><ul>`;
             ruleResult.regelpruefung.fehler.forEach(hinweis => {
                  const lcHint = hinweis.toLowerCase();
                  const isReduction = lcHint.includes("menge auf") || lcHint.includes("quantité réduite") || lcHint.includes("quantità ridotta");
                  const style = isReduction ? "color: var(--danger); font-weight: bold;" : "";
                  if (isReduction) {
                      hasHintForThisLKN = true;
                      hasHintsOverall = true;
                  }
                  regelnHtml += `<li style="${style}">${escapeHtml(hinweis)}</li>`;
             });
             regelnHtml += `</ul>`;
        }

        const total_tp = (al + ipl) * anzahl;
        gesamtTP += total_tp;
        const detailsSummaryStyle = hasHintForThisLKN ? ' class="rule-hint-trigger"' : '';

        const regelnCellContent = regelnHtml
            ? `<details><summary${detailsSummaryStyle}>${tDyn('thRegeln')}</summary><div class="tardoc-rule-content">${regelnHtml}</div></details>`
            : tDyn('none');

        tardocTableBody += `
            <tr>
                <td>${createInfoLink(lkn,'lkn')}</td><td>${escapeHtml(name)}</td>
                <td>${al.toFixed(2)}</td><td>${ipl.toFixed(2)}</td>
                <td>${anzahl}</td><td>${total_tp.toFixed(2)}</td>
                <td>${regelnCellContent}</td>
            </tr>`;
    }

    const overallSummaryClass = hasHintsOverall ? ' class="rule-hint-trigger"' : '';
    let html = `<details open><summary ${overallSummaryClass}>${tDyn('tardocDetails')} (${tardocLeistungen.length} Positionen)</summary>`;
    html += `
        <div class="tardoc-table-wrapper">
            <table border="1" class="tardoc-table">
                <colgroup>
                    <col class="col-lkn">
                    <col class="col-name">
                    <col class="col-al">
                    <col class="col-ipl">
                    <col class="col-anzahl">
                    <col class="col-total">
                    <col class="col-regeln">
                </colgroup>
                <thead><tr><th>${tDyn('thLkn')}</th><th>${tDyn('thLeistung')}</th><th>${tDyn('thAl')}</th><th>${tDyn('thIpl')}</th><th>${tDyn('thAnzahl')}</th><th>${tDyn('thTotal')}</th><th>${tDyn('thRegeln')}</th></tr></thead>
                <tbody>${tardocTableBody}</tbody>
                <tfoot><tr><th colspan="5" class="tardoc-total-label">${tDyn('gesamtTp')}</th><td class="tardoc-total-value">${gesamtTP.toFixed(2)}</td><td></td></tr></tfoot>
            </table>
        </div>`;
    html += `</details>`;
    lastTardocTotalTp = gesamtTP;
    refreshTpwSummary();
    return html;
}


// Hilfsfunktion: Sucht TARDOC-Details lokal
function processTardocLookup(lkn) {
    let result = { applicable: false, data: null, al: 0, ipl: 0, leistungsname: 'N/A', regeln: '' };
    // Schlüssel anpassen, falls nötig (aus TARDOC_Tarifpositionen...)
    const TARDOC_LKN_KEY = 'LKN';
    const AL_KEY = 'AL_(normiert)';
    const IPL_KEY = 'IPL_(normiert)';
    const DESC_KEY_1 = 'Bezeichnung';
    const RULES_KEY_1 = 'Regeln';

    if (!Array.isArray(data_tardocGesamt) || data_tardocGesamt.length === 0) {
        console.warn(`TARDOC-Daten nicht geladen oder leer für LKN ${lkn}.`);
        return result;
    }
    const tardocPosition = data_tardocGesamt.find(item => item && item[TARDOC_LKN_KEY] && String(item[TARDOC_LKN_KEY]).toUpperCase() === lkn.toUpperCase());
    if (!tardocPosition) {
        // console.warn(`LKN ${lkn} nicht in lokalen TARDOC-Daten gefunden.`); // Weniger verbose
        return result;
    }

    result.applicable = true; result.data = tardocPosition;
    const parseGermanFloat = (value) => {
        if (typeof value === 'string') {
            return parseFloat(value.replace(',', '.')) || 0;
        }
        return parseFloat(value) || 0;
    };
    result.al = parseGermanFloat(tardocPosition[AL_KEY]);
    result.ipl = parseGermanFloat(tardocPosition[IPL_KEY]);
    result.leistungsname = getLangField(tardocPosition, DESC_KEY_1) || 'N/A';
    result.regeln = formatRules(tardocPosition[RULES_KEY_1]);
    return result;
}


// ─── 5 · Enter-Taste als Default für Return ─────────────────
document.addEventListener("DOMContentLoaded", function() {
    const uiField = $("userInput");
    const icdField = $("icdInput");
    const medicationField = $("medicationInput");

    function handleEnter(e) {
        if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
             // Prüfe, ob Daten geladen wurden (mindestens der Leistungskatalog)
             if (Array.isArray(data_leistungskatalog) && data_leistungskatalog.length > 0) {
                  getBillingAnalysis();
             } else {
                  console.log("Daten noch nicht geladen, warte...");
                  const button = $('analyzeButton');
                  if(button && !button.disabled) { // Nur ändern, wenn nicht schon deaktiviert
                     const originalText = button.textContent;
                     button.textContent = "Lade Daten...";
                     // Optional: Nach kurzer Zeit wieder zurücksetzen, falls das Laden hängt
                     setTimeout(() => {
                         if (button.textContent === "Lade Daten...") {
                             button.textContent = originalText;
                         }
                     }, 3000);
                  }
             }
        }
    }

    if (uiField) uiField.addEventListener("keydown", handleEnter);
    if (icdField) icdField.addEventListener("keydown", handleEnter);
    if (medicationField) medicationField.addEventListener("keydown", handleEnter);
});

// Mache die Hauptfunktion global verfügbar
window.getBillingAnalysis = getBillingAnalysis;
