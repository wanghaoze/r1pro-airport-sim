"""Passenger contact remains physical evidence without a blanket prohibition."""
from types import SimpleNamespace
import numpy as np
import pytest

from r1pro_teleop.single_tray_lab.control import ControlProfile, SingleTrayController


def contact_fixture(a, b, *, depth=.0003, force=2., loaded=True):
    c = SingleTrayController.__new__(SingleTrayController)
    c.robot = {1}; c.payload = {2}; c.tray = {3}; c.tables = {4}; c.flexes = {0}
    c.loaded = loaded; c.holding_sides = {'right'}
    c.p = ControlProfile()
    names = {0:'floor', 1:'right_forearm', 2:'passenger_backpack', 3:'tray', 4:'table',
             'payload_flex':'flex:passenger_coat', 'unknown_flex':'unregistered_flex'}
    c.m = SimpleNamespace(body=lambda body: SimpleNamespace(name=names[body]))
    contact = SimpleNamespace(entities=(a,b), dist=-depth, force=force)
    c.d = SimpleNamespace(contact=[contact])
    c._entity = lambda contact, index: (contact.entities[index], names[contact.entities[index]])
    def actual_force(model, data, index, vector): vector[0] = data.contact[index].force
    c.mj = SimpleNamespace(mj_contactForce=actual_force)
    return c


@pytest.mark.parametrize('payload', [2, 'payload_flex'])
@pytest.mark.parametrize('reverse', [False, True])
def test_allowed_robot_passenger_touch_preserves_force_depth_and_is_not_grasp_or_support(payload, reverse):
    c = contact_fixture(payload, 1) if reverse else contact_fixture(1, payload)
    contacts = c._contacts()
    assert contacts['illegal_contacts'] == []
    assert contacts['robot_payload_contacts'][0]['normal_force_n'] == 2.
    assert contacts['robot_payload_contacts'][0]['distance_m'] == -.0003
    assert contacts['robot_payload_contacts'][0]['penetration_m'] == .0003
    assert contacts['hard_max_penetration'] == .0003 and contacts['soft_payload_max_penetration'] == 0.
    assert contacts['gripper_contact_force'] == {'left':0., 'right':0.}
    assert contacts['supported_payload_entities'] == set() and contacts['payload_support_contacts'] == 0
    assert not c._penetration_exceeds(contacts)


@pytest.mark.parametrize('payload', [2, 'payload_flex'])
def test_robot_payload_touch_still_fails_existing_hard_penetration_limit(payload):
    c = contact_fixture(1, payload, depth=.0031)
    contacts = c._contacts()
    assert contacts['illegal_contacts'] == [] and len(contacts['robot_payload_contacts']) == 1
    assert c._penetration_exceeds(contacts) and c.p.max_penetration_m == .003
    assert c._penetration_exceeds(contacts, planning_preload=True)


def test_unknown_flex_and_robot_table_collision_are_still_illegal():
    for other in ('unknown_flex', 4):
        c = contact_fixture(1, other)
        contacts = c._contacts()
        assert contacts['illegal_contacts'] and not contacts['robot_payload_contacts']


def test_loaded_floor_contact_and_real_tray_support_are_unchanged():
    c = contact_fixture(2, 0)
    assert c._contacts()['payload_floor_contacts'] == 1
    c = contact_fixture(2, 3)
    contacts = c._contacts()
    assert contacts['supported_payload_entities'] == {2}
    assert contacts['payload_support_contacts'] == 1 and not contacts['robot_payload_contacts']
