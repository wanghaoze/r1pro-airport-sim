"""Bounded planning DAG; motion nodes are executed by the feedback FSM.

This is the logical task contract, not a replacement physics executor. Repeated
operations/retries have distinct IDs. Actual transition events form another
acyclic chain with monotonic IDs, including any failed or recovery nodes.
"""


def build_task_dag(operations, retries):
    nodes=[{'id':'start','kind':'start'},{'id':'done','kind':'complete'},{'id':'failed','kind':'failed'}]
    edges=[]
    def edge(a,b,when):edges.append({'from':a,'to':b,'when':when})
    for op in range(operations):
        select=f'o{op}.select';nodes.append({'id':select,'kind':'select'})
        if op==0:edge('start',select,'begin')
        edge(select,'done','all_physically_verified')
        for retry in range(retries):
            p=f'o{op}.r{retry}.'
            kinds=('align','assess','direct','pull','join','lift','transport','place','verify','recover')
            nodes.extend({'id':p+k,'kind':k} for k in kinds)
            if retry==0:edge(select,p+'align','target_selected')
            for a,b,condition in (
                ('align','assess','aligned'),('assess','direct','direct_grasp_or_adjust'),
                ('assess','pull','reach_risk_and_safe_single_hand_path'),
                ('direct','verify','ordinary_adjust_complete'),('direct','lift','bilateral_grasp'),
                ('pull','join','supported_progress_and_post_pull_IK'),('join','lift','bilateral_contact'),
                ('lift','transport','lift_verified'),('transport','place','at_destination'),
                ('place','verify','support_release_adjust_complete')):edge(p+a,p+b,condition)
            edge(p+'verify','done','all_physically_verified')
            edge(p+'verify',f'o{op+1}.select' if op+1<operations else 'failed','more_work')
            for k in kinds[:-1]:
                edge(p+k,'failed','unrecoverable_fault')
                if k not in ('pull','join'):edge(p+k,p+'recover','recoverable_supported_fault')
            edge(p+'recover',f'o{op}.r{retry+1}.align' if retry+1<retries else 'failed','bounded_retry')
    return {'schema':'airport_task_dag/1','execution_engine':'feedback_FSM',
            'nodes':nodes,'edges':edges}
