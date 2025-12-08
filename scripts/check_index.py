"""Quick sanity check for key DOM hooks in `index.html`."""

from pathlib import Path

from bs4 import BeautifulSoup


def main() -> None:
    project_root = Path(__file__).resolve().parents[1]
    index_path = project_root / "index.html"
    try:
        content = index_path.read_text(encoding="utf-8")
    except Exception as exc:
        print(f"Error reading {index_path.name}: {exc}")
        return

    soup = BeautifulSoup(content, "html.parser")
    print(f"app-shell found: {bool(soup.find(class_='app-shell'))}")
    print(f"top-info found: {bool(soup.find(class_='top-info'))}")


if __name__ == "__main__":
    main()
