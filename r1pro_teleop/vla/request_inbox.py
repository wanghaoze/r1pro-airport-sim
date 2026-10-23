"""Poll sequential native requests without rescanning retained evidence files.

For a fresh run, FilePolicyClient publishes contiguous per-room sequence numbers
starting at zero by atomic rename. This is not a crashed-service resume protocol.
"""
from pathlib import Path


class RequestInbox:
    def __init__(self,directory,room_ids):
        ids=list(room_ids)
        if not ids or any(type(room)!=int or room<0 for room in ids) or len(set(ids))!=len(ids):
            raise ValueError('invalid_policy_inbox_rooms')
        self.directory=Path(directory)
        self.next_sequence={room:0 for room in sorted(ids)}

    def path_for(self,room):
        return self.directory/f'room{room:03d}_{self.next_sequence[room]:06d}.request.npz'

    def ready(self):
        # One existence check per registered room, independent of run duration.
        for room in self.next_sequence:
            path=self.path_for(room)
            if path.is_file():yield room,path

    def acknowledge(self,room,path):
        if Path(path)!=self.path_for(room):raise ValueError('policy_inbox_sequence_mismatch')
        self.next_sequence[room]+=1
