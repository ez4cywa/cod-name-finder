"""Synthetic end-to-end checks, invoked inside the isolated installer validation.

The installed worker runs with System32-only PATH and no source PYTHONPATH.
No game files, community rows or upstream snapshots are used in these cases.
"""
import csv
import hashlib
import json
from pathlib import Path
import struct

from finder.formats import decode_cdb, encode_cdb
from finder.hashing import PROFILES


def validate_upstream_features(root, execute_pipeline):
    root=Path(root);root.mkdir()
    iw=PROFILES['iw-resource63'];alias=PROFILES['fnv1a64']
    tail='.lnn.75.48000.all'
    summaries=[]

    def case(label,profile,kind,targets,tables,expected,required_methods,*,snapshot=None):
        base=root/label;base.mkdir();folder=base/'Hashed';folder.mkdir();indexes=base/'Indexes';indexes.mkdir()
        for asset_kind,name in targets:
            (folder/f'{asset_kind}_{profile.digest(name):016x}.bin').write_bytes(b'synthetic hash target')
        for table,rows in tables.items():(indexes/table).write_bytes(encode_cdb(rows))
        before={str(path):hashlib.sha256(path.read_bytes()).hexdigest() for location in (folder,indexes)
                for path in location.rglob('*') if path.is_file()}
        config={'folder':str(folder),'indexes':str(indexes),'output':str(base/'Output'),
                'profile':profile.id,'asset_type':kind,'game':'COD2026','backend':'cpu',
                'cross_asset':True,'budget':100000,'seconds':120,'number_max':0,'exclude_material':False}
        if snapshot is not None:config.update(input_mode='snapshot',snapshot_file=str(snapshot))
        config_path=base/'run.json';config_path.write_text(json.dumps(config),encoding='utf-8')
        events=[json.loads(line) for line in execute_pipeline(config_path).splitlines() if line.strip()]
        result=events[-1]['result'];assert result['status']=='completed',result
        wanted={profile.digest(name):profile.normalize(name) for name in expected}
        assert decode_cdb((Path(result['path'])/'verified.cdb').read_bytes())==wanted
        with Path(result['new_names_csv']).open(encoding='utf-8',newline='') as stream:
            assert {int(key,16):name for key,name in csv.reader(stream)}==wanted
        evidence=[json.loads(line) for line in (Path(result['path'])/'evidence.jsonl').read_text(encoding='utf-8').splitlines()]
        found_methods={row['method_id'] for row in evidence}
        assert required_methods<=found_methods,(required_methods,found_methods)
        for row in evidence:assert profile.digest(row['name'])==int(row['hash'],16)
        repeat_events=[json.loads(line) for line in execute_pipeline(config_path).splitlines() if line.strip()]
        repeat=repeat_events[-1]['result'];assert repeat['complete_cache_reused'] and repeat['processed']==0
        assert decode_cdb((Path(repeat['path'])/'verified.cdb').read_bytes())==wanted
        assert before=={str(path):hashlib.sha256(path.read_bytes()).hexdigest() for location in (folder,indexes)
                        for path in location.rglob('*') if path.is_file()}
        summaries.append({'case':label,'new_names':len(wanted),'methods':sorted(found_methods),
                          'standalone_worker':True,'incremental_csv_cdb':True,'complete_cache_reused':True,
                          'sources_unchanged':True})

    donor='iw9/family/iw9_event_a'+tail;anchor='rex/family/rex_other_01'+tail
    byte_source='rex/byte/shot_a'+tail
    case('SoundNames',iw,'sndasset',[('sndasset',anchor),('sndasset','rex/family/rex_event_a'+tail),
         ('sndasset','rex/byte/shot_z'+tail)],
         {'fnv1a_xsounds_v2.cdb':{iw.digest(donor):donor,iw.digest(anchor):anchor.replace('.','/'),
                                     iw.digest(byte_source):byte_source}},
         ['rex/family/rex_event_a'+tail,'rex/byte/shot_z'+tail],
         {'soundplans.repeated_namespace','soundbyte.final_basename_byte'})

    animation='rex_vm_ar_kilo2_reload';image='hud_rex_ar_mike4_icon';desired_image='hud_rex_ar_kilo2_icon'
    case('TypedImage',iw,'image',[('image',image),('image',desired_image)],
         {'fnv1a_ximages_v2.cdb':{iw.digest(image):image},
          'fnv1a_xanims_v2.cdb':{iw.digest(animation):animation}},[desired_image],{'typedplans.typed_weapon_slot'})

    known_alias='wfoly_ar_mike4_reload_01';desired_alias='wfoly_ar_kilo2_reload_01'
    case('AnimationAlias',alias,'soundbankalias',[('soundbankalias',known_alias),('soundbankalias',desired_alias)],
         {'fnv1a_soundbanks_aliases_v2.cdb':{alias.digest(known_alias):known_alias},
          'fnv1a_xanims_v2.cdb':{iw.digest('rex_vm_ar_mike4_reload'):'rex_vm_ar_mike4_reload',
                               iw.digest(animation):animation}},[desired_alias],{'typedplans.animation_core_alias'})

    # A tiny modern v1 capture exercises remapped pool indexes and 63-bit alias
    # vocabulary. It cannot authenticate alias output in the full-64 domain.
    capture=root/'ModernCapture';capture.mkdir();game=b'MODWAR7'
    observed='rex/foley/wfoly_rex_ar_mike4_reload_01'+tail
    missing_alias='wfoly_rex_ar_mike4_inspect';missing='rex/foley/'+missing_alias+'_01'+tail
    records=sorted([(iw.digest(observed),901),(iw.digest(missing),901),
                    (alias.digest(missing_alias)&((1<<63)-1),902)])
    ids=capture/'modern.ids';ids.write_bytes(b'CODIDS'+struct.pack('<HH',1,len(game))+game+
          struct.pack('<Q',len(records))+b''.join(struct.pack('<QH',key,pool) for key,pool in records))
    ids.with_suffix('.pools.txt').write_text('MODWAR7 -- 3 assets in 2 filled pools\n'
          'index asset type assets\n901 sound_asset 2\n902 sound_alias 1\n',encoding='utf-8')
    case('AliasFileFamily',iw,'sndasset',[],
         {'fnv1a_xsounds_v2.cdb':{iw.digest(observed):observed},
          'fnv1a_soundbanks_aliases_v2.cdb':{alias.digest(missing_alias):missing_alias}},
         [missing],{'soundplans.alias_missing_family'},snapshot=ids)
    return summaries
