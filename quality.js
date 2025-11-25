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
    if(!translations[lang]) lang='de';
    return (translations[lang] && translations[lang][key]) || translations.de[key] || key;
}

let examplesData = [];
let currentLang = 'de';

let tokenTotals = {
    llm1: { input: 0, output: 0 },
    llm2: { input: 0, output: 0 }
};
let perfStats = { durationsMs: [] };

function applyLanguage(lang){
    currentLang = lang;
    document.documentElement.lang = lang;
    document.getElementById('qcHeader').textContent = t('qcTitle', lang);
    document.getElementById('testAllBtn').textContent = t('qcTestAll', lang);
    document.getElementById('qcId').textContent = t('qcColId', lang);
    document.getElementById('qcExample').textContent = t('qcColExample', lang);
    document.getElementById('qcAction').textContent = t('qcColAction', lang);
    document.getElementById('qcResDe').textContent = t('qcColResDe', lang);
    document.getElementById('qcResFr').textContent = t('qcColResFr', lang);
    document.getElementById('qcResIt').textContent = t('qcColResIt', lang);
    buildTable();
    updateTokenSummary();
    updatePerformanceSummary();
}

function loadExamples(){
    fetch('data/baseline_results.json')
        .then(r=>r.json())
        .then(d=>{ examplesData=d; buildTable(); });
}

let totalTests = 0;
let passedTests = 0;

function buildTable(){
    const tbody = document.querySelector('#exampleTable tbody');
    if(!tbody || !Object.keys(examplesData).length) return;
    tbody.innerHTML='';
    const btnText = t('qcTestExample', currentLang);

    for(const [id, ex] of Object.entries(examplesData)){
        // Try to get example text in current language, fallback to DE, then first available
        let text = ex.query[currentLang] || ex.query['de'] || Object.values(ex.query)[0] || '';

        const tr=document.createElement('tr');
        tr.setAttribute('data-example-id', id);
        tr.innerHTML=`<td>${id}</td>
                      <td>${text}</td>
                      <td><button class="single-test-all-langs" data-id="${id}">${btnText}</button></td>
                      <td id="res-${id}-de"></td>
                      <td id="res-${id}-fr"></td>
                      <td id="res-${id}-it"></td>`;
        tbody.appendChild(tr);
    }
    document.querySelectorAll('.single-test-all-langs').forEach(btn => {
        btn.addEventListener('click', () => runTestsForRow(btn.dataset.id));
    });
    updateOverallSummary();
}

function runTest(id, lang) {
    return new Promise((resolve) => {
        const exampleId = parseInt(id);
        const started = (typeof performance !== 'undefined' && performance.now) ? performance.now() : Date.now();
        fetch('/api/test-example', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ id: exampleId, lang: lang })
        })
        .then(r => {
            if (!r.ok) {
                throw new Error(`HTTP error ${r.status}`);
            }
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
            updatePerformanceSummary();
        });
    });
}

let testQueue = [];
let isTesting = false;

async function runTestsForRow(id) {
    testQueue.push(id);
    processTestQueue();
}

function processTestQueue(isTestAll = false) {
    return new Promise(resolve => {
        if (isTesting || testQueue.length === 0) {
            if (!isTesting && testQueue.length === 0) {
                if (isTestAll) {
                    const testAllBtn = document.getElementById('testAllBtn');
                    const singleTestBtns = document.querySelectorAll('.single-test-all-langs');
                    testAllBtn.disabled = false;
                    singleTestBtns.forEach(btn => btn.disabled = false);
                }
            }
            resolve();
            return;
        }
        isTesting = true;
        const id = testQueue.shift();

        const singleTestBtn = document.querySelector(`.single-test-all-langs[data-id="${id}"]`);
        if(singleTestBtn) singleTestBtn.disabled = true;

        // Clear previous results for this row
        document.getElementById(`res-${id}-de`).textContent = '...';
        document.getElementById(`res-${id}-fr`).textContent = '...';
        document.getElementById(`res-${id}-it`).textContent = '...';

        const langs = ['de', 'fr', 'it'];
        (async () => {
            for (const lang of langs) {
                const cell = document.getElementById(`res-${id}-${lang}`);
                if(cell) cell.textContent = t('qcTestingLang', currentLang).replace('{lang}', lang);
                await runTest(id, lang); // Wait for each test to complete before starting the next
            }

            if(singleTestBtn && !isTestAll) singleTestBtn.disabled = false;

            isTesting = false;
            await processTestQueue(isTestAll);
            resolve();
        })();
    });
}

async function testAll() {
    const testAllBtn = document.getElementById('testAllBtn');
    const singleTestBtns = document.querySelectorAll('.single-test-all-langs');

    testAllBtn.disabled = true;
    singleTestBtns.forEach(btn => btn.disabled = true);

    totalTests = 0;
    passedTests = 0;
    tokenTotals = { llm1: { input: 0, output: 0 }, llm2: { input: 0, output: 0 } };
    perfStats = { durationsMs: [] };
    updateTokenSummary();
    updatePerformanceSummary();

    const exampleIds = Object.keys(examplesData);
    totalTests = exampleIds.length * 3;

    for (const exampleId of exampleIds) {
        testQueue.push(exampleId);
    }
    await processTestQueue(true);

    // After all tests are run, count the passed tests
    const results = document.querySelectorAll('td[id^="res-"]');
    passedTests = Array.from(results).filter(cell => cell.style.color === 'green').length;

    updateOverallSummary();
}

function updateOverallSummary() {
    const summaryDiv = document.getElementById('overallSummary');
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

function percentile(values, pct){
    if(!values.length) return 0;
    const sorted=[...values].sort((a,b)=>a-b);
    const k=(sorted.length-1)*pct;
    const f=Math.floor(k);
    const c=Math.ceil(k);
    if(f===c) return sorted[k];
    return sorted[f]+(sorted[c]-sorted[f])*(k-f);
}

function updatePerformanceSummary(){
    const div=document.getElementById('perfSummary');
    if(!div) return;
    if(!perfStats.durationsMs.length){
        div.textContent='';
        div.style.display='none';
        return;
    }
    const durations=perfStats.durationsMs;
    const sum=durations.reduce((a,b)=>a+b,0);
    const avg=sum/durations.length;
    const median=percentile(durations,0.5);
    const p95=percentile(durations,0.95);
    const max=Math.max(...durations);
    div.textContent = t('qcPerfStats', currentLang)
        .replace('{avg}', avg.toFixed(0))
        .replace('{med}', median.toFixed(0))
        .replace('{p95}', p95.toFixed(0))
        .replace('{max}', max.toFixed(0));
    div.style.display='inline-flex';
}

document.getElementById('testAllBtn').addEventListener('click', testAll);

document.addEventListener('DOMContentLoaded', () => {
    const stored=localStorage.getItem('language');
    if(stored && ['de','fr','it'].includes(stored)) currentLang=stored;
    loadTranslations().then(() => {
        applyLanguage(currentLang);
        loadExamples();
    });
});
