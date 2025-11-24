from bs4 import BeautifulSoup
try:
    with open('index.html', 'r', encoding='utf-8') as f:
        content = f.read()
    soup = BeautifulSoup(content, 'html.parser')
    print(f"app-shell found: {bool(soup.find(class_='app-shell'))}")
    print(f"top-info found: {bool(soup.find(class_='top-info'))}")
except Exception as e:
    print(f"Error: {e}")
