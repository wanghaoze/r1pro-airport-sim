"""Render actual mobile three-table source; old one-table traces are rejected."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from scripts.render_single_tray_lab import main
if __name__=='__main__':
 sys.argv.extend(['--expected-profile','three_table_single_tray_action3_v1']);main()
