import argparse,json,sys
from pathlib import Path

def _configure_stdio():
    # GUI workers read UTF-8 pipes, independently of the Windows console code
    # page, locale, or an inherited PYTHONIOENCODING setting.
    for stream in (sys.stdout,sys.stderr):
        if stream is not None and hasattr(stream,'reconfigure'):
            stream.reconfigure(encoding='utf-8',errors='backslashreplace',line_buffering=True)

def _dispatch(argv,context):
    parser=argparse.ArgumentParser(description='COD Name Finder 一键名称查找')
    parser.add_argument('--work',help=argparse.SUPPRESS)
    sub=parser.add_subparsers(dest='command',metavar='{gui,run,estimate,cordycep,methods,table-audit,community,upstream,tutorial,devices}')
    sub.add_parser('gui');sub.add_parser('tutorial');sub.add_parser('devices')
    run=sub.add_parser('run',help='读取一键配置并完成查找和增量导出');run.add_argument('config');run.add_argument('--control',help=argparse.SUPPRESS)
    run.add_argument('--estimate',action='store_true',help='只显示候选空间、碰撞期望与时间估计')
    run.add_argument('--anyway',action='store_true',help='显式覆盖连续零新增的方法守卫')
    quote=sub.add_parser('estimate',help='只估算，不执行查找');quote.add_argument('config');quote.add_argument('--control',help=argparse.SUPPRESS)
    methods=sub.add_parser('methods',help='方法产率与耗尽报告');methods.add_argument('action',choices=['report']);methods.add_argument('output',help='运行输出根目录或账本文件')
    audit=sub.add_parser('table-audit',help='逐表回算鉴定哈希规则');audit.add_argument('folder');audit.add_argument('--profile',action='append');audit.add_argument('--filter');audit.add_argument('--sample-limit',type=int)
    community=sub.add_parser('community',help='显式只读同步或导入社区表');community.add_argument('action',choices=['sync','import']);community.add_argument('folder');community.add_argument('--refresh',action='store_true');community.add_argument('--profile');community.add_argument('--borrowed',action='store_true');community.add_argument('--output')
    upstream=sub.add_parser('upstream',help='预览并按用户选择提交上游名称贡献 PR')
    upstream.add_argument('action',choices=['auth-status','auth-save','auth-clear','prepare','submit'])
    upstream.add_argument('--export');upstream.add_argument('--package')
    upstream.add_argument('--offline',action='store_true',help='仅离线生成预览，不读取凭据或访问网络；只用于 prepare')
    upstream.add_argument('--stdin',action='store_true',help='从标准输入读取凭据 JSON；Token 不放在参数中')
    loader=sub.add_parser('cordycep',help='只读捕获已加载的 Cordycep 或启动所选本地作品');loader.add_argument('action',choices=['status','capture','scripts'])
    loader.add_argument('--directory',required=True);loader.add_argument('--game',choices=['COD2026','BO7'],default='COD2026')
    loader.add_argument('--output');loader.add_argument('--pid',type=int);loader.add_argument('--launch',action='store_true');loader.add_argument('--script',help='运行所选目录根下的 BAT 文件');loader.add_argument('--load-all',action='store_true');loader.add_argument('--control',help=argparse.SUPPRESS)
    worker=sub.add_parser('worker',help=argparse.SUPPRESS);worker.add_argument('task');worker.add_argument('control')
    shot=sub.add_parser('screenshot',help=argparse.SUPPRESS);shot.add_argument('path');shot.add_argument('--tutorial',action='store_true')
    args=parser.parse_args(argv)
    context['command']=args.command or 'gui'
    if args.command in (None,'gui','tutorial','screenshot'):
        from .gui import main as gui_main
        return gui_main(getattr(args,'path',None),tutorial=args.command=='tutorial' or getattr(args,'tutorial',False))
    if args.command=='devices':
        from .backends import devices
        print(json.dumps(devices(),ensure_ascii=False));return 0
    if args.command=='upstream':
        from .upstream import authentication,prepare,submit
        if args.offline and args.action!='prepare':raise ValueError('--offline 仅适用于 prepare')
        credentials={}
        if args.stdin:
            raw=sys.stdin.read(8193)
            if len(raw)>8192:raise ValueError('GitHub 凭据输入过大')
            credentials=json.loads(raw)
            if not isinstance(credentials,dict) or set(credentials)-{'token','remember_token'}:
                raise ValueError('GitHub 凭据须为允许字段组成的 JSON 对象')
            if not isinstance(credentials.get('token',''),str) or not isinstance(credentials.get('remember_token',False),bool):
                raise ValueError('GitHub 凭据字段类型无效')
        token=credentials.get('token') or None
        progress=lambda n,m:print(json.dumps({'event':'progress','processed':n,'message':m},ensure_ascii=False),flush=True)
        if args.action.startswith('auth-'):
            result=authentication(args.action,token)
        else:
            if not args.offline and credentials.get('remember_token') and token:authentication('auth-save',token)
            if args.action=='prepare':
                if not args.export:raise ValueError('请选择本次完整导出目录')
                result=prepare(args.export,token=token,offline=args.offline,progress=progress)
            else:
                package=args.package
                if not package and args.export:package=prepare(args.export,token=token,progress=progress)['package_dir']
                if not package:raise ValueError('请先预览本次提交')
                result=submit(package,token=token,progress=progress)
        print(json.dumps(result,ensure_ascii=False),flush=True);return 0
    if args.command=='cordycep':
        from .cordycep import discover,capture,startup_scripts
        if args.action=='scripts':
            print(json.dumps(startup_scripts(args.directory),ensure_ascii=False));return 0
        if args.action=='status':
            print(json.dumps(discover(args.directory,args.pid),ensure_ascii=False));return 0
        if not args.output:raise ValueError('请选择捕获快照输出目录')
        if args.load_all and not args.launch:raise ValueError('loadall 仅用于本软件新启动的加载器；现有实例请先自行完成加载')
        control=(lambda:Path(args.control).read_text(encoding='utf-8').strip()) if args.control else (lambda:'run')
        progress=lambda n,m:print(json.dumps({'event':'progress','processed':n,'message':m},ensure_ascii=False),flush=True)
        result=capture(args.directory,args.game,args.output,args.pid,args.launch,args.load_all,progress,control,script=args.script)
        print(json.dumps({'event':'result','result':result},ensure_ascii=False),flush=True);return 0
    if args.command=='methods':
        from .methods import SharedLedger
        root=Path(args.output);path=root if root.suffix in ('.sqlite','.db') else root/'.namefinder-ledger.sqlite'
        if not path.is_file():raise ValueError('所选输出目录没有方法账本，请先完成一次运行')
        with SharedLedger(path,readonly=True) as ledger:result=ledger.report()
        print(json.dumps(result,ensure_ascii=False));return 0
    if args.command=='table-audit':
        from .tableaudit import audit_tables
        result=audit_tables(args.folder,profiles=args.profile,name_filter=args.filter,sample_limit=args.sample_limit)
        print(json.dumps(result,ensure_ascii=False));return 0
    if args.command=='community':
        from .community import sync_community,import_community
        result=sync_community(args.folder,enabled=True,refresh=args.refresh) if args.action=='sync' else import_community(
            args.folder,selected_profile=args.profile,borrowed=args.borrowed,output_dir=args.output)
        print(json.dumps(result,ensure_ascii=False));return 0
    if args.command=='worker':
        if not args.work:raise ValueError('后台任务缺少工作数据库路径')
        from .engine import run_task
        result=run_task(args.work,args.task,lambda n,m:print(json.dumps({'position':n,'message':m},ensure_ascii=False),flush=True),lambda:Path(args.control).read_text(encoding='utf-8').strip())
        print(json.dumps(result,ensure_ascii=False));return 0
    from .pipeline import run as run_pipeline
    context['config_file']=str(Path(args.config).resolve())
    config=json.loads(Path(args.config).read_text(encoding='utf-8'))
    if not isinstance(config,dict):raise ValueError('运行配置必须是 JSON 对象')
    if getattr(args,'anyway',False):config['anyway']=True
    if isinstance(config.get('folder'),str) and config['folder']:
        context['input_folder']=str(Path(config['folder']).resolve())
    control=(lambda:Path(args.control).read_text(encoding='utf-8').strip()) if args.control else (lambda:'run')
    progress=lambda n,m:print(json.dumps({'event':'progress','processed':n,'message':m},ensure_ascii=False),flush=True)
    if args.command=='estimate' or getattr(args,'estimate',False):
        from .estimate import estimate
        result=estimate(config,progress,control)
        print(json.dumps({'event':'estimate','estimate':result},ensure_ascii=False),flush=True);return 0
    result=run_pipeline(config,progress,control)
    print(json.dumps({'event':'result','result':result},ensure_ascii=False),flush=True)
    return 0

def main(argv=None):
    _configure_stdio()
    context={}
    try:
        return _dispatch(argv,context)
    except KeyboardInterrupt:
        print(json.dumps({'event':'error','type':'KeyboardInterrupt','message':'用户中断运行',**context},ensure_ascii=False),flush=True)
        return 130
    except Exception as error:
        if isinstance(error,json.JSONDecodeError):
            message=f'配置文件不是有效 JSON：第 {error.lineno} 行，第 {error.colno} 列'
        elif isinstance(error,UnicodeDecodeError):
            message='输入文本不是有效 UTF-8，请重新保存为 UTF-8 编码'
        else:
            message=str(error) or '运行失败，请检查输入文件和配置'
        print(json.dumps({'event':'error','type':type(error).__name__,'message':message,**context},ensure_ascii=False),flush=True)
        return 2

if __name__=='__main__':raise SystemExit(main())
