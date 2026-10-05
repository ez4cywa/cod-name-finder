"""Bounded native meet-in-the-middle search, independent of upstream code.

No target top bit is guessed.  The low 63-bit ring represents both 64-bit
lifts exactly.  Truncated 60-bit evidence deliberately keeps the forward path.
"""
import ctypes
import math
import time
import weakref

import numpy as np

from .backends import CPU, choose_backend as choose_forward_backend
from .hashing import ALGORITHMS, native

REVERSIBLE = frozenset(('fnv', 't7-script', 'secure', 'suffix', 'prime32', 'djb2xor'))
MAX_TABLE_ENTRIES = 2_000_000
SCAN_SIZE = 65536


def plan_cost(plan, profile, target_count):
    """Quote every safe slot split with byte work and an explicit memory bound.

    Estimates are primitive byte operations, not equivalent candidate hashes.
    They do not assert a measured CPU speed.  All widths retain the original
    mixed-radix indices and neither side splits a UTF-8 byte sequence.
    """
    total = plan.total
    reason = ''
    if profile.algorithm not in REVERSIBLE:
        reason = 'algorithm has a noninvertible finalizer'
    elif profile.prime % 2 == 0:
        reason = 'even multiplier has no modular inverse'
    elif profile.mask not in ((1 << 32)-1, (1 << 63)-1, (1 << 64)-1):
        reason = 'truncated/unsupported mask uses forward verification'
    elif profile.algorithm in ('prime32','djb2xor') and profile.mask != (1 << 32)-1:
        reason = '32-bit arithmetic requires its full 32-bit comparison domain'
    elif len(plan.slots) < 2:
        reason = 'a literal list has no independent suffix slots'
    elif target_count <= 0:
        reason = 'empty target set'
    # All registered normalization is ASCII case/slash replacement, which
    # preserves UTF8 byte lengths. Avoid a second normalization pass over large
    # vocabularies during quoting; CPU packing performs the authoritative pass.
    lengths = [sum(len(v.encode('utf-8')) for v in slot)/len(slot) for slot in plan.slots]
    secret_length = len(profile.secret)
    finalize = (secret_length if profile.algorithm == 'suffix' else int(profile.algorithm == 't7-script'))
    full_bytes = sum(lengths) + finalize + (secret_length if profile.algorithm == 'secure' else 0)
    forward_work = total * max(full_bytes, 1)
    quote = {'strategy': 'forward', 'equivalent_candidates': total,
             'estimated_forward_hashes': total, 'forward_byte_operations': forward_work,
             'reason': reason, 'options': []}
    if reason:
        return quote
    for split in range(1, len(plan.slots)):
        heads = math.prod(len(s) for s in plan.slots[:split])
        tails = total // heads
        prefix_bytes = sum(lengths[:split])
        suffix_bytes = sum(lengths[split:]) + finalize
        empty_heads = profile.algorithm == 'secure' and all('' in s for s in plan.slots[:split])
        variant_count = 2 if empty_heads else 1
        if profile.algorithm == 'secure':
            prefix_bytes += secret_length
            if empty_heads:
                suffix_bytes += secret_length / 2
        # Each head crossing a scan edge is rehashed once on the tail-table path.
        head_passes = heads + math.ceil(total/SCAN_SIZE) - 1
        reverse_queries = tails * target_count * variant_count
        tail_entries = reverse_queries
        tail_cost = head_passes * max(prefix_bytes, 1) + reverse_queries * max(suffix_bytes, 1)
        if tail_entries <= MAX_TABLE_ENTRIES:
            quote['options'].append({'split': split, 'direction': 'reverse-target-table',
                'heads': heads, 'tails': tails, 'table_entries_upper_bound': tail_entries,
                'estimated_forward_hashes': head_passes, 'estimated_reverse_queries': reverse_queries,
                'estimated_byte_operations': tail_cost,
                'fixed_byte_operations':reverse_queries*max(suffix_bytes,1),
                'scan_byte_operations':head_passes*max(prefix_bytes,1),
                'prefix_mean_bytes':max(prefix_bytes,1),'suffix_mean_bytes':max(suffix_bytes,1),
                'empty_head_variant': empty_heads})
        # An indexed head table saves forward work but clipped calls can revisit
        # tail queries; include that repetition instead of quoting an ideal pass.
        head_reverse_queries = min(total, math.ceil(total/SCAN_SIZE)*min(tails,SCAN_SIZE+1))*target_count*variant_count
        head_cost = heads * max(prefix_bytes, 1) + head_reverse_queries * max(suffix_bytes, 1)
        if heads <= MAX_TABLE_ENTRIES:
            quote['options'].append({'split': split, 'direction': 'forward-head-table',
                'heads': heads, 'tails': tails, 'table_entries_upper_bound': heads,
                'estimated_forward_hashes': heads, 'estimated_reverse_queries': head_reverse_queries,
                'estimated_byte_operations': head_cost,
                'fixed_byte_operations':heads*max(prefix_bytes,1),
                'scan_byte_operations':head_reverse_queries*max(suffix_bytes,1),
                'prefix_mean_bytes':max(prefix_bytes,1),'suffix_mean_bytes':max(suffix_bytes,1),
                'target_variants':target_count*variant_count,'empty_head_variant': empty_heads})
    eligible = [o for o in quote['options'] if o['estimated_byte_operations']*2 < forward_work
                and o['estimated_forward_hashes']*2 < total]
    if not eligible:
        quote['reason'] = 'no bounded split predicts at least a twofold work saving'
        return quote
    best = min(eligible, key=lambda o: (o['estimated_byte_operations'], o['table_entries_upper_bound']))
    quote.update(best)
    quote['strategy'] = 'peeled'
    quote['estimated_hash_ratio'] = total/max(best['estimated_forward_hashes'],1)
    return quote


def _api():
    library = native()
    if getattr(library, '_peeling_initialized', False):
        return library
    u8p = ctypes.POINTER(ctypes.c_uint8)
    u32p = ctypes.POINTER(ctypes.c_uint32)
    u64p = ctypes.POINTER(ctypes.c_uint64)
    library.hash_peel_new.argtypes = [u8p,u32p,ctypes.c_size_t,u32p,u32p,ctypes.c_size_t,
        ctypes.c_size_t,ctypes.c_uint32,ctypes.c_uint64,ctypes.c_uint64,ctypes.c_uint64,
        ctypes.c_uint32,u8p,ctypes.c_size_t,u64p,ctypes.c_size_t,u64p]
    library.hash_peel_new.restype = ctypes.c_void_p
    library.hash_peel_scan.argtypes = [ctypes.c_void_p,ctypes.c_uint64,ctypes.c_size_t,u8p,u64p]
    library.hash_peel_scan.restype = None
    library.hash_peel_free.argtypes = [ctypes.c_void_p]
    library.hash_peel_free.restype = None
    library._peeling_initialized = True
    return library


def _ptr(array, kind):
    return array.ctypes.data_as(ctypes.POINTER(kind))


class PeeledCPU(CPU):
    name = 'Rust CPU · suffix peeling'

    def __init__(self, plan, profile, targets, threads=0, quote=None):
        super().__init__(plan,profile,targets,threads)
        self.total = plan.total
        self.quote = quote or plan_cost(plan,profile,len(targets))
        if self.quote['strategy'] != 'peeled':
            raise ValueError('当前规则没有安全且划算的反向剥离方案')
        library = _api()
        counts = np.zeros(3,dtype=np.uint64)
        self._owner = library.hash_peel_new(_ptr(self.data,ctypes.c_uint8),_ptr(self.offsets,ctypes.c_uint32),
            len(self.offsets)-1,_ptr(self.starts,ctypes.c_uint32),_ptr(self.radices,ctypes.c_uint32),
            len(self.radices),self.quote['split'],int(self.quote['direction']=='forward-head-table'),
            profile.seed,profile.prime,profile.mask,ALGORITHMS[profile.algorithm],
            _ptr(self.secret,ctypes.c_uint8),len(profile.secret),_ptr(self.targets,ctypes.c_uint64),
            len(self.targets),_ptr(counts,ctypes.c_uint64))
        if not self._owner:
            raise ValueError('原生剥离准备拒绝了不可逆参数或超限组合表')
        self._finalizer = weakref.finalize(self,library.hash_peel_free,self._owner)
        self.stats = {'execution_mode':'peeled','profile_id':profile.id,'mask_used':profile.mask,'equivalent_candidates':0,
            'actual_forward_hashes':int(counts[0]),'prepared_forward_hashes':int(counts[0]),
            'reverse_steps':int(counts[1]),'table_entries':int(counts[2]),'hash_ratio':0.0,
            'split':self.quote['split'],'direction':self.quote['direction']}
        self.last_stats = {}

    def scan(self, base, count):
        if self._owner is None:
            raise RuntimeError('剥离引擎已关闭')
        if base < 0 or count < 0 or base+count > self.total:
            raise ValueError('剥离批次超出原规则组合范围')
        if not count:
            self.last_stats = {'equivalent_candidates':0,'actual_forward_hashes':0,'reverse_steps':0}
            return []
        flags = np.zeros(count,dtype=np.uint8)
        counts = np.zeros(3,dtype=np.uint64)
        _api().hash_peel_scan(self._owner,base,count,_ptr(flags,ctypes.c_uint8),_ptr(counts,ctypes.c_uint64))
        self.last_stats = {'equivalent_candidates':count,'actual_forward_hashes':int(counts[0]),
                           'reverse_steps':int(counts[1])}
        for key,value in self.last_stats.items():
            self.stats[key] += value
        self.stats['hash_ratio'] = self.stats['equivalent_candidates']/max(self.stats['actual_forward_hashes'],1)
        return np.flatnonzero(flags).tolist()

    def close(self):
        self._finalizer()
        self._owner = None


def _count_forward(backend,calibration_hashes=0):
    """Retain CPU/GPU type identity and its existing independent self-test."""
    original = backend.scan
    backend.stats = {'execution_mode':'forward','profile_id':backend.profile.id,
                     'mask_used':backend.profile.mask,'equivalent_candidates':0,
                     'actual_forward_hashes':calibration_hashes,
                     'calibration_forward_hashes':calibration_hashes,'reverse_steps':0,'hash_ratio':1.0}
    backend.last_stats = {}
    def scan(base,count):
        hits = original(base,count)
        backend.last_stats = {'equivalent_candidates':count,'actual_forward_hashes':count,'reverse_steps':0}
        for key,value in backend.last_stats.items():
            backend.stats[key] += value
        backend.stats['hash_ratio']=backend.stats['equivalent_candidates']/max(backend.stats['actual_forward_hashes'],1)
        return hits
    backend.scan = scan
    return backend


def forward_backend(plan,profile,targets,threads=0):
    """Counted CPU fallback; an already-failed peel/GPU is never retried."""
    return _count_forward(CPU(plan,profile,targets,threads))


def choose_backend(mode, plan, profile, targets, threads=0, device_index=0):
    quote = plan_cost(plan,profile,len(targets))
    if mode != 'gpu' and quote['strategy'] == 'peeled':
        tick = time.perf_counter()
        try:
            peeled = PeeledCPU(plan,profile,targets,threads,quote)
            return peeled, {'selected':peeled.name,'execution_mode':'peeled',
                'preparation_seconds':time.perf_counter()-tick,'peeling_cost':quote,
                'counts_include_preparation':True}
        except (AttributeError,ValueError,OSError) as error:
            quote['fallback'] = str(error)
    backend,info = choose_forward_backend(mode,plan,profile,targets,threads,device_index)
    info['peeling_cost'] = quote
    info['execution_mode'] = 'forward'
    if mode == 'gpu' and quote['strategy'] == 'peeled':
        info['reason'] = 'explicit GPU selection keeps device forward hashing and CPU verification'
    return _count_forward(backend,info.get('successful_calibration_forward_hashes',0)),info
