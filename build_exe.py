# -*- coding: utf-8 -*-
"""
Windows .exe 打包脚本
使用方法: python build_exe.py
需要先安装: pip install pyinstaller
"""
import os
import sys
import shutil
import subprocess

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
DIST_DIR = os.path.join(PROJECT_DIR, 'dist')
BUILD_DIR = os.path.join(PROJECT_DIR, 'build')
SPEC_FILE = os.path.join(PROJECT_DIR, 'weibo_search_gui.spec')
EXE_NAME = '微博搜索爬虫'

def clean():
    for d in [DIST_DIR, BUILD_DIR]:
        if os.path.isdir(d):
            shutil.rmtree(d)
    if os.path.isfile(SPEC_FILE):
        os.remove(SPEC_FILE)

def build():
    cmd = [
        sys.executable, '-m', 'PyInstaller',
        '--noconfirm',
        '--onefile',
        '--windowed',
        '--name', EXE_NAME,
        # 收集完整包（含子模块、数据文件、元数据）
        '--collect-all', 'scrapy',
        '--collect-all', 'twisted',
        '--collect-all', 'lxml',
        '--collect-all', 'w3lib',
        '--collect-all', 'cssselect',
        '--collect-all', 'parsel',
        '--collect-all', 'PyQt5',
        # project modules
        '--hidden-import', 'weibo',
        '--hidden-import', 'weibo.spiders',
        '--hidden-import', 'weibo.spiders.search',
        '--hidden-import', 'weibo.pipelines',
        '--hidden-import', 'weibo.items',
        '--hidden-import', 'weibo.settings',
        '--hidden-import', 'weibo.utils',
        '--hidden-import', 'weibo.utils.util',
        '--hidden-import', 'weibo.utils.region',
        # data files
        '--add-data', f'{os.path.join(PROJECT_DIR, "weibo")}:weibo',
        '--add-data', f'{os.path.join(PROJECT_DIR, "scrapy.cfg")}:.',
        # icon (optional)
        # '--icon', 'icon.ico',
        os.path.join(PROJECT_DIR, 'gui.py'),
    ]

    print('=' * 60)
    print('正在打包，请耐心等待...')
    print('=' * 60)
    result = subprocess.run(cmd, cwd=PROJECT_DIR)
    if result.returncode == 0:
        exe_path = os.path.join(DIST_DIR, EXE_NAME)
        if sys.platform == 'win32':
            exe_path += '.exe'
        print()
        print('=' * 60)
        print(f'打包成功! 生成文件:')
        print(f'  {exe_path}')
        print('=' * 60)
    else:
        print('\n打包失败，请检查错误信息。')
        sys.exit(1)


if __name__ == '__main__':
    clean()
    build()
