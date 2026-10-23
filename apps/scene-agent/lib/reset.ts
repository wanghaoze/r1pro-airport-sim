import type {Room} from './core';
import initial from './initial-snapshot.json';
/** Restore each room's own complete baseline, not the currently selected object's fields. */
export function resetRooms(rooms:Room[],ids:number[]):Room[]{
  const selected=new Set(ids);
  return rooms.map(room=>selected.has(room.id)?structuredClone(initial.rooms.find(base=>base.id===room.id) as Room):room);
}
