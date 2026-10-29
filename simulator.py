"""Independent keyboard simulator. Default launch requests administrator rights."""
import argparse
import ctypes
import os
from pathlib import Path
import sys
from keyscope.config import ROOT, read_settings, resolve_path
from keyscope.simulator_launch import is_admin, launch_simulator

def main():
    parser=argparse.ArgumentParser(description='TXT keyboard simulator')
    parser.add_argument('--directory',default=read_settings()['output_dir'])
    parser.add_argument('--score')
    parser.add_argument('--language',choices=('zh','en'),default='zh')
    parser.add_argument('--dry-run',action='store_true',help='Preview timing without sending keyboard input; no elevation required.')
    args=parser.parse_args()
    if os.name!='nt': raise SystemExit('Windows is required.')
    if not args.dry_run and not is_admin():
        launch_simulator(args.directory,args.score,args.language)
        return
    if Path(sys.executable).parent==ROOT/'runtime':
        os.environ['TCL_LIBRARY']=str(ROOT/'runtime/tcl/tcl8.6')
        os.environ['TK_LIBRARY']=str(ROOT/'runtime/tcl/tk8.6')
    try: ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except OSError: pass
    import tkinter as tk
    from keyscope.simulator_ui import Simulator
    root=tk.Tk()
    Simulator(root,resolve_path(args.directory),resolve_path(args.score) if args.score else None,args.language,args.dry_run)
    root.mainloop()

if __name__=='__main__':
    try: main()
    except Exception as exc:
        # pythonw has no console; keep startup failures visible.
        if os.name=='nt': ctypes.windll.user32.MessageBoxW(None,str(exc),'Simulator error',0x10)
        else: raise
