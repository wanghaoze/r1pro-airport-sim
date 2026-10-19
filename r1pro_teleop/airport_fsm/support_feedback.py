"""Read-only support-force measurements for experimental control diagnostics.

These measurements do not authorize release or replace Evidence.table_contact.
No force is applied, no simulation step is taken, and no guard is relaxed.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable
import numpy as np


@dataclass(frozen=True)
class SupportForce:
    """Contact reaction on the tray from the explicitly named support bodies.

    ``signed_normal_n`` includes friction projected onto the support normal.
    ``load_n`` clips only the *net* negative component, not each contact, so
    opposing forces cannot create fictitious load. Qualifying contact count
    uses the existing Evidence normal-force cutoff; it is diagnostic only.
    """

    resultant_world_n: tuple[float, float, float]
    signed_normal_n: float
    load_n: float
    tangent_world_n: tuple[float, float, float]
    pair_count: int
    qualifying_contact_count: int


def measure_support_force(model, data, tray_body: int, support_bodies: Iterable[int],
                          *, normal=(0., 0., 1.), contact_force: Callable | None = None) -> SupportForce:
    """Sum actual MuJoCo contact reactions without updating model/data.

    MuJoCo reports contact-local force acting on geom2; geom1 receives its
    opposite. Contact frame axes are stored as rows, hence ``frame.T @ f``.
    Only tray/support pairs count: fingers, other trays and floor are excluded
    unless a caller explicitly names them as support bodies. Production callers
    should pass Runtime.table_bodies, never all colliding objects.

    The optional callback has mj_contactForce's signature and permits isolated
    unit tests. The default uses MuJoCo's read-only force extraction API.
    """
    if isinstance(tray_body, bool) or not isinstance(tray_body, (int, np.integer)):
        raise ValueError('Integer tray body ID required')
    supports = frozenset(support_bodies)
    if (not 0 <= tray_body < model.nbody or tray_body in supports
            or any(isinstance(b, bool) or not isinstance(b, (int, np.integer))
                   or not 0 <= b < model.nbody for b in supports)):
        raise ValueError('Distinct valid tray and support body IDs required')
    normal = np.asarray(normal, dtype=float)
    if normal.shape != (3,) or not np.isfinite(normal).all() or np.linalg.norm(normal) <= 1e-12:
        raise ValueError('Finite nonzero support normal required')
    normal = normal / np.linalg.norm(normal)
    if contact_force is None:
        import mujoco
        contact_force = mujoco.mj_contactForce
    resultant = np.zeros(3)
    pair_count = qualifying = 0
    local = np.zeros(6)
    for index in range(data.ncon):
        contact = data.contact[index]
        body1, body2 = (int(model.geom_bodyid[g]) for g in (contact.geom1, contact.geom2))
        if body2 == tray_body and body1 in supports:
            sign = 1.
        elif body1 == tray_body and body2 in supports:
            sign = -1.
        else:
            continue
        local[:] = 0.
        contact_force(model, data, index, local)
        frame = np.asarray(contact.frame).reshape(3, 3)
        if not np.isfinite(local).all() or not np.isfinite(frame).all():
            raise ValueError('Nonfinite physical contact force/frame')
        resultant += sign * (frame.T @ local[:3])
        pair_count += 1
        qualifying += int(local[0] > .05)
    signed = float(np.dot(resultant, normal))
    tangent = resultant - signed * normal
    return SupportForce(tuple(map(float, resultant)), signed, max(0., signed),
                        tuple(map(float, tangent)), pair_count, qualifying)
