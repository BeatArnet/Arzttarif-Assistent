import json

with open('data/baseline_results.json', 'r', encoding='utf-8') as f:
    data = json.load(f)

new_data = {}
for key, value in data.items():
    new_value = {}
    new_value['query'] = value['query']
    new_value['baseline'] = value['baseline']['de']
    new_value['current'] = value['current']
    new_data[key] = new_value

with open('data/baseline_results_new.json', 'w', encoding='utf-8') as f:
    json.dump(new_data, f, indent=2, ensure_ascii=False)
