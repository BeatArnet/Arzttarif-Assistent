#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Hybrid-Erkenner für TARDOC-Tarifziffern
=======================================

Dieser Erkenner kombiniert:
1. Regelbasierte Erkennung mit Mapping-Tabellen
2. Keyword-basierte Extraktion
3. Semantische Suche als Fallback

Dadurch wird die Genauigkeit der Tarifziffern-Erkennung verbessert,
insbesondere für häufige medizinische Eingriffe.
"""

import json
import re
import os
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple, Set, Union

class HybridRecognizer:
    """Hybrid-Erkenner für TARDOC-Tarifziffern"""
    
    def __init__(self, data_dir: str = "data"):
        """Initialisiert den Hybrid-Erkenner mit Mapping-Tabellen"""
        self.data_dir = Path(data_dir)
        self.mappings = self._load_mappings()
        self.keywords = self._extract_all_keywords()
        
    def _load_mappings(self) -> Dict[str, Any]:
        """Lädt die Mapping-Tabellen aus der JSON-Datei"""
        # Versuche Mapping-Tabelle im angegebenen Verzeichnis
        mapping_file = self.data_dir / "medical_mappings.json"
        if mapping_file.is_file():
            with open(mapping_file, "r", encoding="utf-8") as f:
                return json.load(f)
        # Fallback: Mapping-Tabelle im Skript-Verzeichnis suchen
        script_dir = Path(__file__).parent
        fallback_file = script_dir / "medical_mappings.json"
        if fallback_file.is_file():
            with open(fallback_file, "r", encoding="utf-8") as f:
                return json.load(f)
        # Keine Mapping-Datei gefunden
        print(f"⚠️ Mapping-Tabelle nicht gefunden in {mapping_file} oder {fallback_file}. Erstelle leere Tabelle.")
        return {}
        
    def _extract_all_keywords(self) -> Dict[str, Set[str]]:
        """Extrahiert alle Keywords aus den Mapping-Tabellen für schnelle Suche"""
        keywords = {
            "varianten": set(),
            "körperregionen": set(),
            "methoden": set(),
            "zusatz": set()
        }
        
        for entry_key, entry in self.mappings.items():
            for category in ["varianten", "körperregionen", "methoden", "zusatz"]:
                if category in entry:
                    for keyword in entry[category]:
                        keywords[category].add(keyword.lower())
        
        return keywords
    
    def analyze_text(self, text: str) -> Dict[str, Any]:
        """
        Analysiert den Text und gibt erkannte Tarifziffern zurück
        
        Args:
            text: Der zu analysierende Text
            
        Returns:
            Dict mit erkannten Tarifziffern und extrahierten Informationen
        """
        # Text normalisieren
        text_lower = text.lower()
        # Unterstütze mehrere Leistungen getrennt mit "und"/"oder"
        # Teile den Text in Segmente und wertet jedes Segment separat aus
        segments = re.split(r'\s*\b(?:und|oder)\b\s*', text_lower)
        if len(segments) > 1:
            all_identified: List[Dict[str, Any]] = []
            explanations: List[str] = []
            # Kontextinformationen (z.B. Alter, Geschlecht) aus dem gesamten Text extrahieren
            overall_info = self._extract_info(text_lower)
            for seg in segments:
                seg = seg.strip(" ,.")
                if not seg:
                    continue
                # Einzelnes Segment analysieren
                seg_info = self._extract_info(seg)
                seg_result = self._apply_mappings(seg, seg_info)
                if seg_result.get("identified_leistungen"):
                    all_identified.extend(seg_result["identified_leistungen"])
                    explanations.append(seg_result.get("begruendung_llm", ""))
            # Kombiniertes Ergebnis zurückgeben
            return {
                "identified_leistungen": all_identified,
                "extracted_info": overall_info,
                "begruendung_llm": " ".join(explanations)
            }
        
        # 1. Extrahiere strukturierte Informationen
        extracted_info = self._extract_info(text_lower)
        
        # 2. Regelbasierte Erkennung mit Mapping-Tabellen
        mapping_results = self._apply_mappings(text_lower, extracted_info)
        
        # 3. Wenn Mapping-Ergebnisse vorhanden, diese zurückgeben
        if mapping_results["identified_leistungen"]:
            return mapping_results
        
        # 4. Fallback: Leere Ergebnisse zurückgeben (würde in der Praxis zur semantischen Suche führen)
        return {
            "identified_leistungen": [],
            "extracted_info": extracted_info,
            "begruendung_llm": "Keine passenden Tarifziffern in den Mapping-Tabellen gefunden."
        }
    
    def _extract_info(self, text: str) -> Dict[str, Any]:
        """Extrahiert strukturierte Informationen aus dem Text"""
        info = {
            "dauer_minuten": 0,
            "menge": 1,
            "alter": 0,
            "geschlecht": "unbekannt",
            "eingriff": "",
            "körperregion": "",
            "methode": ""
        }
        
        # Dauer extrahieren (z.B. "10 Minuten", "15 Min", "5'" für Minuten)
        # Akzeptiert ausgeschrieben, abgekürzt mit/ohne Punkt oder als Apostroph/Prime
        duration_match = re.search(r"(\d+)\s*(?:minuten|min(?:\.)?|['’′])", text)
        if duration_match:
            info["dauer_minuten"] = int(duration_match.group(1))
        
        # Alter extrahieren (z.B. "42-jährige", "Patient 65 Jahre")
        age_match = re.search(r'(\d+)[\s-]*(?:jährige|jahre|jahr|j\.)', text)
        if age_match:
            info["alter"] = int(age_match.group(1))
        
        # Geschlecht extrahieren
        if re.search(r'\b(?:frau|patientin|weiblich)\b', text):
            info["geschlecht"] = "weiblich"
        elif re.search(r'\b(?:mann|patient|männlich)\b', text) and not re.search(r'\bpatientin\b', text):
            info["geschlecht"] = "männlich"
        
        # Eingriff, Körperregion und Methode durch Keyword-Matching
        for category, keywords in self.keywords.items():
            for keyword in keywords:
                if keyword in text:
                    if category == "varianten":
                        info["eingriff"] = keyword
                    elif category == "körperregionen":
                        info["körperregion"] = keyword
                    elif category == "methoden":
                        info["methode"] = keyword
        
        return info
    
    def _apply_mappings(self, text: str, extracted_info: Dict[str, Any]) -> Dict[str, Any]:
        """Wendet die Mapping-Tabellen auf den Text an"""
        result = {
            "identified_leistungen": [],
            "extracted_info": extracted_info,
            "begruendung_llm": ""
        }
        
        # Bewertung für jedes Mapping berechnen
        mapping_scores = {}
        for mapping_key, mapping in self.mappings.items():
            score = self._calculate_mapping_score(text, mapping, extracted_info)
            if score > 0:
                mapping_scores[mapping_key] = score
        
        # Wenn keine Mappings gefunden wurden, leere Ergebnisse zurückgeben
        if not mapping_scores:
            return result
        
        # Bestes Mapping auswählen
        best_mapping_key = max(mapping_scores, key=mapping_scores.get)
        best_mapping = self.mappings[best_mapping_key]
        
        # Tarifziffern aus dem besten Mapping extrahieren
        for tarif in best_mapping["tarifziffern"]:
            code = tarif["code"]
            menge = tarif["menge"]
            
            # Wenn Menge ein String ist (z.B. "DAUER_IN_MIN / 5"), berechnen
            if isinstance(menge, str) and "DAUER_IN_MIN" in menge:
                if extracted_info["dauer_minuten"] > 0:
                    # Formel auswerten (z.B. "DAUER_IN_MIN / 5")
                    formula = menge.replace("DAUER_IN_MIN", str(extracted_info["dauer_minuten"]))
                    try:
                        menge = max(1, int(eval(formula)))
                    except:
                        menge = 1
                else:
                    menge = 1
            
            result["identified_leistungen"].append({
                "lkn": code,
                "menge": menge
            })
        
        # Begründung erstellen
        result["begruendung_llm"] = self._generate_explanation(best_mapping_key, best_mapping, extracted_info)
        
        return result
    
    def _calculate_mapping_score(self, text: str, mapping: Dict[str, Any], info: Dict[str, Any]) -> float:
        """Berechnet einen Score für die Übereinstimmung eines Mappings mit dem Text"""
        score = 0.0
        
        # Prüfe Varianten (Eingriff)
        if "varianten" in mapping:
            for variant in mapping["varianten"]:
                if variant in text:
                    score += 3.0
                    break
        
        # Prüfe Körperregionen
        if "körperregionen" in mapping:
            for region in mapping["körperregionen"]:
                if region in text:
                    score += 2.0
                    break
        
        # Prüfe Methoden
        if "methoden" in mapping:
            for method in mapping["methoden"]:
                if method in text:
                    score += 2.0
                    break
        
        # Prüfe Zusatz (z.B. "hausärztlich")
        if "zusatz" in mapping:
            for zusatz in mapping["zusatz"]:
                if zusatz in text:
                    score += 1.5
                    break
        
        return score
    
    def _generate_explanation(self, mapping_key: str, mapping: Dict[str, Any], info: Dict[str, Any]) -> str:
        """Generiert eine Erklärung für die erkannten Tarifziffern"""
        # Mapping-Key für bessere Lesbarkeit formatieren
        readable_key = mapping_key.replace("_", " ").capitalize()
        
        # Tarifziffern für die Erklärung formatieren
        tarif_codes = [f"{t['code']} {t['menge']}x" for t in mapping["tarifziffern"]]
        tarif_str = ", ".join(tarif_codes)
        
        # Erklärung generieren
        explanation = f"Erkannt: {readable_key}. "
        
        if info["körperregion"]:
            explanation += f"Körperregion: {info['körperregion']}. "
        
        if info["methode"]:
            explanation += f"Methode: {info['methode']}. "
        
        if info["dauer_minuten"] > 0:
            explanation += f"Dauer: {info['dauer_minuten']} Minuten. "
        
        explanation += f"Empfohlene Tarifziffern: {tarif_str}"
        
        return explanation


# Wenn direkt ausgeführt, Beispiel demonstrieren
if __name__ == "__main__":
    recognizer = HybridRecognizer()
    
    # Beispiel-Texte
    test_texts = [
        "Entfernung Warze am Oberkörper mit scharfem Löffel und 10 Minuten Information Patienten",
        "Hausärztliche Konsultation von 17 Minuten",
        "Kiefergelenk, Luxation. Geschlossene Reposition",
        "Aufklärung des Patienten und Leberbiopsie durch die Haut",
        "Blinddarmentfernung als alleinige Leistung",
        "Korrektur eines Hallux valgus rechts",
        "Konsultation 10 Minuten und Entfernung einer gestielten Warze am Stamm"
    ]
    
    # Jeden Text analysieren und Ergebnisse ausgeben
    for text in test_texts:
        print(f"\n--- Analyse für: '{text}' ---")
        result = recognizer.analyze_text(text)
        
        print("Extrahierte Informationen:")
        for key, value in result["extracted_info"].items():
            print(f"  {key}: {value}")
        
        print("\nErkannte Tarifziffern:")
        if result["identified_leistungen"]:
            for leistung in result["identified_leistungen"]:
                print(f"  {leistung['lkn']} {leistung['menge']}x")
        else:
            print("  Keine Tarifziffern erkannt")
        
        print("\nBegründung:")
        print(f"  {result['begruendung_llm']}")
        print("-" * 50)
