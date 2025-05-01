// calculator.js - Vollständige Version (27.04.2025)
// Arbeitet mit zweistufigem Backend. Holt lokale Details zur Anzeige.

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

function showSpinner(htmlContent = "Prüfung läuft, bitte warten...") {
    const spinner = $('spinner'); const button = $('analyzeButton');
    if (spinner) { spinner.innerHTML = htmlContent; spinner.style.display = 'block'; }
    if (button) button.disabled = true;
}

function hideSpinner() {
    const spinner = $('spinner'); const button = $('analyzeButton');
    if (spinner) { spinner.innerHTML = ""; spinner.style.display = 'none'; }
    if (button) button.disabled = false;
}

// ─── 2 · Daten laden (vereinfacht ohne Caching) ───────────────────────────
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
        return [];
    }
}

async function loadData() {
    console.log("Lade Frontend-Daten vom Server...");
    displayOutput("<p>Lade Tarifdaten...</p>", "info");
    let loadedDataArray = [];
    try {
        loadedDataArray = await Promise.all([
            fetchJSON(DATA_PATHS.leistungskatalog), fetchJSON(DATA_PATHS.pauschaleLP),
            fetchJSON(DATA_PATHS.pauschalen), fetchJSON(DATA_PATHS.pauschaleBedingungen),
            fetchJSON(DATA_PATHS.tardocGesamt), fetchJSON(DATA_PATHS.tabellen)
        ]);

        if (loadedDataArray.some(data => data === undefined)) { throw new Error("Einige Daten konnten nicht korrekt vom Server geholt werden."); }

        [ data_leistungskatalog, data_pauschaleLeistungsposition, data_pauschalen,
          data_pauschaleBedingungen, data_tardocGesamt, data_tabellen ] = loadedDataArray;

        console.log("Frontend-Daten vom Server geladen.");
        if (!$("output")?.classList.contains("error")) {
            displayOutput("<p>Daten geladen. Bereit zur Prüfung.</p>", "success");
            setTimeout(() => { if ($("output") && $("output").className === 'success') displayOutput(""); }, 2000);
        }
    } catch (error) {
         console.error("Schwerwiegender Fehler beim Laden der Frontend-Daten:", error);
         displayOutput(`<p class="error">Fehler beim Laden der notwendigen Frontend-Daten: ${escapeHtml(error.message)}. Bitte Seite neu laden.</p>`, "error");
         return;
    }

    // Finale Prüfung auf kritische Daten
    let missingDataErrors = [];
    if (!data_leistungskatalog || data_leistungskatalog.length === 0) missingDataErrors.push("Leistungskatalog");
    if (!data_tardocGesamt || data_tardocGesamt.length === 0) missingDataErrors.push("TARDOC-Daten");
    if (!data_pauschalen || data_pauschalen.length === 0) missingDataErrors.push("Pauschalen");

    if (missingDataErrors.length > 0) {
         const errorMsg = `Folgende kritische Daten fehlen: ${missingDataErrors.join(', ')}. Funktionalität eingeschränkt.`;
         console.error(errorMsg);
         if (!$("output")?.classList.contains("error")) { displayOutput(`<p class="error">${escapeHtml(errorMsg)}</p>`, "error"); }
    } else { console.log("Alle kritischen Daten scheinen vorhanden zu sein."); }
}

// Cache-Löschfunktion wird nicht mehr benötigt
// function clearDataCache() { ... }

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

    showSpinner("<h4>Analyse gestartet...</h4><p>Sende Anfrage an Server...</p>");
    displayOutput("", "info"); // Leere Haupt-Output

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
        console.log("[getBillingAnalysis] Prüfe Backend-Antwortstruktur...");
        if (!backendResponse || !backendResponse.llm_ergebnis_stufe1 || !backendResponse.abrechnung || !backendResponse.abrechnung.type) {
             throw new Error("Unerwartete Hauptstruktur vom Server erhalten.");
        }
        console.log("[getBillingAnalysis] Backend-Antwortstruktur ist OK.");

    } catch (e) {
        console.error("Fehler bei Backend-Anfrage oder Verarbeitung:", e);
        let msg = `<p>Server-Fehler: ${escapeHtml(e.message)}</p>`;
        if (rawResponseText && !e.message.includes(rawResponseText.substring(0,50))) { msg += `<details style="margin-top:1em"><summary>Raw Response</summary><pre>${escapeHtml(rawResponseText)}</pre></details>`; }
        displayOutput(msg, "error");
        hideSpinner();
        return;
    }

    // --- Ergebnisse verarbeiten und anzeigen ---
    try {
        console.log("[getBillingAnalysis] Starte Ergebnisverarbeitung.");
        const llmResultStufe1 = backendResponse.llm_ergebnis_stufe1;
        const abrechnung = backendResponse.abrechnung; // Das finale Abrechnungsergebnis
        const identifiedLeistungen = llmResultStufe1.identified_leistungen || [];
        const extractedInfo = llmResultStufe1.extracted_info || {};
        // Regelprüfungsergebnisse nur zur optionalen Anzeige bei Fehlern
        const ruleResultsDetailsList = backendResponse.regel_ergebnisse_details || [];

        // --- Baue LLM Analyse HTML für den Spinner ---
        let llmAnalysisHtml = `<h4>LLM-Analyse (Stufe 1) abgeschlossen</h4>`;
        if (identifiedLeistungen.length > 0) {
            const lknStrings = identifiedLeistungen.map(l => `${l.lkn} (${l.typ || '?'}, Menge:${l.menge ?? 'N/A'})`).join(', ');
            llmAnalysisHtml += `<p><b>Identifizierte LKN(s):</b> ${lknStrings}</p><ul>`;
            identifiedLeistungen.forEach(l => {
                 const desc = l.beschreibung || beschreibungZuLKN(l.lkn) || 'N/A';
                 llmAnalysisHtml += `<li><b>${escapeHtml(l.lkn)}:</b> ${escapeHtml(desc)}</li>`;
            });
            llmAnalysisHtml += `</ul>`;
        } else { llmAnalysisHtml += `<p><i>Keine LKN identifiziert.</i></p>`; }
        let extractedDetails = [];
        if (extractedInfo.dauer_minuten !== null) extractedDetails.push(`Dauer: ${extractedInfo.dauer_minuten} Min.`);
        if (extractedInfo.menge_allgemein !== null && extractedInfo.menge_allgemein !== 0) extractedDetails.push(`Menge: ${extractedInfo.menge_allgemein}`);
        if (extractedInfo.alter !== null && extractedInfo.alter !== 0) extractedDetails.push(`Alter: ${extractedInfo.alter}`);
        if (extractedInfo.geschlecht !== null && extractedInfo.geschlecht !== 'null' && extractedInfo.geschlecht !== 'unbekannt') extractedDetails.push(`Geschlecht: ${extractedInfo.geschlecht}`);
        if (extractedDetails.length > 0) { llmAnalysisHtml += `<p><b>Extrahierte Details:</b> ${extractedDetails.join(', ')}</p>`; }
        llmAnalysisHtml += `<p><b>Begründung LLM (Stufe 1):</b> ${escapeHtml(llmResultStufe1.begruendung_llm || 'N/A')}</p>`;
        llmAnalysisHtml += `<p class="processing-notice"><i>Prüfe Regeln und finale Abrechnung...</i></p>`;

        // Zeige LLM-Analyse im Spinner-Bereich an
        showSpinner(llmAnalysisHtml);

        // --- Baue das FINALE HTML für den Output-Bereich ---
        // Kurze Verzögerung, damit der Spinner sichtbar ist
        setTimeout(() => {
            htmlOutput = `<h2>Ergebnisse für «${escapeHtml(userInput)}»</h2>`;
            // Titel "Finale Abrechnung" entfernt

            let abrechnungsDetailHtml = ""; // HTML für die Tabelle/Details

            switch (abrechnung.type) {
                case "Pauschale":
                    console.log("[getBillingAnalysis] Abrechnungstyp: Pauschale", abrechnung.details);
                    htmlOutput += `<p class="success"><b>Abrechnung als Pauschale empfohlen.</b></p>`;
                    if (abrechnung.details) {
                         // Rufe Hilfsfunktion zur Anzeige der Pauschale auf
                         abrechnungsDetailHtml = displayPauschale(abrechnung.details, abrechnung.bedingungs_pruef_html);
    
                         // *** Zeige Bedingungsfehler an, falls vorhanden ***
                         if (abrechnung.bedingungs_fehler && abrechnung.bedingungs_fehler.length > 0) {
                              abrechnungsDetailHtml += `<p class="error" style="margin-top: 10px;"><b>Achtung: Folgende Bedingungen sind aktuell nicht erfüllt:</b></p><ul>`;
                              abrechnung.bedingungs_fehler.forEach(fehler => {
                                   abrechnungsDetailHtml += `<li class="error">${escapeHtml(fehler)}</li>`;
                              });
                              abrechnungsDetailHtml += `</ul>`;
                         }    
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
                     if (ruleResultsDetailsList && ruleResultsDetailsList.length > 0) {
                         abrechnungsDetailHtml += `<details style="margin-top:1em;"><summary>Details zur Regelprüfung (evtl. relevant)</summary>`;
                         ruleResultsDetailsList.forEach((resultItem) => {
                             const lkn = resultItem.lkn || 'Unbekannt';
                             abrechnungsDetailHtml += `<h5>LKN: ${lkn} (Finale Menge: ${resultItem.finale_menge})</h5>`;
                             if (resultItem.regelpruefung && !resultItem.regelpruefung.abrechnungsfaehig) {
                                 if (resultItem.regelpruefung.fehler && resultItem.regelpruefung.fehler.length > 0) {
                                      abrechnungsDetailHtml += `<ul>`;
                                      resultItem.regelpruefung.fehler.forEach(fehler => { abrechnungsDetailHtml += `<li class="error">${escapeHtml(fehler)}</li>`; });
                                      abrechnungsDetailHtml += `</ul>`;
                                 } else { abrechnungsDetailHtml += `<p><i>Keine spezifischen Fehler gefunden, aber nicht abrechnungsfähig.</i></p>`; }
                             } else if (resultItem.regelpruefung && resultItem.regelpruefung.fehler && resultItem.regelpruefung.fehler.length > 0) {
                                 abrechnungsDetailHtml += `<p><b>Hinweise:</b></p><ul>`;
                                 resultItem.regelpruefung.fehler.forEach(hinweis => {
                                      const style = hinweis.includes("Menge auf") ? "color: var(--accent); font-weight: bold;" : "";
                                      abrechnungsDetailHtml += `<li style="${style}">${escapeHtml(hinweis)}</li>`;
                                 });
                                 abrechnungsDetailHtml += `</ul>`;
                             } else if (resultItem.regelpruefung) { abrechnungsDetailHtml += `<p><i>Regelprüfung OK oder nicht durchgeführt.</i></p>`; }
                             else { abrechnungsDetailHtml += `<p><i>Kein Regelprüfungsergebnis vorhanden.</i></p>`; }
                         });
                         abrechnungsDetailHtml += `</details>`;
                     }
                    break;

                default:
                    console.error("[getBillingAnalysis] Unbekannter Abrechnungstyp:", abrechnung.type);
                    htmlOutput += `<p class="error"><b>Unbekannter Abrechnungstyp vom Server.</b></p>`;
            }

            htmlOutput += abrechnungsDetailHtml; // Füge die generierte Tabelle/Fehler hinzu
            displayOutput(htmlOutput, "info"); // Zeige das finale Ergebnis im Haupt-Output
            console.log("[getBillingAnalysis] Frontend-Verarbeitung abgeschlossen.");
            hideSpinner(); // Spinner ausblenden, nachdem der Output gesetzt wurde

        }, 100); // Kurze Verzögerung von 100ms

    } catch (error) {
         console.error("[getBillingAnalysis] Unerwarteter Fehler bei Ergebnisverarbeitung:", error);
         displayOutput(`<p class="error">Ein interner Fehler ist aufgetreten: ${escapeHtml(error.message)}</p><pre>${escapeHtml(error.stack)}</pre>`, "error");
         hideSpinner(); // Spinner auch hier ausblenden
    }
    // Das finally hier ist nicht mehr nötig, da es im setTimeout-Callback ist
} // Ende getBillingAnalysis


// ─── 4 · Hilfsfunktionen zur ANZEIGE von Pauschalen/TARDOC ────

function displayPauschale(pauschaleDetails, bedingungsHtml = "") {
    // --- !!! ANPASSEN: Korrekten Schlüssel für Pauschale in Pauschalen-Daten !!! ---
    const PAUSCHALE_KEY = 'Pauschale';
    const PAUSCHALE_TEXT_KEY = 'Pauschale_Text';
    const PAUSCHALE_TP_KEY = 'Taxpunkte';
    // --- !!! ENDE ANPASSUNG !!! ---
    if (!pauschaleDetails) return "<p class='error'>Pauschalendetails fehlen.</p>";
    let html = `<!-- Titel "Abrechnung als Pauschale" wird jetzt in getBillingAnalysis gesetzt -->`;
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
         html += `<details><summary>Details Pauschalen-Bedingungsprüfung</summary>${bedingungsHtml}</details>`;
    }
    return html;
}

// Zeigt die Tabelle für die abzurechnenden TARDOC-Leistungen an
// Nimmt ruleResultsDetailsList entgegen, um Regelhinweise anzuzeigen
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

        // --- !!! SCHLÜSSELNAMEN PRÜFEN / ANPASSEN !!! ---
        const name = leistung.beschreibung || tardocDetails.leistungsname || 'N/A';
        const al = tardocDetails.al;
        const ipl = tardocDetails.ipl;
        let regelnHtml = tardocDetails.regeln ? `<p>${escapeHtml(tardocDetails.regeln)}</p>` : ''; // TARDOC-Regeln
        // --- !!! ENDE ANPASSUNG !!! ---

        // --- Füge Regelhinweise aus Backend hinzu ---
        const ruleResult = ruleResultsDetailsList.find(r => r.lkn === lkn);
        let hasHint = false; // Flag für roten Text
        let hintListHtml = ""; // Baue die Liste separat auf
        // Zeige Hinweise nur, wenn Fehler vorhanden sind (da abrechnungsfaehig=true sein muss, um hier zu sein)
        if (ruleResult && ruleResult.regelpruefung && ruleResult.regelpruefung.fehler && ruleResult.regelpruefung.fehler.length > 0) {
             if (regelnHtml) regelnHtml += "<hr style='margin: 5px 0; border-color: #eee;'>";
             regelnHtml += `<p><b>Hinweise Regelprüfung:</b></p><ul>`;
             ruleResult.regelpruefung.fehler.forEach(hinweis => {
                  const isReduction = hinweis.includes("Menge auf");
                  const style = isReduction ? "color: var(--danger); font-weight: bold;" : ""; // Rot/Fett bei Reduktion
                  if (isReduction) hasHint = true; // Setze Flag für roten Details-Link
                  regelnHtml += `<li style="${style}">${escapeHtml(hinweis)}</li>`;
             });
             regelnHtml += `</ul>`;
        }
        // --- ENDE Regelhinweise ---

        const total_tp = (al + ipl) * anzahl;
        gesamtTP += total_tp;

        // Style für Details-Summary, wenn ein Hinweis vorhanden ist
        const detailsSummaryStyle = hasHint ? ' class="rule-hint-trigger"' : ''; // CSS-Klasse für roten Text

        tardocTableBody += `
            <tr>
                <td>${escapeHtml(lkn)}</td><td>${escapeHtml(name)}</td>
                <td>${al.toFixed(2)}</td><td>${ipl.toFixed(2)}</td>
                <td>${anzahl}</td><td>${total_tp.toFixed(2)}</td>
                <td>${regelnHtml ? `<details><summary${detailsSummaryStyle}>Details</summary>${regelnHtml}</details>` : ''}</td>
            </tr>`;
    }

    let html = `<!-- Titel "TARDOC-Positionen" wird jetzt in getBillingAnalysis gesetzt -->`;
    html += `
        <table border="1" style="border-collapse: collapse; width: 100%; margin-bottom: 10px;">
            <thead><tr><th>LKN</th><th>Leistung</th><th>AL</th><th>IPL</th><th>Anzahl</th><th>Total TP</th><th>Regeln</th></tr></thead>
            <tbody>${tardocTableBody}</tbody>
            <tfoot><tr><th colspan="5" style="text-align:right;">Gesamt TARDOC TP:</th><th colspan="2">${gesamtTP.toFixed(2)}</th></tr></tfoot>
        </table>`;
    return html;
}

// Hilfsfunktion: Sucht nur die TARDOC-Details (AL, IPL, Regeln etc.) lokal
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