// Übersetzungen laden und bereitstellen
let translations = {};
function loadTranslations() {
    if (Object.keys(translations).length) return Promise.resolve(translations);
    return fetch('translations.json')
        .then(r => r.json())
        .then(data => {
            const base = data.de || {};
            for (const [lang, vals] of Object.entries(data)) {
                translations[lang] = { ...base, ...vals };
            }
            return translations;
        });
}

function t(key, lang = currentLang) {
    const useLang = translations[lang] ? lang : 'de';
    return (translations[useLang] && translations[useLang][key]) || (translations.de && translations.de[key]) || key;
}

let examplesData = {};
let groups = { einzelleistungen: [], pauschalen: [] };
let currentLang = 'de';

let tokenTotals = {
    llm1: { input: 0, output: 0 },
    llm2: { input: 0, output: 0 },
};
let perfStats = { durationsMs: [] };
let totalTests = 0;
let passedTests = 0;
let perfStatsByGroup = { einzelleistungen: [], pauschalen: [] };
let exampleIdToGroup = {};

let testQueue = [];
let isTesting = false;

function applyLanguage(lang) {
    currentLang = lang;
    document.documentElement.lang = lang;
    const header = document.getElementById('qcHeader');
    if (header) header.textContent = t('qcTitle', lang);
    const testAllBtn = document.getElementById('testAllBtn');
    if (testAllBtn) testAllBtn.textContent = t('qcTestAll', lang);

    const headerLabels = {
        de: { einz: 'Einzelleistungen', pausch: 'Pauschalen' },
        fr: { einz: 'Prestations individuelles', pausch: 'Forfaits' },
        it: { einz: 'Prestazioni singole', pausch: 'Forfait' },
    };
    const labels = headerLabels[lang] || headerLabels.de;
    const hEinz = document.getElementById('headerEinzelleistungen');
    if (hEinz) hEinz.textContent = labels.einz;
    const hPausch = document.getElementById('headerPauschalen');
    if (hPausch) hPausch.textContent = labels.pausch;

    document.querySelectorAll('.col-id').forEach(el => (el.textContent = t('qcColId', lang)));
    document.querySelectorAll('.col-example').forEach(el => (el.textContent = t('qcColExample', lang)));
    document.querySelectorAll('.col-action').forEach(el => (el.textContent = t('qcColAction', lang)));
    document.querySelectorAll('.col-res-de').forEach(el => (el.textContent = t('qcColResDe', lang)));
    document.querySelectorAll('.col-res-fr').forEach(el => (el.textContent = t('qcColResFr', lang)));
    document.querySelectorAll('.col-res-it').forEach(el => (el.textContent = t('qcColResIt', lang)));

    buildTable();
    updateTokenSummary();
    updatePerformanceSummary();
}

function loadExamples() {
    fetch('data/baseline_results.json')
        .then(r => r.json())
        .then(raw => {
            if (raw._groups) {
                groups = raw._groups;
            } else {
                groups = { einzelleistungen: [], pauschalen: [] };
            }

            const filtered = Object.fromEntries(
                Object.entries(raw || {}).filter(([key, val]) => {
                    if (key.startsWith('_')) return false;
                    if (!val || typeof val !== 'object') return false;
                    if (!val.query || typeof val.query !== 'object') return false;
                    return true;
                })
            );
            examplesData = filtered;

            if (!raw._groups) {
                for (const [id, ex] of Object.entries(examplesData)) {
                    if (ex.baseline && ex.baseline.pauschale) {
                        groups.pauschalen.push(id);
                    } else {
                        groups.einzelleistungen.push(id);
                    }
                }
            }

            exampleIdToGroup = {};
            (groups.einzelleistungen || []).forEach(id => (exampleIdToGroup[id] = 'einzelleistungen'));
            (groups.pauschalen || []).forEach(id => (exampleIdToGroup[id] = 'pauschalen'));

            buildTable();
        })
        .catch(err => {
            console.error('Beispiele konnten nicht geladen werden:', err);
        });
}

function buildTable() {
    const tbodyEinz = document.querySelector('#tableEinzelleistungen tbody');
    const tbodyPausch = document.querySelector('#tablePauschalen tbody');

    if (tbodyEinz) tbodyEinz.innerHTML = '';
    if (tbodyPausch) tbodyPausch.innerHTML = '';

    if (!Object.keys(examplesData).length) {
        updateOverallSummary();
        return;
    }

    const btnText = t('qcTestExample', currentLang);

    const createRow = id => {
        const ex = examplesData[id];
        if (!ex || !ex.query) return null;
        const text = ex.query[currentLang] || ex.query.de || Object.values(ex.query)[0] || '';
        const tr = document.createElement('tr');
        tr.dataset.exampleId = id;
        tr.innerHTML = `
            <td>${id}</td>
            <td>${text}</td>
            <td><button class="single-test-all-langs action-btn" data-id="${id}">${btnText}</button></td>
            <td id="res-${id}-de"></td>
            <td id="res-${id}-fr"></td>
            <td id="res-${id}-it"></td>
        `;
        return tr;
    };

    (groups.einzelleistungen || []).forEach(id => {
        const tr = createRow(id);
        if (tr && tbodyEinz) tbodyEinz.appendChild(tr);
    });

    (groups.pauschalen || []).forEach(id => {
        const tr = createRow(id);
        if (tr && tbodyPausch) tbodyPausch.appendChild(tr);
    });

    document.querySelectorAll('.single-test-all-langs').forEach(btn => {
        btn.addEventListener('click', () => runTestsForRow(btn.dataset.id));
    });

    updateOverallSummary();
}

function runTest(id, lang) {
    return new Promise(resolve => {
        const exampleId = Number(id);
        const idStr = String(id);
        const started = (typeof performance !== 'undefined' && performance.now) ? performance.now() : Date.now();
        fetch('/api/test-example', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ id: exampleId, lang }),
        })
            .then(r => {
                if (!r.ok) throw new Error(`HTTP error ${r.status}`);
                return r.json();
            })
            .then(res => {
                const cell = document.getElementById(`res-${id}-${lang}`);
                if (!cell) {
                    resolve({ id, lang, passed: false, error: 'Cell not found' });
                    return;
                }
                if (res.token_usage) {
                    const t1 = res.token_usage.llm_stage1 || {};
                    const t2 = res.token_usage.llm_stage2 || {};
                    tokenTotals.llm1.input += t1.input_tokens || 0;
                    tokenTotals.llm1.output += t1.output_tokens || 0;
                    tokenTotals.llm2.input += t2.input_tokens || 0;
                    tokenTotals.llm2.output += t2.output_tokens || 0;
                    updateTokenSummary();
                }
                if (res.passed) {
                    cell.textContent = t('qcPass', currentLang);
                    cell.style.color = 'green';
                    resolve({ id, lang, passed: true });
                } else {
                    cell.textContent = t('qcFail', currentLang) + (res.diff ? ': ' + res.diff : '');
                    cell.style.color = 'red';
                    resolve({ id, lang, passed: false, diff: res.diff });
                }
            })
            .catch(error => {
                const cell = document.getElementById(`res-${id}-${lang}`);
                if (cell) {
                    cell.textContent = t('qcError', currentLang);
                    cell.style.color = 'orange';
                }
                console.error(`Error testing example ${id} lang ${lang}:`, error);
                resolve({ id, lang, passed: false, error: error.message });
            })
            .finally(() => {
                const ended = (typeof performance !== 'undefined' && performance.now) ? performance.now() : Date.now();
                const durationMs = Math.max(0, ended - started);
                perfStats.durationsMs.push(durationMs);
                const groupName = exampleIdToGroup[idStr];
                if (groupName && perfStatsByGroup[groupName]) {
                    perfStatsByGroup[groupName].push(durationMs);
                }
                updatePerformanceSummary();
            });
    });
}

async function runTestsForRow(id) {
    testQueue.push(id);
    await processTestQueue();
}

function processTestQueue(isTestAll = false) {
    return new Promise(resolve => {
        if (isTesting || testQueue.length === 0) {
            if (!isTesting && testQueue.length === 0 && isTestAll) {
                const testAllBtn = document.getElementById('testAllBtn');
                const singleTestBtns = document.querySelectorAll('.single-test-all-langs');
                if (testAllBtn) testAllBtn.disabled = false;
                singleTestBtns.forEach(btn => (btn.disabled = false));
            }
            resolve();
            return;
        }
        isTesting = true;
        const id = testQueue.shift();

        const singleTestBtn = document.querySelector(`.single-test-all-langs[data-id="${id}"]`);
        if (singleTestBtn) singleTestBtn.disabled = true;

        ['de', 'fr', 'it'].forEach(lang => {
            const cell = document.getElementById(`res-${id}-${lang}`);
            if (cell) cell.textContent = '...';
        });

        (async () => {
            for (const lang of ['de', 'fr', 'it']) {
                const cell = document.getElementById(`res-${id}-${lang}`);
                if (cell) cell.textContent = t('qcTestingLang', currentLang).replace('{lang}', lang);
                await runTest(id, lang);
            }

            if (singleTestBtn && !isTestAll) singleTestBtn.disabled = false;

            isTesting = false;
            await processTestQueue(isTestAll);
            resolve();
        })();
    });
}

async function testAll() {
    const testAllBtn = document.getElementById('testAllBtn');
    const singleTestBtns = document.querySelectorAll('.single-test-all-langs');

    if (testAllBtn) testAllBtn.disabled = true;
    singleTestBtns.forEach(btn => (btn.disabled = true));

    totalTests = 0;
    passedTests = 0;
    tokenTotals = { llm1: { input: 0, output: 0 }, llm2: { input: 0, output: 0 } };
    perfStats = { durationsMs: [] };
    perfStatsByGroup = { einzelleistungen: [], pauschalen: [] };
    updateTokenSummary();
    updatePerformanceSummary();

    const exampleIds = Object.keys(examplesData);
    totalTests = exampleIds.length * 3;

    testQueue = [...exampleIds];
    await processTestQueue(true);

    const results = document.querySelectorAll('td[id^="res-"]');
    passedTests = Array.from(results).filter(cell => cell.style.color === 'green').length;

    updateOverallSummary();
}

function updateOverallSummary() {
    const summaryDiv = document.getElementById('overallSummary');
    if (!summaryDiv) return;
    if (totalTests > 0) {
        summaryDiv.textContent = t('qcSummary', currentLang)
            .replace('{passed}', passedTests)
            .replace('{total}', totalTests);
        summaryDiv.style.display = 'inline-flex';
    } else {
        summaryDiv.textContent = '';
        summaryDiv.style.display = 'none';
    }
}

function updateTokenSummary() {
    const div = document.getElementById('tokenSummary');
    if (!div) return;
    const hasTokens = tokenTotals.llm1.input || tokenTotals.llm1.output || tokenTotals.llm2.input || tokenTotals.llm2.output;
    if (!hasTokens) {
        div.textContent = '';
        div.style.display = 'none';
        return;
    }
    const line1 = t('qcTokensLlm1', currentLang)
        .replace('{in}', tokenTotals.llm1.input)
        .replace('{out}', tokenTotals.llm1.output);
    const line2 = t('qcTokensLlm2', currentLang)
        .replace('{in}', tokenTotals.llm2.input)
        .replace('{out}', tokenTotals.llm2.output);
    div.innerHTML = line1 + '<br>' + line2;
    div.style.display = 'inline-flex';
}

function percentile(values, pct) {
    if (!values.length) return 0;
    const sorted = [...values].sort((a, b) => a - b);
    const k = (sorted.length - 1) * pct;
    const f = Math.floor(k);
    const c = Math.ceil(k);
    if (f === c) return sorted[k];
    return sorted[f] + (sorted[c] - sorted[f]) * (k - f);
}

function updatePerformanceSummary() {
    const formatPerfStats = durations => {
        if (!durations.length) return '';
        const sum = durations.reduce((a, b) => a + b, 0);
        const avg = sum / durations.length;
        const median = percentile(durations, 0.5);
        const p95 = percentile(durations, 0.95);
        const max = Math.max(...durations);
        return t('qcPerfStats', currentLang)
            .replace('{avg}', avg.toFixed(0))
            .replace('{med}', median.toFixed(0))
            .replace('{p95}', p95.toFixed(0))
            .replace('{max}', max.toFixed(0));
    };

    const setText = (el, text) => {
        if (!el) return;
        if (text) {
            el.textContent = text;
            el.style.display = 'inline-flex';
        } else {
            el.textContent = '';
            el.style.display = 'none';
        }
    };

    setText(document.getElementById('perfSummary'), formatPerfStats(perfStats.durationsMs));
    setText(document.getElementById('perfEinzSummary'), formatPerfStats(perfStatsByGroup.einzelleistungen || []));
    setText(document.getElementById('perfPauschSummary'), formatPerfStats(perfStatsByGroup.pauschalen || []));
}

document.addEventListener('DOMContentLoaded', () => {
    const stored = localStorage.getItem('language');
    if (stored && ['de', 'fr', 'it'].includes(stored)) currentLang = stored;

    loadTranslations().then(() => {
        applyLanguage(currentLang);
        loadExamples();
    });

    const testAllBtn = document.getElementById('testAllBtn');
    if (testAllBtn) testAllBtn.addEventListener('click', testAll);
});
