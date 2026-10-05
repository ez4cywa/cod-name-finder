import csv
import json
from pathlib import Path

import pytest

from finder.exporter import export, saluki_known_keys
from finder.formats import decode_cdb, encode_cdb
from finder.hashing import PROFILES
from finder.store import Store


def test_exact_name_excludes_old_profile_and_low60_keys_in_every_output(tmp_path):
    profile=PROFILES['iw-resource63']
    names=['same_key_and_name','same_key_other_name','old_profile_name',
        'low60_existing_name','empty_old_name','weapons_rifle_fire','name_case']
    entries={profile.digest(name):name for name in names}
    hashes={name:h for h,name in entries.items()}
    assert hashes['low60_existing_name']>((1<<60)-1)
    store=Store(tmp_path/'work.sqlite')
    try:
        for h,name in entries.items():
            store.db.execute('INSERT INTO assets VALUES (?,?,?)',('xanim',f'{h:016x}','fixture'))
            store.add_evidence(h,name,profile.id,'fixture','test','discovered',{})
        store.db.commit()
        indexes=tmp_path/'saluki/hash_pkg';indexes.mkdir(parents=True)
        legacy={hashes['same_key_and_name']:'same_key_and_name',
            hashes['same_key_other_name']:'different_existing_name',
            PROFILES['fnv1a63'].digest('old_profile_name'):'old_profile_name',
            hashes['low60_existing_name']&((1<<60)-1):'low60_existing_name',
            hashes['empty_old_name']:'',
            17:'weapons/rifle/fire',18:'NAME_CASE'}
        first=encode_cdb(legacy,allow_existing_names=True)
        (indexes/'first.cdb').write_bytes(first)
        second=encode_cdb({19:'old_profile_name',hashes['same_key_and_name']:'same_key_and_name'})
        nested=indexes/'nested';nested.mkdir();(nested/'second.cdb').write_bytes(second)

        # The original API remains a full-key-only check.
        key_only,sources=saluki_known_keys(indexes,set(entries))
        assert key_only=={hashes['same_key_and_name'],hashes['same_key_other_name']}
        assert len(sources)==2
        excluded,_=saluki_known_keys(indexes,set(entries),entries=entries)
        assert excluded=={hashes[name] for name in names[:4]}

        report=export(store,tmp_path/'exports',kinds=['xanim'],saluki_dir=indexes.parent)
        assert report['excluded_saluki_existing_keys']==4
        assert report['saluki_exclusion_counts']=={
            'by_key':2,'by_name':3,'both':1,'key_only':1,'name_only':2,'total':4}
        expected={hashes[name]:name for name in names[4:]}
        folder=Path(report['path'])
        assert decode_cdb((folder/'verified.cdb').read_bytes())==expected
        assert decode_cdb((folder/'hash_pkg/fnv1a_xanims_v2.cdb').read_bytes())==expected
        with (folder/'verified.csv').open(encoding='utf-8',newline='') as file:
            assert {int(h,16):name for h,name in csv.reader(file)}==expected
        evidence=[json.loads(line) for line in (folder/'evidence.jsonl').read_text(encoding='utf-8').splitlines()]
        assert {row['name'] for row in evidence}==set(expected.values())
        manifest=json.loads((folder/'manifest.json').read_text(encoding='utf-8'))
        assert manifest['saluki_exclusion_counts']==report['saluki_exclusion_counts']
        assert (indexes/'first.cdb').read_bytes()==first
        assert (nested/'second.cdb').read_bytes()==second
    finally:
        store.close()


def test_name_match_keeps_literal_text_and_does_not_truncate_target(tmp_path):
    folder=tmp_path/'indexes';folder.mkdir()
    target=0x123456789abcdef0
    (folder/'names.cdb').write_bytes(encode_cdb({
        target&((1<<60)-1):'different_name',
        1:'weapons/rifle/fire',2:'Weapons_Rifle_Fire',3:' exact_name ',4:'',5:'   ',6:'exact_name'},
        allow_existing_names=True))
    entries={target:'unrelated_name',7:'weapons_rifle_fire',8:'weapons/rifle/fire',
        9:'exact_name',4:'empty_index_name',5:'whitespace_index_name'}
    excluded,_=saluki_known_keys(folder,set(entries),entries=entries)
    assert excluded=={8,9}
    # An entry outside the selected target set never becomes an excluded target.
    excluded,_=saluki_known_keys(folder,{target},entries=entries)
    assert excluded==set()


def test_unreadable_index_fails_closed_even_after_matching_every_target(tmp_path,monkeypatch):
    folder=tmp_path/'indexes';folder.mkdir()
    (folder/'first.cdb').write_bytes(encode_cdb({1:'known_name'}))
    (folder/'later.cdb').write_bytes(encode_cdb({2:'another_name'}))
    original=Path.read_bytes
    def read(path):
        if path.name=='later.cdb':raise OSError('fixture read failure')
        return original(path)
    monkeypatch.setattr(Path,'read_bytes',read)
    with pytest.raises(ValueError,match='索引读取失败.*later.cdb'):
        saluki_known_keys(folder,{1},entries={1:'known_name'})
