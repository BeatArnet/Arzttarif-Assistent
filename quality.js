const qcTranslations = {
    de: {title:'Qualitätskontrolle', testExample:'Beispiel testen', testAll:'Alle Beispiele testen', pass:'OK', fail:'Fehler'},
    fr: {title:'Contrôle de qualité', testExample:'Tester exemple', testAll:'Tester tous les exemples', pass:'OK', fail:'Erreur'},
    it: {title:'Controllo qualità', testExample:'Prova esempio', testAll:'Testa tutti gli esempi', pass:'OK', fail:'Errore'}
};
let examplesData = [];
let currentLang = 'de';

function applyLanguage(lang){
    currentLang = lang;
    const t = qcTranslations[lang];
    document.documentElement.lang = lang;
    document.getElementById('qcHeader').textContent = t.title;
    document.getElementById('testAllBtn').textContent = t.testAll;
    buildTable();
}

function loadExamples(){
    fetch('data/beispiele.json')
        .then(r=>r.json())
        .then(d=>{ examplesData=d; buildTable(); });
}

let totalTests = 0;
let passedTests = 0;

function buildTable(){
    const tbody = document.querySelector('#exampleTable tbody');
    if(!tbody || !examplesData.length) return;
    tbody.innerHTML='';
    const t = qcTranslations[currentLang]; // For button text, example text uses specific lang

    for(let i=1;i<examplesData.length;i++){ // Assuming example 0 is header or metadata
        const ex=examplesData[i];
        // Try to get example text in current language, fallback to DE, then first available
        const exampleTextKey = 'value_' + currentLang.toUpperCase();
        const exampleTextKeyExtended = 'extendedValue_' + currentLang.toUpperCase();
        let text = ex[exampleTextKeyExtended] || ex[exampleTextKey] || ex['extendedValue_DE'] || ex['value_DE'] || '';
        if (!text) { // Fallback to first available text if DE is also empty
            const firstValKey = Object.keys(ex).find(k => k.startsWith('value_') || k.startsWith('extendedValue_'));
            if (firstValKey) text = ex[firstValKey];
        }

        const tr=document.createElement('tr');
        tr.setAttribute('data-example-id', i);
        tr.innerHTML=`<td>${i}</td>
                      <td>${text}</td>
                      <td><button class="single-test-all-langs" data-id="${i}">${t.testExample}</button></td>
                      <td id="res-${i}-de"></td>
                      <td id="res-${i}-fr"></td>
                      <td id="res-${i}-it"></td>`;
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
            if (res.passed) {
                cell.textContent = qcTranslations[currentLang].pass;
                cell.style.color = 'green';
                resolve({ id, lang, passed: true });
            } else {
                cell.textContent = qcTranslations[currentLang].fail + (res.diff ? ': ' + res.diff : '');
                cell.style.color = 'red';
                resolve({ id, lang, passed: false, diff: res.diff });
            }
        })
        .catch(error => {
            const cell = document.getElementById(`res-${id}-${lang}`);
            if (cell) {
                cell.textContent = 'error';
                cell.style.color = 'orange';
            }
            console.error(`Error testing example ${id} lang ${lang}:`, error);
            resolve({ id, lang, passed: false, error: error.message });
        });
    });
}

async function runTestsForRow(id) {
    // Clear previous results for this row
    document.getElementById(`res-${id}-de`).textContent = '...';
    document.getElementById(`res-${id}-fr`).textContent = '...';
    document.getElementById(`res-${id}-it`).textContent = '...';

    const langs = ['de', 'fr', 'it'];
    for (const lang of langs) {
        await runTest(id, lang); // Wait for each test to complete before starting the next
    }
    // Note: Overall summary is not updated per row, only for testAll
}

async function testAll() {
    totalTests = 0;
    passedTests = 0;
    const testPromises = [];
    // examplesData[0] is often metadata or headers, actual examples start from index 1
    // or ensure examplesData is filtered to only contain actual examples.
    // Assuming examplesData[0] might be an issue if it's not a valid example.
    // Let's iterate from 1, or adjust if examplesData is 0-indexed for actual examples.
    const numExamples = examplesData.length -1; // if examples start from 1
    totalTests = numExamples * 3; // DE, FR, IT for each example

    for (let i = 1; i < examplesData.length; i++) {
        const exampleId = i; // Or examplesData[i].id if available and more robust
        document.getElementById(`res-${exampleId}-de`).textContent = '...';
        document.getElementById(`res-${exampleId}-fr`).textContent = '...';
        document.getElementById(`res-${exampleId}-it`).textContent = '...';

        testPromises.push(runTest(exampleId, 'de'));
        testPromises.push(runTest(exampleId, 'fr'));
        testPromises.push(runTest(exampleId, 'it'));
    }

    const results = await Promise.all(testPromises);
    passedTests = results.filter(r => r.passed).length;
    updateOverallSummary();
}

function updateOverallSummary() {
    const summaryDiv = document.getElementById('overallSummary');
    if (totalTests > 0) {
        summaryDiv.textContent = `Gesamt: ${passedTests} / ${totalTests} bestanden.`;
    } else {
        summaryDiv.textContent = '';
    }
}

document.getElementById('testAllBtn').addEventListener('click', testAll);

document.addEventListener('DOMContentLoaded', () => {
    const stored=localStorage.getItem('language');
    if(stored && ['de','fr','it'].includes(stored)) currentLang=stored;
    applyLanguage(currentLang);
    loadExamples();
});
