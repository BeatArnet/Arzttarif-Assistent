#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Server-Integration für den Hybrid-Erkenner
=========================================

Diese Datei zeigt, wie der Hybrid-Erkenner in den bestehenden Flask-Server
integriert werden kann, um die Tarifziffern-Erkennung zu verbessern.
"""

from hybrid_recognizer import HybridRecognizer

def integrate_hybrid_recognizer(app, server_module):
    """
    Integriert den Hybrid-Erkenner in den bestehenden Flask-Server
    
    Args:
        app: Die Flask-App
        server_module: Das Server-Modul mit den bestehenden Funktionen
    """
    # Hybrid-Erkenner initialisieren
    recognizer = HybridRecognizer()
    
    # Original-Funktion für /api/analyze-billing speichern
    original_analyze_billing = server_module.analyze_billing
    
    # Neue Funktion für /api/analyze-billing definieren
    @app.route("/api/analyze-billing", methods=["POST"])
    def enhanced_analyze_billing():
        """
        Verbesserte Version der analyze_billing-Funktion, die den Hybrid-Erkenner verwendet
        """
        # Eingabedaten aus der Anfrage extrahieren (wie im Original)
        req = server_module.request.json
        if not req or not req.get("inputText"):
            return server_module.jsonify({"error": "Keine Eingabe"}), 400
        
        text = req.get("inputText", "").strip()
        icds = req.get("icd", [])
        gtins = req.get("gtin", [])
        
        # 1. Zuerst den Hybrid-Erkenner verwenden
        hybrid_result = recognizer.analyze_text(text)
        
        # 2. Wenn der Hybrid-Erkenner Tarifziffern gefunden hat, diese verwenden
        if hybrid_result["identified_leistungen"]:
            # Extrahierte Informationen für das Backend bereitstellen
            server_module.billing_context = {
                "alter": hybrid_result["extracted_info"].get("alter", 0),
                "geschlecht": hybrid_result["extracted_info"].get("geschlecht", "unbekannt"),
                "gtins": gtins
            }
            
            # LLM-Ergebnis simulieren
            llm_result = {
                "identified_leistungen": hybrid_result["identified_leistungen"],
                "extracted_info": {
                    "dauer_minuten": hybrid_result["extracted_info"].get("dauer_minuten", 0),
                    "menge": hybrid_result["extracted_info"].get("menge", 1),
                    "alter": hybrid_result["extracted_info"].get("alter", 0),
                    "geschlecht": hybrid_result["extracted_info"].get("geschlecht", "unbekannt")
                },
                "begruendung_llm": hybrid_result["begruendung_llm"]
            }
            
            # Ergebnisse verarbeiten wie im Original
            results = []
            for item in llm_result["identified_leistungen"]:
                # LKN extrahieren
                if isinstance(item, str):
                    lkn = item
                    item_menge = 1
                else:
                    lkn = item.get("lkn")
                    item_menge = item.get("menge", 1)
                
                # Typ aus Katalog bestimmen (wie im Original)
                cat = next((e for e in server_module.leistungskatalog_data if e.get("LKN") == lkn), {})
                typ_code = cat.get("Typ")
                
                if typ_code in ("P", "PZ"):
                    pausch = server_module.calculate_pauschale(lkn, item_menge, icds, llm_result["identified_leistungen"])
                    if pausch:
                        entry = {"typ": "Pauschale", "lkn": lkn, "menge": item_menge, **pausch}
                    else:
                        entry = {"typ": "Einzelleistung", "lkn": lkn, "menge": item_menge, 
                                **server_module.calculate_einzelleistung(lkn, item_menge, icds)}
                else:
                    entry = {"typ": "Einzelleistung", "lkn": lkn, "menge": item_menge, 
                            **server_module.calculate_einzelleistung(lkn, item_menge, icds)}
                
                results.append(entry)
            
            return server_module.jsonify({"llm_ergebnis": llm_result, "leistungen": results})
        
        # 3. Wenn der Hybrid-Erkenner keine Tarifziffern gefunden hat, auf das Original zurückfallen
        return original_analyze_billing()
    
    # Original-Funktion durch die verbesserte Funktion ersetzen
    server_module.analyze_billing = enhanced_analyze_billing
    
    return app

# Beispiel für die Integration
if __name__ == "__main__":
    print("Dieses Skript dient nur zur Integration und sollte nicht direkt ausgeführt werden.")
    print("Verwenden Sie stattdessen: python server.py")
