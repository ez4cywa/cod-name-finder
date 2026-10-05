"""Single-page standalone workflow; no research-project or manual task UI."""
import json,os,subprocess,sys,tempfile
from pathlib import Path
from PySide6.QtCore import QThread,Signal,QSettings,QTimer,QEvent
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (QApplication,QMainWindow,QWidget,QVBoxLayout,QHBoxLayout,QFormLayout,
    QLineEdit,QPushButton,QComboBox,QCheckBox,QLabel,QPlainTextEdit,QProgressBar,QFileDialog,
    QMessageBox,QDialog,QTextBrowser,QSpinBox,QGroupBox)
from . import VERSION
from .pipeline import Config
from .hashing import PROFILES
from .assets import ASSET_LABELS
from .presets import GAME_DOMAINS

class Job(QThread):
    progress=Signal(int,str);done=Signal(object);failed=Signal(str)
    def __init__(self,config,parent):
        super().__init__(parent);self.config=config;self.control_path=None;self.stopping=False
    def stop(self):
        self.stopping=True
        if self.control_path:
            tmp=self.control_path.with_suffix('.tmp');tmp.write_text('pause',encoding='utf-8');tmp.replace(self.control_path)
    def run(self):
        try:
            with tempfile.TemporaryDirectory(prefix='finder-one-click-') as folder:
                folder=Path(folder);config=folder/'config.json';config.write_text(json.dumps(self.config,ensure_ascii=False),encoding='utf-8')
                self.control_path=folder/'control.txt';self.control_path.write_text('pause' if self.stopping else 'run',encoding='utf-8')
                command=[sys.executable] if getattr(sys,'frozen',False) else [sys.executable,'-m','finder']
                flags=subprocess.CREATE_NO_WINDOW if sys.platform=='win32' else 0
                environment=os.environ.copy();environment['PYTHONIOENCODING']='utf-8';environment['PYTHONUTF8']='1'
                process=subprocess.Popen(command+['run',str(config),'--control',str(self.control_path)],stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,text=True,encoding='utf-8',errors='replace',creationflags=flags,env=environment)
                result=None;failure=None;tail=[]
                for line in process.stdout:
                    try:
                        item=json.loads(line)
                        if item.get('event')=='progress':self.progress.emit(item['processed'],item['message'])
                        if item.get('event')=='result':result=item['result']
                        if item.get('event')=='error':
                            failure=item.get('message') or '查找失败，请检查输入文件和配置'
                            folder=item.get('input_folder')
                            if folder and folder not in failure:failure+='\n哈希文件夹：'+folder
                    except (ValueError,AttributeError,KeyError,TypeError):
                        if line.strip():tail.append(line.strip());tail=tail[-5:]
                process.wait()
                if failure:raise RuntimeError(failure)
                if process.returncode or result is None:
                    message=(f'查找进程退出异常（退出码 {process.returncode}）。' if process.returncode else '查找进程没有返回结果。')
                    if tail:message+='\n'+'\n'.join(tail)
                    raise RuntimeError(message)
                self.done.emit(result)
        except Exception as e:self.failed.emit(str(e))
        finally:self.control_path=None

def button(text,fn):
    b=QPushButton(text);b.setMinimumHeight(34);b.clicked.connect(fn);return b

class Window(QMainWindow):
    def __init__(self):
        super().__init__();self.settings=QSettings('CODNameFinder','OneClick');self.job=None;self.closing=False;self.result=None
        self.setWindowTitle('COD Name Finder · 一键名称查找 '+VERSION);self.resize(1060,850);self.setMinimumSize(880,740)
        root=QWidget();layout=QVBoxLayout(root);layout.setContentsMargins(24,20,24,20);layout.setSpacing(12);self.setCentralWidget(root)
        top=QHBoxLayout();title=QLabel('一键计算资产名称');title.setObjectName('heading');top.addWidget(title);top.addStretch()
        self.help_button=button('使用教程 · F1',self.open_tutorial);top.addWidget(self.help_button);layout.addLayout(top)
        intro=QLabel('选择已导出的哈希文件与已有名称索引，自动生成候选、验证并导出 Saluki 增量。无需研究项目。');intro.setWordWrap(True);layout.addWidget(intro)
        group=QGroupBox('输入与输出');form=QFormLayout(group);form.setVerticalSpacing(10)
        self.folder=QLineEdit(self.settings.value('folder',''));form.addRow('哈希文件夹',self.path_row(self.folder))
        self.game=QComboBox();self.game.addItems([g for g in GAME_DOMAINS if g!='声音容器 / 手动核验'])
        self.game.setCurrentText(self.settings.value('game','COD2026'))
        self.profile=QComboBox()
        for pid in PROFILES:self.profile.addItem(pid,pid)
        choices=QHBoxLayout();choices.addWidget(self.game);choices.addWidget(QLabel('哈希规则'));choices.addWidget(self.profile,1);form.addRow('作品与算法',choices)
        self.asset_type=QComboBox();self.asset_type.addItem('自动识别全部非模型资产','auto')
        for kind,label in ASSET_LABELS.items():self.asset_type.addItem(label+' · '+kind,kind)
        self.asset_type.setCurrentIndex(max(0,self.asset_type.findData(self.settings.value('asset_type','xanim'))))
        self.exclude=QCheckBox('排除材质');self.exclude.setChecked(self.asset_type.currentData()!='material')
        type_row=QHBoxLayout();type_row.addWidget(self.asset_type,1);type_row.addWidget(self.exclude);form.addRow('资产类型',type_row)
        self.asset_type.currentIndexChanged.connect(lambda:self.exclude.setChecked(False) if self.asset_type.currentData()=='material' else None)
        self.indexes=QLineEdit(self.settings.value('indexes',''));self.indexes.setPlaceholderText('Saluki 目录或复制的 CDB 索引文件夹');form.addRow('已有名称索引',self.path_row(self.indexes))
        self.dictionary=QLineEdit(self.settings.value('dictionary',''));self.dictionary.setPlaceholderText('可选：TXT / CSV / TSV / CDB / WNI 名称词典');form.addRow('补充名称词典',self.path_row(self.dictionary,file=True))
        self.cross_asset=QCheckBox('根据其他资产名称推测动画和声音');self.cross_asset.setChecked(self.settings.value('cross_asset',True,type=bool))
        self.cross_asset.setToolTip('从全部已有名称索引和可选已命名文件夹提取武器等名称线索；候选仍须哈希命中并独立验证。')
        form.addRow('关联名称推测',self.cross_asset)
        self.related_folder=QLineEdit(self.settings.value('related_folder',''));self.related_folder.setPlaceholderText('可选：已导出的模型、材质、图像等文件夹')
        self.related_folder.setAccessibleName('其他已命名资产文件夹')
        self.related_row=self.path_row(self.related_folder);form.addRow('其他已命名资产',self.related_row)
        self.related_row.itemAt(1).widget().setAccessibleName('选择其他已命名资产文件夹')
        self.asset_type.currentIndexChanged.connect(self.update_related_controls);self.cross_asset.toggled.connect(self.update_related_controls);self.update_related_controls()
        self.output=QLineEdit(self.settings.value('output',str(Path.home()/'CODNameFinder/Results')));form.addRow('输出目录',self.path_row(self.output))
        self.keyword=QLineEdit();self.keyword.setPlaceholderText('可选；在哈希命中后筛选名称，例如 mike4');form.addRow('结果关键词',self.keyword)
        self.backend=QComboBox();self.backend.addItem('自动选择 CPU / GPU','auto');self.backend.addItem('Rust CPU','cpu');self.backend.addItem('GPU · OpenCL','gpu')
        self.low60=QCheckBox('文件名仅保留低60位（仅生成待核验候选）')
        compute=QHBoxLayout();compute.addWidget(self.backend);compute.addWidget(self.low60);form.addRow('运算方式',compute)
        self.budget=QSpinBox();self.budget.setRange(1000,1000000000);self.budget.setValue(10000000);self.budget.setGroupSeparatorShown(True)
        self.minutes=QSpinBox();self.minutes.setRange(1,1440);self.minutes.setValue(120)
        limits=QHBoxLayout();limits.addWidget(self.budget);limits.addWidget(QLabel('次候选计算，最多'));limits.addWidget(self.minutes);limits.addWidget(QLabel('分钟'));form.addRow('本次预算',limits)
        layout.addWidget(group)
        self.game.currentTextChanged.connect(self.select_profile);self.select_profile()
        saved=self.settings.value('profile','');index=self.profile.findData(saved)
        if index>=0:self.profile.setCurrentIndex(index)
        row=QHBoxLayout();self.start_button=button('一键计算并导出',self.start);self.start_button.setObjectName('primary');row.addWidget(self.start_button,1)
        self.stop_button=button('停止并保存',self.stop);self.stop_button.setEnabled(False);row.addWidget(self.stop_button)
        self.open_button=button('打开结果目录',self.open_result);self.open_button.setEnabled(False);row.addWidget(self.open_button);layout.addLayout(row)
        self.csv_button=button('打开新增 CSV',self.open_csv);self.csv_button.setEnabled(False);row.addWidget(self.csv_button)
        self.progress_bar=QProgressBar();layout.addWidget(self.progress_bar)
        self.status=QLabel('就绪');self.status.setWordWrap(True);layout.addWidget(self.status)
        self.log=QPlainTextEdit();self.log.setReadOnly(True);self.log.setMaximumBlockCount(300);layout.addWidget(self.log,1)
        note=QLabel('仅完整哈希匹配且回算通过的名称进入正式增量；排除 Saluki 已有哈希或名称。候选覆盖有限，不保证所有文件都能命名。');note.setWordWrap(True);layout.addWidget(note)
        self.setStyleSheet("""QWidget{font-family:'Segoe UI','Microsoft YaHei UI';font-size:13px;background:#111b28;color:#e7eef6}
            QGroupBox{border:1px solid #49627d;border-radius:5px;margin-top:12px;padding-top:14px}
            QLineEdit,QComboBox,QSpinBox,QPlainTextEdit,QTextBrowser{background:#1a293b;border:1px solid #49627d;border-radius:4px;padding:5px}
            QPushButton{background:#203247;border:1px solid #49627d;border-radius:4px;padding:6px 14px}
            QPushButton#primary{background:#21557b;border:1px solid #80c8ff;font-weight:600}
            QPushButton:disabled{color:#788b9e} QLabel#heading{font-size:24px;font-weight:600}
            QLineEdit:disabled{color:#788b9e;background:#162232;border-color:#33475d} QCheckBox:disabled{color:#788b9e}
            QProgressBar{border:1px solid #49627d;text-align:center} QProgressBar::chunk{background:#387ea5}
            QCheckBox::indicator{width:16px;height:16px}""")
        help_action=QAction('使用教程',self);help_action.setShortcut('F1');help_action.triggered.connect(self.open_tutorial);self.addAction(help_action)
    def path_row(self,edit,file=False):
        row=QHBoxLayout();row.addWidget(edit,1)
        def choose():
            value=QFileDialog.getOpenFileName(self,'选择名称词典',edit.text(),'名称词典 (*.txt *.csv *.tsv *.cdb *.wni)')[0] if file else QFileDialog.getExistingDirectory(self,'选择文件夹',edit.text())
            if value:edit.setText(value)
        row.addWidget(button('选择…',choose));return row
    def select_profile(self):
        pid='fnv1a63' if self.game.currentText() in ('BO4','BOCW') else 'iw-resource63'
        self.profile.setCurrentIndex(self.profile.findData(pid))
    def update_related_controls(self):
        supported=self.asset_type.currentData() in ('auto','xanim','sndasset','soundbank','soundbanktransient')
        self.cross_asset.setEnabled(supported)
        active=supported and self.cross_asset.isChecked()
        for i in range(self.related_row.count()):self.related_row.itemAt(i).widget().setEnabled(active)
        hint='可选：已命名资产文件夹，递归提取名称线索，不作为哈希目标。' if active else ('勾选关联名称推测后，可选择额外的已命名资产文件夹。' if supported else '仅动画、声音和声音库目标启用关联推测；保留已选路径供下次使用。')
        self.related_folder.setToolTip(hint)
    def configuration(self):
        config=Config(folder=self.folder.text().strip(),indexes=self.indexes.text().strip(),output=self.output.text().strip(),
            profile=self.profile.currentData(),asset_type=self.asset_type.currentData(),game=self.game.currentText(),
            dictionary=self.dictionary.text().strip(),keyword=self.keyword.text().strip(),backend=self.backend.currentData(),
            cross_asset=self.cross_asset.isChecked(),related_folder=self.related_folder.text().strip(),
            exclude_material=self.exclude.isChecked(),low60=self.low60.isChecked(),budget=self.budget.value(),seconds=self.minutes.value()*60)
        if not config.folder or not config.indexes or not config.output:raise ValueError('请选择哈希文件夹、已有名称索引和输出目录')
        return config.validate()
    def start(self):
        if self.job:return
        try:config=self.configuration()
        except Exception as e:QMessageBox.warning(self,'无法开始',str(e));return
        from dataclasses import asdict
        cfg=asdict(config)
        self.save_preferences(cfg)
        self.start_button.setEnabled(False);self.stop_button.setEnabled(True);self.open_button.setEnabled(False);self.csv_button.setEnabled(False);self.log.clear()
        self.progress_bar.setRange(0,config.budget);self.progress_bar.setValue(0)
        self.job=Job(cfg,self);self.job.progress.connect(self.on_progress);self.job.done.connect(self.finished);self.job.failed.connect(self.failed)
        self.job.finished.connect(self.cleanup);self.job.start()
    def save_preferences(self,config):
        for field in ('folder','indexes','output','dictionary','game','profile','asset_type','cross_asset','related_folder'):self.settings.setValue(field,config[field])
    def on_progress(self,n,message):self.progress_bar.setValue(min(n,self.budget.value()));self.status.setText(message);self.log.appendPlainText(message)
    def stop(self):
        if self.job:self.job.stop();self.stop_button.setEnabled(False);self.status.setText('等待当前批次保存并导出已验证结果')
    def finished(self,result):
        self.result=result;self.open_button.setEnabled(True)
        self.csv_button.setEnabled(bool(result.get('new_names_csv')))
        self.csv_button.setToolTip(result.get('new_names_csv',''))
        complete=result['status']=='completed'
        self.status.setText(f"{'完成' if complete else '本次停止或预算耗尽'} · 验证 {result.get('verified_target_matches',0)} 项 · 排除已有 {result.get('excluded_existing',0)} 项 · 输出 {result['entries']} 项")
        self.log.appendPlainText(json.dumps(result,ensure_ascii=False,indent=2))
        if complete:self.progress_bar.setValue(self.progress_bar.maximum())
    def failed(self,message):
        self.status.setText('运行失败：'+message+'\n已保存的工作文件仍保留在输出目录。')
        self.log.appendPlainText(message)
    def cleanup(self):
        self.job.deleteLater();self.job=None;self.start_button.setEnabled(True);self.stop_button.setEnabled(False)
        if self.closing:QTimer.singleShot(0,QApplication.instance().quit)
    def open_result(self):
        if self.result:
            from PySide6.QtCore import QUrl
            from PySide6.QtGui import QDesktopServices
            QDesktopServices.openUrl(QUrl.fromLocalFile(self.result.get('path') or self.result['run_dir']))
    def open_tutorial(self):
        root=Path(sys.executable).parent if getattr(sys,'frozen',False) else Path(__file__).resolve().parents[1]
        path=root/'docs/user-guide.zh-CN.md'
        if not path.exists():QMessageBox.warning(self,'教程缺失','请重新安装完整软件包');return
        if not hasattr(self,'help_dialog'):
            self.help_dialog=QDialog(self);self.help_dialog.setWindowTitle('COD Name Finder 一键使用教程');self.help_dialog.resize(1000,760)
            layout=QVBoxLayout(self.help_dialog);self.help_browser=QTextBrowser();layout.addWidget(self.help_browser);layout.addWidget(button('关闭教程',self.help_dialog.close))
        self.help_browser.setMarkdown(path.read_text(encoding='utf-8'));self.help_dialog.show();self.help_dialog.raise_()
    def open_csv(self):
        if self.result and self.result.get('new_names_csv'):
            from PySide6.QtCore import QUrl
            from PySide6.QtGui import QDesktopServices
            QDesktopServices.openUrl(QUrl.fromLocalFile(self.result['new_names_csv']))
    def closeEvent(self,event):
        if self.job:self.closing=True;self.stop();self.hide();event.ignore()
        else:event.accept();QTimer.singleShot(0,QApplication.instance().quit)

def main(screenshot=None,tutorial=False):
    if getattr(sys,'frozen',False) and sys.platform=='win32' and not screenshot:
        import ctypes
        hwnd=ctypes.windll.kernel32.GetConsoleWindow()
        if hwnd:ctypes.windll.user32.ShowWindow(hwnd,0)
    app=QApplication.instance() or QApplication(sys.argv[:1]);app.setQuitOnLastWindowClosed(False);win=Window();win.show()
    if tutorial:win.open_tutorial()
    if screenshot:
        def capture():
            (win.help_dialog if tutorial else win).grab().save(str(screenshot))
            print(json.dumps({'single_page':True,'algorithm_dropdown':isinstance(win.profile,QComboBox),
                'new_csv_button':hasattr(win,'csv_button'),
                'cross_asset_option':hasattr(win,'cross_asset'),'related_folder_option':hasattr(win,'related_folder'),
                'cross_asset_checkbox':isinstance(win.cross_asset,QCheckBox),'related_folder_picker':hasattr(win,'related_row'),
                'cross_asset_default_enabled':win.cross_asset.isChecked(),
                'asset_type_dropdown':isinstance(win.asset_type,QComboBox),'tutorial_open':tutorial,
                'tutorial_loaded':tutorial and '一键计算并导出' in win.help_browser.toPlainText()},ensure_ascii=False))
            win.close()
        QTimer.singleShot(500,capture)
    result=app.exec()
    # Destroy owned widgets while Qt's event infrastructure is still alive.
    # In particular, avoid leaving a native visible window for interpreter shutdown.
    win.deleteLater();app.sendPostedEvents(None,QEvent.Type.DeferredDelete)
    return result
