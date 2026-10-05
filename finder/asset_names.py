"""One filename grammar shared by importing, candidate seeds and validation."""
from pathlib import Path
import re
from typing import NamedTuple
from .assets import ASSET_LABELS

PREFIX_TYPES={kind:kind for kind in (*ASSET_LABELS,'xmodel')}
PREFIX_TYPES.update({
    'anim':'xanim','model':'xmodel','sound':'sndasset','xsound':'sndasset',
    'ximage':'image','xmaterial':'material','sndbank':'soundbank',
    'sndbanktransient':'soundbanktransient','sndbank_transient':'soundbanktransient',
    'alias':'soundbankalias','sndbankalias':'soundbankalias','bones':'bone',
})
# Accept the explicit x-prefixed spelling and Saluki's shortened spelling.
for kind in ASSET_LABELS:
    if not kind.startswith('x'):PREFIX_TYPES.setdefault('x'+kind,kind)

GENERIC_PREFIXES=('asset','hash','file')
_PREFIX='|'.join(re.escape(p) for p in sorted((*PREFIX_TYPES,*GENERIC_PREFIXES),key=len,reverse=True))
_PATTERN=re.compile(r'^(?:(?P<kind>'+_PREFIX+r')_)?(?:0x)?(?P<hash>[0-9a-f]{1,16})(?:$|[_.])',re.I)
EXTENSION_TYPES={
    '.wav':'sndasset','.flac':'sndasset','.ogg':'sndasset','.mp3':'sndasset','.opus':'sndasset',
    '.dds':'image','.png':'image','.tga':'image','.tif':'image','.tiff':'image','.bmp':'image',
    '.jpg':'image','.jpeg':'image','.iwi':'image',
    '.xanim':'xanim','.xanim_export':'xanim','.xanim_bin':'xanim','.seanim':'xanim',
    '.fbx':'xmodel','.obj':'xmodel','.xmodel':'xmodel','.xmodel_export':'xmodel','.xmodel_bin':'xmodel','.semodel':'xmodel',
    '.sab':'soundbank','.sabl':'soundbank','.sabs':'soundbank',
}
DIRECTORY_TYPES={**PREFIX_TYPES,
    'animations':'xanim','anims':'xanim','models':'xmodel','sounds':'sndasset','audio':'sndasset',
    'images':'image','materials':'material','sndbanks':'soundbank','soundbanks':'soundbank',
    'animpkgs':'animpkg','rawfiles':'rawfile','scriptfiles':'scriptfile',
    'scriptbundles':'scriptbundle','stringtables':'stringtable','weapons':'weapon',
    'attachments':'attachment','structuredtables':'structuredtable',
}

class ExportedName(NamedTuple):
    kind: str
    hash: int

def parse_exported_name(path,default_kind='sndasset',root=None,min_digits=8):
    """Parse only a filename key; ambiguous JSON/CSV/CAST uses context or choice."""
    path=Path(path);match=_PATTERN.match(path.name)
    if not match or len(match.group('hash'))<min_digits:return None
    prefix=(match.group('kind') or '').lower()
    kind=PREFIX_TYPES.get(prefix)
    if not kind:kind=EXTENSION_TYPES.get(path.suffix.lower())
    if not kind and root is not None:
        root=Path(root)
        try:
            relative=path.relative_to(root)
            directories=(root.name,*relative.parts[:-1])
            kind=next((DIRECTORY_TYPES[p.lower()] for p in reversed(directories) if p.lower() in DIRECTORY_TYPES),None)
        except ValueError:pass
    return ExportedName(kind or default_kind,int(match.group('hash'),16))
