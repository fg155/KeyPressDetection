"""Desktop colors matching the tokens in web/style.css."""
from tkinter import ttk

COLORS = {
    'slate_900': '#3a4157', 'slate_800': '#4f5872', 'slate_700': '#5d6784',
    'slate_100': '#e6e8ef', 'highlight': '#759bbb', 'highlight_dark': '#5a7f9f',
    'paper': '#f3f4f4', 'surface': '#ffffff', 'surface_2': '#f8f9f9',
    'line': '#dde1e1', 'line_soft': '#eceeee', 'line_strong': '#c9cfcf',
    'ink': '#2b3142', 'muted': '#6b7285', 'nav_text': '#d3d7e2',
    'danger': '#b4483a', 'danger_soft': '#f8e6e2', 'danger_line': '#ecc6bd',
}


def apply_theme(root):
    c = COLORS
    root.configure(bg=c['paper'])
    style = ttk.Style(root)
    style.theme_use('clam')
    style.configure('.', background=c['paper'], foreground=c['ink'],
                    font=('Segoe UI', 10), bordercolor=c['line'],
                    lightcolor=c['surface'], darkcolor=c['line'],
                    troughcolor=c['line_soft'], focuscolor=c['highlight'],
                    selectbackground=c['slate_800'], selectforeground=c['surface'])
    style.configure('Muted.TLabel', foreground=c['muted'])
    style.configure('Status.TLabel', background=c['slate_100'], foreground=c['slate_800'],
                    padding=(10, 5), font=('Segoe UI', 10, 'bold'))
    style.configure('Error.TLabel', foreground=c['danger'])
    style.configure('TButton', padding=(12, 7), borderwidth=1,
                    background=c['surface'], foreground=c['ink'])
    style.map('TButton',
              background=[('disabled', c['surface_2']), ('pressed', c['slate_100']), ('active', c['surface_2'])],
              foreground=[('disabled', c['muted'])],
              bordercolor=[('disabled', c['line']), ('focus', c['highlight']), ('active', c['line_strong'])],
              lightcolor=[('pressed', c['line'])], darkcolor=[('pressed', c['line'])])
    style.configure('Start.TButton', background=c['slate_800'], foreground=c['surface'],
                    bordercolor=c['slate_800'], lightcolor=c['slate_800'], darkcolor=c['slate_800'])
    style.map('Start.TButton',
              background=[('disabled', c['slate_100']), ('pressed', c['slate_900']), ('active', c['slate_900'])],
              foreground=[('disabled', c['muted']), ('!disabled', c['surface'])],
              bordercolor=[('disabled', c['line']), ('focus', c['highlight']), ('!disabled', c['slate_800'])],
              lightcolor=[('!disabled', c['slate_800'])], darkcolor=[('!disabled', c['slate_800'])])
    style.configure('Stop.TButton', foreground=c['danger'])
    style.map('Stop.TButton',
              foreground=[('disabled', c['muted']), ('!disabled', c['danger'])],
              background=[('disabled', c['surface_2']), ('active', c['danger_soft'])],
              bordercolor=[('disabled', c['line']), ('focus', c['highlight']), ('active', c['danger_line'])])
    for name in ('TEntry', 'TCombobox'):
        style.configure(name, fieldbackground=c['surface'], background=c['surface'],
                        foreground=c['ink'], insertcolor=c['ink'], borderwidth=1,
                        arrowcolor=c['muted'], padding=6)
        style.map(name,
                  fieldbackground=[('disabled', c['surface_2']), ('readonly', c['surface'])],
                  background=[('disabled', c['surface_2']), ('active', c['surface_2']), ('readonly', c['surface'])],
                  foreground=[('disabled', c['muted']), ('readonly', c['ink'])],
                  bordercolor=[('disabled', c['line']), ('focus', c['highlight'])],
                  lightcolor=[('focus', c['highlight'])], darkcolor=[('focus', c['highlight'])],
                  selectbackground=[('!disabled', c['slate_800'])],
                  selectforeground=[('!disabled', c['surface'])])
    style.configure('Vertical.TScrollbar', background=c['slate_100'],
                    troughcolor=c['paper'], arrowcolor=c['muted'], bordercolor=c['line'],
                    lightcolor=c['slate_100'], darkcolor=c['slate_100'])
    style.map('Vertical.TScrollbar', background=[('active', c['line_strong']), ('pressed', c['line_strong'])])
    # Combobox popups are classic Tk listboxes, outside ttk style inheritance.
    for name, value in {'background': c['surface'], 'foreground': c['ink'],
                        'selectBackground': c['slate_800'], 'selectForeground': c['surface'],
                        'highlightColor': c['highlight'], 'highlightBackground': c['line'],
                        'font': ('Segoe UI', 10)}.items():
        root.option_add('*TCombobox*Listbox.' + name, value)
    return style
