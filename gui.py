# -*- coding: utf-8 -*-
import os
import sys
import json
import subprocess
import signal
import logging

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QGridLayout, QGroupBox, QLabel, QLineEdit, QTextEdit, QComboBox,
    QCheckBox, QSpinBox, QDateEdit, QPushButton, QPlainTextEdit,
    QListWidget, QFileDialog, QMessageBox, QScrollArea
)
from PyQt5.QtCore import QThread, pyqtSignal, Qt, QDate
from PyQt5.QtGui import QFont, QTextCursor

IS_FROZEN = getattr(sys, 'frozen', False)

# 打包模式下配置文件保存在 exe 旁边，开发模式下保存在项目目录
if IS_FROZEN:
    APP_DIR = os.path.dirname(sys.executable)
    PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
else:
    APP_DIR = os.path.dirname(os.path.abspath(__file__))
    PROJECT_DIR = APP_DIR

SETTINGS_FILE = os.path.join(PROJECT_DIR, 'weibo', 'gui_settings.py')
SETTINGS_JSON = os.path.join(APP_DIR, '.gui_settings.json')
CONFIG_FILE = os.path.join(APP_DIR, '.gui_config.json')

WEIBO_TYPES = [
    ('全部微博', 0), ('原创微博', 1), ('热门微博', 2),
    ('关注人微博', 3), ('认证用户微博', 4), ('媒体微博', 5), ('观点微博', 6)
]
CONTAIN_TYPES = [
    ('不筛选', 0), ('包含图片', 1), ('包含视频', 2),
    ('包含音乐', 3), ('包含短链接', 4)
]
PROVINCES = [
    '全部', '安徽', '北京', '重庆', '福建', '甘肃', '广东', '广西',
    '贵州', '海南', '河北', '黑龙江', '河南', '湖北', '湖南',
    '内蒙古', '江苏', '江西', '吉林', '辽宁', '宁夏', '青海',
    '山西', '山东', '上海', '四川', '天津', '西藏', '新疆',
    '云南', '浙江', '陕西', '台湾', '香港', '澳门', '海外', '其他'
]


def setup_scrapy_env():
    """设置 Scrapy 环境变量并清除已缓存的 weibo 模块，确保 spider 读到 GUI 生成的设置。"""
    os.environ['SCRAPY_SETTINGS_MODULE'] = 'weibo.gui_settings'
    to_remove = [k for k in sys.modules if k == 'weibo' or k.startswith('weibo.')]
    for k in to_remove:
        del sys.modules[k]


# ── 开发模式：通过 subprocess 调用 scrapy CLI ──

class SpiderWorker(QThread):
    log_signal = pyqtSignal(str)
    finished_signal = pyqtSignal(bool)

    def __init__(self, project_dir):
        super().__init__()
        self.project_dir = project_dir
        self.process = None
        self._is_running = False

    def run(self):
        self._is_running = True
        env = os.environ.copy()
        env['SCRAPY_SETTINGS_MODULE'] = 'weibo.gui_settings'
        try:
            self.process = subprocess.Popen(
                [sys.executable, '-m', 'scrapy', 'crawl', 'search'],
                cwd=self.project_dir,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                bufsize=1,
                universal_newlines=True
            )
            for line in iter(self.process.stdout.readline, ''):
                if not self._is_running:
                    break
                self.log_signal.emit(line.rstrip('\n'))
            self.process.stdout.close()
            self.process.wait()
            self.finished_signal.emit(self.process.returncode == 0)
        except FileNotFoundError:
            self.log_signal.emit('[错误] 未找到 scrapy，请先运行: pip install scrapy')
            self.finished_signal.emit(False)
        except Exception as e:
            self.log_signal.emit(f'[错误] {str(e)}')
            self.finished_signal.emit(False)
        finally:
            self._is_running = False

    def stop(self):
        self._is_running = False
        if self.process and self.process.poll() is None:
            if os.name != 'nt':
                self.process.send_signal(signal.SIGINT)
                try:
                    self.process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self.process.terminate()
                    try:
                        self.process.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        self.process.kill()
            else:
                self.process.terminate()


# ── 打包模式：在进程内通过 Twisted reactor 运行爬虫 ──

class QtLogHandler(logging.Handler):
    """将 Python logging 消息转发到 Qt 信号。"""
    def __init__(self, signal):
        super().__init__()
        self.signal = signal

    def emit(self, record):
        msg = self.format(record)
        self.signal.emit(msg)


class CrawlThread(QThread):
    log_signal = pyqtSignal(str)
    finished_signal = pyqtSignal(bool)

    def __init__(self, project_dir, settings_json_path):
        super().__init__()
        self.project_dir = project_dir
        self.settings_json_path = settings_json_path
        self._is_running = False

    def run(self):
        self._is_running = True
        old_cwd = os.getcwd()
        try:
            os.chdir(self.project_dir)
            setup_scrapy_env()

            from scrapy.crawler import CrawlerProcess
            from scrapy.settings import Settings

            with open(self.settings_json_path, 'r', encoding='utf-8') as f:
                raw = json.load(f)

            settings = Settings()
            for key, value in raw.items():
                settings.set(key, value)

            self.log_signal.emit(f'[系统] 关键词: {settings.get("KEYWORD_LIST")}')
            self.log_signal.emit(f'[系统] 日期: {settings.get("START_DATE")} ~ {settings.get("END_DATE")}')
            self.log_signal.emit(f'[系统] 结果保存至: {settings.get("SAVE_DIR", "./")}')

            # 将 JSON 设置注入为 Python 模块，让 get_project_settings() 读到正确值
            import types
            settings_module = types.ModuleType('weibo.gui_settings')
            for key, value in raw.items():
                setattr(settings_module, key, value)
            sys.modules['weibo.gui_settings'] = settings_module
            os.environ['SCRAPY_SETTINGS_MODULE'] = 'weibo.gui_settings'

            # 预导入 spider 模块，让类属性从正确的 settings 读取
            # setup_scrapy_env 已清除缓存，此时导入会重新执行类定义
            from weibo.spiders.search import SearchSpider

            # 双重保险：直接覆盖类属性（防止 get_project_settings 读到旧文件）
            kw = settings.get('KEYWORD_LIST', [])
            if not isinstance(kw, list):
                kw = [kw]
            # 处理话题编码 #话题# -> %23话题%23
            import weibo.utils.util as _util
            for i, keyword in enumerate(kw):
                if len(keyword) > 2 and keyword[0] == '#' and keyword[-1] == '#':
                    kw[i] = '%23' + keyword[1:-1] + '%23'
            SearchSpider.keyword_list = kw
            SearchSpider.weibo_type = _util.convert_weibo_type(raw.get('WEIBO_TYPE', 1))
            SearchSpider.contain_type = _util.convert_contain_type(raw.get('CONTAIN_TYPE', 0))
            SearchSpider.regions = _util.get_regions(raw.get('REGION', ['全部']))
            SearchSpider.start_date = raw.get('START_DATE', '')
            SearchSpider.end_date = raw.get('END_DATE', '')
            SearchSpider.further_threshold = raw.get('FURTHER_THRESHOLD', 46)
            SearchSpider.limit_result = raw.get('LIMIT_RESULT', 0)

            handler = QtLogHandler(self.log_signal)
            handler.setFormatter(logging.Formatter('%(message)s'))
            logging.root.addHandler(handler)

            process = CrawlerProcess(settings)
            process.crawl('search')
            process.start()

            logging.root.removeHandler(handler)
            self.finished_signal.emit(True)
        except Exception as e:
            self.log_signal.emit(f'[错误] {str(e)}')
            self.finished_signal.emit(False)
        finally:
            os.chdir(old_cwd)
            self._is_running = False

    def stop(self):
        self._is_running = False
        try:
            from twisted.internet import reactor
            if reactor.running:
                reactor.callFromThread(reactor.fireSystemEvent, 'shutdown')
        except Exception:
            pass


# ── 主窗口 ──

class WeiboSearchGUI(QMainWindow):
    def __init__(self):
        super().__init__()
        self.worker = None
        self.init_ui()
        self.load_config()

    def init_ui(self):
        self.setWindowTitle('微博搜索爬虫')
        self.setMinimumSize(700, 800)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        central = QWidget()
        layout = QVBoxLayout(central)
        layout.setSpacing(10)

        layout.addWidget(self._build_basic_group())
        layout.addWidget(self._build_filter_group())
        layout.addWidget(self._build_storage_group())
        layout.addWidget(self._build_advanced_group())
        layout.addWidget(self._build_control_bar())
        layout.addWidget(self._build_log_group())

        scroll.setWidget(central)
        self.setCentralWidget(scroll)

    # ── 基本设置 ──

    def _build_basic_group(self):
        group = QGroupBox('基本设置')
        grid = QGridLayout(group)

        grid.addWidget(QLabel('Cookie:'), 0, 0, Qt.AlignTop)
        self.cookie_edit = QTextEdit()
        self.cookie_edit.setPlaceholderText('从浏览器开发者工具中复制 Cookie 粘贴到这里')
        self.cookie_edit.setMaximumHeight(80)
        grid.addWidget(self.cookie_edit, 0, 1)

        grid.addWidget(QLabel('关键词:'), 1, 0, Qt.AlignTop)
        self.keyword_text = QTextEdit()
        self.keyword_text.setPlaceholderText('每行一个关键词，话题用 #话题名# 包裹')
        self.keyword_text.setMaximumHeight(80)
        grid.addWidget(self.keyword_text, 1, 1)

        grid.addWidget(QLabel('关键词文件:'), 2, 0)
        file_row = QHBoxLayout()
        self.keyword_file_edit = QLineEdit()
        self.keyword_file_edit.setPlaceholderText('可选，指定 .txt 文件路径后将忽略上方的关键词文本')
        self.keyword_file_btn = QPushButton('浏览...')
        self.keyword_file_btn.clicked.connect(self._browse_keyword_file)
        file_row.addWidget(self.keyword_file_edit)
        file_row.addWidget(self.keyword_file_btn)
        grid.addLayout(file_row, 2, 1)

        grid.addWidget(QLabel('保存路径:'), 3, 0)
        save_row = QHBoxLayout()
        self.save_dir_edit = QLineEdit()
        self.save_dir_edit.setPlaceholderText('结果文件保存目录，留空则保存在程序所在目录')
        save_browse = QPushButton('浏览...')
        save_browse.clicked.connect(self._browse_save_dir)
        save_row.addWidget(self.save_dir_edit)
        save_row.addWidget(save_browse)
        grid.addLayout(save_row, 3, 1)

        return group

    # ── 搜索筛选 ──

    def _build_filter_group(self):
        group = QGroupBox('搜索筛选')
        grid = QGridLayout(group)

        grid.addWidget(QLabel('微博类型:'), 0, 0)
        self.weibo_type_combo = QComboBox()
        for name, _ in WEIBO_TYPES:
            self.weibo_type_combo.addItem(name)
        self.weibo_type_combo.setCurrentIndex(1)
        grid.addWidget(self.weibo_type_combo, 0, 1)

        grid.addWidget(QLabel('包含类型:'), 1, 0)
        self.contain_type_combo = QComboBox()
        for name, _ in CONTAIN_TYPES:
            self.contain_type_combo.addItem(name)
        grid.addWidget(self.contain_type_combo, 1, 1)

        grid.addWidget(QLabel('发布地区:'), 2, 0, Qt.AlignTop)
        region_widget = QWidget()
        region_layout = QVBoxLayout(region_widget)
        region_layout.setContentsMargins(0, 0, 0, 0)
        self.region_select_all = QCheckBox('全选/取消全选')
        self.region_select_all.stateChanged.connect(self._toggle_region_all)
        region_layout.addWidget(self.region_select_all)
        self.region_list = QListWidget()
        self.region_list.setSelectionMode(QListWidget.MultiSelection)
        self.region_list.setMaximumHeight(120)
        for p in PROVINCES:
            self.region_list.addItem(p)
        self.region_list.item(0).setSelected(True)
        region_layout.addWidget(self.region_list)
        grid.addWidget(region_widget, 2, 1)

        grid.addWidget(QLabel('开始日期:'), 3, 0)
        self.start_date = QDateEdit()
        self.start_date.setCalendarPopup(True)
        self.start_date.setDate(QDate.currentDate())
        self.start_date.setDisplayFormat('yyyy-MM-dd')
        grid.addWidget(self.start_date, 3, 1)

        grid.addWidget(QLabel('结束日期:'), 4, 0)
        self.end_date = QDateEdit()
        self.end_date.setCalendarPopup(True)
        self.end_date.setDate(QDate.currentDate())
        self.end_date.setDisplayFormat('yyyy-MM-dd')
        grid.addWidget(self.end_date, 4, 1)

        return group

    # ── 存储设置 ──

    def _build_storage_group(self):
        group = QGroupBox('存储设置')
        root_layout = QVBoxLayout(group)

        fmt_row = QHBoxLayout()
        fmt_row.addWidget(QLabel('输出格式:'))
        self.csv_check = QCheckBox('CSV')
        self.csv_check.setChecked(True)
        self.mysql_check = QCheckBox('MySQL')
        self.mongo_check = QCheckBox('MongoDB')
        self.sqlite_check = QCheckBox('SQLite')
        fmt_row.addWidget(self.csv_check)
        fmt_row.addWidget(self.mysql_check)
        fmt_row.addWidget(self.mongo_check)
        fmt_row.addWidget(self.sqlite_check)
        fmt_row.addStretch()
        root_layout.addLayout(fmt_row)

        # MySQL
        self.mysql_container = QWidget()
        mysql_grid = QGridLayout(self.mysql_container)
        mysql_grid.setContentsMargins(20, 0, 0, 0)
        mysql_grid.addWidget(QLabel('主机:'), 0, 0)
        self.mysql_host = QLineEdit('localhost')
        mysql_grid.addWidget(self.mysql_host, 0, 1)
        mysql_grid.addWidget(QLabel('端口:'), 0, 2)
        self.mysql_port = QSpinBox()
        self.mysql_port.setRange(1, 65535)
        self.mysql_port.setValue(3306)
        mysql_grid.addWidget(self.mysql_port, 0, 3)
        mysql_grid.addWidget(QLabel('用户名:'), 1, 0)
        self.mysql_user = QLineEdit('root')
        mysql_grid.addWidget(self.mysql_user, 1, 1)
        mysql_grid.addWidget(QLabel('密码:'), 1, 2)
        self.mysql_password = QLineEdit('123456')
        self.mysql_password.setEchoMode(QLineEdit.Password)
        mysql_grid.addWidget(self.mysql_password, 1, 3)
        mysql_grid.addWidget(QLabel('数据库名:'), 2, 0)
        self.mysql_database = QLineEdit('weibo')
        mysql_grid.addWidget(self.mysql_database, 2, 1)
        self.mysql_container.setVisible(False)
        root_layout.addWidget(self.mysql_container)
        self.mysql_check.toggled.connect(self.mysql_container.setVisible)

        # MongoDB
        self.mongo_container = QWidget()
        mongo_row = QHBoxLayout(self.mongo_container)
        mongo_row.setContentsMargins(20, 0, 0, 0)
        mongo_row.addWidget(QLabel('URI:'))
        self.mongo_uri = QLineEdit('localhost')
        mongo_row.addWidget(self.mongo_uri)
        self.mongo_container.setVisible(False)
        root_layout.addWidget(self.mongo_container)
        self.mongo_check.toggled.connect(self.mongo_container.setVisible)

        # SQLite
        self.sqlite_container = QWidget()
        sqlite_row = QHBoxLayout(self.sqlite_container)
        sqlite_row.setContentsMargins(20, 0, 0, 0)
        sqlite_row.addWidget(QLabel('数据库文件:'))
        self.sqlite_database = QLineEdit('weibo.db')
        sqlite_row.addWidget(self.sqlite_database)
        self.sqlite_container.setVisible(False)
        root_layout.addWidget(self.sqlite_container)
        self.sqlite_check.toggled.connect(self.sqlite_container.setVisible)

        # 媒体下载
        img_row = QHBoxLayout()
        self.download_images = QCheckBox('下载图片')
        self.images_store = QLineEdit('./')
        img_browse = QPushButton('浏览...')
        img_browse.clicked.connect(lambda: self._browse_dir(self.images_store))
        img_row.addWidget(self.download_images)
        img_row.addWidget(self.images_store)
        img_row.addWidget(img_browse)
        root_layout.addLayout(img_row)

        vid_row = QHBoxLayout()
        self.download_videos = QCheckBox('下载视频')
        self.files_store = QLineEdit('./')
        vid_browse = QPushButton('浏览...')
        vid_browse.clicked.connect(lambda: self._browse_dir(self.files_store))
        vid_row.addWidget(self.download_videos)
        vid_row.addWidget(self.files_store)
        vid_row.addWidget(vid_browse)
        root_layout.addLayout(vid_row)

        return group

    # ── 高级设置 ──

    def _build_advanced_group(self):
        group = QGroupBox('高级设置')
        grid = QGridLayout(group)

        grid.addWidget(QLabel('下载延迟(秒):'), 0, 0)
        self.download_delay = QSpinBox()
        self.download_delay.setRange(1, 60)
        self.download_delay.setValue(10)
        grid.addWidget(self.download_delay, 0, 1)

        grid.addWidget(QLabel('搜索阈值:'), 1, 0)
        self.threshold_spin = QSpinBox()
        self.threshold_spin.setRange(1, 100)
        self.threshold_spin.setValue(46)
        self.threshold_spin.setToolTip('结果页数 >= 此值时自动细分搜索，建议 40-50')
        grid.addWidget(self.threshold_spin, 1, 1)

        grid.addWidget(QLabel('结果数量限制:'), 2, 0)
        self.limit_spin = QSpinBox()
        self.limit_spin.setRange(0, 999999)
        self.limit_spin.setValue(0)
        self.limit_spin.setToolTip('0 表示不限制')
        grid.addWidget(self.limit_spin, 2, 1)

        return group

    # ── 控制栏 ──

    def _build_control_bar(self):
        bar = QWidget()
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(0, 5, 0, 5)

        self.save_btn = QPushButton('保存配置')
        self.save_btn.setStyleSheet(
            'QPushButton { background-color: #2196F3; color: white; '
            'font-weight: bold; padding: 8px 18px; border-radius: 4px; }'
            'QPushButton:hover { background-color: #1976D2; }'
        )
        self.save_btn.clicked.connect(self._manual_save)

        self.start_btn = QPushButton('开始爬取')
        self.start_btn.setStyleSheet(
            'QPushButton { background-color: #4CAF50; color: white; '
            'font-weight: bold; padding: 8px 24px; border-radius: 4px; }'
            'QPushButton:hover { background-color: #45a049; }'
            'QPushButton:disabled { background-color: #a5d6a7; }'
        )
        self.start_btn.clicked.connect(self.start_spider)

        self.stop_btn = QPushButton('停止')
        self.stop_btn.setEnabled(False)
        self.stop_btn.setStyleSheet(
            'QPushButton { background-color: #f44336; color: white; '
            'font-weight: bold; padding: 8px 24px; border-radius: 4px; }'
            'QPushButton:hover { background-color: #da190b; }'
            'QPushButton:disabled { background-color: #ef9a9a; }'
        )
        self.stop_btn.clicked.connect(self.stop_spider)

        self.status_label = QLabel('就绪')
        self.status_label.setStyleSheet('font-weight: bold; margin-left: 12px;')

        layout.addWidget(self.save_btn)
        layout.addWidget(self.start_btn)
        layout.addWidget(self.stop_btn)
        layout.addWidget(self.status_label)
        layout.addStretch()
        return bar

    # ── 日志区域 ──

    def _build_log_group(self):
        group = QGroupBox('运行日志')
        layout = QVBoxLayout(group)

        self.log_text = QPlainTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setFont(QFont('Menlo', 11))
        self.log_text.setStyleSheet(
            'QPlainTextEdit { background-color: #1e1e1e; color: #d4d4d4; '
            'border: 1px solid #333; }'
        )
        layout.addWidget(self.log_text)

        clear_btn = QPushButton('清空日志')
        clear_btn.clicked.connect(self.log_text.clear)
        layout.addWidget(clear_btn, alignment=Qt.AlignRight)

        return group

    # ── 辅助方法 ──

    def _browse_keyword_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, '选择关键词文件', '', '文本文件 (*.txt);;所有文件 (*)'
        )
        if path:
            self.keyword_file_edit.setText(path)

    def _browse_save_dir(self):
        path = QFileDialog.getExistingDirectory(self, '选择保存目录')
        if path:
            self.save_dir_edit.setText(path)

    def _browse_dir(self, target_edit):
        path = QFileDialog.getExistingDirectory(self, '选择目录')
        if path:
            target_edit.setText(path)

    def _manual_save(self):
        self.save_config()
        if IS_FROZEN:
            self.write_settings_json()
        else:
            self.write_gui_settings()
        QMessageBox.information(self, '提示', '配置已保存')

    def _toggle_region_all(self, state):
        for i in range(self.region_list.count()):
            item = self.region_list.item(i)
            item.setSelected(state == Qt.Checked)

    def _get_save_dir(self):
        save_dir = self.save_dir_edit.text().strip()
        if save_dir:
            return save_dir
        return APP_DIR if IS_FROZEN else './'

    # ── 核心逻辑 ──

    def validate_inputs(self):
        cookie = self.cookie_edit.toPlainText().strip()
        if not cookie:
            QMessageBox.warning(self, '提示', '请填写 Cookie')
            return False

        keyword_file = self.keyword_file_edit.text().strip()
        keywords = self.keyword_text.toPlainText().strip()
        if not keyword_file and not keywords:
            QMessageBox.warning(self, '提示', '请填写关键词或指定关键词文件')
            return False

        if keyword_file and not os.path.isfile(keyword_file):
            QMessageBox.warning(self, '提示', f'关键词文件不存在: {keyword_file}')
            return False

        if self.start_date.date() > self.end_date.date():
            QMessageBox.warning(self, '提示', '开始日期不能晚于结束日期')
            return False

        has_output = (self.csv_check.isChecked() or self.mysql_check.isChecked()
                      or self.mongo_check.isChecked() or self.sqlite_check.isChecked()
                      or self.download_images.isChecked() or self.download_videos.isChecked())
        if not has_output:
            QMessageBox.warning(self, '提示', '请至少选择一种输出格式或下载选项')
            return False

        return True

    def _collect_pipelines(self):
        pipelines = {'weibo.pipelines.DuplicatesPipeline': 300}
        if self.csv_check.isChecked():
            pipelines['weibo.pipelines.CsvPipeline'] = 301
        if self.mysql_check.isChecked():
            pipelines['weibo.pipelines.MysqlPipeline'] = 302
        if self.mongo_check.isChecked():
            pipelines['weibo.pipelines.MongoPipeline'] = 303
        if self.download_images.isChecked():
            pipelines['weibo.pipelines.MyImagesPipeline'] = 304
        if self.download_videos.isChecked():
            pipelines['weibo.pipelines.MyVideoPipeline'] = 305
        if self.sqlite_check.isChecked():
            pipelines['weibo.pipelines.SQLitePipeline'] = 306
        return pipelines

    def write_gui_settings(self):
        lines = [
            '# -*- coding: utf-8 -*-',
            '# 由 GUI 自动生成，请勿手动编辑',
            'from weibo.settings import *',
            '',
        ]

        cookie = self.cookie_edit.toPlainText().strip()
        lines.append("DEFAULT_REQUEST_HEADERS = {")
        lines.append("    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',")
        lines.append("    'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8,en-US;q=0.7',")
        lines.append(f"    'cookie': {repr(cookie)},")
        lines.append("}")
        lines.append('')

        keyword_file = self.keyword_file_edit.text().strip()
        if keyword_file:
            lines.append(f"KEYWORD_LIST = {repr(keyword_file)}")
        else:
            keywords = [k.strip() for k in self.keyword_text.toPlainText().strip().split('\n') if k.strip()]
            lines.append(f"KEYWORD_LIST = {repr(keywords)}")
        lines.append('')

        lines.append(f"WEIBO_TYPE = {WEIBO_TYPES[self.weibo_type_combo.currentIndex()][1]}")
        lines.append(f"CONTAIN_TYPE = {CONTAIN_TYPES[self.contain_type_combo.currentIndex()][1]}")

        selected_regions = [item.text() for item in self.region_list.selectedItems()]
        if not selected_regions:
            selected_regions = ['全部']
        lines.append(f"REGION = {repr(selected_regions)}")

        lines.append(f"START_DATE = '{self.start_date.date().toString('yyyy-MM-dd')}'")
        lines.append(f"END_DATE = '{self.end_date.date().toString('yyyy-MM-dd')}'")
        lines.append('')

        lines.append(f"DOWNLOAD_DELAY = {self.download_delay.value()}")
        lines.append(f"FURTHER_THRESHOLD = {self.threshold_spin.value()}")
        lines.append(f"LIMIT_RESULT = {self.limit_spin.value()}")
        lines.append(f"SAVE_DIR = {repr(self._get_save_dir())}")
        lines.append('')

        pipelines = self._collect_pipelines()
        lines.append("ITEM_PIPELINES = {")
        for cls, priority in pipelines.items():
            lines.append(f"    '{cls}': {priority},")
        lines.append("}")
        lines.append('')

        if self.download_images.isChecked():
            lines.append(f"IMAGES_STORE = {repr(self.images_store.text().strip() or './')}")
        if self.download_videos.isChecked():
            lines.append(f"FILES_STORE = {repr(self.files_store.text().strip() or './')}")

        if self.mysql_check.isChecked():
            lines.append(f"MYSQL_HOST = {repr(self.mysql_host.text().strip())}")
            lines.append(f"MYSQL_PORT = {self.mysql_port.value()}")
            lines.append(f"MYSQL_USER = {repr(self.mysql_user.text().strip())}")
            lines.append(f"MYSQL_PASSWORD = {repr(self.mysql_password.text())}")
            lines.append(f"MYSQL_DATABASE = {repr(self.mysql_database.text().strip())}")

        if self.mongo_check.isChecked():
            lines.append(f"MONGO_URI = {repr(self.mongo_uri.text().strip())}")

        if self.sqlite_check.isChecked():
            lines.append(f"SQLITE_DATABASE = {repr(self.sqlite_database.text().strip())}")

        content = '\n'.join(lines) + '\n'
        with open(SETTINGS_FILE, 'w', encoding='utf-8') as f:
            f.write(content)

    def write_settings_json(self):
        """将设置写入 JSON 文件，供打包模式下的 CrawlThread 直接读取。"""
        from weibo.settings import (
            BOT_NAME, SPIDER_MODULES, NEWSPIDER_MODULE,
            COOKIES_ENABLED, TELNETCONSOLE_ENABLED,
        )

        settings = {
            'BOT_NAME': BOT_NAME,
            'SPIDER_MODULES': SPIDER_MODULES,
            'NEWSPIDER_MODULE': NEWSPIDER_MODULE,
            'COOKIES_ENABLED': COOKIES_ENABLED,
            'TELNETCONSOLE_ENABLED': TELNETCONSOLE_ENABLED,
            'LOG_LEVEL': 'INFO',
        }

        cookie = self.cookie_edit.toPlainText().strip()
        settings['DEFAULT_REQUEST_HEADERS'] = {
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8,en-US;q=0.7',
            'cookie': cookie,
        }

        keyword_file = self.keyword_file_edit.text().strip()
        if keyword_file:
            settings['KEYWORD_LIST'] = keyword_file
        else:
            keywords = [k.strip() for k in self.keyword_text.toPlainText().strip().split('\n') if k.strip()]
            settings['KEYWORD_LIST'] = keywords

        settings['WEIBO_TYPE'] = WEIBO_TYPES[self.weibo_type_combo.currentIndex()][1]
        settings['CONTAIN_TYPE'] = CONTAIN_TYPES[self.contain_type_combo.currentIndex()][1]

        selected_regions = [item.text() for item in self.region_list.selectedItems()]
        settings['REGION'] = selected_regions if selected_regions else ['全部']

        settings['START_DATE'] = self.start_date.date().toString('yyyy-MM-dd')
        settings['END_DATE'] = self.end_date.date().toString('yyyy-MM-dd')
        settings['DOWNLOAD_DELAY'] = self.download_delay.value()
        settings['FURTHER_THRESHOLD'] = self.threshold_spin.value()
        settings['LIMIT_RESULT'] = self.limit_spin.value()
        settings['SAVE_DIR'] = self._get_save_dir()

        settings['ITEM_PIPELINES'] = self._collect_pipelines()

        if self.download_images.isChecked():
            settings['IMAGES_STORE'] = self.images_store.text().strip() or './'
        if self.download_videos.isChecked():
            settings['FILES_STORE'] = self.files_store.text().strip() or './'

        if self.mysql_check.isChecked():
            settings['MYSQL_HOST'] = self.mysql_host.text().strip()
            settings['MYSQL_PORT'] = self.mysql_port.value()
            settings['MYSQL_USER'] = self.mysql_user.text().strip()
            settings['MYSQL_PASSWORD'] = self.mysql_password.text()
            settings['MYSQL_DATABASE'] = self.mysql_database.text().strip()

        if self.mongo_check.isChecked():
            settings['MONGO_URI'] = self.mongo_uri.text().strip()

        if self.sqlite_check.isChecked():
            settings['SQLITE_DATABASE'] = self.sqlite_database.text().strip()

        with open(SETTINGS_JSON, 'w', encoding='utf-8') as f:
            json.dump(settings, f, ensure_ascii=False, indent=2)

    def start_spider(self):
        if not self.validate_inputs():
            return
        if IS_FROZEN:
            self.write_settings_json()
            self.worker = CrawlThread(PROJECT_DIR, SETTINGS_JSON)
        else:
            self.write_gui_settings()
            self.worker = SpiderWorker(PROJECT_DIR)

        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.status_label.setText('运行中...')
        self.status_label.setStyleSheet('font-weight: bold; color: #2196F3;')

        self.worker.log_signal.connect(self.append_log)
        self.worker.finished_signal.connect(self.on_spider_finished)
        self.worker.start()

    def stop_spider(self):
        if self.worker and self.worker.isRunning():
            self.append_log('[系统] 正在停止爬虫...')
            self.worker.stop()

    def append_log(self, text):
        self.log_text.appendPlainText(text)
        cursor = self.log_text.textCursor()
        cursor.movePosition(QTextCursor.End)
        self.log_text.setTextCursor(cursor)

    def on_spider_finished(self, success):
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        if success:
            self.status_label.setText('已完成')
            self.status_label.setStyleSheet('font-weight: bold; color: #4CAF50;')
            self.append_log('[系统] 爬虫运行完成')
        else:
            self.status_label.setText('已停止/出错')
            self.status_label.setStyleSheet('font-weight: bold; color: #f44336;')
            self.append_log('[系统] 爬虫已停止')

    # ── 配置持久化 ──

    def save_config(self):
        config = {
            'cookie': self.cookie_edit.toPlainText(),
            'keywords': self.keyword_text.toPlainText(),
            'keyword_file': self.keyword_file_edit.text(),
            'save_dir': self.save_dir_edit.text(),
            'weibo_type': self.weibo_type_combo.currentIndex(),
            'contain_type': self.contain_type_combo.currentIndex(),
            'regions': [item.text() for item in self.region_list.selectedItems()],
            'start_date': self.start_date.date().toString(Qt.ISODate),
            'end_date': self.end_date.date().toString(Qt.ISODate),
            'csv': self.csv_check.isChecked(),
            'mysql': self.mysql_check.isChecked(),
            'mongo': self.mongo_check.isChecked(),
            'sqlite': self.sqlite_check.isChecked(),
            'mysql_host': self.mysql_host.text(),
            'mysql_port': self.mysql_port.value(),
            'mysql_user': self.mysql_user.text(),
            'mysql_password': self.mysql_password.text(),
            'mysql_database': self.mysql_database.text(),
            'mongo_uri': self.mongo_uri.text(),
            'sqlite_database': self.sqlite_database.text(),
            'download_images': self.download_images.isChecked(),
            'images_store': self.images_store.text(),
            'download_videos': self.download_videos.isChecked(),
            'files_store': self.files_store.text(),
            'download_delay': self.download_delay.value(),
            'threshold': self.threshold_spin.value(),
            'limit': self.limit_spin.value(),
        }
        try:
            with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
                json.dump(config, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def load_config(self):
        if not os.path.isfile(CONFIG_FILE):
            return
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                c = json.load(f)
        except Exception:
            return

        self.cookie_edit.setPlainText(c.get('cookie', ''))
        self.keyword_text.setPlainText(c.get('keywords', ''))
        self.keyword_file_edit.setText(c.get('keyword_file', ''))
        self.save_dir_edit.setText(c.get('save_dir', ''))
        self.weibo_type_combo.setCurrentIndex(c.get('weibo_type', 1))
        self.contain_type_combo.setCurrentIndex(c.get('contain_type', 0))

        saved_regions = c.get('regions', ['全部'])
        for i in range(self.region_list.count()):
            item = self.region_list.item(i)
            item.setSelected(item.text() in saved_regions)

        if c.get('start_date'):
            self.start_date.setDate(QDate.fromString(c['start_date'], Qt.ISODate))
        if c.get('end_date'):
            self.end_date.setDate(QDate.fromString(c['end_date'], Qt.ISODate))

        self.csv_check.setChecked(c.get('csv', True))
        self.mysql_check.setChecked(c.get('mysql', False))
        self.mongo_check.setChecked(c.get('mongo', False))
        self.sqlite_check.setChecked(c.get('sqlite', False))
        self.mysql_host.setText(c.get('mysql_host', 'localhost'))
        self.mysql_port.setValue(c.get('mysql_port', 3306))
        self.mysql_user.setText(c.get('mysql_user', 'root'))
        self.mysql_password.setText(c.get('mysql_password', '123456'))
        self.mysql_database.setText(c.get('mysql_database', 'weibo'))
        self.mongo_uri.setText(c.get('mongo_uri', 'localhost'))
        self.sqlite_database.setText(c.get('sqlite_database', 'weibo.db'))
        self.download_images.setChecked(c.get('download_images', False))
        self.images_store.setText(c.get('images_store', './'))
        self.download_videos.setChecked(c.get('download_videos', False))
        self.files_store.setText(c.get('files_store', './'))
        self.download_delay.setValue(c.get('download_delay', 10))
        self.threshold_spin.setValue(c.get('threshold', 46))
        self.limit_spin.setValue(c.get('limit', 0))

    def closeEvent(self, event):
        if self.worker and self.worker.isRunning():
            reply = QMessageBox.question(
                self, '确认', '爬虫正在运行中，确定要关闭吗？',
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No
            )
            if reply == QMessageBox.No:
                event.ignore()
                return
            self.worker.stop()
            self.worker.wait(3000)
        self.save_config()
        event.accept()


def main():
    app = QApplication(sys.argv)
    app.setStyle('Fusion')
    window = WeiboSearchGUI()
    window.show()
    sys.exit(app.exec_())


if __name__ == '__main__':
    main()
