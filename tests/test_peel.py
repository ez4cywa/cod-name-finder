"""Native peeling must retain every full-forward hit and original cursor."""
from dataclasses import replace
import math

import pytest

from finder.backends import CPU
from finder.candidates import Plan
from finder.hashing import PROFILES
from finder.peeling import PeeledCPU, choose_backend, plan_cost, REVERSIBLE


def forced_quote(plan, profile, targets, split, direction):
    quote = plan_cost(plan,profile,len(targets))
    selected = next(o for o in quote['options'] if o['split']==split and o['direction']==direction)
    return {**quote,**selected,'strategy':'peeled'}


SUPPORTED = [p for p in PROFILES if PROFILES[p].algorithm in REVERSIBLE
             and PROFILES[p].mask in ((1<<32)-1,(1<<63)-1,(1<<64)-1)]


@pytest.mark.parametrize('profile_id',SUPPORTED)
@pytest.mark.parametrize('direction',['reverse-target-table','forward-head-table'])
def test_peeling_identical_to_forward_full_and_clipped(profile_id,direction):
    profile = PROFILES[profile_id]
    # Empty heads, empty ends, first multibyte UTF8 byte, ASCII case and both
    # separators, including aliases after normalization, all stay distinct idxs.
    plan = Plan([['','A\\','É','水'],['','M4_'],['','Idle','É','7'],['','\\Path','A']])
    wanted = [i for i in range(plan.total) if i%7==0 and plan.at(i)]
    targets = {profile.digest(plan.at(i)) for i in wanted}
    if profile.mask < (1<<64)-1:
        # A noncanonical target must never create a low-bit false positive.
        targets |= {h | (1 << (profile.mask.bit_length())) for h in list(targets)[:2]}
    baseline = CPU(plan,profile,targets,2)
    for split in range(1,len(plan.slots)):
        peeled = PeeledCPU(plan,profile,targets,2,forced_quote(plan,profile,targets,split,direction))
        try:
            assert peeled.scan(0,plan.total)==baseline.scan(0,plan.total)
            for base,count in [(1,1),(2,17),(23,31),(plan.total-3,3)]:
                assert peeled.scan(base,count)==baseline.scan(base,count),(profile_id,split,base)
            assert peeled.stats['equivalent_candidates']==plan.total+52
        finally:
            peeled.close()


def test_63_bit_reverse_represents_both_unknown_full64_lifts():
    profile = PROFILES['iw-resource63']
    full = replace(profile,mask=(1<<64)-1)
    plan = Plan([[f'REX_VM_AR_KILO2_{i}_' for i in range(40)],['_idle','_fire','_empty','\\É']])
    assert any(full.digest(plan.at(i))>>63 for i in range(plan.total))
    targets = {profile.digest(plan.at(i)) for i in range(0,plan.total,9)}
    peeled = PeeledCPU(plan,profile,targets,1,forced_quote(plan,profile,targets,1,'reverse-target-table'))
    try:
        assert peeled.scan(0,plan.total)==CPU(plan,profile,targets,1).scan(0,plan.total)
    finally:
        peeled.close()
    inverse = pow(profile.prime,-1,1<<64)
    for low in targets:
        a,b = low,low | (1<<63)
        for byte in b'_empty'[::-1]:
            a=((a*inverse)^byte)&((1<<64)-1)
            b=((b*inverse)^byte)&((1<<64)-1)
        assert (a&profile.mask)==(b&profile.mask)


@pytest.mark.parametrize('profile_id',['fnv1a32','prime32','djb2-xor32','sab-sdbm32','bo3-bo4-early-script32'])
def test_32_bit_wrapping_and_trailing_multiply(profile_id):
    profile = PROFILES[profile_id]
    plan=Plan([['FFFFFFFF_','\u007f'*100,'Z'*400],['a','\u007f'*300,'','\\x']])
    targets={profile.digest(plan.at(i)) for i in range(plan.total)}
    peeled=PeeledCPU(plan,profile,targets,1,forced_quote(plan,profile,targets,1,'reverse-target-table'))
    try:
        assert peeled.scan(0,plan.total)==list(range(plan.total))
    finally:
        peeled.close()


def test_exact_batch_edges_and_forward_work_statistics():
    profile=PROFILES['fnv1a64']
    plan=Plan([[str(i)+'_' for i in range(21)],[str(i) for i in range(12)]])
    targets={profile.digest(plan.at(i)) for i in range(plan.total)}
    backend=PeeledCPU(plan,profile,targets,1,forced_quote(plan,profile,targets,1,'reverse-target-table'))
    try:
        position=5
        for count in [3,11,23,40]:
            expected=((position+count-1)//12)-(position//12)+1
            assert backend.scan(position,count)==list(range(count))
            assert backend.last_stats['actual_forward_hashes']==expected
            assert backend.last_stats['equivalent_candidates']==count
            position+=count
        assert backend.scan(position,0)==[]
        with pytest.raises(ValueError):backend.scan(plan.total-1,2)
        with pytest.raises(ValueError):backend.scan(-1,1)
    finally:backend.close()


@pytest.mark.parametrize('profile_id',['kvp64','bo4-bocw-script32'])
def test_noninvertible_algorithms_keep_forward(profile_id):
    profile=PROFILES[profile_id]
    plan=Plan([['weapon_','model_'],['x','y']])
    backend,info=choose_backend('cpu',plan,profile,{profile.digest('weapon_x')},1)
    assert backend.name=='Rust CPU'
    assert info['peeling_cost']['strategy']=='forward'
    assert backend.scan(0,plan.total)==[0]
    assert backend.stats['actual_forward_hashes']==plan.total


def test_low60_and_even_multiplier_keep_forward():
    plan=Plan([[str(i) for i in range(100)],[str(i) for i in range(100)]])
    for profile in [replace(PROFILES['fnv1a64'],mask=(1<<60)-1),replace(PROFILES['fnv1a64'],prime=2)]:
        assert plan_cost(plan,profile,1)['strategy']=='forward'


def test_cost_gate_and_100x_forward_reduction_without_python_product():
    profile=PROFILES['iw-resource63']
    plan=Plan([[f'rex_vm_ar_kilo2_{i:06d}_' for i in range(2048)],
               [f'inspect_empty_{i:03d}' for i in range(256)]])
    targets={profile.digest(plan.at(i)) for i in [0,255,256,103001,plan.total-1]}
    backend,info=choose_backend('cpu',plan,profile,targets,2)
    assert isinstance(backend,PeeledCPU)
    hits=[]
    try:
        for base in range(0,plan.total,65536):
            count=min(65536,plan.total-base)
            hits += [base+i for i in backend.scan(base,count)]
        assert hits==[0,255,256,103001,plan.total-1]
        assert backend.stats['hash_ratio']>=100
        assert backend.stats['actual_forward_hashes']==2048
        assert backend.stats['equivalent_candidates']==plan.total
        assert backend.stats['reverse_steps']>0
    finally:backend.close()
    # Large target sets with tiny end choices genuinely have no saving.
    narrow=Plan([[str(i) for i in range(100)],['a','b']])
    assert plan_cost(narrow,profile,10000)['strategy']=='forward'


def test_choose_lower_memory_forward_head_index_direction():
    profile=PROFILES['fnv1a64']
    plan=Plan([['very_long_verified_family_prefix_'+str(i)+'_' for i in range(20)],
               [str(i) for i in range(2000)]])
    targets={profile.digest(plan.at(0))}
    quote=plan_cost(plan,profile,1)
    assert quote['strategy']=='peeled'
    assert quote['direction']=='forward-head-table'
    backend=PeeledCPU(plan,profile,targets,1,quote)
    try:
        assert backend.scan(0,plan.total)==[0]
        assert backend.stats['actual_forward_hashes']==20
        assert backend.stats['prepared_forward_hashes']==20
    finally:backend.close()
