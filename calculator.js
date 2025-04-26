// calculator.js - Vollständige Version (26.04.2025)
// Arbeitet mit Backend, das Mengen berechnet und Regeln prüft.
// Frontend zeigt Ergebnisse an und holt Pauschalen/TARDOC-Details lokal.

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
    tabellen: 'data/tblTabellen.json'
};
const CACHE_KEY = 'tardocRechnerDataCache';
const CACHE_VERSION = '1.1'; // Version erhöht für Cache-Reset

// ─── 1 · Utility‑Funktionen ────────────────────────────────────────────────
function $(id) {
    return document.getElementById(id);
}

function escapeHtml(s) {
    if (s === null || s === undefined) return "";
    // Korrekte Ersetzung mit numerischen Entities für Anführungszeichen
    return String(s).replace(/[&<>"']/g, c => ({
        "&": "&",
        "<": "<",
        ">": ">",
        "\"": "&quot;",
        "'": "'"  
    }[c]));
}

// Findet Beschreibung im lokal geladenen Katalog
function beschreibungZuLKN(lkn) {
    if (!data_leistungskatalog || typeof lkn !== 'string') return "";
    const hit = data_leistungskatalog.find(e => e.LKN?.toUpperCase() === lkn.toUpperCase());
    return hit ? hit.Beschreibung || "Beschreibung nicht gefunden" : "Beschreibung nicht gefunden";
}

function displayOutput(html, type = "info") {
    const out = $("output");
    if (!out) { console.error("Output element not found!"); return; }
    out.innerHTML = html;
    out.className = type;
}

// --- Spinner-Funktionen ---
function showSpinner() {
    const spinner = $('spinner');
    const button = $('analyzeButton');
    if (spinner) spinner.style.display = 'block';
    if (button) button.disabled = true;
}

function hideSpinner() {
    const spinner = $('spinner');
    const button = $('analyzeButton');
    if (spinner) spinner.style.display = 'none';
    if (button) button.disabled = false;
}

// ─── 2 · Daten laden mit Caching ───────────────────────────────────────────
async function fetchJSON(path) {
    try {
        const r = await fetch(path);
        if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
        return await r.json();
    } catch (e) {
        console.warn(`Fehler beim Laden von ${path}:`, e);
        return []; // Leeres Array bei Fehler
    }
}

async function loadData() {
    console.log("Prüfe Daten-Cache...");
    const cachedData = localStorage.getItem(CACHE_KEY);
    let dataValid = false;

    if (cachedData) {
        try {
            const parsed = JSON.parse(cachedData);
            if (parsed.version === CACHE_VERSION && parsed.data) {
                [
                    data_leistungskatalog, data_pauschaleLeistungsposition, data_pauschalen,
                    data_pauschaleBedingungen, data_tardocGesamt, data_tabellen
                ] = parsed.data;
                dataValid = true;
                console.log("Daten aus localStorage-Cache geladen.");
            } else {
                console.log("Cache-Version veraltet oder Daten ungültig.");
                localStorage.removeItem(CACHE_KEY);
            }
        } catch (e) {
            console.warn("Fehler beim Parsen des Caches:", e);
            localStorage.removeItem(CACHE_KEY);
        }
    }

    if (!dataValid) {
        console.log("Lade Frontend-Daten vom Server...");
        displayOutput("<p>Lade Tarifdaten...</p>", "info");
        try {
            const results = await Promise.all([
                fetchJSON(DATA_PATHS.leistungskatalog), fetchJSON(DATA_PATHS.pauschaleLP),
                fetchJSON(DATA_PATHS.pauschalen), fetchJSON(DATA_PATHS.pauschaleBedingungen),
                fetchJSON(DATA_PATHS.tardocGesamt), fetchJSON(DATA_PATHS.tabellen)
            ]);

            if (results.some(res => res === undefined)) {
                 throw new Error("Einige Daten konnten nicht geladen werden.");
            }

            [
                data_leistungskatalog, data_pauschaleLeistungsposition, data_pauschalen,
                data_pauschaleBedingungen, data_tardocGesamt, data_tabellen
            ] = results;

            const cachePayload = { version: CACHE_VERSION, data: results };
            try {
                 localStorage.setItem(CACHE_KEY, JSON.stringify(cachePayload));
                 console.log("Daten im localStorage-Cache gespeichert.");
            } catch (e) { console.warn("Fehler beim Speichern im localStorage:", e); }

            console.log("Frontend-Daten vom Server geladen.");
            displayOutput("<p>Daten geladen. Bereit zur Prüfung.</p>", "success");
            setTimeout(() => { if ($("output") && $("output").className === 'success') displayOutput(""); }, 2000);

        } catch (error) {
             console.error("Schwerwiegender Fehler beim Laden der Frontend-Daten:", error);
             displayOutput(`<p>Fehler beim Laden der notwendigen Frontend-Daten: ${escapeHtml(error.message)}. Die Anwendung funktioniert möglicherweise nicht korrekt.</p>`, "error");
             return;
        }
    }

    // Finale Prüfung, ob kritische Daten vorhanden sind
    if (!data_leistungskatalog || data_leistungskatalog.length === 0) console.error("Leistungskatalog ist leer!");
    if (!data_tardocGesamt || data_tardocGesamt.length === 0) console.warn("TARDOC-Daten sind leer!");
    if (!data_pauschalen || data_pauschalen.length === 0) console.warn("Pauschalen-Daten sind leer!");
}

function clearDataCache() {
    localStorage.removeItem(CACHE_KEY);
    console.log("Daten-Cache gelöscht.");
    // Setze globale Variablen zurück, um Neuladen zu erzwingen
    data_leistungskatalog = []; data_pauschaleLeistungsposition = []; data_pauschalen = [];
    data_pauschaleBedingungen = []; data_tardocGesamt = []; data_tabellen = [];
    displayOutput("<p>Cache gelöscht. Lade Daten neu...</p>", "info");
    loadData().then(() => {
         if ($("output") && $("output").className === 'success') {
              setTimeout(() => { if ($("output").className === 'success') displayOutput(""); }, 1500);
         }
    });
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
    let htmlOutput = ""; // Haupt-HTML-String

    const outputDiv = $("output");
    if (!outputDiv) { console.error("Output element not found!"); return; }

    if (!userInput) {
        displayOutput("<p>Bitte Leistungsbeschreibung eingeben.</p>", "error");
        return;
    }

    showSpinner();
    displayOutput("<p>Prüfe Abrechnung …</p>", "info");

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

        if (!res.ok) {
            let errorMsg = `${res.status} ${res.statusText}`;
            try {
                 const errJson = JSON.parse(rawResponseText);
                 errorMsg = `${res.status}: ${errJson.error || 'Unbekannter Fehler'} ${errJson.details ? '- ' + errJson.details : ''}`;
            } catch(e) { /* Ignore */ }
            throw new Error(errorMsg);
        }

        try {
            backendResponse = JSON.parse(rawResponseText);
        } catch (e) {
            console.error("Fehler beim Parsen der Backend-JSON-Antwort:", e);
            console.error("Raw Response:", rawResponseText);
            throw new Error(`Ungültiges JSON vom Server empfangen: ${e.message}`);
        }

        console.log("[getBillingAnalysis] Backend-Antwort geparst:", backendResponse);

        // Strukturprüfung
        console.log("[getBillingAnalysis] Prüfe Backend-Antwortstruktur...");
        let structureOk = true;
        let errorReason = "Unbekannter Strukturfehler";
        if (!backendResponse) { structureOk = false; errorReason = "BackendResponse ist null."; }
        else {
            if (!backendResponse.llm_ergebnis) { structureOk = false; errorReason = "'llm_ergebnis' fehlt."; }
            if (!backendResponse.regel_ergebnisse) { structureOk = false; errorReason = "'regel_ergebnisse' fehlt."; }
            else if (!Array.isArray(backendResponse.regel_ergebnisse)) { structureOk = false; errorReason = "'regel_ergebnisse' ist kein Array."; }
            else if (backendResponse.regel_ergebnisse.length > 0) {
                 const firstResult = backendResponse.regel_ergebnisse[0];
                 // Prüfe auf 'regelpruefung' UND 'finale_menge'
                 if (!firstResult || firstResult.regelpruefung === undefined || firstResult.finale_menge === undefined) {
                      structureOk = false; errorReason = "Struktur innerhalb von 'regel_ergebnisse' ist unerwartet.";
                 }
            }
        }
        if (!structureOk) {
             console.error("Fehlergrund:", errorReason); console.error("Empfangenes Objekt:", backendResponse);
             throw new Error(`Unerwartete Datenstruktur vom Server erhalten (${errorReason})`);
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
        const llmResult = backendResponse.llm_ergebnis;
        const ruleResultsList = backendResponse.regel_ergebnisse; // Liste der Ergebnisse
        const identifiedLeistungen = llmResult.identified_leistungen || [];
        const extractedInfo = llmResult.extracted_info || {};

        htmlOutput = `<h2>Ergebnisse für «${escapeHtml(userInput)}»</h2>`;

        // 1. LLM Ergebnis anzeigen
        console.log("[getBillingAnalysis] Zeige LLM-Ergebnis an.");
        htmlOutput += `<h3>LLM-Analyse</h3>`;
        if (identifiedLeistungen.length > 0) {
            const lknStrings = identifiedLeistungen.map(l => `${l.lkn} (${l.typ || '?'})`).join(', ');
            htmlOutput += `<p><b>Identifizierte LKN(s):</b> ${lknStrings}</p>`;
            htmlOutput += `<ul>`;
            identifiedLeistungen.forEach(l => {
                 const desc = l.beschreibung || beschreibungZuLKN(l.lkn) || 'N/A';
                 htmlOutput += `<li><b>${escapeHtml(l.lkn)}:</b> ${escapeHtml(desc)}</li>`;
            });
            htmlOutput += `</ul>`;
        } else { htmlOutput += `<p><i>Keine LKN identifiziert.</i></p>`; }
        let extractedDetails = [];
        if (extractedInfo.dauer_minuten !== null) extractedDetails.push(`Dauer: ${extractedInfo.dauer_minuten} Min.`);
        if (extractedInfo.menge_allgemein !== null && extractedInfo.menge_allgemein !== 0) extractedDetails.push(`Menge: ${extractedInfo.menge_allgemein}`);
        if (extractedInfo.alter !== null && extractedInfo.alter !== 0) extractedDetails.push(`Alter: ${extractedInfo.alter}`);
        if (extractedInfo.geschlecht !== null && extractedInfo.geschlecht !== 'null' && extractedInfo.geschlecht !== 'unbekannt') extractedDetails.push(`Geschlecht: ${extractedInfo.geschlecht}`);
        if (extractedDetails.length > 0) { htmlOutput += `<p><b>Extrahierte Details:</b> ${extractedDetails.join(', ')}</p>`; }
        htmlOutput += `<p><b>Begründung LLM:</b> ${escapeHtml(llmResult.begruendung_llm || 'N/A')}</p>`;
        htmlOutput += `<hr>`;

        // 2. Regelprüfung Ergebnis anzeigen
        console.log("[getBillingAnalysis] Zeige Regelprüfungsergebnisse an.");
        htmlOutput += `<h3>Regelprüfung (pro LKN)</h3>`;
        let allRulesOk = true;
        if (!ruleResultsList || !Array.isArray(ruleResultsList)) { htmlOutput += `<p class="error">Fehler: Regelprüfungsergebnisse vom Backend fehlen oder haben falsches Format.</p>`; allRulesOk = false; }
        else if (ruleResultsList.length === 0 && identifiedLeistungen.length > 0) { htmlOutput += `<p class="error">Fehler: Keine Regelprüfungsergebnisse vom Backend erhalten, obwohl LKNs identifiziert wurden.</p>`; allRulesOk = false; }
        else if (ruleResultsList.length === 0 && identifiedLeistungen.length === 0) { htmlOutput += `<p>Keine LKNs zur Prüfung vorhanden.</p>`; allRulesOk = false; }
        else {
            ruleResultsList.forEach((resultItem, index) => {
                const lkn = resultItem.lkn || `Unbekannt (Index ${index})`;
                if (!resultItem.regelpruefung) {
                    console.error(`Fehler: 'regelpruefung' fehlt für LKN ${lkn} in Backend-Antwort! Index: ${index}`, resultItem);
                    htmlOutput += `<h4>Prüfung für LKN: ${lkn}</h4>`;
                    htmlOutput += `<p class="error"><b>Fehler: Regelprüfungsergebnis fehlt!</b></p>`;
                    allRulesOk = false; return;
                }
                const regelPruefung = resultItem.regelpruefung;
                htmlOutput += `<h4>Prüfung für LKN: ${lkn}</h4>`;
                if (regelPruefung.abrechnungsfaehig) {
                    htmlOutput += `<p class="success"><b>Regelkonform abrechnungsfähig</b></p>`;
                    if (regelPruefung.fehler && regelPruefung.fehler.length > 0) {
                         htmlOutput += `<p><b>Hinweise:</b></p><ul>`;
                         regelPruefung.fehler.forEach(hinweis => { htmlOutput += `<li>${escapeHtml(hinweis)}</li>`; });
                         htmlOutput += `</ul>`;
                    }
                } else {
                    allRulesOk = false;
                    htmlOutput += `<p class="error"><b>Nicht regelkonform abrechnungsfähig</b></p>`;
                    if (regelPruefung.fehler && regelPruefung.fehler.length > 0) {
                         htmlOutput += `<p><b>Verletzte Regeln:</b></p><ul>`;
                         regelPruefung.fehler.forEach(fehler => { htmlOutput += `<li>${escapeHtml(fehler)}</li>`; });
                         htmlOutput += `</ul>`;
                    } else { htmlOutput += `<p><i>Keine spezifischen Regelverletzungen angegeben.</i></p>`; }
                }
            });
        }
        htmlOutput += `<hr>`;

        // 3. Finale Abrechnung anzeigen (nur wenn ALLE Regeln OK waren)
        if (!allRulesOk) {
             console.log("[getBillingAnalysis] Regeln nicht OK, Abbruch vor finaler Abrechnung.");
             htmlOutput += `<p class="error"><b>Finale Abrechnung nicht möglich, da Regelverletzungen vorliegen oder Daten fehlen.</b></p>`;
             displayOutput(htmlOutput, "info");
             hideSpinner();
             return;
        }

        console.log("[getBillingAnalysis] Starte finale Abrechnungslogik.");
        htmlOutput += `<h3>Finale Abrechnung</h3>`;
        let abrechnungsDetailHtml = "";
        let hasApplicableResult = false;
        let pauschaleProcessed = false; // Wird in Pauschalenprüfung gesetzt

        // --- a) Pauschalen-Prüfung ---
        const hatPauschalenTyp = identifiedLeistungen.some(l => l.typ === 'P' || l.typ === 'PZ');
        if (hatPauschalenTyp) {
            console.log("[getBillingAnalysis] Prüfe Pauschalen...");
            htmlOutput += `<p><i>Prüfe mögliche Pauschalen...</i></p>`;
            const pauschaleResult = findAndProcessBestPauschale(identifiedLeistungen, icdInput, gtinInput);
            console.log("[getBillingAnalysis] Ergebnis Pauschalenprüfung:", pauschaleResult);
            if (pauschaleResult && pauschaleResult.html !== undefined) {
                 abrechnungsDetailHtml += pauschaleResult.html;
                 if (pauschaleResult.applicable) { hasApplicableResult = true; pauschaleProcessed = true; }
                 else { htmlOutput += `<p><i>Pauschale nicht anwendbar, prüfe TARDOC...</i></p>`; }
            } else { console.error("[getBillingAnalysis] Ungültiges Ergebnis von findAndProcessBestPauschale!"); abrechnungsDetailHtml += `<p class="error">Interner Fehler bei der Pauschalenprüfung.</p>`; }
        } else { console.log("[getBillingAnalysis] Keine Pauschalen-Typen identifiziert."); htmlOutput += `<p><i>Keine Pauschale identifiziert, prüfe TARDOC...</i></p>`; }

        // --- b) TARDOC-Verarbeitung ---
        if (!pauschaleProcessed) {
            console.log("[getBillingAnalysis] Starte TARDOC-Verarbeitung für finale Tabelle...");
            htmlOutput += `<h4>TARDOC-Positionen</h4>`;
            let gesamtTP = 0;
            let tardocTableBody = "";
            let tardocProcessedCount = 0;

            // Iteriere über die Ergebnisse der Regelprüfung
            for (const resultItem of ruleResultsList) {
                 const lkn = resultItem.lkn;
                 const regelPruefung = resultItem.regelpruefung;
                 const finaleMenge = resultItem.finale_menge; // Korrekter Key vom Backend

                 console.log(`[getBillingAnalysis] Prüfe TARDOC für LKN: ${lkn}, Menge: ${finaleMenge}, Regel OK: ${regelPruefung?.abrechnungsfaehig}`);

                 if (lkn && regelPruefung && regelPruefung.abrechnungsfaehig && finaleMenge > 0) {
                      const leistungInfo = identifiedLeistungen.find(l => l.lkn === lkn);
                      const typ = leistungInfo ? leistungInfo.typ : null;

                      // Nur TARDOC-Typen (E/EZ) verarbeiten
                      if (typ === 'E' || typ === 'EZ') {
                           tardocProcessedCount++;
                           console.log(`[getBillingAnalysis] Rufe processTardoc für ${lkn} (Menge: ${finaleMenge}) auf...`);
                           const tardocResult = processTardoc(lkn, icdInput, finaleMenge); // Nutze finale Menge
                           console.log(`[getBillingAnalysis] Ergebnis processTardoc für ${lkn}:`, tardocResult);

                           if (tardocResult.applicable && tardocResult.data) {
                                hasApplicableResult = true;
                                // --- !!! SCHLÜSSELNAMEN PRÜFEN / ANPASSEN !!! ---
                                const TARDOC_LKN_KEY = 'LKN'; // ANPASSEN!
                                const AL_KEY = 'AL_(normiert)'; // ANPASSEN!
                                const IPL_KEY = 'IPL_(normiert)'; // ANPASSEN!
                                const DESC_KEY_1 = 'Bezeichnung'; // ANPASSEN!
                                const RULES_KEY_1 = 'Regeln_bezogen_auf_die_Tarifmechanik'; // ANPASSEN!
                                // --- !!! ENDE ANPASSUNG !!! ---

                                const name = tardocResult.data[DESC_KEY_1] || beschreibungZuLKN(lkn) || 'N/A';
                                const al = parseFloat(tardocResult.data[AL_KEY]) || 0;
                                const ipl = parseFloat(tardocResult.data[IPL_KEY]) || 0;
                                const anzahl = tardocResult.anzahl; // = finaleMenge
                                const total_tp = (al + ipl) * anzahl;
                                const regeln = tardocResult.data[RULES_KEY_1] || '';
                                gesamtTP += total_tp;

                                tardocTableBody += `<tr>
                                    <td>${escapeHtml(lkn)}</td><td>${escapeHtml(name)}</td>
                                    <td>${al.toFixed(2)}</td><td>${ipl.toFixed(2)}</td>
                                    <td>${anzahl}</td><td>${total_tp.toFixed(2)}</td>
                                    <td>${regeln ? `<details><summary>Details</summary><p>${escapeHtml(regeln)}</p></details>` : ''}</td>
                                </tr>`;
                           } else {
                                console.error(`[getBillingAnalysis] processTardoc fehlgeschlagen für ${lkn}.`);
                                abrechnungsDetailHtml += `<p class="error">Fehler bei TARDOC-Details für ${escapeHtml(lkn)}.</p>` + (tardocResult.html || ''); // Füge Fehler-HTML hinzu
                           }
                      } // Ende if Typ E/EZ
                 } // Ende if Regelprüfung OK und Menge > 0
            } // Ende for Schleife

            // Baue Tabelle
            if (tardocTableBody) {
                 console.log("[getBillingAnalysis] Baue TARDOC-Tabelle.");
                 abrechnungsDetailHtml += `<table border="1" style="border-collapse: collapse; width: 100%; margin-bottom: 10px;">
                     <thead><tr><th>LKN</th><th>Leistung</th><th>AL</th><th>IPL</th><th>Anzahl</th><th>Total TP</th><th>Regeln</th></tr></thead>
                     <tbody>${tardocTableBody}</tbody>
                     <tfoot><tr><th colspan="5" style="text-align:right;">Gesamt TARDOC TP:</th><th colspan="2">${gesamtTP.toFixed(2)}</th></tr></tfoot>
                 </table>`;
            } else if (!hasApplicableResult && identifiedLeistungen.filter(l => l.typ === 'E' || l.typ === 'EZ').length > 0) {
                 abrechnungsDetailHtml += `<p><i>Keine TARDOC-Positionen abrechenbar.</i></p>`;
            } else if (!hasApplicableResult && !pauschaleProcessed) { // Nur anzeigen, wenn nicht schon Pauschale verarbeitet wurde
                 abrechnungsDetailHtml += `<p><i>Keine TARDOC-Positionen zur Abrechnung gefunden.</i></p>`;
            }
        } // Ende if (!pauschaleProcessed)

        // --- Abschlussmeldung ---
        if (!hasApplicableResult && identifiedLeistungen.length > 0 && allRulesOk) {
             htmlOutput += "<p><b>Keine anwendbare Abrechnung gefunden oder Fehler bei der Detailverarbeitung.</b></p>";
         }

        htmlOutput += abrechnungsDetailHtml;
        console.log("[getBillingAnalysis] Versuche finale Ausgabe...");
        displayOutput(htmlOutput, "info");
        console.log("[getBillingAnalysis] Frontend-Verarbeitung abgeschlossen.");

    } catch (error) {
         console.error("[getBillingAnalysis] Unerwarteter Fehler bei Ergebnisverarbeitung:", error);
         displayOutput(`<p class="error">Ein interner Fehler ist aufgetreten: ${escapeHtml(error.message)}</p><pre>${escapeHtml(error.stack)}</pre>`, "error");
    } finally {
         hideSpinner();
    }
} // Ende getBillingAnalysis


// ─── 4 · Hilfsfunktionen für Pauschalen/TARDOC ────
// ─── Funktion zur Pauschalenfindung und -prüfung (MIT KAPITEL-PRIORISIERUNG) ────
function findAndProcessBestPauschale(identifiedLeistungen, providedICDs = [], providedGTINs = []) {
    let htmlResult = "";
    let applicable = false;
    let reason = "Keine passende und anwendbare Pauschale gefunden.";
    let selectedPauschaleCode = null;
    let bestPauschaleData = null;

    console.log("[findAndProcessBestPauschale] Starte Funktion.");

    if (!data_pauschaleLeistungsposition || !data_pauschalen || !data_pauschaleBedingungen) {
        console.error("[findAndProcessBestPauschale] Pauschalendaten nicht geladen!");
        return { applicable: false, html: "<p class='error'>Pauschalendaten nicht geladen.</p>", reason: "Daten nicht geladen", selectedPauschaleCode };
    }
    console.log(`[findAndProcessBestPauschale] Daten verfügbar: pauschaleLP=${data_pauschaleLeistungsposition.length}, pauschalen=${data_pauschalen.length}, bedingungen=${data_pauschaleBedingungen.length}`);

    const identifiedLKNs = identifiedLeistungen.map(l => l.lkn);
    // Finde die LKNs, die die Pauschalenprüfung ausgelöst haben (Typ P/PZ)
    const pauschalTriggerLeistungen = identifiedLeistungen.filter(l => l.typ === 'P' || l.typ === 'PZ');
    const pauschalTriggerLKNs = pauschalTriggerLeistungen.map(l => l.lkn);
    console.log("[findAndProcessBestPauschale] Identifizierte LKNs:", identifiedLKNs);
    console.log("[findAndProcessBestPauschale] Pauschal-Trigger-LKNs:", pauschalTriggerLKNs);

    // --- Schritt 2a.1: Mögliche Pauschalen identifizieren ---
    let possiblePauschalenRefs = [];
    const LKN_KEY_IN_PAUSCHALE_LP = 'Leistungsposition'; // ANPASSEN!
    identifiedLKNs.forEach(lkn => {
        const refs = data_pauschaleLeistungsposition.filter(item =>
            item && item[LKN_KEY_IN_PAUSCHALE_LP] && item[LKN_KEY_IN_PAUSCHALE_LP].toUpperCase() === lkn.toUpperCase()
        );
        if (refs.length > 0) { possiblePauschalenRefs.push(...refs); }
    });

    const PAUSCHALE_KEY_IN_PAUSCHALE_LP = 'Pauschale'; // ANPASSEN!
    let possiblePauschalenCodes = new Set(possiblePauschalenRefs.map(ref => ref[PAUSCHALE_KEY_IN_PAUSCHALE_LP]));

    const PAUSCHALE_KEY_IN_PAUSCHALEN = 'Pauschale'; // ANPASSEN!
    pauschalTriggerLKNs.forEach(lkn => {
         if (data_pauschalen.some(p => p[PAUSCHALE_KEY_IN_PAUSCHALEN] === lkn)) { possiblePauschalenCodes.add(lkn); }
    });

    if (possiblePauschalenCodes.size === 0) {
        reason = `Keine gültigen Pauschalen-Codes für LKNs (${identifiedLKNs.join(', ')}) gefunden.`;
        htmlResult = `<p><i>${escapeHtml(reason)}</i></p>`;
        console.log("[findAndProcessBestPauschale]", reason);
        return { applicable: false, html: htmlResult, reason: reason, selectedPauschaleCode };
    }

    const possibleCodesArray = Array.from(possiblePauschalenCodes);
    console.log("[findAndProcessBestPauschale] Finale mögliche Pauschalen-Codes:", possibleCodesArray);
    htmlResult += `<p>Mögliche Pauschalen-Codes: ${possibleCodesArray.map(escapeHtml).join(', ')}</p>`;

    // --- Schritt 2a.2: Passende Pauschale auswählen (MIT NEUER PRIORISIERUNG) ---
    let potentialPauschalenDetails = data_pauschalen.filter(p => p[PAUSCHALE_KEY_IN_PAUSCHALEN] && possibleCodesArray.includes(p[PAUSCHALE_KEY_IN_PAUSCHALEN]));

    if (potentialPauschalenDetails.length === 0) {
         reason = `Keine Details in tblPauschalen zu möglichen Pauschalen (${possibleCodesArray.join(', ')}) gefunden.`;
         htmlResult += `<p><i>${escapeHtml(reason)}</i></p>`;
         console.log("[findAndProcessBestPauschale]", reason);
         return { applicable: false, html: htmlResult, reason: reason, selectedPauschaleCode };
    }
    console.log("[findAndProcessBestPauschale] Details zu potenziellen Pauschalen:", potentialPauschalenDetails);

    // --- NEUE Priorisierungslogik ---
    bestPauschaleData = null;

    // 1. Bestimme Hauptkapitel (aus erster P/PZ-LKN)
    let hauptKapitel = null;
    if (pauschalTriggerLeistungen.length > 0) {
         // Extrahiere Kapitel (z.B. "C04" aus "C04.GC.0020")
         const match = pauschalTriggerLeistungen[0].lkn.match(/^([A-Z]+\d{2})\./);
         if (match) {
              hauptKapitel = match[1]; // z.B. "C04"
              console.log("[Priorisierung] Hauptkapitel bestimmt:", hauptKapitel);
         } else {
              console.warn("[Priorisierung] Konnte Hauptkapitel aus Trigger-LKN nicht extrahieren:", pauschalTriggerLeistungen[0].lkn);
         }
    } else {
         // Sollte nicht passieren, wenn hatPauschalenTyp true war, aber als Fallback
         console.warn("[Priorisierung] Keine P/PZ Trigger-LKN gefunden, um Hauptkapitel zu bestimmen.");
         // Fallback: Versuche Kapitel aus erster identifizierter LKN zu nehmen? Oder null lassen.
         if(identifiedLeistungen.length > 0) {
            const match = identifiedLeistungen[0].lkn.match(/^([A-Z]+\d{2})\./);
            if (match) hauptKapitel = match[1];
         }
    }

    // 2. Suche Pauschalen im Hauptkapitel
    let kapitelPauschalen = [];
    if (hauptKapitel) {
        kapitelPauschalen = potentialPauschalenDetails.filter(p =>
            p[PAUSCHALE_KEY_IN_PAUSCHALEN]?.startsWith(hauptKapitel + ".") // z.B. "C04."
        );
        console.log(`[Priorisierung] Pauschalen im Kapitel ${hauptKapitel}:`, kapitelPauschalen);
    }

    // 3. Wähle beste Pauschale aus
    if (kapitelPauschalen.length > 0) {
        // a) Treffer im Hauptkapitel gefunden -> Wähle hieraus die beste
        console.log("[Priorisierung] Wähle beste Pauschale aus Hauptkapitel.");
        // TODO: Hier Komplexität A-G implementieren, falls nötig
        kapitelPauschalen.sort((a, b) => (a.Taxpunkte || Infinity) - (b.Taxpunkte || Infinity));
        bestPauschaleData = kapitelPauschalen[0];
        htmlResult += `<p><i>Pauschale ${escapeHtml(bestPauschaleData[PAUSCHALE_KEY_IN_PAUSCHALEN])} aus Hauptkapitel gewählt (niedrigste TP im Kapitel).</i></p>`;
    } else {
        // b) Keine Treffer im Hauptkapitel -> Fallback
        console.log("[Priorisierung] Keine Pauschale im Hauptkapitel gefunden. Wähle günstigste aller möglichen.");
        // TODO: Hier ggf. C90/C99 Logik einbauen, falls gewünscht
        potentialPauschalenDetails.sort((a, b) => (a.Taxpunkte || Infinity) - (b.Taxpunkte || Infinity));
        bestPauschaleData = potentialPauschalenDetails[0];
        htmlResult += `<p><i>Fallback: Pauschale ${escapeHtml(bestPauschaleData[PAUSCHALE_KEY_IN_PAUSCHALEN])} gewählt (niedrigste TP aller möglichen).</i></p>`;
    }
    // --- Ende NEUE Priorisierungslogik ---

    if (!bestPauschaleData) {
         // Sollte nicht passieren, wenn potentialPauschalenDetails > 0 war
         console.error("[Priorisierung] FEHLER: bestPauschaleData wurde nicht gesetzt!");
         reason = "Interner Fehler bei Pauschalenauswahl (keine Auswahl).";
         htmlResult += `<p class="error">${escapeHtml(reason)}</p>`;
         return { applicable: false, html: htmlResult, reason: reason, selectedPauschaleCode };
    }

    selectedPauschaleCode = bestPauschaleData[PAUSCHALE_KEY_IN_PAUSCHALEN];
    console.log("[findAndProcessBestPauschale] Finale Auswahl vor Bedingungsprüfung:", selectedPauschaleCode);

    // --- Schritt 2a.3: Bedingungen prüfen ---
    htmlResult += `<ul><li>Prüfe Bedingungen für Pauschale: ${escapeHtml(selectedPauschaleCode)} (${escapeHtml(bestPauschaleData.Pauschale_Text || 'N/A')}) - TP: ${escapeHtml(bestPauschaleData.Taxpunkte || 'N/A')}</li>`;
    const conditionsResult = checkPauschaleConditions(selectedPauschaleCode, providedICDs, providedGTINs);
    htmlResult += conditionsResult.html;
    htmlResult += `</ul>`;

    // --- Schritt 2a.4: Pauschale abrechnen ---
    if (conditionsResult.allMet) {
        console.log(`[findAndProcessBestPauschale] Bedingungen für ${selectedPauschaleCode} erfüllt.`);
        applicable = true; reason = "";
        let abrechnungHtml = `<h4>Abrechnung als Pauschale</h4>`;
        abrechnungHtml += `
            <table border="1" style="border-collapse: collapse; width: 100%;">
                <thead><tr><th>Pauschale Code</th><th>Beschreibung</th><th>Taxpunkte</th></tr></thead>
                <tbody><tr>
                    <td>${escapeHtml(bestPauschaleData[PAUSCHALE_KEY_IN_PAUSCHALEN])}</td>
                    <td>${escapeHtml(bestPauschaleData.Pauschale_Text || 'N/A')}</td>
                    <td>${escapeHtml(bestPauschaleData.Taxpunkte || 'N/A')}</td>
                </tr></tbody>
            </table>`;
        htmlResult = abrechnungHtml + `<details><summary>Prüfdetails Pauschale</summary>${htmlResult}</details>`;
    } else {
         reason = `Bedingungen für Pauschale ${selectedPauschaleCode} nicht erfüllt.`;
         console.log("[findAndProcessBestPauschale]", reason);
         htmlResult = `<p><i>${escapeHtml(reason)}</i></p>` + `<details><summary>Prüfdetails Pauschale (nicht anwendbar)</summary>${htmlResult}</details>`;
         applicable = false;
    }

    console.log("[findAndProcessBestPauschale] Funktion beendet. Applicable:", applicable);
    return { applicable, html: htmlResult, reason, reason, selectedPauschaleCode: applicable ? selectedPauschaleCode : null };
}

function checkPauschaleConditions(pauschaleCode, providedICDs, providedGTINs) {
    if (!data_pauschaleBedingungen) return { allMet: false, html: "<p class='error'>Pauschalen-Bedingungsdaten nicht geladen.</p>" };
    const conditions = data_pauschaleBedingungen.filter(cond => cond.Pauschale === pauschaleCode);
    let allConditionsMet = true; let conditionDetailsHtml = "";
    if (conditions.length > 0) {
        conditionDetailsHtml += `<ul style="margin-left: 20px; font-size: 0.9em;"><li>Bedingungen:</li><ul>`;
        for (const cond of conditions) {
            let conditionMet = checkSingleCondition(cond, providedICDs, providedGTINs);
            const statusClass = conditionMet ? 'success' : 'error'; const statusText = conditionMet ? 'Erfüllt' : 'Nicht erfüllt';
            conditionDetailsHtml += `<li>Typ: ${escapeHtml(cond.Bedingungstyp)}, Wert/Ref: ${escapeHtml(cond.Werte || '-')} -> <span class="${statusClass}">${statusText}</span></li>`;
            if (!conditionMet) { allConditionsMet = false; }
        } conditionDetailsHtml += `</ul></ul>`;
    } else { conditionDetailsHtml += `<p style="margin-left: 20px; font-size: 0.9em;"><i>Keine spezifischen Bedingungen gefunden.</i></p>`; allConditionsMet = true; }
    return { allMet: allConditionsMet, html: conditionDetailsHtml };
}

function checkSingleCondition(condition, providedICDs, providedGTINs) {
    const requiredValue = condition.Werte;
    if (requiredValue === null || requiredValue === undefined || requiredValue === '') return true;
    const conditionTypeUpper = (condition.Bedingungstyp || '').toUpperCase();
    try {
        switch (conditionTypeUpper) {
            case 'ICD': const requiredICDs = String(requiredValue).split(',').map(s => s.trim().toUpperCase()).filter(s => s); return requiredICDs.some(reqICD => providedICDs.includes(reqICD));
            case 'GTIN': const requiredGTINs = String(requiredValue).split(',').map(s => s.trim()).filter(s => s); return requiredGTINs.some(reqGTIN => providedGTINs.includes(reqGTIN));
            case 'LKN': console.warn(`LKN-Bedingung (${requiredValue}) wird derzeit nicht geprüft.`); return true;
            default: console.warn(`Unbekannter Bedingungstyp: ${condition.Bedingungstyp}`); return true;
        }
    } catch (e) { console.error("Fehler in checkSingleCondition:", e, "Bedingung:", condition); return false; }
}

function processTardoc(lkn, providedICDs = [], anzahl = 1) {
    let htmlResult = ""; let applicable = false; let tardocData = null;
    // --- !!! WICHTIG: Schlüsselnamen anpassen !!! ---
    const TARDOC_LKN_KEY = 'LKN'; // ANPASSEN!
    const AL_KEY = 'AL_(normiert)'; // ANPASSEN!
    const IPL_KEY = 'IPL_(normiert)'; // ANPASSEN!
    const DESC_KEY_1 = 'Bezeichnung'; // ANPASSEN!
    const DESC_KEY_2 = 'Beschreibung'; // ANPASSEN!
    const RULES_KEY_1 = 'Regeln_bezogen_auf_die_Tarifmechanik'; // ANPASSEN!
    const ZEIT_LIES_KEY = 'Zeit_LieS'; // ANPASSEN!
    // --- !!! ENDE ANPASSUNG !!! ---

    if (!data_tardocGesamt || data_tardocGesamt.length === 0) { htmlResult = `<p class="error">TARDOC-Daten nicht geladen.</p>`; return { html: htmlResult, applicable: false, data: null, anzahl: anzahl }; }

    const tardocPosition = data_tardocGesamt.find(item => item && item[TARDOC_LKN_KEY] && String(item[TARDOC_LKN_KEY]).toUpperCase() === lkn.toUpperCase());

    if (!tardocPosition) {
        console.error(`LKN ${lkn} nicht in lokalen TARDOC-Daten (Schlüssel: ${TARDOC_LKN_KEY}) gefunden.`);
        if (data_tardocGesamt.length > 0) console.log("Verfügbare Schlüssel im ersten TARDOC-Eintrag:", Object.keys(data_tardocGesamt[0]));
        htmlResult = `<p class="error">LKN ${escapeHtml(lkn)} nicht in lokalen TARDOC-Daten gefunden.</p>`;
        return { html: htmlResult, applicable: false, data: null, anzahl: anzahl };
    }

    applicable = true; tardocData = tardocPosition;
    const al = parseFloat(tardocPosition[AL_KEY]) || 0;
    const ipl = parseFloat(tardocPosition[IPL_KEY]) || 0;
    const leistungsname = tardocPosition[DESC_KEY_1] || tardocPosition[DESC_KEY_2] || 'N/A';
    const regeln = tardocPosition[RULES_KEY_1] || '';
    const summe_tp = al + ipl; const total_tp = summe_tp * anzahl;

    let positionHtml = `
        <table border="1" style="border-collapse: collapse; width: 100%; margin-bottom: 10px;">
            <thead><tr><th>LKN</th><th>Leistung</th><th>AL</th><th>IPL</th><th>Anzahl</th><th>Total TP</th></tr></thead>
            <tbody><tr>
                <td>${escapeHtml(lkn)}</td><td>${escapeHtml(leistungsname)}</td>
                <td>${al.toFixed(2)}</td><td>${ipl.toFixed(2)}</td>
                <td>${anzahl}</td><td>${total_tp.toFixed(2)}</td>
            </tr></tbody>
        </table>`;

    if (regeln) { positionHtml += `<details><summary>Hinweise zu Regeln & Limitationen (aus TARDOC)</summary><p>${escapeHtml(regeln)}</p></details>`; }

    return { html: positionHtml, applicable: true, data: tardocData, anzahl: anzahl };
}


// ─── 5 · Enter-Taste als Default für Return (Trigger) ─────────────────────
document.addEventListener("DOMContentLoaded", function() {
    const uiField = $("userInput");
    const icdField = $("icdInput");
    const gtinField = $("gtinInput"); // Wieder hinzugefügt, falls im HTML vorhanden

    function handleEnter(e) {
        if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            getBillingAnalysis();
        }
    }

    if (uiField) uiField.addEventListener("keydown", handleEnter);
    if (icdField) icdField.addEventListener("keydown", handleEnter);
    if (gtinField) gtinField.addEventListener("keydown", handleEnter); // Event Listener hinzugefügt
});

// Mache die Hauptfunktionen global verfügbar
window.getBillingAnalysis = getBillingAnalysis;
window.clearDataCache = clearDataCache;