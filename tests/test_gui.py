import os
from dataclasses import asdict
import pytest
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication,QComboBox
import finder.gui as gui

def test_single_page_configuration_and_offline_tutorial(tmp_path,monkeypatch):
    settings=QSettings(str(tmp_path/'settings.ini'),QSettings.Format.IniFormat)
    monkeypatch.setattr(gui,'QSettings',lambda *args:settings)
    app=QApplication.instance() or QApplication([]);win=gui.Window()
    assert isinstance(win.profile,QComboBox) and isinstance(win.asset_type,QComboBox)
    assert hasattr(win,'csv_button') and not win.csv_button.isEnabled()
    assert not hasattr(win,'navigation') and not hasattr(win,'catalog')
    win.game.setCurrentText('BO4');assert win.profile.currentData()=='fnv1a63'
    win.profile.setCurrentIndex(win.profile.findData('bo4-bocw-script32'));assert win.profile.currentData()=='bo4-bocw-script32'
    source=tmp_path/'assets';source.mkdir();indexes=tmp_path/'indexes';indexes.mkdir()
    win.folder.setText(str(source));win.indexes.setText(str(indexes));win.output.setText(str(tmp_path/'output'))
    config=win.configuration();assert config.folder==str(source) and config.profile=='bo4-bocw-script32'
    assert config.cross_asset is True and config.related_folder==''
    win.asset_type.setCurrentIndex(win.asset_type.findData('material'));assert not win.exclude.isChecked()
    win.open_tutorial();app.processEvents();assert win.help_dialog.isVisible()
    assert '一键计算并导出' in win.help_browser.toPlainText()
    win.help_dialog.close();win.deleteLater();app.processEvents()

@pytest.fixture
def related_window(tmp_path,monkeypatch):
    settings=QSettings(str(tmp_path/'related-settings.ini'),QSettings.Format.IniFormat)
    monkeypatch.setattr(gui,'QSettings',lambda *args:settings)
    app=QApplication.instance() or QApplication([]);win=gui.Window()
    yield app,win,settings
    win.deleteLater();app.processEvents()

@pytest.mark.parametrize('kind',['auto','xanim','sndasset','soundbank','soundbanktransient'])
def test_related_controls_available_for_animation_and_sound(related_window,kind):
    app,win,settings=related_window
    win.asset_type.setCurrentIndex(win.asset_type.findData(kind))
    assert win.cross_asset.isEnabled() and win.cross_asset.isChecked()
    assert win.related_folder.isEnabled() and win.related_row.itemAt(1).widget().isEnabled()
    win.cross_asset.setChecked(False)
    assert win.cross_asset.isEnabled() and not win.related_folder.isEnabled()
    assert not win.related_row.itemAt(1).widget().isEnabled()

def test_related_preferences_survive_other_target_types(related_window,tmp_path,monkeypatch):
    app,win,settings=related_window
    source=tmp_path/'assets';source.mkdir();indexes=tmp_path/'indexes';indexes.mkdir();related=tmp_path/'known-models';related.mkdir()
    win.folder.setText(str(source));win.indexes.setText(str(indexes));win.output.setText(str(tmp_path/'output'));win.related_folder.setText(str(related))
    for kind in ('image','material','animpkg','rawfile','weapon'):
        win.asset_type.setCurrentIndex(win.asset_type.findData(kind))
        assert not win.cross_asset.isEnabled() and win.cross_asset.isChecked()
        assert not win.related_folder.isEnabled() and not win.related_row.itemAt(1).widget().isEnabled()
        assert win.related_folder.text()==str(related)
    win.asset_type.setCurrentIndex(win.asset_type.findData('xanim'));win.cross_asset.setChecked(False)
    config=win.configuration();assert config.cross_asset is False and config.related_folder==str(related)
    win.save_preferences(asdict(config));settings.sync()
    reloaded=QSettings(settings.fileName(),QSettings.Format.IniFormat)
    monkeypatch.setattr(gui,'QSettings',lambda *args:reloaded)
    restored=gui.Window()
    try:
        assert not restored.cross_asset.isChecked() and restored.related_folder.text()==str(related)
        restored.cross_asset.setChecked(True)
        assert restored.related_folder.isEnabled()
        assert restored.configuration().related_folder==str(related)
    finally:restored.deleteLater();app.processEvents()

def test_related_assets_picker_selects_directory(related_window,tmp_path,monkeypatch):
    app,win,settings=related_window;related=tmp_path/'named';related.mkdir();calls=[]
    def choose(*args):calls.append(args);return str(related)
    monkeypatch.setattr(gui.QFileDialog,'getExistingDirectory',choose)
    monkeypatch.setattr(gui.QFileDialog,'getOpenFileName',lambda *args:pytest.fail('关联资产必须选择目录'))
    win.related_row.itemAt(1).widget().click()
    assert calls and win.related_folder.text()==str(related)
