#!/usr/bin/env python3
"""
Verify BlackBar Phase 1 Setup
Checks if all dependencies are installed correctly.
"""

import sys

def check_presidio():
    """Check if Presidio is installed and working."""
    try:
        from presidio_analyzer import AnalyzerEngine
        from presidio_analyzer.nlp_engine import NlpEngineProvider
        print("✅ Presidio analyzer installed")
        
        # Try to create analyzer
        configuration = {
            "nlp_engine_name": "spacy",
            "models": [{"lang_code": "en", "model_name": "en_core_web_lg"}]
        }
        provider = NlpEngineProvider(nlp_configuration=configuration)
        nlp_engine = provider.create_engine()
        analyzer = AnalyzerEngine(nlp_engine=nlp_engine)
        print("✅ Presidio analyzer initialized successfully")
        return True
    except ImportError:
        print("❌ Presidio not installed")
        print("   Fix: pip install presidio-analyzer presidio-anonymizer")
        return False
    except Exception as e:
        print(f"❌ Presidio error: {e}")
        if "en_core_web_lg" in str(e):
            print("   Fix: python -m spacy download en_core_web_lg")
        return False

def check_spacy():
    """Check if spaCy and model are installed."""
    try:
        import spacy
        print("✅ spaCy installed")
        
        try:
            nlp = spacy.load("en_core_web_lg")
            print("✅ spaCy model 'en_core_web_lg' loaded")
            return True
        except OSError:
            print("❌ spaCy model 'en_core_web_lg' not found")
            print("   Fix: python -m spacy download en_core_web_lg")
            return False
    except ImportError:
        print("❌ spaCy not installed")
        print("   Fix: pip install spacy")
        return False

def check_other_deps():
    """Check other critical dependencies."""
    deps = [
        ("fastapi", "FastAPI"),
        ("pymongo", "PyMongo"),
        ("pymupdf", "PyMuPDF"),
        ("pytesseract", "pytesseract"),
        ("openai", "OpenAI"),
    ]
    
    all_ok = True
    for module, name in deps:
        try:
            __import__(module)
            print(f"✅ {name} installed")
        except ImportError:
            print(f"❌ {name} not installed")
            all_ok = False
    
    return all_ok

def check_ocr_binary():
    """Check if Tesseract OCR binary is available."""
    import subprocess
    try:
        result = subprocess.run(
            ["tesseract", "--version"],
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode == 0:
            version = result.stdout.split('\n')[0]
            print(f"✅ Tesseract OCR installed: {version}")
            return True
        else:
            print("❌ Tesseract OCR not working")
            return False
    except FileNotFoundError:
        print("❌ Tesseract OCR not installed")
        print("   Fix: apt-get install tesseract-ocr (Linux)")
        print("        brew install tesseract (Mac)")
        return False
    except Exception as e:
        print(f"⚠️  Could not check Tesseract: {e}")
        return None

def test_pii_detection():
    """Test PII detection functionality."""
    try:
        from src.utils.pii_detection import detect_pii, map_presidio_to_category
        
        # Test detection
        test_text = "My phone number is 604-555-1234 and my email is john@example.com"
        results = detect_pii(test_text)
        
        if len(results) >= 2:
            print(f"✅ PII detection working ({len(results)} entities found)")
            
            # Test category mapping
            for result in results[:2]:
                category = map_presidio_to_category(result['type'])
                print(f"   - {result['type']} → {category}")
            return True
        else:
            print("⚠️  PII detection found fewer entities than expected")
            return None
    except Exception as e:
        print(f"❌ PII detection test failed: {e}")
        return False

def test_ocr_enhancement():
    """Test OCR enhancement is present."""
    try:
        from src.utils.ocr import extract_text_with_coordinates
        print("✅ Enhanced OCR module imported")
        
        # Check if function signature is correct (async)
        import inspect
        if inspect.iscoroutinefunction(extract_text_with_coordinates):
            print("✅ OCR function is async")
            return True
        else:
            print("⚠️  OCR function is not async (may be old version)")
            return None
    except Exception as e:
        print(f"❌ OCR module test failed: {e}")
        return False

def main():
    """Run all checks."""
    print("=" * 60)
    print("BlackBar Phase 1 Setup Verification")
    print("=" * 60)
    print()
    
    print("Checking Python dependencies...")
    print("-" * 60)
    
    checks = [
        ("Core Dependencies", check_other_deps),
        ("spaCy", check_spacy),
        ("Presidio", check_presidio),
        ("Tesseract OCR", check_ocr_binary),
        ("PII Detection", test_pii_detection),
        ("Enhanced OCR", test_ocr_enhancement),
    ]
    
    results = []
    for name, check_func in checks:
        print()
        result = check_func()
        results.append((name, result))
    
    print()
    print("=" * 60)
    print("Summary")
    print("=" * 60)
    
    passed = sum(1 for _, r in results if r is True)
    failed = sum(1 for _, r in results if r is False)
    warnings = sum(1 for _, r in results if r is None)
    
    for name, result in results:
        if result is True:
            status = "✅ PASS"
        elif result is False:
            status = "❌ FAIL"
        else:
            status = "⚠️  WARN"
        print(f"{status} - {name}")
    
    print()
    print(f"Results: {passed} passed, {failed} failed, {warnings} warnings")
    
    if failed > 0:
        print()
        print("⚠️  Some checks failed. Please fix the issues above.")
        sys.exit(1)
    elif warnings > 0:
        print()
        print("⚠️  Some checks have warnings. Review above for details.")
        sys.exit(0)
    else:
        print()
        print("🎉 All checks passed! You're ready to go.")
        sys.exit(0)

if __name__ == "__main__":
    main()
