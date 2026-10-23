import {gpuSnapshot,json,error} from '@/lib/server';
import {checkpointCatalog} from '@/lib/checkpoint-catalog';
export const dynamic='force-dynamic';
// The Site audience controls access. This read-only route exposes no owner workspace,
// paths, credentials, weights or jobs. Mutating routes retain their owner checks.
export async function GET(){try{return json(checkpointCatalog(await gpuSnapshot()));}catch(e){return error(e);}}
