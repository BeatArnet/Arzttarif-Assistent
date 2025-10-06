// calculator.js - Vollständige Version (06.05.2025)
console.info('calculator.js build 2025-09-22T1215 loaded');
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

// Zusätzliche Pauschalen-Infos
let selectedPauschaleDetails = null;
let evaluatedPauschalenList = [];
let lastBackendResponse = null; // Speichert die letzte Serverantwort für Feedback
let lastUserInput = "";
let progressTimes = {};
let elapsedTimer = null;
let llm1BarInterval = null;
// ICD-Filtermodus: 'all' | 'pauschale'
let icdFilterMode = 'all';
// Spiegeln auf window, damit inline-Scripts (index.html) darauf zugreifen können
window.icdFilterMode = icdFilterMode;
window.selectedPauschaleDetails = selectedPauschaleDetails;

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

function updateSelectedPauschaleDetails(details){
    selectedPauschaleDetails = details || null;
    window.selectedPauschaleDetails = selectedPauschaleDetails;
}

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
        reasonPauschale: 'Begründung Pauschalenauswahl',
        pauschaleDetails: 'Details Pauschale',
        condDetails: 'Details Pauschalen-Bedingungsprüfung',
        overallOk: 'Gesamtlogik erfüllt',
        overallNotOk: 'Gesamtlogik NICHT erfüllt',
        logicOk: '(Logik erfüllt)',
        logicNotOk: '(Logik NICHT erfüllt)',
        errorLkn: 'Fehler: Details für LKN {lkn} nicht gefunden!',
        noData: 'Keine Daten vorhanden.',
        groupNoData: 'Keine Daten zur Leistungsgruppe {code}.',
        potentialIcds: 'Mögliche ICD-Diagnosen',
        thIcdCode: 'ICD Code',
        thIcdText: 'Beschreibung',
        diffTaxpoints: 'Differenz Taxpunkte',
        implantsIncluded: 'Implantate inbegriffen',
        dignitiesLabel: 'Dignitäten',
        descriptionNotFound: 'Beschreibung nicht gefunden',
        progressLLM1Request: 'Anfrage an LLM 1 gestellt...',
        progressLLM1Response: 'Antwort von LLM 1 erhalten...',
        progressPlausi: 'Plausibilisierung läuft...',
        progressLLM2Request: 'Anfrage an LLM 2 gestellt...',
        progressLLM2Response: 'Antwort von LLM 2 erhalten...',
        progressFinal: 'Finale Plausibilisierung...',
        progressDone: 'Fertig.',
        progressQuery: 'Anfrage: «{text}»',
        progressDuration: 'Dauer: {ms} ms',
        progressCandidates: 'Mögliche LKN: {count}'
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
        reasonPauschale: 'Justification du choix du forfait',
        pauschaleDetails: 'Détails forfait',
        condDetails: 'Détails vérification des conditions du forfait',
        overallOk: 'Logique globale remplie',
        overallNotOk: 'Logique globale NON remplie',
        logicOk: '(Logique remplie)',
        logicNotOk: '(Logique NON remplie)',
        errorLkn: 'Erreur : détails pour NPL {lkn} introuvables !',
        noData: 'Aucune donnée disponible.',
        groupNoData: 'Aucune donnée pour le groupe de prestations {code}.',
        potentialIcds: 'Diagnostics ICD possibles',
        thIcdCode: 'Code ICD',
        thIcdText: 'Description',
        diffTaxpoints: 'Différence points tarifaires',
        implantsIncluded: 'Implants inclus',
        dignitiesLabel: 'Dignités',
        descriptionNotFound: 'Description non trouvée',
        progressLLM1Request: 'Requête au LLM 1 envoyée...',
        progressLLM1Response: 'Réponse du LLM 1 reçue...',
        progressPlausi: 'Vérification de plausibilité...',
        progressLLM2Request: 'Requête au LLM 2 envoyée...',
        progressLLM2Response: 'Réponse du LLM 2 reçue...',
        progressFinal: 'Plausibilisation finale...',
        progressDone: 'Terminé.',
        progressQuery: 'Requête : «{text}»',
        progressDuration: 'Durée : {ms} ms',
        progressCandidates: 'NPL potentielles : {count}'
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
        reasonPauschale: 'Motivazione scelta forfait',
        pauschaleDetails: 'Dettagli forfait',
        condDetails: 'Dettagli verifica condizioni forfait',
        overallOk: 'Logica complessiva soddisfatta',
        overallNotOk: 'Logica complessiva NON soddisfatta',
        logicOk: '(Logica soddisfatta)',
        logicNotOk: '(Logica NON soddisfatta)',
        errorLkn: 'Errore: dettagli per NPL {lkn} non trovati!',
        noData: 'Nessun dato disponibile.',
        groupNoData: 'Nessun dato per il gruppo di prestazioni {code}.',
        potentialIcds: 'Possibili diagnosi ICD',
        thIcdCode: 'Codice ICD',
        thIcdText: 'Descrizione',
        diffTaxpoints: 'Differenza punti tariffari',
        implantsIncluded: 'Impianti inclusi',
        dignitiesLabel: 'Dignità',
        descriptionNotFound: 'Descrizione non trovata',
        progressLLM1Request: 'Richiesta al LLM 1 inviata...',
        progressLLM1Response: 'Risposta dal LLM 1 ricevuta...',
        progressPlausi: 'Verifica di plausibilità...',
        progressLLM2Request: 'Richiesta al LLM 2 inviata...',
        progressLLM2Response: 'Risposta dal LLM 2 ricevuta...',
        progressFinal: 'Plausibilizzazione finale...',
        progressDone: 'Completato.',
        progressQuery: 'Richiesta: «{text}»',
        progressDuration: 'Durata: {ms} ms',
        progressCandidates: 'Possibili NPL: {count}'
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
    dignitaeten: 'data/DIGNITAETEN.json' // Path for the new dignities file
};

// Referenz zum Mouse Spinner
let mouseSpinnerElement = null;
let mouseMoveHandler = null; // Zum Speichern des Handlers für removeEventListener

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

function createInfoLink(code, type) {
    return `<a href="#" class="info-link" data-type="${type}" data-code="${escapeHtml(code)}">${escapeHtml(code)}</a>`;
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
    contentDiv.innerHTML = htmlContent;
    modalOverlay.style.display = 'block';
    console.debug('[modal] opened', modalOverlayId);
    logFrontendInteraction('modal-open-success', { modalOverlayId });

    const modalDialog = modalOverlay.querySelector('.info-modal');
    if (modalDialog) {
        // Reset transform property to ensure it opens at the CSS-defined position
        modalDialog.style.transform = 'translate(0px, 0px)';
        if (!modalDialog.classList.contains('draggable-initialized')) {
            makeModalDraggable(modalDialog);
            modalDialog.classList.add('draggable-initialized');
        }
    }
}

function hideModal(modalOverlayId) {
    const modalOverlay = $(modalOverlayId);
    if (modalOverlay) {
        modalOverlay.style.display = 'none';
    }
}

// Globale Variable zur Verfolgung des Resize-Zustands
let isResizing = false;

function makeModalDraggable(modalElement) {
    const handle = modalElement.querySelector('.modal-header') || modalElement;
    let isDragging = false;
    let startX, startY;
    let x = 0, y = 0; // To store the current translation

    function getCurrentTransform() {
        const style = window.getComputedStyle(modalElement);
        const matrix = new DOMMatrix(style.transform);
        x = matrix.m41;
        y = matrix.m42;
    }

    handle.addEventListener('mousedown', (e) => {
        const rect = modalElement.getBoundingClientRect();
        const resizeHandleSize = 20;

        // Prüfen, ob der Klick im Resize-Bereich (unten rechts) ist
        if (e.clientX > rect.right - resizeHandleSize && e.clientY > rect.bottom - resizeHandleSize) {
            isResizing = true;
            return;
        }

        isDragging = true;
        getCurrentTransform();
        startX = e.clientX;
        startY = e.clientY;
        handle.style.cursor = 'grabbing';
    });

    document.addEventListener('mousemove', (e) => {
        if (isDragging) {
            e.preventDefault();
            const dx = e.clientX - startX;
            const dy = e.clientY - startY;
            modalElement.style.transform = `translate(${x + dx}px, ${y + dy}px)`;
        }
    });

    document.addEventListener('mouseup', () => {
        if (isDragging) {
            isDragging = false;
            handle.style.cursor = 'grab';
        }
        // WICHTIG: Setze isResizing nach einer kurzen Verzögerung zurück,
        // damit der Click-Handler des Overlays es zuerst prüfen kann.
        if (isResizing) {
            setTimeout(() => {
                isResizing = false;
            }, 0);
        }
    });

    handle.style.cursor = 'grab';
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

function buildLknInfoHtmlFromCode(code) {
    const pos = findTardocPosition(code);
    if (pos) return buildLknInfoHtml(pos);

    const cat = findCatalogEntry(code);
    if (cat) {
        const desc = getLangField(cat, 'Beschreibung') || '';
        const interp = getLangField(cat, 'MedizinischeInterpretation');
        return `
            <h3>${escapeHtml(cat.LKN)} - ${escapeHtml(desc)}</h3>
            ${interp ? `<p>${escapeHtml(interp)}</p>` : ''}
        `;
    }
    return `<p>${tDyn('noData')}</p>`;
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

function buildLknInfoHtml(pos) {
    if (!pos) return `<p>${tDyn('noData')}</p>`;
    const dign = Array.isArray(pos.Qualitative_Dignität) ? pos.Qualitative_Dignität.map(d => escapeHtml(d.DignitaetText)).join(', ') : '';
    let groups = '';
    if (Array.isArray(pos.Leistungsgruppen)) {
        groups = pos.Leistungsgruppen.map(g => `${createInfoLink(g.Gruppe,'group')}: ${escapeHtml(g.Text || '')}`).join('<br>');
    }
    const rules = formatRules(pos.Regeln);
    const interp = getInterpretation(String(pos.LKN), false);
    const desc = getLangField(pos, 'Bezeichnung') || '';
    return `
        <h3>${escapeHtml(pos.LKN)} - ${escapeHtml(desc)}</h3>
        ${interp ? `<p>${escapeHtml(interp)}</p>` : ''}
        <p><b>AL:</b> ${pos['AL_(normiert)']} <b>IPL:</b> ${pos['IPL_(normiert)']}</p>
        ${dign ? `<p><b>Dignitäten:</b> ${dign}</p>` : ''}
        ${groups ? `<p><b>Leistungsgruppen:</b><br>${groups}</p>` : ''}
        ${rules ? `<p><b>Regeln:</b> ${rules}</p>` : ''}
    `;
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


function buildPauschaleInfoHtml(idx) {
    if (!evaluatedPauschalenList[idx]) return '';
    const p = evaluatedPauschalenList[idx];
    const parse = v => parseFloat(String(v).replace(',', '.')) || 0;
    const selTp = parse(selectedPauschaleDetails?.Taxpunkte);
    const otherTp = parse(p.details?.Taxpunkte);
    const diff = otherTp - selTp;
    const diffTxt = `${diff >= 0 ? '+' : ''}${diff.toFixed(2)}`;
    let html = `<h4>${escapeHtml(p.details?.Pauschale || '')} <small>${tDyn('diffTaxpoints')}: ${diffTxt}</small></h4>`;
    html += displayPauschale(p);
    return html;
}

function showPauschaleInfoByCode(code) {
    const norm = String(code || '').toUpperCase();
    const idx = evaluatedPauschalenList.findIndex(p => String(p.details?.Pauschale || '').toUpperCase() === norm);
    if (idx === -1) return;
    const html = buildPauschaleInfoHtml(idx);
    showInfoModal(html);
}

function buildTablePopup(data, tableName) {
    let tableHtml = `<div class="info-modal-header" style="cursor: grab;"><h2>Tabelle: ${escapeHtml(tableName)}</h2></div>`;
    tableHtml += `<div class="info-modal-body" style="max-height: calc(0.75 * 100vh); overflow-y: auto;">`;
    tableHtml += '<table><thead><tr><th>Code</th><th>Text</th></tr></thead><tbody>';
    data.forEach(row => {
        const code = row.Code || '';
        const text = row.Code_Text || '';
        const isServiceCatalog = row.Tabelle_Typ === 'service_catalog';
        const isMedication = row.Tabelle_Typ === 402;
        const isIcd = row.Tabelle_Typ === 'icd';

        let style = '';
        let codeDisplay = escapeHtml(code);

        if (isServiceCatalog) {
            style = 'font-weight: bold;';
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

// --- Mouse Spinner Funktionen ---
function updateSpinnerPosition(event) {
    if (mouseSpinnerElement) {
        mouseSpinnerElement.style.left = (event.clientX + 15) + 'px';
        mouseSpinnerElement.style.top = (event.clientY + 15) + 'px';
    }
}

function showSpinner(text = tDyn('spinnerWorking')) {
    const spinner = $('spinner');
    const spinnerText = $('spinnerText');
    const button = $('analyzeButton');
    const body = document.body;

    if (spinnerText) spinnerText.textContent = text;
    if (spinner) spinner.style.display = 'block';
    if (button) button.disabled = true;

    if (!mouseSpinnerElement) mouseSpinnerElement = $('mouseSpinner');
    if (mouseSpinnerElement) mouseSpinnerElement.style.display = 'block';
    if (body) body.style.cursor = 'wait';

    if (!mouseMoveHandler) {
        mouseMoveHandler = updateSpinnerPosition;
        document.addEventListener('mousemove', mouseMoveHandler);
    }
}

function hideSpinner() {
    const spinner = $('spinner');
    const spinnerText = $('spinnerText');
    const button = $('analyzeButton');
    const body = document.body;

    if (spinnerText) spinnerText.textContent = '';
    if (spinner) spinner.style.display = 'none';
    if (button) button.disabled = false;

    if (mouseSpinnerElement) mouseSpinnerElement.style.display = 'none';
    if (body) body.style.cursor = 'default';

    if (mouseMoveHandler) {
        document.removeEventListener('mousemove', mouseMoveHandler);
        mouseMoveHandler = null;
    }
}
// --- Ende Mouse Spinner Funktionen ---

// --- Fortschrittsbalken Funktionen ---
function startProgress() {
    const c = $('progressContainer');
    const bar = $('progressBar');
    const text = $('progressText');
    const timer = $('progressTimer');
    if (c) c.style.display = 'block';
    if (bar) bar.style.width = '0%';
    if (text) text.textContent = '';
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

function updateProgress(percent, textKey) {
    const bar = $('progressBar');
    const text = $('progressText');
    if (bar) bar.style.width = percent + '%';
    if (text) text.textContent = tDyn(textKey);
}

function finishProgress() {
    const c = $('progressContainer');
    const timer = $('progressTimer');
    if (c) c.style.display = 'none';
    if (timer) timer.style.display = 'none';
    if (elapsedTimer) { clearInterval(elapsedTimer); elapsedTimer = null; }
    if (llm1BarInterval) { clearInterval(llm1BarInterval); llm1BarInterval = null; }
}

function startLlm1Progress() {
    if (llm1BarInterval) clearInterval(llm1BarInterval);
    let percent = 10;
    llm1BarInterval = setInterval(() => {
        percent = Math.min(percent + 1, 28);
        updateProgress(percent, 'progressLLM1Request');
    }, 1000);
}

function stopLlm1Progress() {
    if (llm1BarInterval) { clearInterval(llm1BarInterval); llm1BarInterval = null; }
}

function logProgress(message) {
    const list = $('progressLog');
    if (list) {
        const li = document.createElement('li');
        li.textContent = message;
        list.appendChild(li);
    }
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
            fetchJSON(DATA_PATHS.dignitaeten) // Fetch dignities
        ]);

        [ data_leistungskatalog, data_pauschaleLeistungsposition, data_pauschalen,
          data_pauschaleBedingungen, data_tardocGesamt, data_tabellen,
          data_interpretationen, data_dignitaeten ] = loadedDataArray; // Assign dignities data

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
    mouseSpinnerElement = $('mouseSpinner');
    loadIcdCheckboxState();
    loadData();
    // Initial: Umschalter verbergen bis Ergebnis vorliegt
    showIcdToggle(false);
    setIcdFilterMode('all');

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
    document.addEventListener('click', (e) => {
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
                } else if (type === 'diagnosis') {
                    html = buildDiagnosisInfoHtmlFromCode(code);
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

        const pLink = e.target.closest('a.pauschale-exp-link');
        if (pLink) {
            e.preventDefault();
            try {
                const code = (pLink.dataset.code || '').trim();
                logFrontendInteraction('pauschale-expansion-click', { code });
                // Find the pauschale in evaluatedPauschalenList and show its bedingungs_pruef_html in the detail modal
                const pauschaleEntry = evaluatedPauschalenList.find(p => String(p.code).toUpperCase() === code.toUpperCase() || String(p.details?.Pauschale).toUpperCase() === code.toUpperCase());
                if (pauschaleEntry && pauschaleEntry.bedingungs_pruef_html) {
                    let headerHtml = `<h2>${tDyn('condDetails')} (${escapeHtml(code)})</h2>`;
                    // Add overall logic status to the header of the detail modal
                    const logicStatusKey = pauschaleEntry.is_valid_structured ? 'logicOk' : 'logicNotOk';
                    const logicStatusText = tDyn(logicStatusKey);
                    const logicStatusColor = pauschaleEntry.is_valid_structured ? 'var(--accent)' : 'var(--danger)';
                    headerHtml += `<p style="font-weight:bold; color:${logicStatusColor}; margin-top:-10px; margin-bottom:15px;">${escapeHtml(logicStatusText)}</p>`;

                    showModal('infoModalDetailOverlay', headerHtml + pauschaleEntry.bedingungs_pruef_html);
                } else {
                    showModal('infoModalDetailOverlay', `<p>Details für Pauschale ${escapeHtml(code)} nicht gefunden oder keine Bedingungs-HTML vorhanden.</p>`);
                }
            } catch (handlerError) {
                console.error('pauschale-exp-link handler failed', handlerError);
                logFrontendInteraction('pauschale-expansion-error', { message: (handlerError && handlerError.message) ? handlerError.message : String(handlerError) });
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
    const useIcd = $('useIcdCheckbox')?.checked ?? true;
    const ageInput = $('ageInput')?.value; // Bleibt vorerst auskommentiert im HTML
    const age = ageInput ? parseInt(ageInput, 10) : null;
    const gender = $('genderSelect')?.value || null; // Bleibt vorerst auskommentiert im HTML
    console.log(`[getBillingAnalysis] Kontext: useIcd=${useIcd}, Age=${age}, Gender=${gender}`);
    console.log(`[getBillingAnalysis] ICD-Prüfung berücksichtigen: ${useIcd}`);
    let backendResponse = null;
    let rawResponseText = "";
    let htmlOutput = "";

    const outputDiv = $("output");
    if (!outputDiv) { console.error("Output element not found!"); return; }
    if (!userInput) { displayOutput(`<p class='error'>${tDyn('pleaseEnter')}</p>`); return; }

    showSpinner(tDyn('spinnerWorking'));
    displayOutput(`
        <div id="progressContainer">
            <div id="progressBar"></div>
            <div id="progressText"></div>
            <div id="progressTimer"></div>
        </div>
        <ul id="progressLog"></ul>`, 'info');
    startProgress();
    logProgress(tDyn('progressLLM1Request') + ' ' + tDyn('progressQuery', {text: userInput}));
    updateProgress(10, 'progressLLM1Request');
    startLlm1Progress();
    progressTimes.llm1Start = performance.now();

    try {
        console.log("[getBillingAnalysis] Sende Anfrage an Backend...");
        const requestBody = {
            inputText: mappedInput,
            icd: icdInput,
            medications: medicationInput,
            useIcd: useIcd,
            age: age,
            gender: gender,
            lang: currentLang
        };
        const res = await fetch("/api/analyze-billing", { method: "POST", headers: {"Content-Type":"application/json"}, body: JSON.stringify(requestBody) });
        rawResponseText = await res.text();
        const llm1Duration = performance.now() - progressTimes.llm1Start;
        stopLlm1Progress();
        updateProgress(30, 'progressLLM1Response');
        // console.log("[getBillingAnalysis] Raw Response vom Backend erhalten:", rawResponseText.substring(0, 500) + "..."); // Gekürzt loggen
        if (!res.ok) { throw new Error(`Server antwortete mit ${res.status}`); }
        backendResponse = JSON.parse(rawResponseText);
        const lknCount = Array.isArray(backendResponse?.llm_ergebnis_stufe1?.rankierte_lkns) ? backendResponse.llm_ergebnis_stufe1.rankierte_lkns.length : 0;
        logProgress(tDyn('progressLLM1Response') + ' ' + tDyn('progressDuration', {ms: llm1Duration.toFixed(0)}) + ' ' + tDyn('progressCandidates', {count: lknCount}));
        progressTimes.plausiStart = performance.now();
        lastBackendResponse = backendResponse; // Für spätere Feedback-Übermittlung
        lastUserInput = userInput;
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
        updateProgress(50, 'progressPlausi');
        logProgress(tDyn('progressPlausi'));

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
                    updateSelectedPauschaleDetails(abrechnung.details);
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
        progressTimes.llm2Start = performance.now();
        updateProgress(70, 'progressLLM2Request');
        logProgress(tDyn('progressLLM2Request'));
        // 3. LLM Stufe 1 Ergebnisse
        htmlOutput += generateLlmStage1Details(llmResultStufe1);
        // 4. LLM Stufe 2 Ergebnisse (Mapping)
        const stage2Html = generateLlmStage2Details(llmResultStufe2); // Ergebnis holen
        const llm2Duration = performance.now() - progressTimes.llm2Start;
        updateProgress(80, 'progressLLM2Response');
        logProgress(tDyn('progressLLM2Response') + ' ' + tDyn('progressDuration', {ms: llm2Duration.toFixed(0)}));
        // console.log("[getBillingAnalysis] Ergebnis von generateLlmStage2Details:", stage2Html.substring(0, 100) + "..."); // Loggen
        htmlOutput += stage2Html; // Hinzufügen
        // 5. Regelprüfungsdetails
        updateProgress(90, 'progressFinal');
        logProgress(tDyn('progressFinal'));
        htmlOutput += generateRuleCheckDetails(regelErgebnisseDetails, abrechnung.type === "Error");

        // --- Finalen Output anzeigen ---
        displayOutput(htmlOutput);
        updateProgress(100, 'progressDone');
        logProgress(tDyn('progressDone'));
        setTimeout(finishProgress, 300);
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
            detailsHtml += `<li><b>Die LKN ${escapeHtml(l.lkn)}:</b> ${escapeHtml(desc)}${mengeText}</li>`;
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
    const bedingungsHtml = abrechnungsObjekt.bedingungs_pruef_html || "";
    const bedingungsFehler = abrechnungsObjekt.bedingungs_fehler || [];
    // MODIFIED: Check both conditions_met (for main object) and is_valid_structured (for items from evaluated_pauschalen list)
    const conditions_met_structured = (abrechnungsObjekt.conditions_met === true) || (abrechnungsObjekt.is_valid_structured === true);

    const PAUSCHALE_KEY = 'Pauschale';
    const PAUSCHALE_TEXT_KEY = 'Pauschale_Text';
    const PAUSCHALE_TP_KEY = 'Taxpunkte';
    const PAUSCHALE_ERKLAERUNG_KEY = 'pauschale_erklaerung_html';

    if (!pauschaleDetails) return `<p class='error'>${tDyn('errorPauschaleMissing')}</p>`;

    const pauschaleCode = escapeHtml(pauschaleDetails[PAUSCHALE_KEY] || 'N/A');
    const pauschaleText = escapeHtml(getLangField(pauschaleDetails, PAUSCHALE_TEXT_KEY) || 'N/A');
    const pauschaleTP = escapeHtml(pauschaleDetails[PAUSCHALE_TP_KEY] || 'N/A');
    const pauschaleErklaerung = pauschaleDetails[PAUSCHALE_ERKLAERUNG_KEY] || "";

    let tableRowsHtml = `
        <tr>
            <td><b>${pauschaleCode}</b></td>
            <td>${pauschaleText}</td>
            <td>${pauschaleTP}</td>
        </tr>`;

    let implantsHtml = '';
    if (pauschaleDetails.Implantate_inbegriffen === true) {
        implantsHtml = escapeHtml(tDyn('implantsIncluded'));
    }

    let dignitiesHtml = '';
    const dignitaetenString = pauschaleDetails.Dignitaeten;
    if (dignitaetenString && typeof dignitaetenString === 'string' && dignitaetenString.trim() !== "") {
        const dignityCodes = dignitaetenString.split('|').map(code => String(code).trim()).filter(Boolean);
        if (dignityCodes.length > 0) {
            if (Object.keys(dignitaetenMap).length === 0) {
                console.warn("DignitaetenMap is empty when trying to display dignities. Dignities will show 'Beschreibung nicht gefunden'. Check data loading for 'data/DIGNITAETEN.json'.");
            }

            let dignitiesDisplayList = [];
            dignityCodes.forEach(code => {
                const dignityDetail = dignitaetenMap[code];
                let description;
                if (dignityDetail) {
                    const lang = (typeof currentLang === 'undefined') ? 'de' : currentLang;
                    if (lang === 'fr') {
                        description = dignityDetail.DignitaetText_f || dignityDetail.DignitaetText || code;
                    } else if (lang === 'it') {
                        description = dignityDetail.DignitaetText_i || dignityDetail.DignitaetText || code;
                    } else {
                        description = dignityDetail.DignitaetText || code;
                    }
                    dignitiesDisplayList.push(`${escapeHtml(code)}, ${escapeHtml(description)}`);
                } else {
                    if (Object.keys(dignitaetenMap).length > 0) {
                        console.warn(`No dignityDetail found in dignitaetenMap for code '${code}'.`);
                    }
                    dignitiesDisplayList.push(`${escapeHtml(code)}, ${escapeHtml(tDyn('descriptionNotFound', {code: code}))}`);
                }
            });

            if (dignitiesDisplayList.length > 0) {
                dignitiesHtml = `<b>${escapeHtml(tDyn('dignitiesLabel'))}:</b><br>${dignitiesDisplayList.join('<br>')}`;
            }
        }
    }

    if (implantsHtml || dignitiesHtml) {
        tableRowsHtml += `
            <tr>
                <td></td>
                <td>${implantsHtml}</td>
                <td>${dignitiesHtml}</td>
            </tr>`;
    }


    let detailsContent = `
        <table border="1" style="border-collapse: collapse; width: 100%; margin-bottom: 10px;">
            <thead><tr><th>${tDyn('pauschaleCode')}</th><th>${tDyn('description')}</th><th>${tDyn('taxpoints')}</th></tr></thead>
            <tbody>${tableRowsHtml}</tbody>
        </table>`;

    if (pauschaleErklaerung) {
         detailsContent += `<details style="margin-top: 10px;"><summary>${tDyn('reasonPauschale')}</summary>${pauschaleErklaerung}</details>`;
    }

    if (bedingungsHtml) {
        // Öffne Details immer, wenn die strukturierte Logik nicht erfüllt war ODER wenn es Einzelfehler gab
        const openAttr = !conditions_met_structured || (bedingungsFehler && bedingungsFehler.length > 0) ? 'open' : '';
        let summary_status_text = conditions_met_structured ? tDyn('overallOk') : tDyn('overallNotOk');

        let bedingungenContent = bedingungsHtml;

        const potentialIcds = Array.isArray(pauschaleDetails['potential_icds']) ? pauschaleDetails['potential_icds'] : [];
        if (potentialIcds.length > 0) {
            let icdRows = '';
            for (const icd of potentialIcds) {
                const code = escapeHtml(icd.Code || '');
                const text = escapeHtml(icd.Code_Text || '');
                icdRows += `<tr><td>${code}</td><td>${text}</td></tr>`;
            }
            const icdTable = `<table border="1" style="border-collapse: collapse; width: 100%; margin-top: 5px;">`+
                             `<thead><tr><th>${tDyn('thIcdCode')}</th><th>${tDyn('thIcdText')}</th></tr></thead>`+
                             `<tbody>${icdRows}</tbody></table>`;
            bedingungenContent += `<details style="margin-top:8px;"><summary>${tDyn('potentialIcds')}</summary>${icdTable}</details>`;
        }

        detailsContent += `<details ${openAttr} style="margin-top: 10px;"><summary>${tDyn('condDetails')} (${summary_status_text})</summary>${bedingungenContent}</details>`;
    }

    let summary_main_status = conditions_met_structured ? `<span style="color:green;">${tDyn('logicOk')}</span>` : `<span style="color:red;">${tDyn('logicNotOk')}</span>`;
    let html = `<details open><summary>${tDyn('pauschaleDetails')}: ${pauschaleCode} ${summary_main_status}</summary>${detailsContent}</details>`;
    return html;
}


// Zeigt TARDOC-Tabelle an
function displayTardocTable(tardocLeistungen, ruleResultsDetailsList = []) {
    if (!tardocLeistungen || tardocLeistungen.length === 0) {
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

        tardocTableBody += `
            <tr>
                <td>${escapeHtml(lkn)}</td><td>${escapeHtml(name)}</td>
                <td>${al.toFixed(2)}</td><td>${ipl.toFixed(2)}</td>
                <td>${anzahl}</td><td>${total_tp.toFixed(2)}</td>
                <td>${regelnHtml ? `<details><summary${detailsSummaryStyle}>${tDyn('thRegeln')}</summary>${regelnHtml}</details>` : tDyn('none')}</td>
            </tr>`;
    }

    const overallSummaryClass = hasHintsOverall ? ' class="rule-hint-trigger"' : '';
    let html = `<details open><summary ${overallSummaryClass}>${tDyn('tardocDetails')} (${tardocLeistungen.length} Positionen)</summary>`;
    html += `
        <table border="1" style="border-collapse: collapse; width: 100%; margin-bottom: 10px;">
            <thead><tr><th>${tDyn('thLkn')}</th><th>${tDyn('thLeistung')}</th><th>${tDyn('thAl')}</th><th>${tDyn('thIpl')}</th><th>${tDyn('thAnzahl')}</th><th>${tDyn('thTotal')}</th><th>${tDyn('thRegeln')}</th></tr></thead>
            <tbody>${tardocTableBody}</tbody>
            <tfoot><tr><th colspan="5" style="text-align:right;">${tDyn('gesamtTp')}</th><th colspan="2">${gesamtTP.toFixed(2)}</th></tr></tfoot>
        </table>`;
    html += `</details>`;
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

