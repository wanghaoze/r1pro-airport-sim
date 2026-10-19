#!/usr/bin/env bash
# New convenience entry; no changes to robot run/scheduler/filter.
set -eo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ACTION="${1:-help}"
MODEL="${2:-mixed}"
case "$ACTION" in
  pick) TEXT='Pick up the tray' ;;
  place) TEXT='Place the tray' ;;
  status)
    python3 - "$ROOT" <<'PY'
import pathlib,sys
root=pathlib.Path(sys.argv[1]);print('Task:',(root/'scheduler/instruction/instruction.txt').read_text().strip())
for p in pathlib.Path('/proc').iterdir():
 if not p.name.isdigit():continue
 try:
  args=(p/'cmdline').read_bytes().split(b'\0')
  if args and pathlib.Path(args[0].decode()).name.startswith('python') and any(b'run_pi05_record_compat_' in x or x.endswith(b'/run.py') or x==b'run.py' for x in args[1:]):print('Client PID:',p.name)
 except (PermissionError,FileNotFoundError,ProcessLookupError):pass
PY
    exit 0 ;;
  *) echo 'Usage: ./vla pick|place [mixed|real]'; echo './vla status'; echo 'Keep workstation keyboard console open: R rearm; E/SPACE stop.'; exit 0 ;;
esac
case "$MODEL" in
  mixed) CONFIG=config_pi05_mixed_gripper80_lan_20261013.toml ;;
  real|real_only) CONFIG=config_pi05_real_only_gripper80_lan_20261013.toml ;;
  *) echo 'Model must be mixed or real' >&2; exit 2 ;;
esac
cd "$ROOT"
exec 9>".vla_client.lock"
flock -n 9 || { echo 'Client already running; stop it before switching task/model.' >&2; exit 3; }
# Cover clients started manually without the new lock. Do not overwrite their task.
python3 - <<'PY'
import pathlib,sys
for p in pathlib.Path('/proc').iterdir():
 if not p.name.isdigit():continue
 try:
  a=(p/'cmdline').read_bytes().split(b'\0')
  if a and pathlib.Path(a[0].decode()).name.startswith('python') and any(b'run_pi05_record_compat_' in x or x.endswith(b'/run.py') or x==b'run.py' for x in a[1:]):
   print('Existing client PID '+p.name+'; stop before switching.',file=sys.stderr);sys.exit(3)
 except (PermissionError,FileNotFoundError,ProcessLookupError):pass
PY
source ./start.sh
export FASTRTPS_DEFAULT_PROFILES_FILE=/opt/galaxea/find_server/super_client_configuration_file.xml
export PYTHONUNBUFFERED=1
# Read-only readiness check; never rearm server or issue model/robot actions.
python - "$CONFIG" <<'PY'
import socket,sys,toml,pathlib
c=toml.load(sys.argv[1]);assert c['joint_command_filter']['enabled']
assert all(c['joint_command_filter'][k]['range']==[0,80] for k in ['left_gripper','right_gripper'])
assert pathlib.Path('/opt/galaxea/find_server/super_client_configuration_file.xml').is_file()
s=socket.create_connection((c['websocket']['host'],c['websocket']['port']),3);s.close()
PY
printf '%s\n' "$TEXT" > scheduler/instruction/instruction.txt
echo "Starting $MODEL: $TEXT (recording + feedback diagnostics). E/SPACE on workstation stops commands."
exec python -u run_pi05_record_compat_20261013_v4.py --config "$CONFIG" --record
