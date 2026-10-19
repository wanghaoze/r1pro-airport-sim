"""CPU-only immutable preregistration of all original held-out test scenes."""
from pathlib import Path
import argparse,json,sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from r1pro_teleop.vla.evaluation_protocol import build_protocol


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--collection',required=True);parser.add_argument('--successful-inventory',required=True)
    parser.add_argument('--output',required=True)
    args=parser.parse_args(argv)
    protocol=build_protocol(args.collection,args.successful_inventory)
    output=Path(args.output).resolve()
    if output.is_relative_to(Path(args.collection).resolve()):raise ValueError('Protocol cannot modify source collection')
    output.parent.mkdir(parents=True,exist_ok=True)
    with output.open('x') as stream:json.dump(protocol,stream,indent=2)
    print(json.dumps(dict(protocol_id=protocol['protocol_id'],main_denominator=protocol['main_denominator'],
        teacher_success_subset_denominator=protocol['teacher_success_subset_denominator'],output=str(output))))


if __name__=='__main__':main()
