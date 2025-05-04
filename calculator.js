// calculator.js - Vollständige Version (28.04.2025) // Datum angepasst
// Arbeitet mit zweistufigem Backend. Holt lokale Details zur Anzeige.
// Mit Mouse Spinner & strukturierter Ausgabe

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
    tardocGesamt: 'data/TARDOCGesamt_optimiert_Tarifpositionen.json',
    tabellen: 'data/tblTabellen.json'
};

// NEU: Referenz zum Mouse Spinner
let mouseSpinnerElement = null;
let mouseMoveHandler = null; // Zum Speichern des Handlers für removeEventListener

// ─── 1 · Utility‑Funktionen ────────────────────────────────────────────────
function $(id) { return document.getElementById(id); }

function escapeHtml(s) {
    if (s === null || s === undefined) return "";
    return String(s).replace(/[&<>"']/g, c => ({ "&": "&", "<": "<", ">": ">", "\"": "%quot;", "'": "'" }[c]));
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
    // Output-Typ-Klasse wird jetzt nicht mehr direkt gesetzt,
    // die Haupt-Ergebnis-Nachricht bekommt ihre eigene Klasse.
    // out.className = type; // Entfernt
}

// --- NEU: Mouse Spinner Funktionen ---
function updateSpinnerPosition(event) {
    if (mouseSpinnerElement) {
        // Position leicht versetzt zum Cursor, damit man noch klicken kann
        mouseSpinnerElement.style.left = (event.clientX + 15) + 'px';
        mouseSpinnerElement.style.top = (event.clientY + 15) + 'px';
    }
}

function showSpinner(text = "Prüfung läuft...") { // Nur noch Text-Spinner
    const textSpinner = $('spinner');
    const button = $('analyzeButton');
    const body = document.body;

    if (textSpinner) {
        textSpinner.innerHTML = text; // Nur Text anzeigen
        textSpinner.style.display = 'block';
    }
    if (button) button.disabled = true;

    // Mouse Spinner anzeigen und Listener starten
    if (!mouseSpinnerElement) mouseSpinnerElement = $('mouseSpinner'); // Einmalig holen
    if (mouseSpinnerElement) mouseSpinnerElement.style.display = 'block';
    if (body) body.style.cursor = 'wait'; // Warte-Cursor für Body

    if (!mouseMoveHandler) { // Handler nur einmal erstellen
        mouseMoveHandler = updateSpinnerPosition;
        document.addEventListener('mousemove', mouseMoveHandler);
    }
}

function hideSpinner() {
    const textSpinner = $('spinner');
    const button = $('analyzeButton');
    const body = document.body;

    if (textSpinner) {
        textSpinner.innerHTML = "";
        textSpinner.style.display = 'none';
    }
    if (button) button.disabled = false;

    // Mouse Spinner ausblenden und Listener entfernen
    if (mouseSpinnerElement) mouseSpinnerElement.style.display = 'none';
    if (body) body.style.cursor = 'default'; // Standard-Cursor

    if (mouseMoveHandler) { // Listener entfernen
        document.removeEventListener('mousemove', mouseMoveHandler);
        mouseMoveHandler = null; // Handler zurücksetzen
    }
}
// --- Ende Mouse Spinner Funktionen ---


// ─── 2 · Daten laden ─────────────────────────────────────────────────────────
async function fetchJSON(path) {
    // ... (unverändert)
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
        // Optional: Hier eine spezifischere Fehlermeldung im UI anzeigen?
        return []; // Leeres Array zurückgeben, damit Promise.all nicht fehlschlägt
    }
}


async function loadData() {
    console.log("Lade Frontend-Daten vom Server...");
    const initialSpinnerMsg = "Lade Tarifdaten...";
    showSpinner(initialSpinnerMsg); // Zeigt Text- und Maus-Spinner, deaktiviert Button
    const outputDiv = $("output");
    if (outputDiv) outputDiv.innerHTML = ""; // Initialen Output leeren

    let loadedDataArray = [];
    let loadError = null; // Flag für Ladefehler

    try {
        loadedDataArray = await Promise.all([
            fetchJSON(DATA_PATHS.leistungskatalog), fetchJSON(DATA_PATHS.pauschaleLP),
            fetchJSON(DATA_PATHS.pauschalen), fetchJSON(DATA_PATHS.pauschaleBedingungen),
            fetchJSON(DATA_PATHS.tardocGesamt), fetchJSON(DATA_PATHS.tabellen)
        ]);

        // Überprüfen, ob alle Daten erfolgreich geladen wurden
        [ data_leistungskatalog, data_pauschaleLeistungsposition, data_pauschalen,
          data_pauschaleBedingungen, data_tardocGesamt, data_tabellen ] = loadedDataArray;

        let missingDataErrors = [];
        if (!data_leistungskatalog || data_leistungskatalog.length === 0) missingDataErrors.push("Leistungskatalog");
        if (!data_tardocGesamt || data_tardocGesamt.length === 0) missingDataErrors.push("TARDOC-Daten");
        if (!data_pauschalen || data_pauschalen.length === 0) missingDataErrors.push("Pauschalen");
        // Füge hier weitere Prüfungen für kritische Daten hinzu, falls nötig
        if (!data_pauschaleBedingungen) missingDataErrors.push("Pauschalen-Bedingungen");
        if (!data_tabellen) missingDataErrors.push("Referenz-Tabellen");


        if (missingDataErrors.length > 0) {
             // Werfe einen Fehler, wenn kritische Daten fehlen
             throw new Error(`Folgende kritische Daten fehlen oder konnten nicht geladen werden: ${missingDataErrors.join(', ')}.`);
        }

        console.log("Frontend-Daten vom Server geladen.");

        // --- KORRIGIERTE LOGIK ---
        // Zeige Erfolgsmeldung kurz im *Haupt-Output*, nicht im Spinner.
        displayOutput("<p class='success'>Daten geladen. Bereit zur Prüfung.</p>");
        // Blende Spinner *sofort* aus und aktiviere Button.
        hideSpinner();
        // Lass die Erfolgsmeldung im Output für ein paar Sekunden stehen.
        setTimeout(() => {
            const currentOutput = $("output");
            // Leere Output nur, wenn es noch die Erfolgsmeldung ist
            if (currentOutput && currentOutput.querySelector('p.success')) {
                 displayOutput(""); // Leeren
            }
        }, 2500); // Erfolgsmeldung 2.5 Sekunden anzeigen
        // --- ENDE KORREKTUR ---

    } catch (error) {
         loadError = error; // Fehler speichern
         console.error("Schwerwiegender Fehler beim Laden der Frontend-Daten:", error);
         // Fehlermeldung im Haupt-Output anzeigen
         displayOutput(`<p class="error">Fehler beim Laden der notwendigen Frontend-Daten: ${escapeHtml(error.message)}. Funktionalität eingeschränkt. Bitte Seite neu laden.</p>`);
         // Spinner ausblenden und Button aktivieren, damit User ggf. neu laden kann
         hideSpinner();
    }
}


document.addEventListener("DOMContentLoaded", () => {
    mouseSpinnerElement = $('mouseSpinner'); // Spinner-Element holen, wenn DOM bereit ist
    loadData(); // Daten laden
});


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
    if (!userInput) { displayOutput("<p class='error'>Bitte Leistungsbeschreibung eingeben.</p>"); return; }

    // Einfacher Text-Spinner
    showSpinner("Analyse gestartet, sende Anfrage...");
    displayOutput("", "info"); // Leere Haupt-Output

    try {
        console.log("[getBillingAnalysis] Sende Anfrage an Backend...");
        const requestBody = { inputText: userInput, icd: icdInput, gtin: gtinInput };
        const res = await fetch("/api/analyze-billing", { method: "POST", headers: {"Content-Type":"application/json"}, body: JSON.stringify(requestBody) });
        rawResponseText = await res.text();
        console.log("[getBillingAnalysis] Raw Response vom Backend erhalten:", rawResponseText.substring(0, 500) + "..."); // Gekürzt loggen
        if (!res.ok) { throw new Error(`Server antwortete mit ${res.status}`); }
        backendResponse = JSON.parse(rawResponseText);
        console.log("[getBillingAnalysis] Backend-Antwort geparst."); // Nicht die ganze Antwort loggen, kann sehr groß sein

        // Strukturprüfung (minimal)
        if (!backendResponse || !backendResponse.llm_ergebnis_stufe1 || !backendResponse.abrechnung || !backendResponse.abrechnung.type) {
             throw new Error("Unerwartete Hauptstruktur vom Server erhalten.");
        }
        console.log("[getBillingAnalysis] Backend-Antwortstruktur ist OK.");
        showSpinner("Antwort erhalten, verarbeite Ergebnisse..."); // Update Spinner Text

    } catch (e) {
        console.error("Fehler bei Backend-Anfrage oder Verarbeitung:", e);
        let msg = `<p class="error">Server-Fehler: ${escapeHtml(e.message)}</p>`;
        // Zeige Raw Response nur bei Parsing-Fehler oder wenn sie kurz ist
        if (rawResponseText && (e instanceof SyntaxError || rawResponseText.length < 1000) && !e.message.includes(rawResponseText.substring(0,50))) {
             msg += `<details style="margin-top:1em"><summary>Raw Response (gekürzt)</summary><pre>${escapeHtml(rawResponseText.substring(0,1000))}${rawResponseText.length > 1000 ? '...' : ''}</pre></details>`;
        }
        displayOutput(msg); // Kein Typ mehr nötig, Styling via CSS Klasse
        hideSpinner();
        return;
    }

    // --- Ergebnisse verarbeiten und anzeigen ---
    try {
        console.log("[getBillingAnalysis] Starte Ergebnisverarbeitung.");
        const llmResultStufe1 = backendResponse.llm_ergebnis_stufe1;
        const abrechnung = backendResponse.abrechnung;
        const regelErgebnisseDetails = backendResponse.regel_ergebnisse_details || [];

        // --- Baue das FINALE HTML für den Output-Bereich ---
        htmlOutput = `<h2>Ergebnis für «${escapeHtml(userInput)}»</h2>`;

        let finalResultHeader = "";
        let finalResultDetailsHtml = ""; // HTML für die Details (Tabelle, etc.)

        // 1. Hauptergebnis bestimmen und formatieren
        switch (abrechnung.type) {
            case "Pauschale":
                console.log("[getBillingAnalysis] Abrechnungstyp: Pauschale", abrechnung.details?.Pauschale);
                finalResultHeader = `<p class="final-result-header success"><b>Abrechnung als Pauschale empfohlen.</b></p>`;
                if (abrechnung.details) {
                    // Übergebe das ganze abrechnung-Objekt an die Funktion
                    finalResultDetailsHtml = displayPauschale(abrechnung);
                } else {
                    finalResultDetailsHtml = "<p class='error'>Fehler: Pauschalendetails fehlen.</p>";
                }
                break;

            case "TARDOC":
                console.log("[getBillingAnalysis] Abrechnungstyp: TARDOC");
                finalResultHeader = `<p class="final-result-header success"><b>Abrechnung als TARDOC-Einzelleistung(en) empfohlen.</b></p>`;
                if (abrechnung.leistungen && abrechnung.leistungen.length > 0) {
                    // Rufe Hilfsfunktion zur Anzeige der TARDOC-Tabelle auf (gibt HTML für <details> zurück)
                    finalResultDetailsHtml = displayTardocTable(abrechnung.leistungen, regelErgebnisseDetails);
                } else {
                    finalResultDetailsHtml = "<p><i>Keine TARDOC-Positionen zur Abrechnung übermittelt.</i></p>";
                }
                break;

            case "Error":
                console.error("[getBillingAnalysis] Abrechnungstyp: Error", abrechnung.message);
                finalResultHeader = `<p class="final-result-header error"><b>Abrechnung nicht möglich oder Fehler aufgetreten.</b></p>`;
                finalResultDetailsHtml = `<p><i>Grund: ${escapeHtml(abrechnung.message || 'Unbekannter Fehler')}</i></p>`;
                // Optional: Regeldetails bei Fehler anzeigen (siehe unten)
                break;

            default:
                console.error("[getBillingAnalysis] Unbekannter Abrechnungstyp:", abrechnung.type);
                finalResultHeader = `<p class="final-result-header error"><b>Unbekannter Abrechnungstyp vom Server.</b></p>`;
                finalResultDetailsHtml = `<p class='error'>Interner Fehler: Unbekannter Abrechnungstyp '${escapeHtml(abrechnung.type)}'.</p>`;
        }

        // Füge Hauptergebnis zum Output hinzu
        htmlOutput += finalResultHeader;

        // 2. Details zur finalen Abrechnung (Pauschale/TARDOC) hinzufügen (ist bereits in <details>)
        htmlOutput += finalResultDetailsHtml;

        // 3. LLM Stufe 1 Ergebnisse (immer anzeigen, einklappbar)
        htmlOutput += generateLlmStage1Details(llmResultStufe1);

        // 4. Regelprüfungsdetails (immer anzeigen, einklappbar, besonders relevant bei Fehlern/Warnungen)
        htmlOutput += generateRuleCheckDetails(regelErgebnisseDetails, abrechnung.type === "Error");

        // --- Finalen Output anzeigen ---
        displayOutput(htmlOutput); // Zeige das finale Ergebnis im Haupt-Output
        console.log("[getBillingAnalysis] Frontend-Verarbeitung abgeschlossen.");
        hideSpinner(); // Spinner ausblenden, nachdem der Output gesetzt wurde

    } catch (error) {
         console.error("[getBillingAnalysis] Unerwarteter Fehler bei Ergebnisverarbeitung im Frontend:", error);
         displayOutput(`<p class="error">Ein interner Fehler im Frontend ist aufgetreten: ${escapeHtml(error.message)}</p><pre>${escapeHtml(error.stack)}</pre>`);
         hideSpinner();
    }
}

// ─── 4 · Hilfsfunktionen zur ANZEIGE (jetzt alle in <details>) ────

// NEU: Generiert den <details> Block für LLM Stufe 1 Ergebnisse
function generateLlmStage1Details(llmResult) {
    if (!llmResult) return "";

    const identifiedLeistungen = llmResult.identified_leistungen || [];
    const extractedInfo = llmResult.extracted_info || {};
    const begruendung = llmResult.begruendung_llm || 'N/A';

    let detailsHtml = `<details><summary>Details LLM-Analyse (Stufe 1)</summary>`;
    detailsHtml += `<div>`; // Container für Inhalt

    if (identifiedLeistungen.length > 0) {
        // Geändert: "Die identifizierte(n) LKN(s)..."
        detailsHtml += `<p><b>Die vom LLM identifizierte(n) LKN(s):</b></p><ul>`;
        identifiedLeistungen.forEach(l => {
            const desc = l.beschreibung || beschreibungZuLKN(l.lkn) || 'N/A';
            const mengeText = l.menge !== null ? ` (Menge: ${l.menge})` : '';
            // Geändert: "Die LKN ..."
            detailsHtml += `<li><b>Die LKN ${escapeHtml(l.lkn)}:</b> ${escapeHtml(desc)}${mengeText}</li>`;
        });
        detailsHtml += `</ul>`;
    } else {
        detailsHtml += `<p><i>Keine LKN durch LLM identifiziert.</i></p>`;
    }

    let extractedDetails = [];
    if (extractedInfo.dauer_minuten !== null) extractedDetails.push(`Dauer: ${extractedInfo.dauer_minuten} Min.`);
    if (extractedInfo.menge_allgemein !== null && extractedInfo.menge_allgemein !== 0) extractedDetails.push(`Menge: ${extractedInfo.menge_allgemein}`);
    if (extractedInfo.alter !== null && extractedInfo.alter !== 0) extractedDetails.push(`Alter: ${extractedInfo.alter}`);
    if (extractedInfo.geschlecht !== null && extractedInfo.geschlecht !== 'null' && extractedInfo.geschlecht !== 'unbekannt') extractedDetails.push(`Geschlecht: ${extractedInfo.geschlecht}`);

    if (extractedDetails.length > 0) {
        detailsHtml += `<p><b>Vom LLM extrahierte Details:</b> ${extractedDetails.join(', ')}</p>`;
    } else {
        detailsHtml += `<p><i>Keine zusätzlichen Details vom LLM extrahiert.</i></p>`
    }

    detailsHtml += `<p><b>Begründung LLM (Stufe 1):</b></p><p style="white-space: pre-wrap;">${escapeHtml(begruendung)}</p>`;
    detailsHtml += `</div></details>`;
    return detailsHtml;
}

// NEU: Generiert den <details> Block für Regelprüfungsdetails
function generateRuleCheckDetails(regelErgebnisse, isErrorCase = false) {
    if (!regelErgebnisse || regelErgebnisse.length === 0) return "";

    // Prüfen, ob es überhaupt relevante Infos gibt (Fehler oder Warnungen)
    const hasRelevantInfo = regelErgebnisse.some(r => r.regelpruefung && r.regelpruefung.fehler && r.regelpruefung.fehler.length > 0);

    // Nur anzeigen, wenn relevante Infos da sind oder wenn es ein Fehlerfall war
    if (!hasRelevantInfo && !isErrorCase && !(regelErgebnisse.length === 1 && regelErgebnisse[0].lkn === null)) {
         return ""; // Nichts anzeigen, wenn alles OK war und kein globaler Fehler vorlag
    }
    // Ausnahme: Wenn die einzige Meldung "Keine gültige LKN..." ist, trotzdem anzeigen
     if (!hasRelevantInfo && !isErrorCase && regelErgebnisse.length === 1 && regelErgebnisse[0]?.regelpruefung?.fehler?.[0]?.includes("Keine gültige LKN")) {
         // Fortfahren
     } else if (!hasRelevantInfo && !isErrorCase) {
         return ""; // Keine relevanten Infos und kein Fehler
     }


    let detailsHtml = `<details ${isErrorCase ? 'open' : ''}><summary>Details Regelprüfung</summary><div>`; // Bei Fehler standardmäßig offen

    regelErgebnisse.forEach((resultItem) => {
        const lkn = resultItem.lkn || 'Unbekannt';
        const initialMenge = resultItem.initiale_menge || 'N/A'; // Annahme: Backend sendet diese Info mit
        const finalMenge = resultItem.finale_menge;
        const regelpruefung = resultItem.regelpruefung;

        detailsHtml += `<h5 style="margin-bottom: 2px; margin-top: 8px;">LKN: ${escapeHtml(lkn)} (Finale Menge: ${finalMenge})</h5>`;

        if (regelpruefung) {
            if (!regelpruefung.abrechnungsfaehig) {
                 detailsHtml += `<p style="color: var(--danger);"><b>Nicht abrechnungsfähig.</b> Grund:</p>`;
                 if (regelpruefung.fehler && regelpruefung.fehler.length > 0) {
                      detailsHtml += `<ul>`;
                      regelpruefung.fehler.forEach(fehler => { detailsHtml += `<li class="error">${escapeHtml(fehler)}</li>`; });
                      detailsHtml += `</ul>`;
                 } else {
                      detailsHtml += `<p><i>Kein spezifischer Grund angegeben, aber nicht abrechnungsfähig.</i></p>`;
                 }
            } else if (regelpruefung.fehler && regelpruefung.fehler.length > 0) {
                 // Abrechnungsfähig, aber mit Hinweisen/Anpassungen
                 detailsHtml += `<p><b>Hinweise / Anpassungen:</b></p><ul>`;
                 regelpruefung.fehler.forEach(hinweis => {
                      const style = hinweis.includes("Menge auf") ? "color: var(--danger); font-weight: bold;" : ""; // War vorher --accent, jetzt --danger für Reduktion
                      detailsHtml += `<li style="${style}">${escapeHtml(hinweis)}</li>`;
                 });
                 detailsHtml += `</ul>`;
            } else {
                 // Abrechnungsfähig ohne Fehler/Hinweise
                 detailsHtml += `<p style="color: var(--accent);"><i>Regelprüfung OK.</i></p>`;
            }
        } else {
             detailsHtml += `<p><i>Kein Regelprüfungsergebnis vorhanden.</i></p>`;
        }
    });

    detailsHtml += `</div></details>`;
    return detailsHtml;
}


// In calculator.js

// Funktion erhält jetzt das ganze Abrechnungs-Objekt
function displayPauschale(abrechnungsObjekt) {
    // --- NUR HIER darf bedingungsHtml deklariert werden ---
    const pauschaleDetails = abrechnungsObjekt.details;
    const bedingungsHtml = abrechnungsObjekt.bedingungs_pruef_html || ""; // <<<< Erste und einzige Deklaration
    const bedingungsFehler = abrechnungsObjekt.bedingungs_fehler || [];
    const conditions_met = abrechnungsObjekt.conditions_met === true;
    // -----------------------------------------------------

    // Schlüssel für Pauschalen-Details
    const PAUSCHALE_KEY = 'Pauschale';
    const PAUSCHALE_TEXT_KEY = 'Pauschale_Text';
    const PAUSCHALE_TP_KEY = 'Taxpunkte';
    const PAUSCHALE_ERKLAERUNG_KEY = 'pauschale_erklaerung_html';
    const POTENTIAL_ICDS_KEY = 'potential_icds';

    if (!pauschaleDetails) return "<p class='error'>Pauschalendetails fehlen.</p>";

    // Werte aus Details holen
    const pauschaleCode = escapeHtml(pauschaleDetails[PAUSCHALE_KEY] || 'N/A');
    const pauschaleText = escapeHtml(pauschaleDetails[PAUSCHALE_TEXT_KEY] || 'N/A');
    const pauschaleTP = escapeHtml(pauschaleDetails[PAUSCHALE_TP_KEY] || 'N/A');
    const pauschaleErklaerung = pauschaleDetails[PAUSCHALE_ERKLAERUNG_KEY] || "";
    const potentialICDs = pauschaleDetails[POTENTIAL_ICDS_KEY] || [];

    // HTML-Struktur aufbauen
    let detailsContent = `
        <table border="1" style="border-collapse: collapse; width: 100%; margin-bottom: 10px;">
            <thead><tr><th>Pauschale Code</th><th>Beschreibung</th><th>Taxpunkte</th></tr></thead>
            <tbody><tr>
                <td>${pauschaleCode}</td>
                <td>${pauschaleText}</td>
                <td>${pauschaleTP}</td>
            </tr></tbody>
        </table>`;

    // 1. Begründung der Auswahl hinzufügen
    if (pauschaleErklaerung) {
         detailsContent += `<details style="margin-top: 10px;"><summary>Begründung Pauschalenauswahl</summary>${pauschaleErklaerung}</details>`;
    }

    // 2. Details zur Bedingungsprüfung hinzufügen (verwende die Variable 'bedingungsHtml')
    if (bedingungsHtml) {
         const openAttr = !conditions_met ? 'open' : ''; // Öffnen, wenn Bedingungen NICHT erfüllt sind
         detailsContent += `<details ${openAttr} style="margin-top: 10px;"><summary>Details Pauschalen-Bedingungsprüfung (${conditions_met ? 'Alle erfüllt' : 'Nicht alle erfüllt'})</summary>${bedingungsHtml}</details>`;
         // Der separate Fehlerblock wurde entfernt, da die Infos jetzt im bedingungsHtml sind
    }

    // 3. Mögliche ICDs hinzufügen
    if (potentialICDs.length > 0) {
        // Finde die Zeile mit "if (potentialICDs..." - das ist etwa Zeile 438 in deiner Datei
        // Stelle sicher, dass hier KEINE zweite Deklaration von bedingungsHtml steht.
        detailsContent += `<details style="margin-top: 10px;"><summary>Mögliche zugehörige ICD-Diagnosen (gem. Bedingungen)</summary><ul>`;
        potentialICDs.forEach(icd => {
            detailsContent += `<li><b>${escapeHtml(icd.Code || 'N/A')}</b>: ${escapeHtml(icd.Code_Text || 'N/A')}</li>`;
        });
        detailsContent += `</ul></details>`;
    }

    // Haupt-Details-Block für die Pauschale erstellen
    let html = `<details open><summary>Details Pauschale: ${pauschaleCode} ${conditions_met ? ' <span style="color:green;">(Bedingungen erfüllt)</span>' : ' <span style="color:red;">(Bedingungen teilweise nicht erfüllt)</span>'}</summary>${detailsContent}</details>`;
    return html;
}

// Stelle sicher, dass diese Zeile am Ende der Datei calculator.js steht:
window.getBillingAnalysis = getBillingAnalysis;

// Anpassung: Zeigt TARDOC-Tabelle in <details>
function displayTardocTable(tardocLeistungen, ruleResultsDetailsList = []) {
    if (!tardocLeistungen || tardocLeistungen.length === 0) {
        return "<p><i>Keine TARDOC-Positionen zur Abrechnung.</i></p>";
    }

    let tardocTableBody = "";
    let gesamtTP = 0;
    let hasHintsOverall = false; // Gibt es irgendwo Hinweise?

    for (const leistung of tardocLeistungen) {
        const lkn = leistung.lkn;
        const anzahl = leistung.menge;
        const tardocDetails = processTardocLookup(lkn); // Lokale Suche nach AL/IPL etc.

        if (!tardocDetails.applicable) {
             tardocTableBody += `<tr><td colspan="7" class="error">Fehler: Details für LKN ${escapeHtml(lkn)} nicht gefunden!</td></tr>`;
             continue;
        }

        // --- !!! SCHLÜSSELNAMEN PRÜFEN / ANPASSEN (aus processTardocLookup) !!! ---
        const name = leistung.beschreibung || tardocDetails.leistungsname || 'N/A';
        const al = tardocDetails.al;
        const ipl = tardocDetails.ipl;
        let regelnHtml = tardocDetails.regeln ? `<p><b>TARDOC-Regel:</b> ${escapeHtml(tardocDetails.regeln)}</p>` : ''; // TARDOC-Text Regeln
        // --- !!! ENDE ANPASSUNG !!! ---

        // --- Füge Hinweise aus Backend-Regelprüfung hinzu ---
        const ruleResult = ruleResultsDetailsList.find(r => r.lkn === lkn);
        let hasHintForThisLKN = false; // Flag für roten Text bei dieser LKN
        if (ruleResult && ruleResult.regelpruefung && ruleResult.regelpruefung.fehler && ruleResult.regelpruefung.fehler.length > 0) {
             if (regelnHtml) regelnHtml += "<hr style='margin: 5px 0; border-color: #eee;'>";
             regelnHtml += `<p><b>Hinweise Backend-Regelprüfung:</b></p><ul>`;
             ruleResult.regelpruefung.fehler.forEach(hinweis => {
                  const isReduction = hinweis.includes("Menge auf");
                  const style = isReduction ? "color: var(--danger); font-weight: bold;" : ""; // Rot/Fett bei Reduktion
                  if (isReduction) {
                      hasHintForThisLKN = true;
                      hasHintsOverall = true; // Gesamtflag setzen
                  }
                  regelnHtml += `<li style="${style}">${escapeHtml(hinweis)}</li>`;
             });
             regelnHtml += `</ul>`;
        }
        // --- ENDE Regelhinweise ---

        const total_tp = (al + ipl) * anzahl;
        gesamtTP += total_tp;

        // Style für Details-Summary, wenn ein Hinweis vorhanden ist
        const detailsSummaryStyle = hasHintForThisLKN ? ' class="rule-hint-trigger"' : ''; // CSS-Klasse für roten Text

        tardocTableBody += `
            <tr>
                <td>${escapeHtml(lkn)}</td><td>${escapeHtml(name)}</td>
                <td>${al.toFixed(2)}</td><td>${ipl.toFixed(2)}</td>
                <td>${anzahl}</td><td>${total_tp.toFixed(2)}</td>
                <td>${regelnHtml ? `<details><summary${detailsSummaryStyle}>Regeln/Hinweise</summary>${regelnHtml}</details>` : 'Keine'}</td>
            </tr>`;
    }

    // Haupt-Details-Block für die TARDOC-Abrechnung
    // Summary hervorheben, wenn es irgendwo Hinweise gab
    const overallSummaryClass = hasHintsOverall ? ' class="rule-hint-trigger"' : '';
    let html = `<details open><summary ${overallSummaryClass}>Details TARDOC Abrechnung (${tardocLeistungen.length} Positionen)</summary>`;
    html += `
        <table border="1" style="border-collapse: collapse; width: 100%; margin-bottom: 10px;">
            <thead><tr><th>LKN</th><th>Leistung</th><th>AL</th><th>IPL</th><th>Anzahl</th><th>Total TP</th><th>Regeln/Hinweise</th></tr></thead>
            <tbody>${tardocTableBody}</tbody>
            <tfoot><tr><th colspan="5" style="text-align:right;">Gesamt TARDOC TP:</th><th colspan="2">${gesamtTP.toFixed(2)}</th></tr></tfoot>
        </table>`;
    html += `</details>`; // Schließe Haupt-Details
    return html;
}


// Hilfsfunktion: Sucht nur die TARDOC-Details lokal (unverändert)
function processTardocLookup(lkn) {
    // ... (unverändert)
    let result = { applicable: false, data: null, al: 0, ipl: 0, leistungsname: 'N/A', regeln: '' };
    // --- !!! WICHTIG: Schlüsselnamen anpassen !!! ---
    const TARDOC_LKN_KEY = 'LKN'; // ANPASSEN!
    const AL_KEY = 'AL_(normiert)'; // ANPASSEN!
    const IPL_KEY = 'IPL_(normiert)'; // ANPASSEN!
    const DESC_KEY_1 = 'Bezeichnung'; // ANPASSEN!
    const RULES_KEY_1 = 'Regeln_bezogen_auf_die_Tarifmechanik'; // ANPASSEN!
    // --- !!! ENDE ANPASSUNG !!! ---

    if (!data_tardocGesamt || data_tardocGesamt.length === 0) { console.warn(`TARDOC-Daten nicht geladen oder leer für LKN ${lkn}.`); return result; }
    const tardocPosition = data_tardocGesamt.find(item => item && item[TARDOC_LKN_KEY] && String(item[TARDOC_LKN_KEY]).toUpperCase() === lkn.toUpperCase());
    if (!tardocPosition) { console.warn(`LKN ${lkn} nicht in lokalen TARDOC-Daten gefunden.`); return result; }

    result.applicable = true; result.data = tardocPosition;
    // Sicherstellen, dass die Werte Zahlen sind, ersetze Komma durch Punkt
    const parseGermanFloat = (value) => {
        if (typeof value === 'string') {
            return parseFloat(value.replace(',', '.')) || 0;
        }
        return parseFloat(value) || 0;
    };
    result.al = parseGermanFloat(tardocPosition[AL_KEY]);
    result.ipl = parseGermanFloat(tardocPosition[IPL_KEY]);
    result.leistungsname = tardocPosition[DESC_KEY_1] || 'N/A';
    result.regeln = tardocPosition[RULES_KEY_1] || '';
    return result;
}


// ─── 5 · Enter-Taste als Default für Return (unverändert) ─────────────────
document.addEventListener("DOMContentLoaded", function() {
    // ... (unverändert)
    const uiField = $("userInput");
    const icdField = $("icdInput");
    const gtinField = $("gtinInput");

    function handleEnter(e) {
        if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            // Stelle sicher, dass Daten geladen sind (oder zumindest versucht wurden zu laden)
             if (data_leistungskatalog.length > 0 || $("output")?.querySelector('.error')) {
                  getBillingAnalysis();
             } else {
                  console.log("Daten noch nicht geladen, warte...");
                  // Optional: Visuelles Feedback geben
                  const button = $('analyzeButton');
                  if(button) button.textContent = "Lade Daten...";
             }
        }
    }

    if (uiField) uiField.addEventListener("keydown", handleEnter);
    if (icdField) icdField.addEventListener("keydown", handleEnter);
    if (gtinField) gtinField.addEventListener("keydown", handleEnter);

});

// Mache die Hauptfunktionen global verfügbar
window.getBillingAnalysis = getBillingAnalysis;