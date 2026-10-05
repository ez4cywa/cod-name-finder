import json
from pathlib import Path
import pytest
from finder.hashing import PROFILES,batch_digest
from finder.backends import CPU,GPU,devices
from finder.candidates import Plan

def test_upstream_cpp_vectors_python_rust_gpu():
    vectors=json.loads((Path(__file__).parent/'fixtures/hash-reference-vectors.json').read_text(encoding='utf-8'))
    for pid,rows in vectors.items():
        profile=PROFILES[pid];names=[r['name'] for r in rows];expected=[int(r['hash'],16) for r in rows]
        assert [profile.digest(n) for n in names]==expected,pid
        assert list(batch_digest(names,profile,3))==expected,pid
        plan=Plan([names]);targets=set(expected)
        assert CPU(plan,profile,targets).scan(0,plan.total)==list(range(plan.total)),pid
        if any('name' in d for d in devices()):
            assert GPU(plan,profile,targets).scan(0,plan.total)==list(range(plan.total)),pid

def test_sab_slash_rules_and_secure_injection():
    assert PROFILES['sab-sdbm32'].digest('A\\B')!=PROFILES['sab-sdbm32'].digest('A/B')
    assert PROFILES['sab-fnv1a64'].digest('A\\B')!=PROFILES['sab-fnv1a64'].digest('A/B')
    assert PROFILES['bo6-script64'].digest('a')!=PROFILES['bo6-sp-script64'].digest('aB')
    assert PROFILES['bo6-script64'].digest('Ab')==PROFILES['bo6-script64'].digest('ab')
