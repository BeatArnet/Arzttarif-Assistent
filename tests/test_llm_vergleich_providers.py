import os
import sys
import types
import importlib
import llm_vergleich


def test_load_server_sets_stage_specific_env(monkeypatch):
    dummy = types.SimpleNamespace()
    monkeypatch.setitem(sys.modules, 'server', dummy)
    reloaded = object()
    monkeypatch.setattr(importlib, 'reload', lambda m: reloaded)

    srv = llm_vergleich.load_server('prov1', 'model1', 'prov2', 'model2')
    assert os.environ['STAGE1_LLM_PROVIDER'] == 'prov1'
    assert os.environ['STAGE1_LLM_MODEL'] == 'model1'
    assert os.environ['STAGE2_LLM_PROVIDER'] == 'prov2'
    assert os.environ['STAGE2_LLM_MODEL'] == 'model2'
    assert srv is reloaded
