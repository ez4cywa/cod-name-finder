"""Bundled Python worker for the Avalonia application; no GUI toolkit required."""
import sys
from finder.__main__ import main, _configure_stdio

if __name__ == '__main__':
    if len(sys.argv)<2 or sys.argv[1] not in ('run','estimate','methods','table-audit','community','devices','cordycep'):
        _configure_stdio()
        print('{"event":"error","message":"后台核心命令无效"}')
        raise SystemExit(2)
    raise SystemExit(main())
