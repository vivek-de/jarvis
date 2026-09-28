"""Phase 8 — document intelligence: parse → embed/store → retrieval-augmented QA.

Import submodules directly (backend.docs.parser / .store / .qa). This package __init__
stays empty on purpose so importing the pure-stdlib parser/qa never drags in psycopg.
"""
