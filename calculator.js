// calculator.js - Vollständige Version mit Korrektur für finale_menge

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
    tardocGesamt: 'data/TARDOCGesamt_optimiert_Tarifpositionen.json', // Pfad zur TARDOC-Datei! ANPASSEN FALLS NÖTIG
    tabellen: 'data/tblTabellen.json'
};
const CACHE_KEY = 'tardocRechnerDataCache';
const CACHE_VERSION = '1.0'; // Ändere dies, um Cache zu invalidieren

// ─── 1 · Utility‑Funktionen ────────────────────────────────────────────────
function $(id) {
    return document.getElementById(id);
}

function escapeHtml(s) {
    if (s === null || s === undefined) return "";
    return String(s).replace(/[&<>"']/g, c => ({
        "&": "&",
        "<": "<",
        ">": ">",
        "\"": "&quot;", // Numerische Entity
        "'": "'"  // Numerische Entity
    }[c]));
}

function beschreibungZuLKN(lkn) {
    if (!data_leistungskatalog || typeof lkn !== 'string') return "";
    const hit = data_leistungskatalog.find(e => e.LKN?.toUpperCase() === lkn.toUpperCase());
    return hit ? hit.Beschreibung || "" : "";
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
        return [];
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
            setTimeout(() => { if ($("output").className === 'success') displayOutput(""); }, 2000);

        } catch (error) {
             console.error("Schwerwiegender Fehler beim Laden der Frontend-Daten:", error);
             displayOutput(`<p>Fehler beim Laden der notwendigen Frontend-Daten: ${escapeHtml(error.message)}. Die Anwendung funktioniert möglicherweise nicht korrekt.</p>`, "error");
             return;
        }
    }

    if (!data_leistungskatalog || data_leistungskatalog.length === 0) console.error("Leistungskatalog ist leer!");
    if (!data_tardocGesamt || data_tardocGesamt.length === 0) console.warn("TARDOC-Daten sind leer!");
    if (!data_pauschalen || data_pauschalen.length === 0) console.warn("Pauschalen-Daten sind leer!");
}

function clearDataCache() {
    localStorage.removeItem(CACHE_KEY);
    console.log("Daten-Cache gelöscht.");
    data_leistungskatalog = []; data_pauschaleLeistungsposition = []; data_pauschalen = [];
    data_pauschaleBedingungen = []; data_tardocGesamt = []; data_tabellen = [];
    displayOutput("<p>Cache gelöscht. Lade Daten neu...</p>", "info");
    loadData().then(() => {
         if ($("output").className === 'success') {
              setTimeout(() => { if ($("output").className === 'success') displayOutput(""); }, 1500);
         }
    });
}

document.addEventListener("DOMContentLoaded", loadData);

// ─── 3 · Hauptlogik (Button‑Click) ────────────────────────────────────────
async function getBillingAnalysis() {
    const userInput = $("userInput").value.trim();
    const icdInput = $("icdInput").value.trim()
                  .split(",").map(s => s.trim().toUpperCase()).filter(Boolean);
    // GTIN wird hier nicht mehr aus Input gelesen, könnte aber im requestBody gesendet werden
    const gtinInput = []; // Leeres Array, wenn Feld entfernt wurde

    if (!userInput) {
        displayOutput("<p>Bitte Leistungsbeschreibung eingeben.</p>", "error");
        return;
    }

    showSpinner();
    displayOutput("<p>Prüfe Abrechnung …</p>", "info");

    let backendResponse;
    let rawResponseText = "";
    try {
        const requestBody = {
            inputText: userInput,
            icd: icdInput,
            gtin: gtinInput // Sende GTINs, falls Backend sie braucht
        };

        const res = await fetch("/api/analyze-billing", {
            method: "POST",
            headers: {"Content-Type":"application/json"},
            body: JSON.stringify(requestBody)
        });

        rawResponseText = await res.text();

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

        // Detaillierte Prüfung der Backend-Antwortstruktur
        console.log("Prüfe Backend-Antwortstruktur...");
        let structureOk = true;
        let errorReason = "Unbekannter Strukturfehler";

        if (!backendResponse) { structureOk = false; errorReason = "BackendResponse ist null."; }
        else {
            if (!backendResponse.llm_ergebnis) { structureOk = false; errorReason = "'llm_ergebnis' fehlt."; }
            else { /* Tiefere Prüfung optional */ }

            // Korrigierte Prüfung auf regel_ergebnisse (Plural!)
            if (!backendResponse.regel_ergebnisse) { structureOk = false; errorReason = "'regel_ergebnisse' fehlt."; }
            else if (!Array.isArray(backendResponse.regel_ergebnisse)) { structureOk = false; errorReason = "'regel_ergebnisse' ist kein Array."; }
            else if (backendResponse.regel_ergebnisse.length > 0) {
                 const firstResult = backendResponse.regel_ergebnisse[0];
                 // Prüfe auf 'regelpruefung' UND 'finale_menge' (korrekter Key vom Backend)
                 if (!firstResult || firstResult.regelpruefung === undefined || firstResult.finale_menge === undefined) { // <-- KORRIGIERT
                      structureOk = false;
                      errorReason = "Struktur innerhalb von 'regel_ergebnisse' ist unerwartet.";
                      console.log("Erstes Element in regel_ergebnisse:", firstResult);
                 } else { console.log("Struktur von regel_ergebnisse[0] scheint OK."); }
            } else { console.log("regel_ergebnisse ist ein leeres Array."); }
        }

        if (!structureOk) {
             console.error("Fehlergrund:", errorReason);
             console.error("Empfangenes Objekt:", backendResponse);
             throw new Error(`Unerwartete Datenstruktur vom Server erhalten (${errorReason})`);
        }
        console.log("Backend-Antwortstruktur ist OK.");

    } catch (e) {
        console.error("Fehler bei Backend-Anfrage:", e);
        let msg = `<p>Server-Fehler: ${escapeHtml(e.message)}</p>`;
        if (rawResponseText && !e.message.includes(rawResponseText.substring(0,50))) {
            msg += `<details style="margin-top:1em"><summary>Raw Response</summary><pre>${escapeHtml(rawResponseText)}</pre></details>`;
        }
        displayOutput(msg, "error");
        hideSpinner(); // Spinner bei Fehler ausblenden
        return;
    }

    // --- Ergebnisse verarbeiten und anzeigen ---
    const llmResult = backendResponse.llm_ergebnis;
    const ruleResultsList = backendResponse.regel_ergebnisse;
    const identifiedLeistungen = llmResult.identified_leistungen || [];
    const extractedInfo = llmResult.extracted_info || {};

    let htmlOutput = `<h2>Ergebnisse für «${escapeHtml(userInput)}»</h2>`;

    // 1. LLM Ergebnis anzeigen
    htmlOutput += `<h3>LLM-Analyse</h3>`;
    if (identifiedLeistungen.length > 0) {
        const lknStrings = identifiedLeistungen.map(l => `${l.lkn} (${l.typ || '?'})`).join(', ');
        htmlOutput += `<p><b>Identifizierte LKN(s):</b> ${lknStrings}</p>`;
        htmlOutput += `<ul>`;
        identifiedLeistungen.forEach(l => {
             htmlOutput += `<li><b>${escapeHtml(l.lkn)}:</b> ${escapeHtml(l.beschreibung || 'N/A')}</li>`;
        });
        htmlOutput += `</ul>`;
    } else { htmlOutput += `<p><i>Keine LKN identifiziert.</i></p>`; }
    let extractedDetails = [];
    if (extractedInfo.dauer_minuten !== null) extractedDetails.push(`Dauer: ${extractedInfo.dauer_minuten} Min.`);
    if (extractedInfo.menge !== null && extractedInfo.menge !== 0) extractedDetails.push(`Menge: ${extractedInfo.menge}`);
    if (extractedInfo.alter !== null && extractedInfo.alter !== 0) extractedDetails.push(`Alter: ${extractedInfo.alter}`);
    if (extractedInfo.geschlecht !== null && extractedInfo.geschlecht !== 'null' && extractedInfo.geschlecht !== 'unbekannt') extractedDetails.push(`Geschlecht: ${extractedInfo.geschlecht}`);
    if (extractedDetails.length > 0) { htmlOutput += `<p><b>Extrahierte Details:</b> ${extractedDetails.join(', ')}</p>`; }
    htmlOutput += `<p><b>Begründung LLM:</b> ${escapeHtml(llmResult.begruendung_llm || 'N/A')}</p>`;
    htmlOutput += `<hr>`;

    // 2. Regelprüfung Ergebnis anzeigen
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
         htmlOutput += `<p class="error"><b>Finale Abrechnung nicht möglich, da Regelverletzungen vorliegen oder Daten fehlen.</b></p>`;
         displayOutput(htmlOutput, "info");
         hideSpinner(); // Spinner ausblenden
         return;
    }

    htmlOutput += `<h3>Finale Abrechnung</h3>`;
    let abrechnungsDetailHtml = "";
    let hasApplicableResult = false;
    let combinedTardocResults = [];
    let pauschaleProcessed = false;

    // --- a) Pauschalen-Prüfung ---
    const pauschalLeistungen = identifiedLeistungen.filter(l => l.typ === 'P' || l.typ === 'PZ');
    if (pauschalLeistungen.length > 0) {
        const pauschalLKN = pauschalLeistungen[0];
        const ruleResultForPauschale = ruleResultsList.find(r => r.lkn === pauschalLKN.lkn);
        if (ruleResultForPauschale && ruleResultForPauschale.regelpruefung.abrechnungsfaehig) {
            htmlOutput += `<p>Leistung wird primär als Pauschale (${escapeHtml(pauschalLKN.lkn)}) geprüft.</p>`;
            const pauschaleResult = processPauschale(pauschalLKN.lkn, icdInput, gtinInput); // GTIN wieder hinzugefügt
            abrechnungsDetailHtml += pauschaleResult.html;
            if (pauschaleResult.applicable) { hasApplicableResult = true; pauschaleProcessed = true; }
            else { htmlOutput += `<p><i>Pauschale ${escapeHtml(pauschalLKN.lkn)} nicht anwendbar (${escapeHtml(pauschaleResult.reason)}), prüfe TARDOC...</i></p>`; }
        } else { htmlOutput += `<p><i>Identifizierte Pauschale ${escapeHtml(pauschalLKN.lkn)} ist nicht regelkonform, prüfe TARDOC...</i></p>`; }
    }

    // --- b) TARDOC-Verarbeitung ---
    if (!pauschaleProcessed) {
        htmlOutput += `<h4>TARDOC-Positionen</h4>`;
        let gesamtTP = 0;
        let tardocTableBody = "";

        // Iteriere über die Ergebnisse der Regelprüfung
        for (const resultItem of ruleResultsList) {
             const lkn = resultItem.lkn;
             const regelPruefung = resultItem.regelpruefung;
             const finaleMenge = resultItem.finale_menge; // Korrekter Key vom Backend

             // Verarbeite nur, wenn LKN vorhanden, Regelprüfung OK und Menge > 0
             if (lkn && regelPruefung && regelPruefung.abrechnungsfaehig && finaleMenge > 0) {
                  const leistungInfo = identifiedLeistungen.find(l => l.lkn === lkn);
                  const typ = leistungInfo ? leistungInfo.typ : null;

                  // Nur TARDOC-Typen (E/EZ) verarbeiten
                  if (typ === 'E' || typ === 'EZ') {
                       console.log(`Verarbeite TARDOC LKN: ${lkn} mit finaler Menge: ${finaleMenge}`);
                       const tardocResult = processTardoc(lkn, icdInput, finaleMenge); // Nutze finale Menge

                       if (tardocResult.applicable && tardocResult.data) {
                            hasApplicableResult = true;
                            // --- !!! SCHLÜSSELNAMEN PRÜFEN !!! ---
                            const TARDOC_LKN_KEY = 'LKN'; // ANPASSEN!
                            const AL_KEY = 'AL_(normiert)'; // ANPASSEN!
                            const IPL_KEY = 'IPL_(normiert)'; // ANPASSEN!
                            const DESC_KEY_1 = 'Bezeichnung'; // ANPASSEN!
                            const RULES_KEY_1 = 'Regeln_bezogen_auf_die_Tarifmechanik'; // ANPASSEN!
                            // --- !!! ENDE PRÜFUNG !!! ---

                            const name = tardocResult.data[DESC_KEY_1] || 'N/A';
                            const al = parseFloat(tardocResult.data[AL_KEY]) || 0;
                            const ipl = parseFloat(tardocResult.data[IPL_KEY]) || 0;
                            const anzahl = tardocResult.anzahl; // = finaleMenge
                            const total_tp = (al + ipl) * anzahl;
                            const regeln = tardocResult.data[RULES_KEY_1] || '';
                            gesamtTP += total_tp;

                            tardocTableBody += `<tr>
                                <td>${escapeHtml(lkn)}</td>
                                <td>${escapeHtml(name)}</td>
                                <td>${al.toFixed(2)}</td>
                                <td>${ipl.toFixed(2)}</td>
                                <td>${anzahl}</td>
                                <td>${total_tp.toFixed(2)}</td>
                                <td>${regeln ? `<details><summary>Details</summary><p>${escapeHtml(regeln)}</p></details>` : ''}</td>
                            </tr>`;
                       } else {
                            abrechnungsDetailHtml += `<p class="error">Fehler bei TARDOC-Details für ${escapeHtml(lkn)}.</p>` + tardocResult.html;
                       }
                  } // Ende if Typ E/EZ
             } // Ende if Regelprüfung OK und Menge > 0
        } // Ende for Schleife

        // Baue Tabelle nur, wenn Zeilen vorhanden sind
        if (tardocTableBody) {
             abrechnungsDetailHtml += `<table border="1" style="border-collapse: collapse; width: 100%; margin-bottom: 10px;">
                 <thead><tr><th>LKN</th><th>Leistung</th><th>AL</th><th>IPL</th><th>Anzahl</th><th>Total TP</th><th>Regeln</th></tr></thead>
                 <tbody>${tardocTableBody}</tbody>
                 <tfoot><tr><th colspan="5" style="text-align:right;">Gesamt TARDOC TP:</th><th colspan="2">${gesamtTP.toFixed(2)}</th></tr></tfoot>
             </table>`;
        } else if (!hasApplicableResult && identifiedLeistungen.filter(l => l.typ === 'E' || l.typ === 'EZ').length > 0) {
             abrechnungsDetailHtml += `<p><i>Keine TARDOC-Positionen abrechenbar (Menge 0 oder Fehler bei Detailabruf).</i></p>`;
        }
    } // Ende if (!pauschaleProcessed)

    // --- Abschlussmeldung ---
    if (!hasApplicableResult && identifiedLeistungen.length > 0 && allRulesOk) {
         htmlOutput += "<p><b>Keine anwendbare Abrechnung gefunden oder Fehler bei der Detailverarbeitung.</b></p>";
     }

    htmlOutput += abrechnungsDetailHtml;
    displayOutput(htmlOutput, "info");
    console.log("Frontend-Verarbeitung abgeschlossen.");
    hideSpinner(); // Spinner am Ende ausblenden

} // Korrektes schließendes Brace für getBillingAnalysis


// ─── 4 · Hilfsfunktionen für Pauschalen/TARDOC ────
function processPauschale(lkn, providedICDs = [], providedGTINs = []) {
    let htmlResult = "";
    let applicable = false;
    let reason = "Unbekannter Grund";
    let selectedPauschaleCode = null;

    if (!data_pauschaleLeistungsposition || !data_pauschalen || !data_pauschaleBedingungen) {
        return { applicable: false, html: "<p class='error'>Pauschalendaten nicht geladen.</p>", reason: "Daten nicht geladen", selectedPauschaleCode };
    }

    const possiblePauschalenRefs = data_pauschaleLeistungsposition.filter(item => item.LKN && item.LKN.toUpperCase() === lkn.toUpperCase());
    if (possiblePauschalenRefs.length === 0) {
        reason = `Keine Pauschalen-Referenz für LKN ${lkn}.`;
        htmlResult = `<p><i>${escapeHtml(reason)}</i></p>`;
        return { applicable: false, html: htmlResult, reason: reason, selectedPauschaleCode };
    }

    const possiblePauschalenCodes = possiblePauschalenRefs.map(ref => ref.Pauschale);
    htmlResult += `<p>Mögliche Pauschalen-Codes: ${possiblePauschalenCodes.map(escapeHtml).join(', ')}</p>`;

    let potentialPauschalen = data_pauschalen.filter(p => p.Pauschale && possiblePauschalenCodes.includes(p.Pauschale));
    if (potentialPauschalen.length === 0) {
         reason = `Keine Details zu den Pauschalen (${possiblePauschalenCodes.join(', ')}) gefunden.`;
         htmlResult += `<p><i>${escapeHtml(reason)}</i></p>`;
         return { applicable: false, html: htmlResult, reason: reason, selectedPauschaleCode };
    }

    potentialPauschalen.sort((a, b) => (a.Taxpunkte || Infinity) - (b.Taxpunkte || Infinity));
    let bestPauschale = null;
    let conditionCheckPassed = false;

    htmlResult += `<ul>`;
    for (const pauschale of potentialPauschalen) {
        htmlResult += `<li>Prüfe Pauschale: ${escapeHtml(pauschale.Pauschale)} (${escapeHtml(pauschale.Pauschale_Text || 'N/A')}) - TP: ${escapeHtml(pauschale.Taxpunkte || 'N/A')}</li>`;
        const conditionsResult = checkPauschaleConditions(pauschale.Pauschale, providedICDs, providedGTINs);
        htmlResult += conditionsResult.html;

        if (conditionsResult.allMet) {
            bestPauschale = pauschale;
            conditionCheckPassed = true;
            selectedPauschaleCode = bestPauschale.Pauschale;
            htmlResult += `<p class="success" style="margin-left: 20px;">=> Bedingungen erfüllt. Auswahl dieser Pauschale.</p>`;
            break;
        } else {
             htmlResult += `<p style="margin-left: 20px;">=> Bedingungen nicht erfüllt.</p>`;
        }
    }
    htmlResult += `</ul>`;

    if (bestPauschale && conditionCheckPassed) {
        applicable = true;
        reason = "";
        let abrechnungHtml = `<h4>Abrechnung als Pauschale</h4>`;
        abrechnungHtml += `
            <table border="1" style="border-collapse: collapse; width: 100%;">
                <thead><tr><th>Pauschale Code</th><th>Beschreibung</th><th>Taxpunkte</th></tr></thead>
                <tbody><tr>
                    <td>${escapeHtml(bestPauschale.Pauschale)}</td>
                    <td>${escapeHtml(bestPauschale.Pauschale_Text || 'N/A')}</td>
                    <td>${escapeHtml(bestPauschale.Taxpunkte || 'N/A')}</td>
                </tr></tbody>
            </table>`;
        htmlResult = abrechnungHtml + `<details><summary>Prüfdetails Pauschale</summary>${htmlResult}</details>`;

    } else {
         reason = reason === "Unbekannter Grund" ? "Keine der möglichen Pauschalen erfüllt die Bedingungen." : reason;
         htmlResult = `<details><summary>Prüfdetails Pauschale (nicht anwendbar)</summary>${htmlResult}</details>`;
    }

    return { applicable, html: htmlResult, reason, selectedPauschaleCode };
}

function checkPauschaleConditions(pauschaleCode, providedICDs, providedGTINs) {
    if (!data_pauschaleBedingungen) return { allMet: false, html: "<p class='error'>Pauschalen-Bedingungsdaten nicht geladen.</p>" };

    const conditions = data_pauschaleBedingungen.filter(cond => cond.Pauschale === pauschaleCode);
    let allConditionsMet = true;
    let conditionDetailsHtml = "";

    if (conditions.length > 0) {
        conditionDetailsHtml += `<ul style="margin-left: 20px; font-size: 0.9em;"><li>Bedingungen:</li><ul>`;
        for (const cond of conditions) {
            let conditionMet = checkSingleCondition(cond, providedICDs, providedGTINs);
            const statusClass = conditionMet ? 'success' : 'error';
            const statusText = conditionMet ? 'Erfüllt' : 'Nicht erfüllt';
            conditionDetailsHtml += `<li>Typ: ${escapeHtml(cond.Bedingungstyp)}, Wert/Ref: ${escapeHtml(cond.Werte || '-')} -> <span class="${statusClass}">${statusText}</span></li>`;
            if (!conditionMet) { allConditionsMet = false; }
        }
        conditionDetailsHtml += `</ul></ul>`;
    } else {
        conditionDetailsHtml += `<p style="margin-left: 20px; font-size: 0.9em;"><i>Keine spezifischen Bedingungen gefunden.</i></p>`;
        allConditionsMet = true;
    }

    return { allMet: allConditionsMet, html: conditionDetailsHtml };
}

function checkSingleCondition(condition, providedICDs, providedGTINs) {
    const requiredValue = condition.Werte;
    if (requiredValue === null || requiredValue === undefined || requiredValue === '') return true;

    const conditionTypeUpper = (condition.Bedingungstyp || '').toUpperCase();

    try {
        switch (conditionTypeUpper) {
            case 'ICD':
                const requiredICDs = String(requiredValue).split(',').map(s => s.trim().toUpperCase()).filter(s => s);
                return requiredICDs.some(reqICD => providedICDs.includes(reqICD));
            case 'GTIN':
                const requiredGTINs = String(requiredValue).split(',').map(s => s.trim()).filter(s => s);
                return requiredGTINs.some(reqGTIN => providedGTINs.includes(reqGTIN));
            case 'LKN':
                 console.warn(`LKN-Bedingung (${requiredValue}) wird derzeit nicht geprüft.`);
                 return true;
            default:
                console.warn(`Unbekannter Bedingungstyp: ${condition.Bedingungstyp}`);
                return true;
        }
    } catch (e) {
         console.error("Fehler in checkSingleCondition:", e, "Bedingung:", condition);
         return false;
    }
}

function processTardoc(lkn, providedICDs = [], anzahl = 1) {
    let htmlResult = "";
    let applicable = false;
    let tardocData = null;

    // --- !!! WICHTIG: Schlüsselnamen anpassen !!! ---
    const TARDOC_LKN_KEY = 'LKN'; // Beispiel: Anpassen!
    const AL_KEY = 'AL_(normiert)'; // Beispiel: Anpassen!
    const IPL_KEY = 'IPL_(normiert)'; // Beispiel: Anpassen!
    const DESC_KEY_1 = 'Bezeichnung'; // Beispiel: Anpassen!
    const DESC_KEY_2 = 'Beschreibung'; // Beispiel: Anpassen!
    const RULES_KEY_1 = 'Regeln_bezogen_auf_die_Tarifmechanik'; // Beispiel: Anpassen!
    // --- !!! ENDE ANPASSUNG !!! ---

    if (!data_tardocGesamt || data_tardocGesamt.length === 0) {
        htmlResult = `<p class="error">TARDOC-Daten nicht geladen.</p>`;
        return { html: htmlResult, applicable: false, data: null, anzahl: anzahl };
    }

    // console.log(`Suche TARDOC-Details für LKN: ${lkn} mit Key: ${TARDOC_LKN_KEY}`);
    const tardocPosition = data_tardocGesamt.find(item =>
        item && item[TARDOC_LKN_KEY] && String(item[TARDOC_LKN_KEY]).toUpperCase() === lkn.toUpperCase()
    );

    if (!tardocPosition) {
        console.error(`LKN ${lkn} nicht in lokalen TARDOC-Daten (Schlüssel: ${TARDOC_LKN_KEY}) gefunden.`);
        if (data_tardocGesamt.length > 0) console.log("Verfügbare Schlüssel im ersten TARDOC-Eintrag:", Object.keys(data_tardocGesamt[0]));
        htmlResult = `<p class="error">LKN ${escapeHtml(lkn)} nicht in lokalen TARDOC-Daten gefunden.</p>`;
        return { html: htmlResult, applicable: false, data: null, anzahl: anzahl };
    }

    // console.log(`TARDOC-Details für ${lkn} gefunden.`);
    applicable = true;
    tardocData = tardocPosition;

    const al = parseFloat(tardocPosition[AL_KEY]) || 0;
    const ipl = parseFloat(tardocPosition[IPL_KEY]) || 0;
    const leistungsname = tardocPosition[DESC_KEY_1] || tardocPosition[DESC_KEY_2] || 'N/A';
    const regeln = tardocPosition[RULES_KEY_1] || '';
    const summe_tp = al + ipl;
    const total_tp = summe_tp * anzahl;

    let positionHtml = `
        <table border="1" style="border-collapse: collapse; width: 100%; margin-bottom: 10px;">
            <thead><tr><th>LKN</th><th>Leistung</th><th>AL</th><th>IPL</th><th>Anzahl</th><th>Total TP</th></tr></thead>
            <tbody><tr>
                <td>${escapeHtml(lkn)}</td>
                <td>${escapeHtml(leistungsname)}</td>
                <td>${al.toFixed(2)}</td>
                <td>${ipl.toFixed(2)}</td>
                <td>${anzahl}</td>
                <td>${total_tp.toFixed(2)}</td>
            </tr></tbody>
        </table>`;

    if (regeln) {
        positionHtml += `<details><summary>Hinweise zu Regeln & Limitationen (aus TARDOC)</summary><p>${escapeHtml(regeln)}</p></details>`;
    }

    return { html: positionHtml, applicable: true, data: tardocData, anzahl: anzahl };
}


// ─── 5 · Enter-Taste als Default für Return (Trigger) ─────────────────────
document.addEventListener("DOMContentLoaded", function() {
    const uiField = $("userInput");
    const icdField = $("icdInput");
    // const gtinField = $("gtinInput"); // Entfernt, falls nicht im HTML

    function handleEnter(e) {
        if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            getBillingAnalysis();
        }
    }

    if (uiField) uiField.addEventListener("keydown", handleEnter);
    if (icdField) icdField.addEventListener("keydown", handleEnter);
    // if (gtinField) gtinField.addEventListener("keydown", handleEnter); // Entfernt
});

// Mache die Hauptfunktionen global verfügbar
window.getBillingAnalysis = getBillingAnalysis;
window.clearDataCache = clearDataCache;