"""Explicit hash profiles; source profiles and target profiles remain separate."""
from dataclasses import dataclass, asdict
import ctypes
import os
from pathlib import Path
import sys
from .registry import PROFILE_DATA, PROFILE_CONFIG_KEYS, ALGORITHM_IDS
from .generated_registry import REGISTRY_SHA256

MASK64 = (1 << 64) - 1

@dataclass(frozen=True)
class Profile:
    id: str
    seed: int
    mask: int
    ascii_lower: bool = True
    slash: bool = True
    prime: int = 0x100000001b3
    algorithm: str = 'fnv'
    secret: str = ''

    def normalize(self, name):
        if not name or any(c in name for c in '\x00\r\n'):
            raise ValueError('名称为空或包含 NUL/换行')
        if self.slash:
            name = name.replace('\\', '/')
        if self.ascii_lower:
            name = name.translate(str.maketrans('ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'))
        return name

    def digest(self, name):
        data=self.normalize(name).encode('utf-8')
        h = self.seed
        if self.algorithm=='secure':data=data[:1]+self.secret.encode('ascii')+data[1:]
        if self.algorithm=='suffix':data+=self.secret.encode('ascii')
        if self.algorithm=='bo4-script':
            for byte in data:
                v=(h+byte)&0xffffffff
                mixed=(v^((v<<10)&0xffffffff))&0xffffffff
                h=(mixed+(mixed>>6))&0xffffffff
            v=(9*h)&0xffffffff
            return (0x8001*(v^(v>>11)))&self.mask
        if self.algorithm in ('prime32','djb2xor'):
            for byte in data:
                h=((self.prime*h+byte) if self.algorithm=='prime32' else (self.prime*h)^byte)&0xffffffff
            return h&self.mask
        if self.algorithm=='kvp':
            for i,byte in enumerate(data):h=(h+(self.prime+i)*byte)&MASK64
            return (h^((h^(h>>10))>>10))&self.mask
        for byte in data:
            h = ((h ^ byte) * self.prime) & MASK64
        if self.algorithm=='t7-script':h=(h*self.prime)&MASK64
        return h & self.mask

    def json(self):
        return asdict(self)

PROFILES = {row['id']: Profile(**{k: row[k] for k in PROFILE_CONFIG_KEYS}) for row in PROFILE_DATA}
ALGORITHMS = ALGORITHM_IDS
BUILTIN_IDS=frozenset(PROFILES)

def parse_hash(value):
    value = str(value).strip().lower().removeprefix('0x')
    if not 1 <= len(value) <= 16 or any(c not in '0123456789abcdef' for c in value):
        raise ValueError('哈希须为 1–16 位十六进制')
    return int(value, 16)

def native_path():
    root = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parents[1]))
    return root / 'finder_native.dll'

_library = None
def native():
    global _library
    if _library is None:
        path = native_path()
        if not path.exists():
            path = Path(__file__).resolve().parents[1] / 'native/target/release/finder_native.dll'
        library = ctypes.CDLL(str(path))
        u8p = ctypes.POINTER(ctypes.c_uint8)
        u32p = ctypes.POINTER(ctypes.c_uint32)
        u64p = ctypes.POINTER(ctypes.c_uint64)
        try:
            library.hash_registry_sha256.argtypes = []
            library.hash_registry_sha256.restype = u8p
            library.hash_registry_sha256_len.argtypes = []
            library.hash_registry_sha256_len.restype = ctypes.c_size_t
            loaded = ctypes.string_at(library.hash_registry_sha256(), library.hash_registry_sha256_len()).decode('ascii')
        except AttributeError as error:
            raise RuntimeError('本机计算引擎版本过旧，请重新安装完整发布包或重新构建 native 引擎') from error
        if loaded != REGISTRY_SHA256:
            raise RuntimeError('Python 与本机计算引擎算法注册表不一致，请重新安装完整发布包或重新构建 native 引擎')
        library.hash_batch.argtypes = [u8p, u32p, ctypes.c_size_t, ctypes.c_uint64,
            ctypes.c_uint64, ctypes.c_uint64, ctypes.c_uint32,u8p,ctypes.c_size_t,u64p,ctypes.c_size_t]
        library.hash_batch.restype = None
        library.hash_combinations.argtypes = [u8p, u32p, ctypes.c_size_t, u32p, u32p,
            ctypes.c_size_t, ctypes.c_uint64, ctypes.c_size_t, ctypes.c_uint64,
            ctypes.c_uint64,ctypes.c_uint64,ctypes.c_uint32,u8p,ctypes.c_size_t,
            u64p, ctypes.c_size_t, u8p, ctypes.c_size_t]
        library.hash_combinations.restype = None
        _library = library
    return _library

def pack(names):
    import numpy as np
    offsets = [0]
    data = bytearray()
    for name in names:
        data.extend(name.encode('utf-8'))
        offsets.append(len(data))
    if len(data) >= (1 << 32):
        raise ValueError('批次字符串超过 4GiB')
    return np.frombuffer(bytes(data) or b'\x00', dtype=np.uint8), np.array(offsets, dtype=np.uint32)

def batch_digest(names, profile, threads=0):
    import numpy as np
    normalized = [profile.normalize(n) for n in names]
    if not names:
        return []
    data, offsets = pack(normalized)
    out = np.empty(len(names), dtype=np.uint64)
    secret=np.frombuffer(profile.secret.encode('ascii') or b'\0',dtype=np.uint8)
    native().hash_batch(data.ctypes.data_as(ctypes.POINTER(ctypes.c_uint8)),
        offsets.ctypes.data_as(ctypes.POINTER(ctypes.c_uint32)), len(names),
        profile.seed,profile.prime, profile.mask,ALGORITHMS[profile.algorithm],
        secret.ctypes.data_as(ctypes.POINTER(ctypes.c_uint8)),len(profile.secret),
        out.ctypes.data_as(ctypes.POINTER(ctypes.c_uint64)),
        threads or max(1, (os.cpu_count() or 2) // 2))
    return out
