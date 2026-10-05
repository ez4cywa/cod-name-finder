import json
from pathlib import Path
import re
import pytest
from finder.hashing import ALGORITHMS, BUILTIN_IDS, PROFILES, batch_digest, native
import ctypes
from finder.registry import GAME_DOMAINS, REGISTRY_SHA256, table_rule, validate_domain
from finder.generated_registry import ALGORITHMS as METADATA, OPENCL_DEFINES
from finder.backends import CPU, GPU, devices, KERNEL
from finder.candidates import Plan
from scripts.generate_hash_registry import generate, validate

ROOT = Path(__file__).resolve().parents[1]


def test_generated_registry_is_up_to_date_and_runtime_source_independent():
    generate(check=True)
    data = json.loads((ROOT / 'docs/hash-registry.json').read_text(encoding='utf-8'))
    assert BUILTIN_IDS == {p['id'] for p in data['profiles']}
    assert all(ALGORITHMS[n] == d['native_id'] == d['opencl_id'] for n, d in METADATA.items())
    assert re.fullmatch('[0-9a-f]{64}', REGISTRY_SHA256)
    assert 'docs/' not in (ROOT / 'finder/registry.py').read_text(encoding='utf-8')
    assert 'Path(' not in (ROOT / 'finder/generated_registry.py').read_text(encoding='utf-8')
    for row in data['profiles']:
        assert PROFILES[row['id']].json() == {k: row[k] for k in PROFILES[row['id']].json()}
    assert 'GeneratedRegistry.ProfileIds' in (ROOT / 'dotnet/CODNameFinder.Core/HashProfiles.cs').read_text()


def test_dispatch_constants_come_from_single_registry():
    assert KERNEL.startswith(OPENCL_DEFINES)
    assert not re.search(r'alg==\d', KERNEL)
    rust = (ROOT / 'native/src/registry_generated.rs').read_text()
    native = (ROOT / 'native/src/lib.rs').read_text()
    assert 'registry_generated' in native
    for name, entry in METADATA.items():
        symbol = 'ALG_' + name.upper().replace('-', '_')
        assert f'{symbol}: u32 = {entry["native_id"]};' in rust
        assert f'#define {symbol} {entry["opencl_id"]}' in KERNEL
        assert symbol in native


def test_native_library_runtime_registry_fingerprint():
    library = native()
    assert ctypes.string_at(library.hash_registry_sha256(), library.hash_registry_sha256_len()).decode() == REGISTRY_SHA256


def test_cod2026_evidence_domains_and_unknown_symbol_gating():
    for kind in ('xanim', 'image', 'material', 'animpkg', 'soundbank', 'sndasset', 'scriptfile'):
        assert validate_domain('COD2026', 'iw-resource63', kind)['status'] == 'evidence'
    assert validate_domain('COD2026', 'fnv1a64', 'soundbankalias')['profile'] == 'fnv1a64'
    with pytest.raises(ValueError, match='不匹配'):
        validate_domain('COD2026', 'iw-resource63', 'soundbankalias')
    with pytest.raises(ValueError, match='不匹配'):
        validate_domain('COD2026', 'fnv1a64', 'asset')
    for domain, profile in [('script', 'bo6-script64'), ('dvar', 'iw-dvar64'), ('omnvar', 'bo6-omnvar64')]:
        with pytest.raises(ValueError, match='尚未证实'):
            validate_domain('COD2026', profile, domain)
        assert validate_domain('COD2026', profile, domain, allow_unverified=True)['requires_calibration']
        with pytest.raises(ValueError, match='尚未证实'):
            validate_domain('COD2026', profile)
    assert 'fnv1a63' not in GAME_DOMAINS['COD2026'].values()
    assert all('Dvar' not in d for d in GAME_DOMAINS['COD2026'])
    assert validate_domain('COD2026', 'fnv1a63')['requires_calibration']
    assert validate_domain('', 'fnv1a64-raw')['status'] == 'candidate'


def test_per_table_masks_and_normalization_are_distinct():
    assert table_rule('fnv1a_strings.csv')['profile'] == 'fnv1a60'
    assert table_rule('fnv1a_bones.csv')['profile'] == 'fnv1a32'
    assert table_rule('fnv1a_bones_v2.csv')['profile'] == 'fnv1a64'
    assert table_rule('fnv1a_soundbanks_aliases_v2.csv')['profile'] == 'fnv1a64'
    assert table_rule('fnv1a_soundbanks_v2.csv')['profile'] == 'iw-resource63'
    assert table_rule('fnv1a_english_xsounds.csv')['profile'] == 'fnv1a63'
    assert table_rule('bo2_ipak.csv')['profile'] is None
    assert PROFILES['fnv1a60'].mask == (1 << 60) - 1
    assert PROFILES['fnv1a63-no-fold'].digest('A\\B') != PROFILES['fnv1a63'].digest('A\\B')


def test_invalid_registry_does_not_generate_unknown_defaults():
    data = json.loads((ROOT / 'docs/hash-registry.json').read_text(encoding='utf-8'))
    data['domains']['COD2026'][-1]['profile'] = 'bo6-omnvar64'
    with pytest.raises(ValueError, match='Unknown domain'):
        validate(data)


def test_synthetic_table_vectors_python_rust_opencl_consistent():
    # Committed goldens come from the independent MIT C++ reference, not PROFILES.
    fixture = json.loads((ROOT / 'tests/fixtures/community-table-vectors.json').read_text(encoding='utf-8'))
    assert fixture['synthetic'] is True
    assert len(fixture['tables']) == 11
    assert sum(len(t['rows']) for t in fixture['tables']) == 220
    assert 'commit' not in fixture
    for table in fixture['tables']:
        assert table_rule(table['table'] + '.csv')['profile'] == table['profile']
        assert 'source_sha256' not in table
        assert all('source_row' not in row and 'nf_fixture' in row['name'].lower() for row in table['rows'])
        rows = table['rows']
        assert len(rows) >= 20
        p = PROFILES[table['profile']]
        names, keys = [r['name'] for r in rows], [int(r['hash'], 16) for r in rows]
        assert [p.digest(n) for n in names] == keys
        assert list(batch_digest(names, p, 3)) == keys
        plan = Plan([names])
        assert CPU(plan, p, set(keys), 3).scan(0, plan.total) == list(range(plan.total))
        if any('name' in d for d in devices()):
            assert GPU(plan, p, set(keys), 3).scan(0, plan.total) == list(range(plan.total))

