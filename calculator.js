// calculator.js - Vollständige Version (30.04.2025)
// Arbeitet mit zweistufigem Backend. Holt lokale Details zur Anzeige.

// ─── 0 · Globale Datencontainer ─────────────────────────────────────────────
let data_leistungskatalog = [];
let data_pauschaleLeistungsposition = [];
let data_pauschalen = [];
let data_pauschaleBedingungen = [];
let data_tardocGesamt = [];
let data_tabellen = [];
let mouseSpinnerElement = null;
let isProcessing = false; // Flag, ob gerade verarbeitet wird

// Pfade zu den lokalen JSON-Daten
const DATA_PATHS = {
    leistungskatalog: 'data/tblLeistungskatalog.json',
    pauschaleLP: 'data/tblPauschaleLeistungsposition.json',
    pauschalen: 'data/tblPauschalen.json',
    pauschaleBedingungen: 'data/tblPauschaleBedingungen.json',
    tardocGesamt: 'data/TARDOCGesamt_optimiert_Tarifpositionen.json', // ANPASSEN!
    tabellen: 'data/tblTabellen.json' // Korrigiert
};
const CACHE_KEY = 'tardocRechnerDataCache';
const CACHE_VERSION = '1.1'; // Version erhöht für Cache-Reset

// ─── 1 · Utility‑Funktionen ────────────────────────────────────────────────
function $(id) { return document.getElementById(id); }

function escapeHtml(s) {
    if (s === null || s === undefined) return "";
    // Korrekte Ersetzung mit numerischen Entities für Anführungszeichen
    return String(s).replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "\"": "&#34;", "'": "&#39;" }[c]));
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

function showSpinner(htmlContent = "Prüfung läuft, bitte warten...") { // Standardtext hinzugefügt
    const spinner = $('spinner');
    const button = $('analyzeButton');
    if (spinner) {
        spinner.innerHTML = htmlContent; // Zeige übergebenen HTML-Inhalt
        spinner.style.display = 'block';
    }
    if (button) button.disabled = true;
}

function hideSpinner() {
    const spinner = $('spinner');
    const button = $('analyzeButton');
    if (spinner) {
        spinner.innerHTML = ""; // Inhalt leeren
        spinner.style.display = 'none';
    }
    if (button) button.disabled = false;
}

// Funktion zum Aktualisieren der Spinner-Position
const updateSpinnerPosition = (event) => {
    if (mouseSpinnerElement && isProcessing) {
        // Kleiner Offset, damit der Spinner nicht direkt unter dem Cursor ist
        const offsetX = 15;
        const offsetY = 10;
        mouseSpinnerElement.style.left = `${event.clientX + offsetX}px`;
        mouseSpinnerElement.style.top = `${event.clientY + offsetY}px`;
    }
};

// Funktion zum Starten des Maus-Spinners
function showMouseSpinner() {
    if (!mouseSpinnerElement) {
        mouseSpinnerElement = $('mouseSpinner'); // Hole das Element einmal
    }
    if (mouseSpinnerElement) {
        isProcessing = true;
        mouseSpinnerElement.style.display = 'block';
        // Füge den Event Listener hinzu, wenn Verarbeitung startet
        document.addEventListener('mousemove', updateSpinnerPosition);
        console.log("Mouse Spinner aktiviert.");
    }
    // Deaktiviere den Button
    const button = $('analyzeButton');
    if (button) button.disabled = true;
}

// Funktion zum Stoppen des Maus-Spinners
function hideMouseSpinner() {
    if (mouseSpinnerElement) {
        isProcessing = false;
        mouseSpinnerElement.style.display = 'none';
        // Entferne den Event Listener, wenn Verarbeitung endet
        document.removeEventListener('mousemove', updateSpinnerPosition);
        console.log("Mouse Spinner deaktiviert.");
    }
     // Aktiviere den Button
    const button = $('analyzeButton');
    if (button) button.disabled = false;
}
// --- Ende Maus-Spinner Funktionen ---

// ─── 2 · Daten laden mit Caching ───────────────────────────────────────────
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
    console.log("Prüfe Daten-Cache...");
    const cachedData = localStorage.getItem(CACHE_KEY);
    let dataValid = false;
    let loadedDataArray = [];

    if (cachedData) {
        try {
            const parsed = JSON.parse(cachedData);
            if (parsed.version === CACHE_VERSION && parsed.data && Array.isArray(parsed.data) && parsed.data.length === Object.keys(DATA_PATHS).length) {
                loadedDataArray = parsed.data;
                dataValid = true;
                console.log("Daten aus localStorage-Cache geladen.");
            } else { console.log("Cache-Version veraltet oder Daten ungültig."); localStorage.removeItem(CACHE_KEY); }
        } catch (e) { console.warn("Fehler beim Parsen des Caches:", e); localStorage.removeItem(CACHE_KEY); }
    }

    if (!dataValid) {
        console.log("Lade Frontend-Daten vom Server...");
        displayOutput("<p>Lade Tarifdaten...</p>", "info");
        try {
            loadedDataArray = await Promise.all([
                fetchJSON(DATA_PATHS.leistungskatalog), fetchJSON(DATA_PATHS.pauschaleLP),
                fetchJSON(DATA_PATHS.pauschalen), fetchJSON(DATA_PATHS.pauschaleBedingungen),
                fetchJSON(DATA_PATHS.tardocGesamt), fetchJSON(DATA_PATHS.tabellen)
            ]);

            if (loadedDataArray.some(data => data === undefined)) { throw new Error("Einige Daten konnten nicht korrekt vom Server geholt werden."); }

            const cachePayload = { version: CACHE_VERSION, data: loadedDataArray };
            try { localStorage.setItem(CACHE_KEY, JSON.stringify(cachePayload)); console.log("Daten im Cache gespeichert."); }
            catch (e) { console.warn("Fehler beim Speichern im Cache:", e); }

            console.log("Frontend-Daten vom Server geladen.");
            if (!$("output")?.classList.contains("error")) {
                displayOutput("<p>Daten geladen. Bereit zur Prüfung.</p>", "success");
                setTimeout(() => { if ($("output") && $("output").className === 'success') displayOutput(""); }, 2000);
            }
        } catch (error) {
             console.error("Schwerwiegender Fehler beim Laden der Frontend-Daten:", error);
             displayOutput(`<p class="error">Fehler beim Laden der notwendigen Frontend-Daten: ${escapeHtml(error.message)}. Bitte Seite neu laden.</p>`, "error");
             data_leistungskatalog = []; data_pauschaleLeistungsposition = []; data_pauschalen = [];
             data_pauschaleBedingungen = []; data_tardocGesamt = []; data_tabellen = [];
             return;
        }
    }

    // Weise die geladenen/gecachten Daten den globalen Variablen zu
    if (loadedDataArray && loadedDataArray.length === Object.keys(DATA_PATHS).length) {
        [ data_leistungskatalog, data_pauschaleLeistungsposition, data_pauschalen,
          data_pauschaleBedingungen, data_tardocGesamt, data_tabellen ] = loadedDataArray;
    } else {
         console.error("Fehler bei der Zuweisung der geladenen Daten.");
         displayOutput(`<p class="error">Interner Fehler beim Verarbeiten der geladenen Daten.</p>`, "error");
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

    // *** KORREKTER FUNKTIONSAUFRUF ***
    showSpinner("<h4>Analyse gestartet...</h4><p>Sende Anfrage an Server...</p>");
    showMouseSpinner();
    displayOutput("", "info"); // Leere den Haupt-Output

    try {
        console.log("[getBillingAnalysis] Sende Anfrage an Backend...");
        const requestBody = { inputText: userInput, icd: icdInput, gtin: gtinInput };
        const res = await fetch("/api/analyze-billing", {
            method: "POST",
            headers: {"Content-Type":"application/json"},
            body: JSON.stringify(requestBody)
        });
        rawResponseText = await res.text();
        console.log("[getBillingAnalysis] Raw Response vom Backend erhalten:", rawResponseText);
        showSpinner("<h4>Analyse läuft...</h4><p>Antwort vom Server erhalten, parse Daten...</p>");

        if (!res.ok) {
            let errorMsg = `${res.status} ${res.statusText}`;
            try { const errJson = JSON.parse(rawResponseText); errorMsg = `${res.status}: ${errJson.error || 'Unbekannter Fehler'} ${errJson.details ? '- ' + errJson.details : ''}`; } catch(e) { /* Ignore */ }
            throw new Error(errorMsg);
        }
        try { backendResponse = JSON.parse(rawResponseText); }
        catch (e) { throw new Error(`Ungültiges JSON vom Server empfangen: ${e.message}`); }

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
        hideMouseSpinner();
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
        let llmAnalysisHtml = `<h4>LLM-Analyse (Stufe 1)</h4>`;
        if (identifiedLeistungen.length > 0) {
            const lknStrings = identifiedLeistungen.map(l => `${l.lkn} (${l.typ || '?'}, Menge:${l.menge ?? 'N/A'})`).join(', ');
            llmAnalysisHtml += `<p><b>Identifizierte LKN(s):</b> ${lknStrings}</p><ul>`;
            identifiedLeistungen.forEach(l => {
                 const desc = l.beschreibung || beschreibungZuLKN(l.lkn) || 'N/A';
                 llmAnalysisHtml += `<li><b>${escapeHtml(l.lkn)}:</b> ${escapeHtml(desc)}</li>`;
            });
            llmAnalysisHtml += `</ul>`;
            showSpinner(llmAnalysisHtml);
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
        htmlOutput = `<h2>Ergebnisse für «${escapeHtml(userInput)}»</h2>`;
        // Titel "Finale Abrechnung" entfernt

        let abrechnungsDetailHtml = ""; // HTML für die Tabelle/Details

        switch (abrechnung.type) {
            case "Pauschale":
                console.log("[getBillingAnalysis] Abrechnungstyp: Pauschale", abrechnung.details);
                htmlOutput += `<p class="success"><b>Abrechnung als Pauschale empfohlen.</b></p>`;
                if (abrechnung.details) {
                     abrechnungsDetailHtml = displayPauschale(abrechnung.details, abrechnung.bedingungs_pruef_html);
                } else { abrechnungsDetailHtml = "<p class='error'>Fehler: Pauschalendetails fehlen.</p>"; }
                break;

            case "TARDOC":
                console.log("[getBillingAnalysis] Abrechnungstyp: TARDOC", abrechnung.leistungen);
                htmlOutput += `<p class="success"><b>Abrechnung als TARDOC-Einzelleistung(en) empfohlen.</b></p>`;
                if (abrechnung.leistungen && abrechnung.leistungen.length > 0) {
                     // Übergib die Regel-Details an die Tabellenfunktion
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
                         // Zeige nur LKNs, die Probleme hatten oder relevant sind
                         if (resultItem.regelpruefung && !resultItem.regelpruefung.abrechnungsfaehig) {
                             abrechnungsDetailHtml += `<h5>LKN: ${lkn} (Finale Menge: ${resultItem.finale_menge})</h5>`;
                             if (resultItem.regelpruefung.fehler && resultItem.regelpruefung.fehler.length > 0) {
                                  abrechnungsDetailHtml += `<ul>`;
                                  resultItem.regelpruefung.fehler.forEach(fehler => { abrechnungsDetailHtml += `<li class="error">${escapeHtml(fehler)}</li>`; });
                                  abrechnungsDetailHtml += `</ul>`;
                             } else { abrechnungsDetailHtml += `<p><i>Keine spezifischen Fehler gefunden, aber nicht abrechnungsfähig.</i></p>`; }
                         } else if (resultItem.regelpruefung && resultItem.regelpruefung.fehler && resultItem.regelpruefung.fehler.length > 0) {
                             // Zeige auch Hinweise (z.B. Mengenreduktion)
                             abrechnungsDetailHtml += `<h5>LKN: ${lkn} (Finale Menge: ${resultItem.finale_menge})</h5>`;
                             abrechnungsDetailHtml += `<p><b>Hinweise:</b></p><ul>`;
                             resultItem.regelpruefung.fehler.forEach(hinweis => {
                                  const style = hinweis.includes("Menge auf") ? "color: var(--accent); font-weight: bold;" : "";
                                  abrechnungsDetailHtml += `<li style="${style}">${escapeHtml(hinweis)}</li>`;
                             });
                             abrechnungsDetailHtml += `</ul>`;
                         }
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

    } catch (error) {
         console.error("[getBillingAnalysis] Unerwarteter Fehler bei Ergebnisverarbeitung:", error);
         displayOutput(`<p class="error">Ein interner Fehler ist aufgetreten: ${escapeHtml(error.message)}</p><pre>${escapeHtml(error.stack)}</pre>`, "error");
    } finally {
         hideSpinner(); // Spinner am Ende ausblenden
         hideMouseSpinner();
    }
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
         html += `<details><summary>Details Pauschalen-Bedingungsprüfung</summary>${bedingungsHtml}</details>`; // Bedingungs-HTML vom Backend
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
        let hasErrorHint = false; // Umbenannt für Klarheit (zeigt an, ob es einen Fehler/Warnhinweis gibt)
        let hintListHtml = ""; // Baue die Liste separat auf

        if (ruleResult && ruleResult.regelpruefung && ruleResult.regelpruefung.fehler && ruleResult.regelpruefung.fehler.length > 0) {
             hintListHtml += `<ul>`;
             ruleResult.regelpruefung.fehler.forEach(hinweis => {
                  const isReduction = hinweis.includes("Menge auf");
                  const style = isReduction ? "color: var(--danger); font-weight: bold;" : ""; // Rot/Fett bei Reduktion
                  if (isReduction) hasErrorHint = true; // Setze Flag, wenn Menge reduziert wurde
                  hintListHtml += `<li style="${style}">${escapeHtml(hinweis)}</li>`;
             });
             hintListHtml += `</ul>`;
        }
        // --- ENDE Regelhinweise ---

        const total_tp = (al + ipl) * anzahl;
        gesamtTP += total_tp;

        // --- Baue Details-Summary dynamisch ---
        let summaryText = "Details";
        let summaryClass = "";
        if (hasErrorHint) {
            summaryText = "Details (Hinweis!)"; // Geänderter Text
            summaryClass = "rule-hint-trigger"; // CSS-Klasse für roten Text
        }
        // --- Ende Details-Summary ---

        // Füge TARDOC-Regeln und Regelprüfungshinweise zusammen
        let combinedRegelnHtml = "";
        if (tardocDetails.regeln) {
             combinedRegelnHtml += `<p><b>TARDOC-Regeln:</b> ${escapeHtml(tardocDetails.regeln)}</p>`;
        }
        if (hintListHtml) {
             if (combinedRegelnHtml) combinedRegelnHtml += "<hr style='margin: 5px 0; border-color: #eee;'>";
             combinedRegelnHtml += `<p><b>Hinweise Regelprüfung:</b></p>${hintListHtml}`;
        }

         // Baue die Tabellenzeile (<tr>)
        tardocTableBody += `
            <tr>
                <td>${escapeHtml(lkn)}</td><td>${escapeHtml(name)}</td>
                <td>${al.toFixed(2)}</td><td>${ipl.toFixed(2)}</td>
                <td>${anzahl}</td><td>${total_tp.toFixed(2)}</td>
                <td>${combinedRegelnHtml ? `<details><summary class="${summaryClass}">${summaryText}</summary>${combinedRegelnHtml}</details>` : ''}</td>
            </tr>`;
    } // Ende der Schleife über TARDOC-Leistungen

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