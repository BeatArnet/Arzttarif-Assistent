// calculator.js - Version 02.05.2025
// Mit detaillierter Anzeige, Maus-Spinner, Regelhinweisen

// ─── 0 · Globale Datencontainer ─────────────────────────────────────────────
let data_leistungskatalog = [];
let data_pauschaleLeistungsposition = [];
let data_pauschalen = [];
let data_pauschaleBedingungen = [];
let data_tardocGesamt = [];
let data_tabellen = [];

// Pfade zu den lokalen JSON-Daten
const DATA_PATHS = {
    leistungskatalog: 'data/tblLeistungskatalog.json',
    pauschaleLP: 'data/tblPauschaleLeistungsposition.json',
    pauschalen: 'data/tblPauschalen.json',
    pauschaleBedingungen: 'data/tblPauschaleBedingungen.json',
    tardocGesamt: 'data/TARDOCGesamt_optimiert_Tarifpositionen.json', // ANPASSEN!
    tabellen: 'data/tblTabellen.json' // Korrigiert
};
// Kein Caching mehr

// ─── 1 · Utility‑Funktionen ────────────────────────────────────────────────
function $(id) { return document.getElementById(id); }

function escapeHtml(s) {
    if (s === null || s === undefined) return "";
    // Korrekte Ersetzung mit numerischen Entities für Anführungszeichen
    return String(s).replace(/[&<>"']/g, c => ({ "&": "&", "<": "<", ">": ">", "\"": "&quot;", "'": "'" }[c]));
}

function beschreibungZuLKN(lkn) {
    if (!data_leistungskatalog || typeof lkn !== 'string') return "N/A";
    const hit = data_leistungskatalog.find(e => e.LKN?.toUpperCase() === lkn.toUpperCase());
    return hit ? hit.Beschreibung || lkn : lkn;
}

function displayOutput(html, type = "info") {
    const out = $("output");
    if (!out) { console.error("Output element not found!"); return; }
    out.innerHTML = html;
    out.className = type;
}

// --- Maus-Spinner Funktionen ---
let mouseSpinnerElement = null;
let isProcessing = false;

const updateSpinnerPosition = (event) => {
    if (mouseSpinnerElement && isProcessing) {
        const offsetX = 15; const offsetY = 10;
        mouseSpinnerElement.style.left = `${event.clientX + offsetX}px`;
        mouseSpinnerElement.style.top = `${event.clientY + offsetY}px`;
    }
};

function showMouseSpinner() {
    if (!mouseSpinnerElement) mouseSpinnerElement = $('mouseSpinner');
    if (mouseSpinnerElement) {
        isProcessing = true; mouseSpinnerElement.style.display = 'block';
        document.addEventListener('mousemove', updateSpinnerPosition);
        console.log("Mouse Spinner aktiviert.");
    }
    const button = $('analyzeButton'); if (button) button.disabled = true;
}

function hideMouseSpinner() {
    if (mouseSpinnerElement) {
        isProcessing = false; mouseSpinnerElement.style.display = 'none';
        document.removeEventListener('mousemove', updateSpinnerPosition);
        console.log("Mouse Spinner deaktiviert.");
    }
    const button = $('analyzeButton'); if (button) button.disabled = false;
}
// --- Ende Maus-Spinner ---

// ─── 2 · Daten laden (vereinfacht ohne Caching) ───────────────────────────
async function fetchJSON(path) { /* ... Implementierung wie zuvor ... */ }
async function loadData() { /* ... Implementierung wie zuvor ... */ }
// Cache-Löschfunktion wird nicht mehr benötigt
document.addEventListener("DOMContentLoaded", loadData);

// ─── 3 · Hauptlogik (Button‑Click) ────────────────────────────────────────
async function getBillingAnalysis() {
    console.log("[getBillingAnalysis] Funktion gestartet.");
    const userInput = $("userInput").value.trim();
    const icdInput = $("icdInput").value.trim().split(",").map(s => s.trim().toUpperCase()).filter(Boolean);
    const gtinInput = ($("gtinInput") ? $("gtinInput").value.trim().split(",").map(s => s.trim()).filter(Boolean) : []);

    let backendResponse = null;
    let rawResponseText = "";
    let htmlOutput = "";

    const outputDiv = $("output");
    if (!outputDiv) { console.error("Output element not found!"); return; }
    if (!userInput) { displayOutput("<p>Bitte Leistungsbeschreibung eingeben.</p>", "error"); return; }

    showMouseSpinner(); // Dynamischen Spinner starten
    displayOutput("<p>Prüfe Abrechnung …</p>", "info");

    try {
        console.log("[getBillingAnalysis] Sende Anfrage an Backend...");
        const requestBody = { inputText: userInput, icd: icdInput, gtin: gtinInput };
        const res = await fetch("/api/analyze-billing", { method: "POST", headers: {"Content-Type":"application/json"}, body: JSON.stringify(requestBody) });
        rawResponseText = await res.text();
        console.log("[getBillingAnalysis] Raw Response vom Backend erhalten:", rawResponseText);
        if (!res.ok) { throw new Error(`Server antwortete mit ${res.status}`); }
        backendResponse = JSON.parse(rawResponseText);
        console.log("[getBillingAnalysis] Backend-Antwort geparst:", backendResponse);

        // Strukturprüfung
        if (!backendResponse || !backendResponse.llm_ergebnis_stufe1 || !backendResponse.abrechnung || !backendResponse.abrechnung.type) {
             throw new Error("Unerwartete Hauptstruktur vom Server erhalten.");
        }
        console.log("[getBillingAnalysis] Backend-Antwortstruktur ist OK.");

    } catch (e) {
        console.error("Fehler bei Backend-Anfrage oder Verarbeitung:", e);
        let msg = `<p>Server-Fehler: ${escapeHtml(e.message)}</p>`;
        if (rawResponseText && !e.message.includes(rawResponseText.substring(0,50))) { msg += `<details style="margin-top:1em"><summary>Raw Response</summary><pre>${escapeHtml(rawResponseText)}</pre></details>`; }
        displayOutput(msg, "error");
        hideMouseSpinner();
        return;
    }

    // --- Ergebnisse verarbeiten und anzeigen ---
    try {
        console.log("[getBillingAnalysis] Starte Ergebnisverarbeitung.");
        const llmResultStufe1 = backendResponse.llm_ergebnis_stufe1;
        const abrechnung = backendResponse.abrechnung;
        const identifiedLeistungen = llmResultStufe1.identified_leistungen || [];
        const extractedInfo = llmResultStufe1.extracted_info || {};
        const ruleResultsDetailsList = backendResponse.regel_ergebnisse_details || []; // Für Regelhinweise

        // --- Baue das FINALE HTML für den Output-Bereich ---
        htmlOutput = `<h2>Ergebnisse für «${escapeHtml(userInput)}»</h2>`;

        // 1. LLM Stufe 1 Ergebnis anzeigen (JETZT ALS TABELLE)
        htmlOutput += `<h3>LLM-Analyse (Stufe 1: LKN-Identifikation)</h3>`;
        if (identifiedLeistungen.length > 0) {
            htmlOutput += `
                <table border="1" style="border-collapse: collapse; width: 100%; margin-bottom: 10px;">
                    <thead><tr><th>LKN</th><th>Typ</th><th>Menge (LLM)</th><th>Beschreibung (LLM)</th></tr></thead>
                    <tbody>`;
            identifiedLeistungen.forEach(l => {
                 htmlOutput += `
                     <tr>
                         <td>${escapeHtml(l.lkn || 'N/A')}</td>
                         <td>${escapeHtml(l.typ || '?')}</td>
                         <td>${escapeHtml(l.menge ?? 'N/A')}</td>
                         <td>${escapeHtml(l.beschreibung || beschreibungZuLKN(l.lkn) || 'N/A')}</td>
                     </tr>`;
            });
            htmlOutput += `</tbody></table>`;
        } else { htmlOutput += `<p><i>Keine LKN identifiziert.</i></p>`; }
        // Extrahierte Details und Begründung
        let extractedDetails = [];
        if (extractedInfo.dauer_minuten !== null) extractedDetails.push(`Dauer: ${extractedInfo.dauer_minuten} Min.`);
        if (extractedInfo.menge_allgemein !== null && extractedInfo.menge_allgemein !== 0) extractedDetails.push(`Menge: ${extractedInfo.menge_allgemein}`);
        if (extractedInfo.alter !== null && extractedInfo.alter !== 0) extractedDetails.push(`Alter: ${extractedInfo.alter}`);
        if (extractedInfo.geschlecht !== null && extractedInfo.geschlecht !== 'null' && extractedInfo.geschlecht !== 'unbekannt') extractedDetails.push(`Geschlecht: ${extractedInfo.geschlecht}`);
        if (extractedDetails.length > 0) { htmlOutput += `<p><b>Extrahierte Details:</b> ${extractedDetails.join(', ')}</p>`; }
        htmlOutput += `<p><b>Begründung LLM (Stufe 1):</b> ${escapeHtml(llmResultStufe1.begruendung_llm || 'N/A')}</p>`;
        htmlOutput += `<hr>`;

        // 2. Finale Abrechnung anzeigen
        // Titel "Finale Abrechnung" entfernt

        let abrechnungsDetailHtml = ""; // HTML für die Tabelle/Details

        switch (abrechnung.type) {
            case "Pauschale":
                console.log("[getBillingAnalysis] Abrechnungstyp: Pauschale", abrechnung.details);
                htmlOutput += `<p class="success"><b>Abrechnung als Pauschale empfohlen.</b></p>`;
                if (abrechnung.details) {
                     // Zeige Pauschale und Bedingungsdetails
                     abrechnungsDetailHtml = displayPauschale(abrechnung.details, abrechnung.bedingungs_pruef_html);
                     // NEU: Zeige verworfene TARDOC-Leistungen
                     abrechnungsDetailHtml += displayDiscardedTardocInfo(identifiedLeistungen, ruleResultsDetailsList);
                     // NEU: Zeige alternative Pauschalen (optional, falls Backend sie liefert)
                     // abrechnungsDetailHtml += displayAlternativePauschalen(abrechnung.alternative_pauschalen);
                } else { abrechnungsDetailHtml = "<p class='error'>Fehler: Pauschalendetails fehlen.</p>"; }
                break;

            case "TARDOC":
                console.log("[getBillingAnalysis] Abrechnungstyp: TARDOC", abrechnung.leistungen);
                htmlOutput += `<p class="success"><b>Abrechnung als TARDOC-Einzelleistung(en) empfohlen.</b></p>`;
                if (abrechnung.leistungen && abrechnung.leistungen.length > 0) {
                     abrechnungsDetailHtml = displayTardocTable(abrechnung.leistungen, ruleResultsDetailsList);
                } else { abrechnungsDetailHtml = "<p><i>Keine TARDOC-Positionen zur Abrechnung übermittelt.</i></p>"; }
                break;

            case "Error":
                console.error("[getBillingAnalysis] Abrechnungstyp: Error", abrechnung.message);
                htmlOutput += `<p class="error"><b>Abrechnung nicht möglich oder Fehler aufgetreten.</b></p>`;
                abrechnungsDetailHtml = `<p><i>Grund: ${escapeHtml(abrechnung.message || 'Unbekannter Fehler')}</i></p>`;
                 // Zeige Regelprüfungsdetails bei Fehler an
                 abrechnungsDetailHtml += displayRuleCheckDetailsOnError(ruleResultsDetailsList);
                break;

            default:
                console.error("[getBillingAnalysis] Unbekannter Abrechnungstyp:", abrechnung.type);
                htmlOutput += `<p class="error"><b>Unbekannter Abrechnungstyp vom Server.</b></p>`;
        }

        htmlOutput += abrechnungsDetailHtml;
        displayOutput(htmlOutput, "info");
        console.log("[getBillingAnalysis] Frontend-Verarbeitung abgeschlossen.");

    } catch (error) {
         console.error("[getBillingAnalysis] Unerwarteter Fehler bei Ergebnisverarbeitung:", error);
         displayOutput(`<p class="error">Ein interner Fehler ist aufgetreten: ${escapeHtml(error.message)}</p><pre>${escapeHtml(error.stack)}</pre>`, "error");
    } finally {
         hideSpinner();
    }
} // Ende getBillingAnalysis


// ─── 4 · Hilfsfunktionen zur ANZEIGE ────

// Zeigt die Details EINER anwendbaren Pauschale an
function displayPauschale(pauschaleDetails, bedingungsHtml = "") {
    // --- !!! ANPASSEN: Korrekten Schlüssel für Pauschale in Pauschalen-Daten !!! ---
    const PAUSCHALE_KEY = 'Pauschale';
    const PAUSCHALE_TEXT_KEY = 'Pauschale_Text';
    const PAUSCHALE_TP_KEY = 'Taxpunkte';
    // --- !!! ENDE ANPASSUNG !!! ---
    if (!pauschaleDetails) return "<p class='error'>Pauschalendetails fehlen.</p>";
    let html = `<h4>Abgerechnete Pauschale</h4>`; // Titel hinzugefügt
    html += `
        <table border="1" style="border-collapse: collapse; width: 100%; margin-bottom: 10px;">
            <thead><tr><th>Pauschale Code</th><th>Beschreibung</th><th>Taxpunkte</th></tr></thead>
            <tbody><tr>
                <td>${escapeHtml(pauschaleDetails[PAUSCHALE_KEY] || 'N/A')}</td>
                <td>${escapeHtml(pauschaleDetails[PAUSCHALE_TEXT_KEY] || 'N/A')}</td>
                <td>${escapeHtml(pauschaleDetails[PAUSCHALE_TP_KEY] || 'N/A')}</td>
            </tr></tbody>
        </table>`;
    if (bedingungsHtml) {
         // --- NEU: Zeige spezifische ICDs bei Bedingungsfehler ---
         let enhancedBedingungsHtml = bedingungsHtml;
         const fehlendeIcdMatch = bedingungsHtml.match(/Typ: HAUPTDIAGNOSE IN TABELLE, Wert\/Ref: '([^']+)' \(Tabelle: None\): <span style="color:red/);
         if (fehlendeIcdMatch && fehlendeIcdMatch[1]) {
              const tabellenName = fehlendeIcdMatch[1];
              const moeglicheIcds = getCodesFromTable(tabellenName, "icd");
              if (moeglicheIcds.length > 0) {
                   enhancedBedingungsHtml += `<details style="margin-left: 40px;"><summary>Mögliche ICD-Codes für Tabelle '${escapeHtml(tabellenName)}'</summary><ul>`;
                   moeglicheIcds.forEach(icd => {
                        enhancedBedingungsHtml += `<li>${escapeHtml(icd.Code)}: ${escapeHtml(icd.Code_Text)}</li>`;
                   });
                   enhancedBedingungsHtml += `</ul></details>`;
              }
         }
         // --- ENDE ICD-Anzeige ---
         html += `<details><summary>Details Pauschalen-Bedingungsprüfung</summary>${enhancedBedingungsHtml}</details>`;
    }
    return html;
}

// Zeigt die Tabelle für die abzurechnenden TARDOC-Leistungen an
function displayTardocTable(tardocLeistungen, ruleResultsDetailsList = []) {
    if (!tardocLeistungen || tardocLeistungen.length === 0) {
        return "<p><i>Keine TARDOC-Positionen zur Abrechnung.</i></p>";
    }
    let tardocTableBody = "";
    let gesamtTP = 0;
    for (const leistung of tardocLeistungen) {
        const lkn = leistung.lkn;
        const anzahl = leistung.menge;
        const tardocDetails = processTardocLookup(lkn);
        if (!tardocDetails.applicable) {
             tardocTableBody += `<tr><td colspan="7" class="error">Fehler: Details für LKN ${escapeHtml(lkn)} nicht gefunden!</td></tr>`;
             continue;
        }
        const name = leistung.beschreibung || tardocDetails.leistungsname || 'N/A';
        const al = tardocDetails.al; const ipl = tardocDetails.ipl;
        let regelnHtml = tardocDetails.regeln ? `<p>${escapeHtml(tardocDetails.regeln)}</p>` : '';
        const ruleResult = ruleResultsDetailsList.find(r => r.lkn === lkn);
        let hasHint = false; let hintListHtml = "";
        if (ruleResult?.regelpruefung?.fehler?.length > 0) {
             if (regelnHtml) regelnHtml += "<hr style='margin: 5px 0; border-color: #eee;'>";
             hintListHtml += `<p><b>Hinweise Regelprüfung:</b></p><ul>`;
             ruleResult.regelpruefung.fehler.forEach(hinweis => {
                  const isReduction = hinweis.includes("Menge auf");
                  const style = isReduction ? "color: var(--danger); font-weight: bold;" : "";
                  if (isReduction) hasHint = true;
                  hintListHtml += `<li style="${style}">${escapeHtml(hinweis)}</li>`;
             });
             hintListHtml += `</ul>`;
        }
        const total_tp = (al + ipl) * anzahl; gesamtTP += total_tp;
        const detailsSummaryStyle = hasHint ? ' class="rule-hint-trigger"' : '';
        const finalRegelnHtml = regelnHtml + hintListHtml; // Kombiniere TARDOC-Regeln und Hinweise

        tardocTableBody += `
            <tr>
                <td>${escapeHtml(lkn)}</td><td>${escapeHtml(name)}</td>
                <td>${al.toFixed(2)}</td><td>${ipl.toFixed(2)}</td>
                <td>${anzahl}</td><td>${total_tp.toFixed(2)}</td>
                <td>${finalRegelnHtml ? `<details><summary${detailsSummaryStyle}>Details</summary>${finalRegelnHtml}</details>` : ''}</td>
            </tr>`;
    }
    let html = `<h4>TARDOC-Positionen</h4>`; // Titel wieder hinzugefügt
    html += `<table ...><tbody>${tardocTableBody}</tbody><tfoot>...</tfoot></table>`; // Tabellenstruktur wie zuvor
    return html;
}

// Hilfsfunktion: Sucht nur die TARDOC-Details lokal
function processTardocLookup(lkn) {
    let result = { applicable: false, data: null, al: 0, ipl: 0, leistungsname: 'N/A', regeln: '' };
    // --- !!! WICHTIG: Schlüsselnamen anpassen !!! ---
    const TARDOC_LKN_KEY = 'LKN'; // ANPASSEN!
    const AL_KEY = 'AL_(normiert)'; // ANPASSEN!
    const IPL_KEY = 'IPL_(normiert)'; // ANPASSEN!
    const DESC_KEY_1 = 'Bezeichnung'; // ANPASSEN!
    const RULES_KEY_1 = 'Regeln_bezogen_auf_die_Tarifmechanik'; // ANPASSEN!
    // --- !!! ENDE ANPASSUNG !!! ---
    if (!data_tardocGesamt || data_tardocGesamt.length === 0) { console.error(`TARDOC-Daten nicht geladen für LKN ${lkn}.`); return result; }
    const tardocPosition = data_tardocGesamt.find(item => item && item[TARDOC_LKN_KEY] && String(item[TARDOC_LKN_KEY]).toUpperCase() === lkn.toUpperCase());
    if (!tardocPosition) { console.error(`LKN ${lkn} nicht in lokalen TARDOC-Daten gefunden.`); return result; }
    result.applicable = true; result.data = tardocPosition;
    result.al = parseFloat(tardocPosition[AL_KEY]) || 0;
    result.ipl = parseFloat(tardocPosition[IPL_KEY]) || 0;
    result.leistungsname = tardocPosition[DESC_KEY_1] || 'N/A';
    result.regeln = tardocPosition[RULES_KEY_1] || '';
    return result;
}

// --- NEUE Hilfsfunktionen ---

// Zeigt verworfene TARDOC LKNs an, wenn eine Pauschale gilt
function displayDiscardedTardocInfo(identifiedLeistungen, ruleResultsDetailsList) {
    let html = "";
    const discardedTardoc = [];
    // Finde alle E/EZ LKNs, die regelkonform waren
    ruleResultsDetailsList.forEach(res => {
        const lknInfo = identifiedLeistungen.find(l => l.lkn === res.lkn);
        if (lknInfo && (lknInfo.typ === 'E' || lknInfo.typ === 'EZ') && res.regelpruefung?.abrechnungsfaehig) {
             discardedTardoc.push({
                 lkn: res.lkn,
                 beschreibung: lknInfo.beschreibung || beschreibungZuLKN(res.lkn),
                 menge: res.finale_menge
             });
        }
    });

    if (discardedTardoc.length > 0) {
        html += `<details style="margin-top: 15px;"><summary>Informatorisch: Identifizierte TARDOC-Leistungen (nicht abgerechnet wg. Pauschale)</summary>`;
        html += `<ul>`;
        discardedTardoc.forEach(l => {
            html += `<li><b>${escapeHtml(l.lkn)}</b> (Menge: ${l.menge}): ${escapeHtml(l.beschreibung)}</li>`;
        });
        html += `</ul></details>`;
    }
    return html;
}

// Zeigt Details zur Regelprüfung an, wenn Backend einen Fehler meldet
function displayRuleCheckDetailsOnError(ruleResultsDetailsList) {
    let html = "";
    if (ruleResultsDetailsList && ruleResultsDetailsList.length > 0) {
        html += `<details style="margin-top:1em;"><summary>Details zur Regelprüfung (evtl. relevant)</summary>`;
        ruleResultsDetailsList.forEach((resultItem) => {
            const lkn = resultItem.lkn || 'Unbekannt';
            html += `<h5>LKN: ${lkn} (Finale Menge: ${resultItem.finale_menge})</h5>`;
            if (resultItem.regelpruefung && !resultItem.regelpruefung.abrechnungsfaehig) {
                if (resultItem.regelpruefung.fehler && resultItem.regelpruefung.fehler.length > 0) {
                     html += `<ul>`;
                     resultItem.regelpruefung.fehler.forEach(fehler => { html += `<li class="error">${escapeHtml(fehler)}</li>`; });
                     html += `</ul>`;
                } else { html += `<p><i>Keine spezifischen Fehler gefunden, aber nicht abrechnungsfähig.</i></p>`; }
            } else if (resultItem.regelpruefung && resultItem.regelpruefung.fehler && resultItem.regelpruefung.fehler.length > 0) {
                html += `<p><b>Hinweise:</b></p><ul>`;
                resultItem.regelpruefung.fehler.forEach(hinweis => {
                     const style = hinweis.includes("Menge auf") ? "color: var(--accent); font-weight: bold;" : "";
                     html += `<li style="${style}">${escapeHtml(hinweis)}</li>`;
                });
                html += `</ul>`;
            } else if (resultItem.regelpruefung) { html += `<p><i>Regelprüfung OK oder nicht durchgeführt.</i></p>`; }
            else { html += `<p><i>Kein Regelprüfungsergebnis vorhanden.</i></p>`; }
        });
        html += `</details>`;
    }
    return html;
}

// Holt Codes aus tblTabellen für eine gegebene Tabelle und Typ
function getCodesFromTable(tableName, tableType) {
    if (!data_tabellen || !tableName || !tableType) return [];
    // --- !!! ANPASSEN: Korrekte Schlüsselnamen in tblTabellen !!! ---
    const TAB_CODE_KEY = "Code";
    const TAB_TEXT_KEY = "Code_Text";
    const TAB_TABELLE_KEY = "Tabelle";
    const TAB_TYP_KEY = "Tabelle_Typ";
    // --- !!! ENDE ANPASSUNG !!! ---
    return data_tabellen.filter(e =>
        e[TAB_TABELLE_KEY] === tableName && e[TAB_TYP_KEY] === tableType
    ).map(e => ({ Code: e[TAB_CODE_KEY], Code_Text: e[TAB_TEXT_KEY] || '' }));
}


// ─── 5 · Enter-Taste als Default für Return (Trigger) ─────────────────────
document.addEventListener("DOMContentLoaded", function() {
    const uiField = $("userInput");
    const icdField = $("icdInput");
    const gtinField = $("gtinInput");

    function handleEnter(e) {
        if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            getBillingAnalysis();
        }
    }

    if (uiField) uiField.addEventListener("keydown", handleEnter);
    if (icdField) icdField.addEventListener("keydown", handleEnter);
    if (gtinField) gtinField.addEventListener("keydown", handleEnter);
});

// Mache die Hauptfunktionen global verfügbar
window.getBillingAnalysis = getBillingAnalysis;
// window.clearDataCache = clearDataCache; // Entfernt