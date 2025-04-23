// calculator.js – komplett neu (17‑Apr‑2025)
// ---------------------------------------------------------------------------
// Dieses Skript kommuniziert mit /api/analyze-billing, zeigt die Ergebnisse
// robust im GUI an und benötigt keinerlei Änderungen im Flask‑Backend.
// ---------------------------------------------------------------------------

// ─── 0 · Globale Datencontainer ─────────────────────────────────────────────
let data_leistungskatalog = [];
let data_pauschaleLeistungsposition = [];
let data_pauschalen = [];
let data_pauschaleBedingungen = [];
let data_tardocGesamt = [];
let data_tabellen = [];

const DATA_PATHS = {
    leistungskatalog: "data/tblLeistungskatalog.json",
    pauschaleLP: "data/tblPauschaleLeistungsposition.json",
    pauschalen: "data/tblPauschalen.json",
    pauschaleBedingungen: "data/tblPauschaleBedingungen.json",
    tardocGesamt: "data/tblTardoc_Gesamt.json",   // optional
    tabellen: "data/tblTabellen.json",
};

// ─── 1 · Utility‑Funktionen ────────────────────────────────────────────────
function $(id) { return document.getElementById(id); }

function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[c]));
}

function beschreibungZuLKN(lkn) {
    const hit = data_leistungskatalog.find(e => e.LKN?.toUpperCase() === lkn.toUpperCase());
    return hit ? hit.Beschreibung || "" : "";
}

function displayOutput(html, type = "info") {
    const out = $("output");
    out.innerHTML = html;
    out.className = type;
}

// ─── 2 · Daten laden ───────────────────────────────────────────────────────
async function fetchJSON(path) {
    try {
        const r = await fetch(path);
        if (!r.ok) throw new Error(r.status);
        return await r.json();
    } catch (e) {
        console.warn("Fehler beim Laden", path, e);
        return [];
    }
}

async function loadData() {
    [data_leistungskatalog,
     data_pauschaleLeistungsposition,
     data_pauschalen,
     data_pauschaleBedingungen,
     data_tardocGesamt,
     data_tabellen] = await Promise.all([
        fetchJSON(DATA_PATHS.leistungskatalog),
        fetchJSON(DATA_PATHS.pauschaleLP),
        fetchJSON(DATA_PATHS.pauschalen),
        fetchJSON(DATA_PATHS.pauschaleBedingungen),
        fetchJSON(DATA_PATHS.tardocGesamt),
        fetchJSON(DATA_PATHS.tabellen),
    ]);
    console.log("Frontend‑Daten geladen.");
}

document.addEventListener("DOMContentLoaded", loadData);

// ─── 3 · Hauptlogik (Button‑Click) ────────────────────────────────────────
async function getBillingAnalysis() {
    const text = $("userInput").value.trim();
    const icds = $("icdInput").value.trim()
                  .split(",").map(s => s.trim().toUpperCase()).filter(Boolean);
    // Medikamente (GTINs) optional
    const gtins = $("gtinInput").value.trim()
                  .split(",").map(s => s.trim()).filter(Boolean);
    if (!text) { displayOutput("Bitte Leistungsbeschreibung eingeben.", "error"); return; }

    // Statusmeldung
    displayOutput("Prüfe Abrechnung …", "info");

    // Menge wird aus LLM-Extraktion ermittelt; kein separates Eingabefeld notwendig

    // Anfrage an Backend und Roh-Antwort für Debugging speichern
    let backend;
    let rawResponseText = "";
    try {
        const res = await fetch("/api/analyze-billing", {
            method: "POST",
            headers: {"Content-Type":"application/json"},
            body: JSON.stringify({inputText: text, icd: icds, gtin: gtins})
        });
        rawResponseText = await res.text();
        if (!res.ok) throw new Error(`${res.status} ${rawResponseText}`);
        try {
            backend = JSON.parse(rawResponseText);
        } catch (e) {
            throw new Error(`Ungültiges JSON: ${e.message}`);
        }
    } catch (e) {
        console.error(e);
        let msg = `Server-Fehler: ${escapeHtml(e.message)}`;
        if (rawResponseText) {
            msg += `<details style=\"margin-top:1em\"><summary>Raw Response</summary><pre>${escapeHtml(rawResponseText)}</pre></details>`;
        }
        displayOutput(msg, "error");
        return;
    }

    const llm = backend.llm_ergebnis;
    if (!llm) { displayOutput("Unerwartetes Backend-Format", "error"); return; }

    // Leistungen direkt aus Backend-Abrechnungsvorschlag verwenden
    const itemsArr = Array.isArray(backend.leistungen)
        ? backend.leistungen.map(item => ({ ...item, beschreibung: beschreibungZuLKN(item.lkn) }))
        : [];

    // HTML-Ergebnis zusammenstellen
    let html = `<h2>Ergebnisse für «${escapeHtml(text)}»</h2>`;
    // LLM-Analyse: erkannte Leistungen und Mengen
    html += `<h3>LLM-Analyse</h3>`;
    if (Array.isArray(llm.identified_leistungen) && llm.identified_leistungen.length) {
        html += `<ul>` + llm.identified_leistungen.map(item => {
            const code = typeof item === 'string' ? item : item.lkn || '';
            const qty  = (item && item.menge) ? `, Menge ${item.menge}` : '';
            return `<li>${escapeHtml(code)}${escapeHtml(qty)}</li>`;
        }).join('') + `</ul>`;
    } else {
        html += `<p><i>Keine LKN identifiziert.</i></p>`;
    }
    // Extrahierte Informationen
    const info = llm.extracted_info || {};
    const meta = [];
    if (info.dauer_minuten) meta.push(`Dauer ${info.dauer_minuten} Min`);
    if (info.alter) meta.push(`Alter ${info.alter}`);
    if (info.geschlecht && info.geschlecht !== "unbekannt") meta.push(info.geschlecht);
    // Hinweis auf extrahierte Dauer/Menge entfällt hier
    if (meta.length) html += `<p>${meta.join(" · ")}</p>`;
    html += `<p><b>Begründung LLM:</b> ${escapeHtml(llm.begruendung_llm || "-")}</p>`;
    // Abrechnungs-Vorschlag
    html += `<h3>Abrechnungs-Vorschlag</h3>`;
    if (itemsArr.length) {
        html += `<table border="1" style="border-collapse:collapse;width:100%">`;
        html += `<thead><tr><th>Typ</th><th>Code</th><th>Beschreibung</th><th>Menge</th><th>Details</th><th>Summe TP</th><th>Gültig</th></tr></thead><tbody>`;
        itemsArr.forEach(i => {
            const ok = i.abrechnungsfaehig;
            // Code für Anzeige (Pauschale oder Einzelleistung)
            const code = i.typ === "Pauschale" ? i.pauschale : i.lkn;
            const beschr = beschreibungZuLKN(code);
            let details = "";
            if (i.typ === "Pauschale") {
                details = `Taxpunkte/Einheit: ${i.taxpunkte_per_unit.toFixed(2)}`;
            } else {
                details = `AL: ${i.al.toFixed(2)}, IPL: ${i.ipl.toFixed(2)}`;
            }
            const sumTP = i.sum_taxpunkte.toFixed(2);
            html += `<tr>`;
            html += `<td>${escapeHtml(i.typ)}</td>`;
            html += `<td>${escapeHtml(code)}</td>`;
            html += `<td>${escapeHtml(beschr)}</td>`;
            html += `<td>${i.menge}</td>`;
            html += `<td>${escapeHtml(details)}</td>`;
            html += `<td>${sumTP}</td>`;
            html += `<td>${ok ? `<span style="color:green;">✓</span>` : `<span style="color:red;">✗</span>`}`;
            if (i.fehler?.length) {
                html += `<details><summary>Fehler (${i.fehler.length})</summary><ul>`
                     + i.fehler.map(f => `<li>${escapeHtml(f)}</li>`).join("") + `</ul></details>`;
            }
            html += `</td></tr>`;
        });
        html += `</tbody>`;
        // Totale Summe der Taxpunkte
        const totalTP = itemsArr.reduce((sum, i) => sum + parseFloat(i.sum_taxpunkte), 0);
        html += `<tfoot><tr><td colspan="5"><strong>Summe TP</strong></td><td><strong>${totalTP.toFixed(2)}</strong></td><td></td></tr></tfoot>`;
        html += `</table>`;
    } else {
        html += `<p><i>Keine Abrechnungsvorschläge verfügbar.</i></p>`;
    }
    // Debug: Raw Server-Antwort anzeigen
    if (typeof rawResponseText !== 'undefined' && rawResponseText) {
        html += `<details style="margin-top:1em; white-space: pre-wrap;"><summary>Raw Server-Antwort</summary><pre>${escapeHtml(rawResponseText)}</pre></details>`;
    }
    displayOutput(html, "info");
}

// ─── 4 · Button binding ───────────────────────────────────────────────
// ─── 4 · Button binding ───────────────────────────────────────────────
window.getBillingAnalysis = getBillingAnalysis;

// ─── 5 · Enter-Taste als Default für Return (Trigger) ─────────────────────
document.addEventListener("DOMContentLoaded", function() {
    const uiField = document.getElementById("userInput");
    const icdField = document.getElementById("icdInput");
    if (uiField) {
        uiField.addEventListener("keydown", function(e) {
            // Enter ohne Shift in Textarea löst Abrechnung aus
            if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                getBillingAnalysis();
            }
        });
    }
    if (icdField) {
        icdField.addEventListener("keydown", function(e) {
            // Enter in ICD-Eingabe löst Abrechnung aus
            if (e.key === "Enter") {
                e.preventDefault();
                getBillingAnalysis();
            }
        });
    }
});
