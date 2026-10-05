import pytest
from finder.store import Store
from finder.assets import ASSET_LABELS
from finder.pipeline import readable_names
from finder.hashing import PROFILES

TYPE_PREFIX_CASES=[
    ('sndasset','sound'),('sndasset','sndasset'),('image','image'),('xanim','anim'),('xanim','xanim'),
    ('material','material'),('soundbank','sndbank'),('soundbank','soundbank'),
    ('soundbanktransient','soundbanktransient'),('soundbanktransient','sndbanktransient'),
    ('animpkg','animpkg'),('rawfile','rawfile'),('scriptfile','scriptfile'),('scriptbundle','scriptbundle'),
    ('stringtable','stringtable'),('localize','localize'),('weapon','weapon'),('attachment','attachment'),
    ('structuredtable','structuredtable'),('keyvaluepairs','keyvaluepairs'),
    ('soundbankalias','alias'),('soundbankalias','sndbankalias'),('bone','bone'),
    ('scriptfield','scriptfield'),('dvar','dvar'),('omnvar','omnvar'),
]

@pytest.mark.parametrize('extension',['json','csv'])
def test_saluki_sndbank_export_is_a_soundbank_target(tmp_path,extension):
    folder=tmp_path/'sndbanks';folder.mkdir()
    (folder/f'sndbank_123456789abcdef0.{extension}').write_bytes(b'fixture')
    with_store=Store(tmp_path/'work.sqlite')
    try:
        report=with_store.import_exported(folder,'COD2026','iw-resource63',default_kind='soundbank',kinds=['soundbank'])
        assert report['hashed_files']==1 and report['unique_assets']==1
        assert [(r['kind'],r['hash']) for r in with_store.targets()]==[('soundbank','123456789abcdef0')]
    finally:with_store.close()

@pytest.mark.parametrize('kind,prefix',TYPE_PREFIX_CASES)
@pytest.mark.parametrize('hex_text',['f1234567','0x7abc012345678901'])
def test_every_dropdown_type_imports_correctly_and_hash_is_not_a_seed(tmp_path,kind,prefix,hex_text):
    folder=tmp_path/'assets';folder.mkdir();filename=f'{prefix.upper()}_{hex_text}.json'
    (folder/filename).write_bytes(b'fixture')
    (folder/'known_asset_name.all.json').write_bytes(b'fixture')
    store=Store(tmp_path/'work.sqlite')
    try:
        report=store.import_exported(folder,'test','iw-resource63',default_kind=kind,kinds=[kind])
        assert report['hashed_files']==1 and report['recognized_files']==1
        assert report['unrecognized']==1 and report['types_filtered']==0
        row=store.targets(exclude_material=False)[0]
        assert row['kind']==kind and int(row['hash'],16)==int(hex_text,16)
        assert readable_names(folder)=={'known_asset_name.all'}
    finally:store.close()

def test_matrix_covers_all_dropdown_types():
    assert {kind for kind,prefix in TYPE_PREFIX_CASES}==set(ASSET_LABELS)

def test_generic_extension_directory_context_and_model_exclusion(tmp_path):
    root=tmp_path/'mixed';root.mkdir()
    samples=[('sndbanks/json/1111111111111111.json','soundbank'),
        ('animpkgs/2222222222222222.bin','animpkg'),('rawfiles/file_3333333333333333.bin','rawfile'),
        ('hash_4444444444444444.seanim','xanim'),('5555555555555555.sab','soundbank'),
        ('hash_6666666666666666.fbx','xmodel')]
    for filename,kind in samples:
        path=root/filename;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(b'fixture')
    store=Store(tmp_path/'work.sqlite')
    try:
        report=store.import_exported(root,'test','iw-resource63')
        assert report['hashed_files']==5 and report['models_excluded']==1
        assert {r['kind'] for r in store.targets()}=={'soundbank','animpkg','rawfile','xanim'}
    finally:store.close()

def test_filter_mismatch_error_describes_detected_type(tmp_path):
    (tmp_path/'sndbank_123456789abcdef0.json').write_bytes(b'fixture')
    store=Store(tmp_path/'work.sqlite')
    try:
        with pytest.raises(ValueError,match='soundbank: 1'):
            store.import_exported(tmp_path,'test','iw-resource63',default_kind='xanim',kinds=['xanim'])
    finally:store.close()

def test_32bit_script_hash_with_omitted_leading_zero_is_not_a_readable_name(tmp_path):
    profile=PROFILES['fnv1a32']
    name=next(n for n in (f'test_script_{i}' for i in range(100)) if profile.digest(n)<0x10000000)
    h=profile.digest(name);folder=tmp_path/'scripts';folder.mkdir()
    (folder/f'scriptfile_{h:x}.gsc').write_bytes(b'fixture')
    store=Store(tmp_path/'work.sqlite')
    try:
        result=store.import_exported(folder,'test',profile.id,default_kind='scriptfile',kinds=['scriptfile'])
        assert result['hashed_files']==1 and int(store.targets()[0]['hash'],16)==h
        assert readable_names(folder,profile.id)==set()
    finally:store.close()
