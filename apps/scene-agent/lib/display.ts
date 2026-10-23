// Translate known historical system labels at display time; stored receipts stay immutable.
export function displayText(value:unknown):string {
  let text=typeof value==='string'?value:value==null?'':typeof value==='object'?errorText(value):String(value);
  const entries:Record<string,string>={
    '新 300 对 + 真机 50/50':'New 300 pairs + real 50/50','自选配比':'Custom mix','真机 100%':'Real 100%','真机 90% / 仿真 10%':'Real 90% / sim 10%',
    '作业流程已结束；训练完成不等于闭环验证通过。':'Job finished. Training completion does not imply closed-loop success.',
    '既有训练监督器仍在运行；新任务保持排队。':'The existing training supervisor is running. New jobs remain queued.',
    '已冻结任务配置；等待当前 GPU 训练释放资源。':'Job configuration frozen. Waiting for GPU resources.',
    'GPU 上仍有模型或仿真进程；新任务保持排队。':'A model or simulation still uses the GPU. New jobs remain queued.',
    '独立任务已登记，等待 GPU；现有训练继续。':'Independent job registered, waiting for GPU. Existing training continues.',
    'GPU 已释放，启动独立作业。':'GPU available. Starting an independent job.',
    '复核固定数据来源与检查点身份。':'Verifying fixed data sources and checkpoint identity.',
    '作业进程身份消失且未记录正常退出；保留失败现场。':'Job process disappeared without a normal exit receipt. Failure evidence preserved.',
    '32房间草稿已同步。原生颜色适配与物理预检待验证；没有改变当前仿真或训练输入。':'32-room draft synced. Native color adaptation and physics preflight remain unverified. Current inputs are unchanged.',
    '编辑器调整位姿与颜色':'Editor pose and color changes','恢复版本':'Restore version','修改场景':'Edit scene',
    '现有训练监督器身份或心跳未通过核验。未重复启动任务；请检查服务器运行证据。':'The existing supervisor identity or heartbeat could not be verified. No duplicate job was started. Check the server evidence.',
    'GPU 资源状态暂不可核验；新任务保持排队。':'GPU resources could not be verified. New jobs remain queued.',
    'GPU 显存状态暂不可核验；新任务保持排队。':'GPU memory state could not be verified. New jobs remain queued.',
  };
  for(const [from,to] of Object.entries(entries))text=text.replaceAll(from,to);
  return text.replace(/已关联现有监督器，当前阶段 (.*?)。数据资格满足后由既有流程执行训练。/g,'Attached to the existing supervisor; stage: $1. The existing pipeline starts training after data validation.').replace(/(\d+) 步/g,'$1 steps');
}
// Native failures may carry {type,message,traceback}. Never render objects as React children.
export function errorText(value:unknown):string {
  if(value==null)return '';
  if(typeof value!=='object')return String(value);
  if(Array.isArray(value))return value.map(errorText).join('; ');
  const row=value as Record<string,unknown>;
  if(row.message!=null)return [row.type,errorText(row.message)].filter(Boolean).join(': ');
  if(row.error!=null)return errorText(row.error);
  return JSON.stringify(value);
}
export const datasetNames:Record<string,string>={isaac300_20261017:'Isaac · new 300 pairs',real_pickplace_v2:'Real Pick / Place',isaac32_narrow_20261016:'Isaac · narrow distribution',isaac32_wide_20261016:'Isaac · wide distribution'};
