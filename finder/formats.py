"""Independent implementation of PNDB/LZ4 name index format; never masks keys."""
import csv
import struct
from pathlib import Path
import lz4.block

MAX_RAW = 512 * 1024 * 1024

def encode_cdb(entries,allow_existing_names=False):
    entries = sorted(entries.items(), key=lambda pair: (pair[1], pair[0]))
    raw = bytearray()
    for h, name in entries:
        if not 0 <= h < 1 << 64 or '\x00' in name or (not allow_existing_names and (not name or any(c in name for c in '\r\n'))):
            raise ValueError('无效 CDB 键或名称')
        raw.extend(name.encode('utf-8') + b'\x00')
    raw.extend(b''.join(struct.pack('<Q', h) for h, _ in entries))
    if len(raw) > MAX_RAW:
        raise ValueError('CDB 超过 512MiB 限制，请分批导出')
    compressed = lz4.block.compress(bytes(raw), store_size=False)
    return struct.pack('<4sIII', b'PNDB', len(entries), len(compressed), len(raw)) + compressed

def decode_cdb(blob):
    if len(blob) < 16:
        raise ValueError('CDB 头部损坏')
    magic, count, packed, size = struct.unpack_from('<4sIII', blob)
    if magic != b'PNDB' or len(blob) != packed + 16 or size > MAX_RAW or count > size // 9:
        raise ValueError('CDB 格式或长度无效')
    if count == 0:
        if size != 0:
            raise ValueError('空 CDB 载荷无效')
        return {}
    raw = lz4.block.decompress(blob[16:], uncompressed_size=size)
    if len(raw) != size:
        raise ValueError('CDB 解压长度不符')
    pos = 0
    names = []
    for _ in range(count):
        end = raw.index(0, pos)
        names.append(raw[pos:end].decode('utf-8'))
        pos = end + 1
    if len(raw) - pos != count * 8:
        raise ValueError('CDB 名称/键数组长度不符')
    keys = struct.unpack_from(f'<{count}Q', raw, pos)
    if len(set(keys)) != count:
        raise ValueError('CDB 重复键')
    return dict(zip(keys, names))

def iter_dictionary(path):
    from .hashing import parse_hash
    path = Path(path)
    if path.suffix.lower() == '.cdb':
        yield from decode_cdb(path.read_bytes()).items()
    elif path.suffix.lower() == '.wni':
        blob = path.read_bytes()
        if len(blob) < 18:
            raise ValueError('WNI 头部损坏')
        magic, version, n, packed, size = struct.unpack_from('<4sHIII', blob)
        if magic != b'WNI ' or version != 1 or len(blob) != packed + 18 or size > MAX_RAW:
            raise ValueError('WNI 格式无效')
        raw = lz4.block.decompress(blob[18:], uncompressed_size=size)
        pos = 0
        for _ in range(n):
            h = struct.unpack_from('<Q', raw, pos)[0]
            pos += 8
            end = raw.index(0, pos)
            yield h, raw[pos:end].decode('utf-8')
            pos = end + 1
        if pos != len(raw):
            raise ValueError('WNI 尾部异常')
    else:
        with path.open(encoding='utf-8-sig', newline='') as f:
            for row in csv.reader(f):
                if not row:
                    continue
                try:
                    if len(row) != 2:
                        raise ValueError('需两列')
                    yield parse_hash(row[0]), row[1]
                except ValueError as e:
                    yield None, str(e)
