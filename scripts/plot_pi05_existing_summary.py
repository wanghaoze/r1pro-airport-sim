"""Plot verified existing aggregate reports while paired inference is pending."""
import json
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

ROOT=Path(__file__).resolve().parents[1]
REF=ROOT/'runs/real_only_pi05_20261012_v1_reference'
OUT=ROOT/'runs/pi05_real_mixed_comparison_20261012_v1/local_prior_summary'
OUT.mkdir(parents=True,exist_ok=True)
pure=json.loads((REF/'latest_status.json').read_text(encoding='utf-8-sig'))['evaluation/test_summary.json']['groups']
mixed=json.loads((REF/'historical_comparison_audit.json').read_text(encoding='utf-8-sig'))['historical_reports']['mse_mixed_pi05.json']['groups']
plt.rcParams.update({'font.family':'DejaVu Sans','font.size':11,'axes.spines.top':False,'axes.spines.right':False})
fig,axes=plt.subplots(1,2,figsize=(12,5.5));x=np.arange(2);width=.34
tasks=['Pick up the tray','Place the tray']
for k,(label,rows,color) in enumerate([('Real-only',pure,'#0072B2'),('Mixed (90/10)',mixed,'#D55E00')]):
    vals=[[np.sqrt(rows[t]['arm_mse_rad2'])*180/np.pi for t in tasks],[np.sqrt(rows[t]['gripper_mse_mm2']) for t in tasks]]
    for ax,y in zip(axes,vals):
        bars=ax.bar(x+(k-.5)*width,y,width,label=label,color=color,hatch=None if k==0 else '//')
        ax.bar_label(bars,fmt='%.2f',padding=4,fontsize=10)
for ax,title,unit in zip(axes,['Arm-joint prediction error','Gripper prediction error'],['RMSE (deg)','RMSE (mm)']):
    ax.set_title(title);ax.set_ylabel(unit);ax.set_xticks(x,['Pick (11 episodes)','Place (8 episodes)']);ax.set_ylim(0,ax.get_ylim()[1]*1.2);ax.grid(axis='y',alpha=.18);ax.set_axisbelow(True);ax.legend()
fig.suptitle('Existing real-test reports: real-only vs mixed pi0.5',fontsize=16)
fig.text(.5,.03,'Same 19 held-out episodes; stride 5, valid H20. Historical runs used different flow noise.\nOffline prediction only; paired all-frame per-joint evaluation is pending.',ha='center',fontsize=10)
fig.subplots_adjust(top=.85,bottom=.22,wspace=.25)
fig.savefig(OUT/'existing_test_summary.png',dpi=160);fig.savefig(OUT/'existing_test_summary.pdf');plt.close(fig)
(OUT/'source_metrics.json').write_text(json.dumps({'real_only':pure,'mixed':mixed,'scope':'existing_historical_reports_not_paired_noise'},indent=2))
print(OUT)
