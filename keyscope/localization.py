"""Desktop UI translations (Chinese, English)."""
LABELS = {
    'title': ('按键模拟器', 'Keyboard simulator'), 'directory': ('输出目录', 'Output directory'),
    'browse': ('选择文件夹', 'Browse folder'), 'refresh': ('刷新', 'Refresh'), 'score': ('TXT 谱子', 'TXT score'),
    'open': ('打开 TXT', 'Open TXT'), 'start': ('开始', 'Start'), 'stop': ('停止 · {stop_hotkey}', 'Stop · {stop_hotkey}'),
    'speed': ('速度', 'Speed'), 'hold': ('按住时长 / ms', 'Hold / ms'), 'merge': ('合并间隔 / ms', 'Merge gap / ms'),
    'countdown': ('倒计时 / s', 'Countdown / s'), 'mode': ('模式', 'Mode'),
    'modes': (('合并连续检测', '逐行点击'), ('Merge detections', 'Tap each row')),
    'hint': ('{hotkey} 开始 / 暂停 · {stop_hotkey} 停止 · 切窗暂停，回到游戏后按 {hotkey} 继续', '{hotkey} Start / Pause · {stop_hotkey} Stop · Window changes pause playback; press {hotkey} in the game to resume'),
    'pause': ('暂停', 'Pause'), 'resume': ('继续', 'Resume'), 'paused': ('已暂停', 'Paused'),
    'settings': ('设置', 'Settings'), 'hotkey': ('开始 / 暂停快捷键', 'Start / Pause hotkey'),
    'stop_hotkey': ('停止快捷键', 'Stop hotkey'), 'save': ('保存', 'Save'),
    'hotkey_conflict': ('两个快捷键不能相同。', 'Choose different hotkeys.'),
    'settings_error': ('无法保存设置，请查看日志。', 'Could not save settings. See the log.'),
    'idle': ('空闲', 'Idle'), 'playing': ('播放中', 'Playing'), 'waiting': ('倒计时', 'Countdown'),
    'stopped': ('已停止', 'Stopped'), 'completed': ('已完成', 'Completed'), 'failed': ('失败', 'Failed'),
    'admin': ('管理员', 'Administrator'), 'standard': ('普通权限', 'Standard user'), 'dry': ('测试模式 · 不发送按键', 'Dry run · No keyboard input'),
    'empty': ('目录中没有 TXT', 'No TXT files in this directory'),
    'info': ('{rows} 行 · {notes} 次按键 · {seconds:.2f} s', '{rows} rows · {notes} key presses · {seconds:.2f} s'),
    'log': ('日志', 'Log'), 'selected': ('未选择 TXT', 'No TXT selected'),
}

PICKER_TITLES = {"zh": {"directory": "选择文件夹", "model": "选择模型", "video": "选择视频"}, "en": {"directory": "Select directory", "model": "Select model", "video": "Select video"}}
LANGUAGE_NAMES = {'zh':'中文', 'en':'English'}
