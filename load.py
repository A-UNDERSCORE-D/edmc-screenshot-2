"""Automatic elite dangerous screenshot renaming and conversion."""

import pathlib
import shlex
import subprocess
import threading
import tkinter as tk
from datetime import datetime
from typing import Any, Dict, Optional

import myNotebook as nb
import plug
from config import config
from EDMCLogging import get_plugin_logger

DEFAULT_FORMAT = '{timestamp}-{system}.{location}.{ext}'
DEFAULT_COMMAND = 'convert "{old}" "{new}"'
PLUGIN_NAME = 'screenshot-2'
logger = get_plugin_logger(PLUGIN_NAME)


class ScreenshotRenamer:
    CONFIG_NAMES = {
        'sshot_path': 'edss2_sshot_path',
        'format': 'edss2_rename_format',
        'convert': 'edss2_do_convert',
        'command': 'edss2_convert_command',
        'remove': 'edss2_remove_old_file',
    }
    PADX = 10

    @staticmethod
    def config_wrapper_str(name: str, default: Optional[str]) -> str:
        if hasattr(config, 'get_str'):
            return config.get_str(name, default=default)

        return str(config.get(name) or default)

    @staticmethod
    def config_wrapper_bool(name: str, default: Optional[bool]) -> bool:
        if hasattr(config, 'get_bool'):
            return config.get_bool(name, default=default)

        return bool(config.get(name) or default)

    def __init__(self) -> None:
        get_config_str = get_config_bool = config.get
        if hasattr(config, 'get_str'):
            get_config_str = config.get_str
            get_config_bool = config.get_bool

        self.sshot_path = tk.StringVar(value=self.config_wrapper_str(self.CONFIG_NAMES['sshot_path'], default=''))
        self.rename_format = tk.StringVar(value=self.config_wrapper_str(
            self.CONFIG_NAMES['format'], default=DEFAULT_FORMAT
        ))
        self.do_convert = tk.BooleanVar(value=self.config_wrapper_bool(self.CONFIG_NAMES['convert'], default=True))
        self.command = tk.StringVar(value=self.config_wrapper_str(
            self.CONFIG_NAMES['command'], default=DEFAULT_COMMAND
        ))
        self.remove_old = tk.BooleanVar(value=self.config_wrapper_bool(self.CONFIG_NAMES['remove'], default=False))

    def load(self) -> str:
        return PLUGIN_NAME

    def config_page(self, parent: nb.Notebook) -> tk.Frame:
        current_row = 0
        frame = nb.Frame(parent)
        frame.columnconfigure(1, weight=1)

        nb.Label(frame, text='Screenshot Directory').grid(row=current_row, column=0, sticky=tk.W)
        nb.Entry(frame, textvariable=self.sshot_path).grid(row=current_row, column=1, sticky=tk.EW, padx=self.PADX)
        current_row += 1

        nb.Label(frame, text='Rename Pattern').grid(row=current_row, column=0, sticky=tk.W)
        nb.Entry(frame, textvariable=self.rename_format).grid(row=current_row, column=1, sticky=tk.EW, padx=self.PADX)
        current_row += 1

        nb.Label(frame, text='Convert to PNG').grid(row=current_row, column=0, sticky=tk.W)
        nb.Checkbutton(frame, variable=self.do_convert).grid(row=current_row, column=1, padx=self.PADX)
        current_row += 1

        nb.Label(frame, text='Command to use for conversion').grid(row=current_row, column=0, sticky=tk.W)
        nb.Entry(frame, textvariable=self.command).grid(row=current_row, column=1, sticky=tk.EW, padx=self.PADX)
        current_row += 1

        nb.Label(frame, text='Remove old file (eg leftover from `convert`)').grid(
            row=current_row, column=0, sticky=tk.W)
        nb.Checkbutton(frame, variable=self.remove_old).grid(row=current_row, column=1, padx=self.PADX)

        return frame

    def on_config_close(self):
        config.set(self.CONFIG_NAMES['sshot_path'], self.sshot_path.get())
        config.set(self.CONFIG_NAMES['format'], self.rename_format.get())
        config.set(self.CONFIG_NAMES['convert'], self.do_convert.get())
        config.set(self.CONFIG_NAMES['command'], self.command.get())
        config.set(self.CONFIG_NAMES['remove'], self.remove_old.get())

    def on_journal_entry(self, cmdr: str, is_beta: bool, system: str, station: str, entry: Dict[str, Any]):
        if entry['event'] != 'Screenshot':
            return

        t = datetime.now()

        sshot_file_name = entry['Filename'].split('\\')[-1]
        sshot_dir_path = pathlib.Path(self.sshot_path.get()).expanduser()
        sshot_file_path: pathlib.Path = sshot_dir_path / sshot_file_name

        if not sshot_file_path.exists():
            plug.show_error('Invalid Screenshot')
            logger.warn(f'Invalid path to screenshot file: {sshot_file_path}')
            return

        format_data = {
            'hour': t.hour,
            'minute': t.minute,
            'second': t.second,
            'day': t.day,
            'month': t.month,
            'year': t.year,
            'timestamp': t.isoformat(timespec='seconds'),
            # Elite stuff
            'cmdr': cmdr,
            'is_beta': is_beta,
            'system': entry.get('System', system),
            'location': entry.get('Body', station),
            'ext': 'bmp'
        }
        try:
            new_name = self.rename_format.get().format(**format_data).replace(' ', '_')
        except KeyError as e:
            plug.show_error(f'Unknown rename verb: {e}')
            logger.warn(f'Unknown replacement verb in screenshot rename: {e}')
            return

        new_path = sshot_dir_path / new_name
        sshot_file_path.rename(new_path)

        plug.show_error(f'Renamed screenshot')
        logger.info(f'Renamed {sshot_file_path.parts[-1]} to {new_name}')

        if self.do_convert.get():
            logger.info('Starting convert thread')
            threading.Thread(
                target=self.convert_path,
                args=(new_path, new_path.with_suffix('.png'), self.command.get(), self.remove_old.get())
            ).start()

    @staticmethod
    def convert_path(old_path: pathlib.Path, new_path: pathlib.Path, command: str, remove_old: bool):
        split = shlex.split(command)
        fmt = {'old': str(old_path), 'new': str(new_path)}
        split = [x.format(**fmt) for x in split]
        logger.info(f'Executing: {split}')
        plug.show_error('Converting screenshot...')
        res = subprocess.run(split)

        if res.returncode != 0:
            plug.show_error('Conversion failed. See Log.')
            logger.warn('Nonezero exit code from command. Not removing if enabled. stderr follows')
            logger.warn(res.stderr)
            return

        plug.show_error('Conversion complete')

        if remove_old:
            if not old_path.is_file() or not old_path.exists():
                raise ValueError(f'{old_path} is not a file or does not exist')

            logger.info(f'Removing {old_path}')
            plug.show_error('Removing old file')
            old_path.unlink()


s = ScreenshotRenamer()


def plugin_start3(path: str) -> str:
    return s.load()


def plugin_prefs(parent: nb.Notebook, cmdr: str, is_beta: bool) -> Optional[tk.Frame]:
    return s.config_page(parent)


def prefs_changed(cmdr: str, is_beta: bool) -> None:
    return s.on_config_close()


def journal_entry(
    cmdr: str, is_beta: bool, system: str, station: str, entry: Dict[str, Any], state: Dict[str, Any]
) -> None:
    return s.on_journal_entry(cmdr, is_beta, system, station, entry)
