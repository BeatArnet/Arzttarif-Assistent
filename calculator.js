// calculator.js - Vollständige Version (06.05.2025)
// Arbeitet mit zweistufigem Backend (Mapping-Ansatz). Holt lokale Details zur Anzeige.
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


function beschreibungZuLKN(lkn) {
    // Stellt sicher, dass data_leistungskatalog geladen ist und ein Array ist
    if (!Array.isArray(data_leistungskatalog) || data_leistungskatalog.length === 0 || typeof lkn !== 'string') {
        // console.warn(`beschreibungZuLKN: Daten nicht bereit oder ungültige LKN für ${lkn}`);
        return lkn; // Gibt LKN zurück, wenn keine Beschreibung gefunden wird
    }
    // Case-insensitive Suche
    const hit = data_leistungskatalog.find(e => e.LKN?.toUpperCase() === lkn.toUpperCase());
    // Gibt Beschreibung zurück oder LKN selbst, wenn keine Beschreibung vorhanden ist
    return hit ? (hit.Beschreibung || lkn) : lkn;
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

function showSpinner(text = "Prüfung läuft...") {
    const textSpinner = $('spinner');
    const button = $('analyzeButton');
    const body = document.body;

    if (textSpinner) {
        textSpinner.innerHTML = escapeHtml(text); // Text escapen
        textSpinner.style.display = 'block';
    }
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
    const textSpinner = $('spinner');
    const button = $('analyzeButton');
    const body = document.body;

    if (textSpinner) {
        textSpinner.innerHTML = "";
        textSpinner.style.display = 'none';
    }
    if (button) button.disabled = false;

    if (mouseSpinnerElement) mouseSpinnerElement.style.display = 'none';
    if (body) body.style.cursor = 'default';

    if (mouseMoveHandler) {
        document.removeEventListener('mousemove', mouseMoveHandler);
        mouseMoveHandler = null;
    }
}
// --- Ende Mouse Spinner Funktionen ---


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
    const initialSpinnerMsg = "Lade Tarifdaten...";
    showSpinner(initialSpinnerMsg);
    const outputDiv = $("output");
    if (outputDiv) outputDiv.innerHTML = "";

    let loadedDataArray = [];
    let loadError = null;

    try {
        loadedDataArray = await Promise.all([
            fetchJSON(DATA_PATHS.leistungskatalog), fetchJSON(DATA_PATHS.pauschaleLP),
            fetchJSON(DATA_PATHS.pauschalen), fetchJSON(DATA_PATHS.pauschaleBedingungen),
            fetchJSON(DATA_PATHS.tardocGesamt), fetchJSON(DATA_PATHS.tabellen)
        ]);

        [ data_leistungskatalog, data_pauschaleLeistungsposition, data_pauschalen,
          data_pauschaleBedingungen, data_tardocGesamt, data_tabellen ] = loadedDataArray;

        let missingDataErrors = [];
        if (!Array.isArray(data_leistungskatalog) || data_leistungskatalog.length === 0) missingDataErrors.push("Leistungskatalog");
        if (!Array.isArray(data_tardocGesamt) || data_tardocGesamt.length === 0) missingDataErrors.push("TARDOC-Daten");
        if (!Array.isArray(data_pauschalen) || data_pauschalen.length === 0) missingDataErrors.push("Pauschalen");
        if (!Array.isArray(data_pauschaleBedingungen) || data_pauschaleBedingungen.length === 0) missingDataErrors.push("Pauschalen-Bedingungen");
        if (!Array.isArray(data_tabellen) || data_tabellen.length === 0) missingDataErrors.push("Referenz-Tabellen");

        if (missingDataErrors.length > 0) {
             throw new Error(`Folgende kritische Daten fehlen oder konnten nicht geladen werden: ${missingDataErrors.join(', ')}.`);
        }

        console.log("Frontend-Daten vom Server geladen.");

        displayOutput("<p class='success'>Daten geladen. Bereit zur Prüfung.</p>");
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
    mouseSpinnerElement = $('mouseSpinner');
    loadIcdCheckboxState();
    loadData();
});

// ─── 3 · Hauptlogik (Button‑Click) ────────────────────────────────────────
async function getBillingAnalysis() {
    console.log("[getBillingAnalysis] Funktion gestartet.");
    const userInput = $("userInput").value.trim();
    const icdInput = $("icdInput").value.trim().split(",").map(s => s.trim().toUpperCase()).filter(Boolean);
    const gtinInput = ($("gtinInput") ? $("gtinInput").value.trim().split(",").map(s => s.trim()).filter(Boolean) : []);
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
    if (!userInput) { displayOutput("<p class='error'>Bitte Leistungsbeschreibung eingeben.</p>"); return; }

    showSpinner("Analyse gestartet, sende Anfrage...");
    displayOutput("", "info");

    try {
        console.log("[getBillingAnalysis] Sende Anfrage an Backend...");
        const requestBody = {
            inputText: userInput,
            icd: icdInput,
            gtin: gtinInput,
            useIcd: useIcd,
            age: age,
            gender: gender
        };
        const res = await fetch("/api/analyze-billing", { method: "POST", headers: {"Content-Type":"application/json"}, body: JSON.stringify(requestBody) });
        rawResponseText = await res.text();
        // console.log("[getBillingAnalysis] Raw Response vom Backend erhalten:", rawResponseText.substring(0, 500) + "..."); // Gekürzt loggen
        if (!res.ok) { throw new Error(`Server antwortete mit ${res.status}`); }
        backendResponse = JSON.parse(rawResponseText);
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
        showSpinner("Antwort erhalten, verarbeite Ergebnisse...");

    } catch (e) {
        console.error("Fehler bei Backend-Anfrage oder Verarbeitung:", e);
        let msg = `<p class="error">Server-Fehler: ${escapeHtml(e.message)}</p>`;
        if (rawResponseText && (e instanceof SyntaxError || rawResponseText.length < 1000) && !e.message.includes(rawResponseText.substring(0,50))) {
             msg += `<details style="margin-top:1em"><summary>Raw Response (gekürzt)</summary><pre>${escapeHtml(rawResponseText.substring(0,1000))}${rawResponseText.length > 1000 ? '...' : ''}</pre></details>`;
        }
        displayOutput(msg);
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
        htmlOutput = `<h2>Ergebnis für «${escapeHtml(userInput)}»</h2>`;

        let finalResultHeader = "";
        let finalResultDetailsHtml = "";

        // 1. Hauptergebnis bestimmen und formatieren
        switch (abrechnung.type) {
            case "Pauschale":
                console.log("[getBillingAnalysis] Abrechnungstyp: Pauschale", abrechnung.details?.Pauschale);
                finalResultHeader = `<p class="final-result-header success"><b>Abrechnung als Pauschale.</b></p>`;
                if (abrechnung.details) {
                    finalResultDetailsHtml = displayPauschale(abrechnung);
                } else {
                    finalResultDetailsHtml = "<p class='error'>Fehler: Pauschalendetails fehlen.</p>";
                }
                break;
            case "TARDOC":
                 console.log("[getBillingAnalysis] Abrechnungstyp: TARDOC");
                 finalResultHeader = `<p class="final-result-header success"><b>Abrechnung als TARDOC-Einzelleistung(en).</b></p>`;
                 if (abrechnung.leistungen && abrechnung.leistungen.length > 0) {
                     finalResultDetailsHtml = displayTardocTable(abrechnung.leistungen, regelErgebnisseDetails);
                 } else {
                     finalResultDetailsHtml = "<p><i>Keine TARDOC-Positionen zur Abrechnung übermittelt.</i></p>";
                 }
                 break;
             case "Error":
                console.error("[getBillingAnalysis] Abrechnungstyp: Error", abrechnung.message);
                finalResultHeader = `<p class="final-result-header error"><b>Abrechnung nicht möglich oder Fehler aufgetreten.</b></p>`;
                finalResultDetailsHtml = `<p><i>Grund: ${escapeHtml(abrechnung.message || 'Unbekannter Fehler')}</i></p>`;
                break;
            default:
                console.error("[getBillingAnalysis] Unbekannter Abrechnungstyp:", abrechnung.type);
                finalResultHeader = `<p class="final-result-header error"><b>Unbekannter Abrechnungstyp vom Server.</b></p>`;
                finalResultDetailsHtml = `<p class='error'>Interner Fehler: Unbekannter Abrechnungstyp '${escapeHtml(abrechnung.type)}'.</p>`;
        }

        // Füge Hauptergebnis zum Output hinzu
        htmlOutput += finalResultHeader;
        // 2. Details zur finalen Abrechnung (Pauschale/TARDOC) hinzufügen
        htmlOutput += finalResultDetailsHtml;
        // 3. LLM Stufe 1 Ergebnisse
        htmlOutput += generateLlmStage1Details(llmResultStufe1);
        // 4. LLM Stufe 2 Ergebnisse (Mapping)
        const stage2Html = generateLlmStage2Details(llmResultStufe2); // Ergebnis holen
        // console.log("[getBillingAnalysis] Ergebnis von generateLlmStage2Details:", stage2Html.substring(0, 100) + "..."); // Loggen
        htmlOutput += stage2Html; // Hinzufügen
        // 5. Regelprüfungsdetails
        htmlOutput += generateRuleCheckDetails(regelErgebnisseDetails, abrechnung.type === "Error");

        // --- Finalen Output anzeigen ---
        displayOutput(htmlOutput);
        console.log("[getBillingAnalysis] Frontend-Verarbeitung abgeschlossen.");
        hideSpinner();

    } catch (error) {
         console.error("[getBillingAnalysis] Unerwarteter Fehler bei Ergebnisverarbeitung im Frontend:", error);
         displayOutput(`<p class="error">Ein interner Fehler im Frontend ist aufgetreten: ${escapeHtml(error.message)}</p><pre>${escapeHtml(error.stack)}</pre>`);
         hideSpinner();
    }
}

// ─── 4 · Hilfsfunktionen zur ANZEIGE ────────────────────────────────────────

// Funktion zum Speichern/Laden des Checkbox-Status
function saveIcdCheckboxState() {
    const checkbox = $('useIcdCheckbox');
    if (checkbox) {
        localStorage.setItem('useIcdRelevance', checkbox.checked);
    }
}

function loadIcdCheckboxState() {
    const checkbox = $('useIcdCheckbox');
    if (checkbox) {
        const savedState = localStorage.getItem('useIcdRelevance');
        checkbox.checked = (savedState === null || savedState === 'true');
        checkbox.addEventListener('change', saveIcdCheckboxState);
    }
}

// Generiert den <details> Block für LLM Stufe 1 Ergebnisse
function generateLlmStage1Details(llmResult) {
    if (!llmResult) return "";

    const identifiedLeistungen = llmResult.identified_leistungen || [];
    const extractedInfo = llmResult.extracted_info || {};
    const begruendung = llmResult.begruendung_llm || 'N/A';

    let detailsHtml = `<details><summary>Details LLM-Analyse (Stufe 1)</summary>`;
    detailsHtml += `<div>`;

    if (identifiedLeistungen.length > 0) {
        detailsHtml += `<p><b>Die vom LLM identifizierte(n) LKN(s):</b></p><ul>`;
        identifiedLeistungen.forEach(l => {
            // Hole Beschreibung aus lokalen Daten, wenn möglich
            const desc = beschreibungZuLKN(l.lkn);
            const mengeText = l.menge !== null && l.menge !== 1 ? ` (Menge: ${l.menge})` : ''; // Menge nur anzeigen wenn != 1
            detailsHtml += `<li><b>Die LKN ${escapeHtml(l.lkn)}:</b> ${escapeHtml(desc)}${mengeText}</li>`;
        });
        detailsHtml += `</ul>`;
    } else {
        detailsHtml += `<p><i>Keine LKN durch LLM identifiziert.</i></p>`;
    }

    let extractedDetails = [];
    if (extractedInfo.dauer_minuten !== null) extractedDetails.push(`Dauer: ${extractedInfo.dauer_minuten} Min.`);
    if (extractedInfo.menge_allgemein !== null && extractedInfo.menge_allgemein !== 0) extractedDetails.push(`Menge: ${extractedInfo.menge_allgemein}`);
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

// Generiert den <details> Block für LLM Stufe 2 Ergebnisse (Mapping)
function generateLlmStage2Details(llmResultStufe2) {
    // console.log("generateLlmStage2Details aufgerufen mit:", llmResultStufe2);

    // Prüft auf die korrekte Struktur für Mapping-Ergebnisse
    if (!llmResultStufe2 || !llmResultStufe2.mapping_results || !Array.isArray(llmResultStufe2.mapping_results) || llmResultStufe2.mapping_results.length === 0) {
        // console.log("generateLlmStage2Details: Keine gültigen Mapping-Ergebnisse gefunden, gebe leeren String zurück.");
        return ""; // Nichts anzeigen, wenn keine Mapping-Ergebnisse vorhanden sind
    }

    const mappingResults = llmResultStufe2.mapping_results;
    let detailsHtml = `<details><summary>Details LLM-Analyse Stufe 2 (TARDOC-zu-Pauschalen-LKN Mapping)</summary>`;
    detailsHtml += `<div>`;
    detailsHtml += `<p>Folgende TARDOC LKNs wurden versucht, auf äquivalente Pauschalen-Bedingungs-LKNs zu mappen:</p><ul>`;

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

    let detailsHtml = `<details ${isErrorCase || hasOnlyNoLknError ? 'open' : ''}><summary>Details Regelprüfung</summary><div>`;

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
                 detailsHtml += `<p style="color: var(--danger);"><b>Nicht abrechnungsfähig.</b></p>`; // Grund wird in Fehlern gelistet
                 if (regelpruefung.fehler && regelpruefung.fehler.length > 0) {
                      detailsHtml += `<ul>`;
                      regelpruefung.fehler.forEach(fehler => { detailsHtml += `<li class="error">${escapeHtml(fehler)}</li>`; });
                      detailsHtml += `</ul>`;
                 } else if (lkn !== 'N/A') { // Nur anzeigen, wenn es eine LKN gab
                      detailsHtml += `<p><i>Kein spezifischer Grund angegeben.</i></p>`;
                 }
            } else if (regelpruefung.fehler && regelpruefung.fehler.length > 0) {
                 detailsHtml += `<p><b>Hinweise / Anpassungen:</b></p><ul>`;
                 regelpruefung.fehler.forEach(hinweis => {
                      const style = hinweis.includes("Menge auf") ? "color: var(--danger); font-weight: bold;" : "";
                      detailsHtml += `<li style="${style}">${escapeHtml(hinweis)}</li>`;
                 });
                 detailsHtml += `</ul>`;
            } else if (lkn !== 'N/A') { // Nur anzeigen, wenn es eine LKN gab
                 detailsHtml += `<p style="color: var(--accent);"><i>Regelprüfung OK.</i></p>`;
            }
        } else if (lkn !== 'N/A') { // Nur anzeigen, wenn es eine LKN gab
             detailsHtml += `<p><i>Kein Regelprüfungsergebnis vorhanden.</i></p>`;
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
    const conditions_met_structured = abrechnungsObjekt.conditions_met === true;

    const PAUSCHALE_KEY = 'Pauschale';
    const PAUSCHALE_TEXT_KEY = 'Pauschale_Text';
    const PAUSCHALE_TP_KEY = 'Taxpunkte';
    const PAUSCHALE_ERKLAERUNG_KEY = 'pauschale_erklaerung_html';

    if (!pauschaleDetails) return "<p class='error'>Pauschalendetails fehlen.</p>";

    const pauschaleCode = escapeHtml(pauschaleDetails[PAUSCHALE_KEY] || 'N/A');
    const pauschaleText = escapeHtml(pauschaleDetails[PAUSCHALE_TEXT_KEY] || 'N/A');
    const pauschaleTP = escapeHtml(pauschaleDetails[PAUSCHALE_TP_KEY] || 'N/A');
    const pauschaleErklaerung = pauschaleDetails[PAUSCHALE_ERKLAERUNG_KEY] || "";

    let detailsContent = `
        <table border="1" style="border-collapse: collapse; width: 100%; margin-bottom: 10px;">
            <thead><tr><th>Pauschale Code</th><th>Beschreibung</th><th>Taxpunkte</th></tr></thead>
            <tbody><tr>
                <td>${pauschaleCode}</td>
                <td>${pauschaleText}</td>
                <td>${pauschaleTP}</td>
            </tr></tbody>
        </table>`;

    if (pauschaleErklaerung) {
         detailsContent += `<details style="margin-top: 10px;"><summary>Begründung Pauschalenauswahl</summary>${pauschaleErklaerung}</details>`;
    }

    if (bedingungsHtml) {
        // Öffne Details immer, wenn die strukturierte Logik nicht erfüllt war ODER wenn es Einzelfehler gab
        const openAttr = !conditions_met_structured || (bedingungsFehler && bedingungsFehler.length > 0) ? 'open' : '';
        let summary_status_text = conditions_met_structured ? "Gesamtlogik erfüllt" : "Gesamtlogik NICHT erfüllt";
        detailsContent += `<details ${openAttr} style="margin-top: 10px;"><summary>Details Pauschalen-Bedingungsprüfung (${summary_status_text})</summary>${bedingungsHtml}</details>`;
    }

    // Block für potenzielle ICDs wurde entfernt

    let summary_main_status = conditions_met_structured ? '<span style="color:green;">(Logik erfüllt)</span>' : '<span style="color:red;">(Logik NICHT erfüllt)</span>';
    let html = `<details open><summary>Details Pauschale: ${pauschaleCode} ${summary_main_status}</summary>${detailsContent}</details>`;
    return html;
}


// Zeigt TARDOC-Tabelle an
function displayTardocTable(tardocLeistungen, ruleResultsDetailsList = []) {
    if (!tardocLeistungen || tardocLeistungen.length === 0) {
        return "<p><i>Keine TARDOC-Positionen zur Abrechnung.</i></p>";
    }

    let tardocTableBody = "";
    let gesamtTP = 0;
    let hasHintsOverall = false;

    for (const leistung of tardocLeistungen) {
        const lkn = leistung.lkn;
        const anzahl = leistung.menge;
        const tardocDetails = processTardocLookup(lkn); // Lokale Suche

        if (!tardocDetails.applicable) {
             tardocTableBody += `<tr><td colspan="7" class="error">Fehler: Details für LKN ${escapeHtml(lkn)} nicht gefunden!</td></tr>`;
             continue;
        }

        const name = leistung.beschreibung || tardocDetails.leistungsname || 'N/A';
        const al = tardocDetails.al;
        const ipl = tardocDetails.ipl;
        let regelnHtml = tardocDetails.regeln ? `<p><b>TARDOC-Regel:</b> ${escapeHtml(tardocDetails.regeln)}</p>` : '';

        const ruleResult = ruleResultsDetailsList.find(r => r.lkn === lkn);
        let hasHintForThisLKN = false;
        if (ruleResult && ruleResult.regelpruefung && ruleResult.regelpruefung.fehler && ruleResult.regelpruefung.fehler.length > 0) {
             if (regelnHtml) regelnHtml += "<hr style='margin: 5px 0; border-color: #eee;'>";
             regelnHtml += `<p><b>Hinweise Backend-Regelprüfung:</b></p><ul>`;
             ruleResult.regelpruefung.fehler.forEach(hinweis => {
                  const isReduction = hinweis.includes("Menge auf");
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
                <td>${regelnHtml ? `<details><summary${detailsSummaryStyle}>Regeln/Hinweise</summary>${regelnHtml}</details>` : 'Keine'}</td>
            </tr>`;
    }

    const overallSummaryClass = hasHintsOverall ? ' class="rule-hint-trigger"' : '';
    let html = `<details open><summary ${overallSummaryClass}>Details TARDOC Abrechnung (${tardocLeistungen.length} Positionen)</summary>`;
    html += `
        <table border="1" style="border-collapse: collapse; width: 100%; margin-bottom: 10px;">
            <thead><tr><th>LKN</th><th>Leistung</th><th>AL</th><th>IPL</th><th>Anzahl</th><th>Total TP</th><th>Regeln/Hinweise</th></tr></thead>
            <tbody>${tardocTableBody}</tbody>
            <tfoot><tr><th colspan="5" style="text-align:right;">Gesamt TARDOC TP:</th><th colspan="2">${gesamtTP.toFixed(2)}</th></tr></tfoot>
        </table>`;
    html += `</details>`;
    return html;
}


// Hilfsfunktion: Sucht TARDOC-Details lokal
function processTardocLookup(lkn) {
    let result = { applicable: false, data: null, al: 0, ipl: 0, leistungsname: 'N/A', regeln: '' };
    // Schlüssel anpassen, falls nötig (aus TARDOCGesamt...)
    const TARDOC_LKN_KEY = 'LKN';
    const AL_KEY = 'AL_(normiert)';
    const IPL_KEY = 'IPL_(normiert)';
    const DESC_KEY_1 = 'Bezeichnung';
    const RULES_KEY_1 = 'Regeln_bezogen_auf_die_Tarifmechanik';

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
    result.leistungsname = tardocPosition[DESC_KEY_1] || 'N/A';
    result.regeln = tardocPosition[RULES_KEY_1] || '';
    return result;
}


// ─── 5 · Enter-Taste als Default für Return ─────────────────
document.addEventListener("DOMContentLoaded", function() {
    const uiField = $("userInput");
    const icdField = $("icdInput");
    const gtinField = $("gtinInput");

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
    if (gtinField) gtinField.addEventListener("keydown", handleEnter);
});

// Mache die Hauptfunktion global verfügbar
window.getBillingAnalysis = getBillingAnalysis;